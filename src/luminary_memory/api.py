from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.backends import get_backend
from luminary_memory.budget import truncate
from luminary_memory.config import Settings
from luminary_memory.embeddings.fastembed import FastembedEngine
from luminary_memory.ingest.llm import LLMEnricher, NoopEnricher
from luminary_memory.ingest.whitelist import WhitelistFilter
from luminary_memory.types import Memory, RecallResult


def _try_index_graph(backend, memory: Memory) -> None:
    import logging

    from luminary_memory.recall.graph import index_memory_entities

    try:
        index_memory_entities(backend, memory)
    except Exception:  # noqa: BLE001 -- graph indexing is best-effort; never abort ingest
        logging.getLogger(__name__).warning(
            "graph indexing failed for memory %s (non-fatal)", memory.id
        )

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
        self.enricher = enricher or (NoopEnricher() if not self.settings.ingest_llm else None)

    def ingest(self, text: str, tags: list[str] | None = None,
               source: str | None = None) -> int | None:
        if not self.whitelist.accepts(text):
            return None

        content, summary, entities, extra_tags = text, None, [], []
        if self.enricher is not None:
            enriched = self.enricher.enrich(text)
            content, summary, entities, extra_tags = (
                enriched.content, enriched.summary, enriched.entities, enriched.tags,
            )

        metadata: dict = {}
        if summary:
            metadata["summary"] = summary
        if entities:
            metadata["entities"] = entities

        m = Memory(
            content=content,
            metadata=metadata,
            source=source,
            tags=list(dict.fromkeys((tags or []) + extra_tags)),
            ttl_seconds=self.settings.ttl_default_seconds,
            embedding=self.engine.embed(content),
        )
        mid = self.backend.add(m)
        m.id = mid
        _try_index_graph(self.backend, m)
        return mid

    def get(self, id: int) -> Memory | None:
        return self.backend.get(id)

    def update(self, memory: Memory) -> None:
        """Update an existing memory in place."""
        self.backend.update(memory)

    def delete(self, id: int) -> None:
        """Delete a memory by id."""
        self.backend.delete(id)

    def list(self, limit: int = 100, offset: int = 0) -> list[Memory]:
        """List memories, most recent first (datetime-aware sort)."""
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        from luminary_memory.recall.temporal import _parse_dt

        all_mem = self.backend.all()
        all_mem.sort(key=lambda m: (_parse_dt(m.created_at or ""), -(m.id or 0)), reverse=True)
        return all_mem[offset:offset + limit]

    def search(self, query: str, limit: int = 10) -> list[tuple[Memory, float]]:
        """Direct keyword (FTS) search without the full recall pipeline."""
        if not (query or "").strip():
            return []
        try:
            return self.backend.keyword_search(query, limit=limit)
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

    def run_lifecycle(self) -> dict[str, int]:
        from luminary_memory.lifecycle.runner import run_lifecycle

        return run_lifecycle(self.backend, self.settings)

    def close(self) -> None:
        self.backend.close()

    def recall(
        self,
        query: str,
        limit: int = 10,
        token_budget: int | None = None,
    ) -> RecallResult:
        from luminary_memory.recall.dedup import dedup_jaccard
        from luminary_memory.recall.fusion import reciprocal_rank_fusion
        from luminary_memory.recall.graph import graph_recall
        from luminary_memory.recall.keyword import keyword_recall
        from luminary_memory.recall.semantic import semantic_recall
        from luminary_memory.recall.temporal import temporal_recall

        budget = token_budget if token_budget is not None else self.settings.token_budget
        rrf_k = self.settings.rrf_k
        dedup_threshold = self.settings.dedup_jaccard_threshold

        # Per-strategy isolation: one failing strategy must not kill recall.
        strategies: list[list[tuple]] = []
        for fn in (
            lambda: semantic_recall(self.backend, self.engine, query, limit=limit),
            lambda: keyword_recall(self.backend, query, limit=limit),
            lambda: temporal_recall(self.backend, limit=limit * 2),
            lambda: graph_recall(self.backend, query, limit=limit),
        ):
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

        if not scored:
            return RecallResult(memories=[], scores=[], strategies_hit=strategies_hit)

        scored = dedup_jaccard(scored, threshold=dedup_threshold)

        memories_ordered = [m for m, _ in scored]
        memories_ordered = truncate(memories_ordered, token_budget=budget)

        id_to_fused = dict(fused)
        final_scores = [float(id_to_fused.get(m.id, 0.0)) for m in memories_ordered]

        from datetime import UTC, datetime

        for m in memories_ordered[:limit]:
            m.access_count += 1
            m.last_accessed_at = datetime.now(UTC).isoformat()
            self.backend.update(m)

        trimmed = {k: v for k, v in strategies_hit.items() if v}
        return RecallResult(
            memories=memories_ordered[:limit],
            scores=final_scores[:limit],
            strategies_hit=trimmed,
        )
