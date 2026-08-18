from __future__ import annotations

import logging
from datetime import UTC
from typing import TYPE_CHECKING

from luminary_memory.backends import get_backend
from luminary_memory.budget import truncate
from luminary_memory.config import Settings
from luminary_memory.embeddings.fastembed import FastembedEngine
from luminary_memory.ingest.llm import LLMEnricher, NoopEnricher
from luminary_memory.ingest.whitelist import WhitelistFilter
from luminary_memory.types import Memory, RecallResult

logger = logging.getLogger(__name__)


def _try_index_graph(backend, memory: Memory) -> None:
    from luminary_memory.recall.graph import index_memory_entities

    try:
        index_memory_entities(backend, memory)
    except Exception:  # noqa: BLE001 -- graph indexing is best-effort; never abort ingest
        logger.warning("graph indexing failed for memory %s (non-fatal)", memory.id)

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


class MemoryClient:
    def __init__(
        self,
        settings: Settings | None = None,
        db_path: str | None = None,
        ingest_whitelist: list[str] | None = None,
        enricher: LLMEnricher | None = None,
        engine: FastembedEngine | None = None,
        backend: MemoryBackend | None = None,
    ):
        self.settings = settings or Settings()
        if db_path is not None:
            self.settings.db_path = db_path
        if ingest_whitelist is not None:
            self.settings.ingest_whitelist = ingest_whitelist

        self.backend = backend or get_backend(self.settings)
        self.whitelist = WhitelistFilter(self.settings.ingest_whitelist)
        self.engine = engine or FastembedEngine(model_name=self.settings.embedding_model)
        # Never leave enricher None: ingest() calls .enrich() unconditionally.
        # Without a custom enricher, fall back to NoopEnricher (safe passthrough).
        self.enricher = enricher or NoopEnricher()

    def ingest(self, text: str, tags: list[str] | None = None,
               source: str | None = None, metadata: dict | None = None) -> int | None:
        if not self.whitelist.accepts(text):
            return None

        content, summary, entities, extra_tags = text, None, [], []
        if self.enricher is not None:
            enriched = self.enricher.enrich(text)
            content, summary, entities, extra_tags = (
                enriched.content, enriched.summary, enriched.entities, enriched.tags,
            )

        meta: dict = dict(metadata or {})
        if summary:
            meta["summary"] = summary
        if entities:
            meta["entities"] = entities

        m = Memory(
            content=content,
            metadata=meta,
            source=source,
            tags=list(dict.fromkeys((tags or []) + extra_tags)),
            ttl_seconds=self.settings.ttl_default_seconds,
            embedding=self.engine.embed(content),
        )
        if self.settings.importance_auto:
            from luminary_memory.lifecycle.importance import estimate_importance

            m.importance = estimate_importance(m)
        mid = self.backend.add(m)
        m.id = mid
        _try_index_graph(self.backend, m)
        return mid

    def ingest_batch(
        self,
        texts: list[str],
        tags: list[list[str] | None] | None = None,
        source: str | None = None,
    ) -> list[int | None]:
        """Batch ingest mirroring :meth:`ingest` per item.

        Whitelist-rejected items yield ``None`` at their index. Embeddings
        are computed in a single ``embed_batch`` call. Enrichment applies
        per item (same semantics as :meth:`ingest`).
        """
        if not texts:
            return []

        n = len(texts)
        if tags is not None and len(tags) != n:
            raise ValueError("tags length must match texts length")
        tag_lists: list[list[str] | None] = list(tags) if tags is not None else [None] * n

        # Enrich per item, track which survive whitelist.
        prepared: list[tuple[int, str, list[str], dict]] = []  # (orig_idx, content, tags, metadata)
        result: list[int | None] = [None] * n
        enriched_contents: list[str] = []
        enriched_idx_map: list[int] = []  # position in enriched_contents -> orig idx

        for i, raw_text in enumerate(texts):
            if not self.whitelist.accepts(raw_text):
                continue
            content, summary, entities, extra_tags = raw_text, None, [], []
            if self.enricher is not None:
                enriched = self.enricher.enrich(raw_text)
                content, summary, entities, extra_tags = (
                    enriched.content, enriched.summary, enriched.entities, enriched.tags,
                )
            metadata: dict = {}
            if summary:
                metadata["summary"] = summary
            if entities:
                metadata["entities"] = entities
            merged_tags = list(dict.fromkeys((tag_lists[i] or []) + extra_tags))
            prepared.append((i, content, merged_tags, metadata))
            enriched_contents.append(content)
            enriched_idx_map.append(i)

        if not prepared:
            return result

        # Single embedding pass.
        embeddings: list[list[float]]
        try:
            batch_fn = getattr(self.engine, "embed_batch", None)
            if batch_fn is not None:
                embeddings = batch_fn(enriched_contents)
            else:
                embeddings = [self.engine.embed(t) for t in enriched_contents]
        except Exception:  # noqa: BLE001 -- embedding failure falls back per-item
            embeddings = [self.engine.embed(t) for t in enriched_contents]

        # Build memories for surviving items.
        memories: list[Memory] = []
        mem_orig_idx: list[int] = []
        for (orig_idx, content, merged_tags, metadata), emb in zip(prepared, embeddings):
            m = Memory(
                content=content,
                metadata=metadata,
                source=source,
                tags=merged_tags,
                ttl_seconds=self.settings.ttl_default_seconds,
                embedding=emb,
            )
            memories.append(m)
            mem_orig_idx.append(orig_idx)

        ids = self.backend.add_many(memories)  # type: ignore[attr-defined]
        # Wire ids back, index graph per memory.
        for mem, mid, orig_idx in zip(memories, ids, mem_orig_idx):
            mem.id = mid
            _try_index_graph(self.backend, mem)
            result[orig_idx] = mid
        return result

    def get(self, id: int) -> Memory | None:
        return self.backend.get(id)

    def update(self, memory: Memory) -> None:
        """Update an existing memory in place (auto-bumps ``updated_at``)."""
        from datetime import UTC, datetime

        memory.updated_at = datetime.now(UTC).isoformat()
        self.backend.update(memory)

    def delete(self, id: int) -> None:
        """Delete a memory by id."""
        self.backend.delete(id)

    def list(self, limit: int = 100, offset: int = 0) -> list[Memory]:
        """List memories, most recent first (SQL-level pagination when supported).

        ``limit=0`` means unlimited (return all). Negative limits raise ``ValueError``.
        """
        n = int(limit)
        if n < 0:
            raise ValueError("limit must be >= 0 (0 means unlimited)")
        o = int(offset)
        if o < 0:
            raise ValueError("offset must be >= 0")
        eff_limit: int | None = None if n == 0 else n
        recent = getattr(self.backend, "recent", None)
        if recent is not None:
            return recent(limit=eff_limit, offset=o)
        # fallback for backends without SQL pagination
        from luminary_memory.recall.temporal import _parse_dt

        all_mem = self.backend.all()
        all_mem.sort(key=lambda m: (_parse_dt(m.created_at or ""), -(m.id or 0)), reverse=True)
        sliced = all_mem[o:]
        return sliced if eff_limit is None else sliced[:eff_limit]

    def search(self, query: str, limit: int = 10) -> list[tuple[Memory, float]]:
        """Direct keyword (FTS) search without the full recall pipeline.

        ``limit=0`` means unlimited; negative limits raise ``ValueError``.
        """
        n = int(limit)
        if n < 0:
            raise ValueError("limit must be >= 0 (0 means unlimited)")
        eff = None if n == 0 else n
        if not (query or "").strip():
            return []
        try:
            return self.backend.keyword_search(query, limit=eff)
        except Exception:  # noqa: BLE001
            return []

    def stats(self) -> dict:
        """Store statistics: count, oldest/newest, avg importance, tags."""
        import statistics

        all_mem = self.backend.all()
        n = len(all_mem)
        if not n:
            return {
                "count": 0,
                "oldest": None,
                "newest": None,
                "avg_importance": 0.0,
                "top_tags": {},
            }

        avg_importance = statistics.fmean([m.importance for m in all_mem])
        tag_counts: dict[str, int] = {}
        for m in all_mem:
            for t in m.tags or []:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:10]
        created = sorted(m.created_at or "" for m in all_mem)
        return {
            "count": n,
            "oldest": created[0] if created else None,
            "newest": created[-1] if created else None,
            "avg_importance": round(avg_importance, 3),
            "top_tags": dict(top_tags),
        }

    def count(self) -> int:
        return self.backend.count()

    def run_lifecycle(self, semantic: bool | None = None) -> dict[str, int]:
        from luminary_memory.lifecycle.runner import run_lifecycle

        return run_lifecycle(self.backend, self.settings, semantic=semantic)

    def health_score(self) -> dict:
        """Store health report: overall 0-100 plus per-dimension breakdown.

        Dimensions (all computed from existing store data — no new schema):

        - ``duplicate_rate`` — share of memories with a near-duplicate
          (Jaccard token overlap > dedup threshold).
        - ``staleness`` — share of memories not accessed in 30 days.
        - ``importance`` — share of memories above ``prune_min_importance``.
        - ``density`` — share of memories with graph relations.
        - ``size`` — store volume vs a healthy scale (0 = empty, 100 = full).

        Returns ``{"score": float, "dimensions": {...}, "recommendations": [...]}``.
        """
        memories = self.list(limit=500)
        total = len(memories)
        if total == 0:
            return {
                "score": 100.0,
                "dimensions": {},
                "recommendations": ["store is empty — nothing to worry about"],
            }

        # --- duplicate_rate -------------------------------------------------
        dup_count = 0
        for i, a in enumerate(memories):
            a_tokens = set(str(a.content).lower().split())
            if not a_tokens:
                continue
            for b in memories[i + 1 :]:
                b_tokens = set(str(b.content).lower().split())
                if not b_tokens:
                    continue
                jac = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
                if jac > self.settings.dedup_jaccard_threshold:
                    dup_count += 1
                    break
        dup_rate = dup_count / total
        dup_health = max(0.0, 100.0 * (1.0 - dup_rate * 5))  # 20% dupes → 0

        # --- staleness ------------------------------------------------------
        from datetime import datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=30)
        stale_count = 0
        for m in memories:
            try:
                if m.last_accessed_at:
                    ts = datetime.fromisoformat(m.last_accessed_at)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    if ts < cutoff:
                        stale_count += 1
            except Exception:  # noqa: BLE001, S112 -- malformed timestamps skipped
                continue
        stale_rate = stale_count / total
        stale_health = max(0.0, 100.0 * (1.0 - stale_rate * 3))  # 33% stale → 0

        # --- importance -------------------------------------------------------
        imp_min = float(getattr(self.settings, "prune_min_importance", 0.2) or 0.2)
        imp_above = sum(1 for m in memories if (m.importance or 0) >= imp_min)
        imp_rate = imp_above / total
        imp_health = 100.0 * imp_rate

        # --- density ----------------------------------------------------------
        try:
            conn = getattr(self.backend, "conn", None)
            rel_count = 0
            if conn is not None:
                rel_count = conn.execute(
                    "SELECT COUNT(DISTINCT source_memory_id) FROM relations"
                ).fetchone()[0]
            density_rate = rel_count / total
        except Exception:  # noqa: BLE001 -- backends without graph tables
            density_rate = 0.0
        density_health = 100.0 * min(1.0, density_rate * 3)  # 33% density → 100

        # --- size --------------------------------------------------------------
        # 0 memories = 0; scale toward 100 at ~1k memories
        size_health = min(100.0, 100.0 * (total / 1000))

        dims = {
            "duplicate_rate": {"value": round(dup_rate, 4), "weight": 0.25, "health": round(dup_health, 1)},
            "staleness": {"value": round(stale_rate, 4), "weight": 0.25, "health": round(stale_health, 1)},
            "importance": {"value": round(imp_rate, 4), "weight": 0.20, "health": round(imp_health, 1)},
            "density": {"value": round(density_rate, 4), "weight": 0.15, "health": round(density_health, 1)},
            "size": {"value": total, "weight": 0.15, "health": round(size_health, 1)},
        }
        score = sum(d["health"] * d["weight"] for d in dims.values())

        recs = []
        if dup_health <= 70:
            recs.append(f"duplicates detected ({dup_rate:.0%}) — run `luminary-memory lifecycle` to consolidate")
        if stale_health <= 70:
            recs.append(f"{stale_count} stale memories (>30d) — run lifecycle prune or LLM maintenance")
        if imp_health <= 70:
            recs.append("low-value memories present — review store or raise prune_min_importance")
        if density_health <= 50 and total >= 20:
            recs.append("low graph density — entities may not be indexed for richer recall")
        return {"score": round(score, 1), "dimensions": dims, "recommendations": recs}

    def run_maintenance(self, review_all: bool = True) -> dict:
        """LLM-driven store maintenance: review memories and prune/update stale facts.

        Sends the current store (or a recent slice when ``review_all`` is
        false) to the configured LLM enricher, which decides per memory:
        ``keep`` (unchanged), ``update`` (new content), or ``delete``
        (obsolete/contradicted/duplicate). Applies the decisions and returns
        a summary dict.

        Requires ``ingest_llm`` (an LLM enricher); no-ops otherwise.
        """
        from luminary_memory.ingest.llm import _parse_enrichment_payload

        if self.enricher is None or isinstance(self.enricher, NoopEnricher):
            return {"skipped": "no LLM enricher configured (set ingest_llm)"}

        memories = self.list(limit=500)
        if not memories:
            return {"reviewed": 0, "deleted": 0, "updated": 0}

        raw = self.enricher.review_memories(memories)
        data = _parse_enrichment_payload(raw)
        actions = data.get("actions")
        if not isinstance(actions, list):
            return {"reviewed": len(memories), "deleted": 0, "updated": 0, "error": "bad LLM response"}

        deleted = updated = 0
        by_id = {m.id: m for m in memories}
        for act in actions:
            if not isinstance(act, dict):
                continue
            mid = act.get("id")
            if mid not in by_id:
                continue
            action = act.get("action")
            if action == "delete":
                try:
                    self.delete(int(mid))
                    deleted += 1
                except Exception:  # noqa: BLE001, S110
                    pass
            elif action == "update":
                new_content = act.get("content")
                if isinstance(new_content, str) and new_content.strip():
                    try:
                        m = by_id[mid]
                        m.content = new_content.strip()
                        self.update(m)
                        updated += 1
                    except Exception:  # noqa: BLE001, S110
                        pass
        return {"reviewed": len(memories), "deleted": deleted, "updated": updated}

    def export(self, path, include_embeddings: bool = True) -> dict:
        """Export all memories to *path* (versioned JSON)."""
        from luminary_memory.export import export_memories

        return export_memories(self.backend, path, include_embeddings=include_embeddings)

    def import_memories(self, path) -> dict:
        """Import memories from *path* (recomputes embeddings when absent)."""
        from luminary_memory.export import import_memories

        try:
            return import_memories(self.backend, path, engine=self.engine)
        except Exception:
            logger.exception("import_memories failed for %s", path)
            raise

    def graph(self, limit: int = 20) -> dict:
        """Return the knowledge graph: top entities and their co-occurrence edges.

        Shape: ``{"entities": [{"name", "degree", "memories"}],
        "relations": [{"source", "target", "weight"}]}``. Backends without a
        queryable graph table return empty lists (pgvector falls back safely).
        """
        entities: list[dict] = []
        relations: list[dict] = []
        conn = getattr(self.backend, "conn", None)
        if conn is None:
            return {"entities": entities, "relations": relations}
        try:
            rows = conn.execute(
                "SELECT e.name, COUNT(DISTINCT r.source_id) + COUNT(DISTINCT r.target_id) AS degree, "
                "COUNT(DISTINCT r.memory_id) AS memories "
                "FROM entities e "
                "LEFT JOIN relations r ON r.source_id = e.id OR r.target_id = e.id "
                "GROUP BY e.id ORDER BY degree DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            for r in rows:
                entities.append({
                    "name": r[0], "degree": int(r[1] or 0), "memories": int(r[2] or 0),
                })
            rel_rows = conn.execute(
                "SELECT s.name, t.name, MAX(r.weight) AS weight "
                "FROM relations r "
                "JOIN entities s ON s.id = r.source_id "
                "JOIN entities t ON t.id = r.target_id "
                "GROUP BY r.source_id, r.target_id "
                "ORDER BY weight DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            for r in rel_rows:
                relations.append({"source": r[0], "target": r[1], "weight": float(r[2] or 0.0)})
        except Exception:
            logger.exception("graph query failed (non-fatal)")
            return {"entities": [], "relations": []}
        return {"entities": entities, "relations": relations}

    def close(self) -> None:
        self.backend.close()

    def recall(
        self,
        query: str,
        limit: int = 10,
        token_budget: int | None = None,
        tags: list[str] | None = None,
    ) -> RecallResult:
        n_limit = int(limit)
        if n_limit < 0:
            raise ValueError("limit must be >= 0 (0 means unlimited)")
        if n_limit == 0:
            n_limit = None  # unlimited — backends treat None as "no limit"
        from luminary_memory.recall.dedup import dedup_jaccard
        from luminary_memory.recall.fusion import reciprocal_rank_fusion
        from luminary_memory.recall.graph import graph_recall
        from luminary_memory.recall.keyword import keyword_recall
        from luminary_memory.recall.semantic import semantic_recall
        from luminary_memory.recall.temporal import temporal_recall

        budget = token_budget if token_budget is not None else self.settings.token_budget
        rrf_k = self.settings.rrf_k
        dedup_threshold = self.settings.dedup_jaccard_threshold
        use_planner = bool(getattr(self.settings, "query_planner", True))
        planner_threshold = float(getattr(self.settings, "query_planner_keyword_threshold", 0.9))

        eff = n_limit
        temporal_limit = (eff * 2) if eff is not None else None
        enabled = None

        strategies: list[list[tuple]] = []
        # Order matters for planner temporal guard: keyword first.
        strat_fns = [
            ("semantic", lambda: semantic_recall(self.backend, self.engine, query, limit=eff)),
            ("keyword", lambda: keyword_recall(self.backend, query, limit=eff)),
            ("temporal", lambda: temporal_recall(self.backend, limit=temporal_limit)),
            ("graph", lambda: graph_recall(self.backend, query, limit=eff)),
        ]

        # If planner is enabled, compute which strategies are active.
        # We need keyword_top_score to decide temporal, so run in two passes.
        strat_map: dict[str, list[tuple]] = {}
        if use_planner:
            # Run keyword first to get top score
            from luminary_memory.recall.planner import plan_strategies as _plan

            # Run keyword in isolation
            kw_rows: list[tuple] = []
            try:
                kw_rows = strat_map["keyword"] = keyword_recall(self.backend, query, limit=eff)
            except Exception:  # noqa: BLE001
                kw_rows = strat_map["keyword"] = []
            top_kw = float(kw_rows[0][1]) if kw_rows else None
            enabled = _plan(query, keyword_top_score=top_kw, planner=True,
                            keyword_threshold=planner_threshold)
            # Run remaining strategies, skipping those disabled by planner
            for name, fn in strat_fns:
                if name == "keyword":
                    continue
                if enabled is not None and name not in enabled:
                    strat_map[name] = []
                    continue
                try:
                    strat_map[name] = fn()
                except Exception:  # noqa: BLE001
                    strat_map[name] = []
            # Restore fixed order for fusion
            for name, _ in strat_fns:
                strategies.append(strat_map.get(name, []))
        else:
            for _name, fn in strat_fns:
                try:
                    strategies.append(fn())
                except Exception:  # noqa: BLE001
                    strategies.append([])

        id_to_mem: dict[int, Memory] = {}
        strategies_hit: dict[str, int] = {}
        ranked_lists: list[list[int]] = []
        for strat in strategies:
            ranked_lists.append([m.id for m, _, _ in strat if m.id is not None])
            for m, score, label in strat:
                if m.id is None:
                    continue
                strategies_hit[label] = strategies_hit.get(label, 0) + 1
                id_to_mem[m.id] = m

        fused = reciprocal_rank_fusion(ranked_lists, k=rrf_k)
        scored: list[tuple[Memory, float]] = [
            (id_to_mem[mid], score) for mid, score in fused if mid in id_to_mem
        ]

        # Tag-scoped filter: restrict to allowed id set before fusion-derived dedup.
        if tags:
            by_tags = getattr(self.backend, "by_tags", None)
            if callable(by_tags):
                allowed = by_tags(list(tags))
                scored = [(m, s) for m, s in scored if m.id in allowed]

        if not scored:
            return RecallResult(memories=[], scores=[], strategies_hit=strategies_hit)

        scored = dedup_jaccard(scored, threshold=dedup_threshold)

        memories_ordered = [m for m, _ in scored]
        memories_ordered = truncate(memories_ordered, token_budget=budget)

        # Attach non-persisted snippet per recalled memory.
        try:
            from luminary_memory.recall.snippets import extract_snippet

            for m in memories_ordered:
                m.snippet = extract_snippet(m.content, query)
        except Exception:  # noqa: BLE001, S110
            pass

        id_to_fused = dict(fused)
        final_scores = [float(id_to_fused.get(m.id, 0.0)) for m in memories_ordered]

        from datetime import UTC, datetime

        for m in memories_ordered[:n_limit]:
            m.access_count += 1
            m.last_accessed_at = datetime.now(UTC).isoformat()
            self.backend.update(m)

        trimmed = {k: v for k, v in strategies_hit.items() if v}
        return RecallResult(
            memories=memories_ordered[:n_limit],
            scores=final_scores[:n_limit],
            strategies_hit=trimmed,
        )
