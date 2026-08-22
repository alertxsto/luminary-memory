from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from luminary_memory.backends import get_backend
from luminary_memory.budget import truncate
from luminary_memory.config import Settings
from luminary_memory.embeddings.fastembed import FastembedEngine
from luminary_memory.ingest.llm import LLMEnricher, NoopEnricher
from luminary_memory.ingest.rules import contains_rule_keyword
from luminary_memory.ingest.whitelist import WhitelistFilter
from luminary_memory.scope import memory_matches_scope, normalize_scope
from luminary_memory.types import Memory, RecallResult

logger = logging.getLogger(__name__)

_QUERY_ALIASES = (
    ("go live", "deploy"),
    ("go-live", "deploy"),
    ("deployment", "deploy"),
    ("destination", "target"),
    ("release destination", "deploy target"),
    ("display theme", "dark mode"),
    ("programming language", "compiler"),
    ("model variant", "model"),
    ("before release", "test suite"),
)

_VALID_MEMORY_STATUSES = frozenset(
    {"candidate", "active", "conflicted", "superseded", "expired", "deleted"}
)


def _expand_query_aliases(query: str) -> str:
    expanded = str(query or "")
    low = expanded.casefold()
    additions: list[str] = []
    for phrase, alias in _QUERY_ALIASES:
        if phrase in low and alias.casefold() not in low:
            additions.append(alias)
    return f"{expanded} {' '.join(additions)}".strip()


def _content_hash(content: str) -> str:
    normalized = " ".join((content or "").strip().split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _snapshot(memory: Memory | None) -> dict | None:
    if memory is None:
        return None
    return {
        "id": memory.id,
        "content": memory.content,
        "metadata": memory.metadata,
        "source": memory.source,
        "tags": memory.tags,
        "importance": memory.importance,
        "user_id": memory.user_id,
        "session_id": memory.session_id,
        "workspace_id": memory.workspace_id,
        "agent_id": memory.agent_id,
        "observed_at": memory.observed_at,
        "valid_from": memory.valid_from,
        "valid_to": memory.valid_to,
        "status": memory.status,
        "confidence": memory.confidence,
        "evidence_quote": memory.evidence_quote,
        "source_id": memory.source_id,
        "claim_key": memory.claim_key,
        "supersedes_id": memory.supersedes_id,
        "content_hash": memory.content_hash,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_embedding(value) -> list[float] | None:
    """Reject malformed vectors before they poison a backend/index."""
    if value is None:
        return None
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not vector or not all(math.isfinite(item) for item in vector):
        return None
    return vector


def _clean_unit_score(value, default: float = 0.5) -> float:
    """Normalize a score that is contractually bounded to ``[0, 1]``.

    Importance and confidence are persisted for a long time and can also be
    supplied by an external enricher. Treat malformed/non-finite values as a
    safe default and clamp out-of-range values before they affect ranking,
    pinning, pruning, or abstention.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))


def _clean_ttl(value) -> int | None:
    """Normalize a persisted TTL so malformed input cannot poison cleanup."""
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _clean_tags(value) -> list[str]:
    """Normalize tag containers without turning a malformed string into chars."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        return []
    tags: list[str] = []
    for item in values:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _embed_safely(engine, text: str) -> list[float] | None:
    """Return a valid vector when the embedder works; keep keyword recall alive otherwise."""
    try:
        return _clean_embedding(engine.embed(text))
    except Exception:
        logger.warning("embedding failed for memory (stored without vector)", exc_info=True)
        return None


def _try_index_graph(backend, memory: Memory) -> None:
    from luminary_memory.recall.graph import index_memory_entities

    try:
        index_memory_entities(backend, memory)
        if getattr(memory, "needs_reindex", False):
            memory.needs_reindex = False
            backend.update(memory)
    except Exception:  # noqa: BLE001 -- graph indexing is best-effort; never abort ingest
        logger.warning("graph indexing failed for memory %s (non-fatal)", memory.id)
        try:
            memory.needs_reindex = True
            backend.update(memory)
        except Exception:
            logger.debug("could not mark memory %s for graph reindex", memory.id, exc_info=True)

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
        scope: dict | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
    ):
        self.settings = settings or Settings()
        if db_path is not None:
            self.settings.db_path = db_path
        if ingest_whitelist is not None:
            self.settings.ingest_whitelist = ingest_whitelist

        self.backend = backend or get_backend(self.settings)
        self.whitelist = WhitelistFilter(self.settings.ingest_whitelist)
        self.engine = engine or FastembedEngine(model_name=self.settings.embedding_model)
        requested_scope = dict(scope or {})
        requested_scope.update(
            {
                key: value
                for key, value in {
                    "user_id": user_id,
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                }.items()
                if value is not None
            }
        )
        self.scope = normalize_scope(requested_scope)
        # Never leave enricher None: ingest() calls .enrich() unconditionally.
        # Without a custom enricher, fall back to NoopEnricher (safe passthrough).
        self.enricher = enricher or NoopEnricher()

    def _scope_for(self, requested: Mapping | None = None) -> dict[str, str]:
        """Merge a request scope without allowing a bound scope override.

        A client constructed for one identity is a capability boundary.  It
        may refine that identity (for example by adding a session), but it
        must never be able to switch users/workspaces by passing a different
        value to an individual operation.
        """
        requested_scope = normalize_scope(requested)
        for field, bound_value in self.scope.items():
            requested_value = requested_scope.get(field)
            if requested_value is not None and requested_value != bound_value:
                raise PermissionError(
                    f"requested {field} does not match the client's bound scope"
                )
        merged = dict(self.scope)
        merged.update(requested_scope)
        return merged

    def _assert_mutable(self, memory: Memory) -> None:
        """Require exact ownership for mutations made by a bound client.

        The scope_include_global read-compatibility switch must not turn a
        visible global row into a row that a tenant can rewrite, retract, or
        delete.
        """
        if self.scope and not memory_matches_scope(
            memory,
            self.scope,
            include_global=False,
            active_only=False,
        ):
            raise PermissionError("memory is outside the client's mutable scope")

    def _is_mutable_scope(self, memory: Memory) -> bool:
        """Return whether a row may receive access/lifecycle mutations.

        Scoped clients may read compatibility-visible global rows, but even a
        read-side access bump is a mutation. Keeping this predicate separate
        from the read visibility predicate prevents recall from changing a
        shared row's access count or importance on behalf of one tenant.
        """
        return not self.scope or memory_matches_scope(
            memory,
            self.scope,
            include_global=False,
            active_only=False,
        )

    def _effective_scope(self, **values) -> dict[str, str]:
        return self._scope_for(values)

    def _record_event(
        self,
        event_type: str,
        memory_id: int | None,
        before: Memory | None = None,
        after: Memory | None = None,
        actor: str | None = "memory-client",
    ) -> None:
        try:
            self.backend.record_event(
                event_type,
                memory_id,
                before=_snapshot(before),
                after=_snapshot(after),
                actor=actor,
            )
        except Exception:
            logger.warning("memory event recording failed for %s", memory_id, exc_info=True)

    def _record_evidence(self, memory: Memory, extractor: str = "direct") -> None:
        quote = (memory.evidence_quote or memory.content or "").strip()
        if not quote or memory.id is None:
            return
        try:
            self.backend.add_evidence(
                memory.id,
                quote,
                source_id=memory.source_id or memory.source,
                observed_at=memory.observed_at,
                extractor=extractor,
                confidence=float(
                    memory.confidence if memory.confidence is not None else 1.0
                ),
            )
        except Exception:
            logger.warning("evidence recording failed for %s", memory.id, exc_info=True)

    def _sync_claim_status(
        self,
        memory_id: int | None,
        status: str,
        valid_to: str | None = None,
    ) -> None:
        if memory_id is None:
            return
        sync = getattr(self.backend, "sync_claim_status", None)
        if not callable(sync):
            return
        try:
            sync(memory_id, status, valid_to=valid_to)
        except Exception:
            logger.warning("claim status sync failed for %s", memory_id, exc_info=True)

    def _record_episode_and_claims(
        self,
        memory: Memory,
        source_text: str,
        claims: list[dict] | None = None,
        episode_id: str | None = None,
    ) -> None:
        """Persist immutable source context plus validated atomic claims."""
        if memory.id is None:
            return
        episode_id = episode_id or f"memory:{memory.id}"
        try:
            self.backend.record_episode(
                episode_id,
                source_text,
                source=memory.source,
                metadata=memory.metadata,
                user_id=memory.user_id,
                session_id=memory.session_id,
                workspace_id=memory.workspace_id,
                agent_id=memory.agent_id,
                observed_at=memory.observed_at,
            )
        except Exception:
            logger.warning("episode ledger write failed for %s", memory.id, exc_info=True)
            return

        # Claims are independent ledger rows. One malformed/external claim
        # must not prevent later valid claims from being retained.
        for claim in claims or []:
            try:
                claim_row = dict(claim)
                claim_row["source_episode_id"] = episode_id
                claim_row.setdefault("observed_at", memory.observed_at)
                claim_row.setdefault("valid_from", memory.valid_from)
                claim_row.setdefault("status", memory.status)
                self.backend.add_claim(
                    memory.id,
                    claim_row,
                    user_id=memory.user_id,
                    session_id=memory.session_id,
                    workspace_id=memory.workspace_id,
                    agent_id=memory.agent_id,
                )
            except Exception:
                logger.warning(
                    "claim ledger write failed for %s; continuing with later claims",
                    memory.id,
                    exc_info=True,
                )

    def _find_exact_duplicate(self, content_hash: str, scope: dict[str, str]) -> Memory | None:
        finder = getattr(self.backend, "find_by_hash", None)
        if callable(finder):
            try:
                found = finder(content_hash, scope=scope)
                if found is not None and memory_matches_scope(
                    found, scope, include_global=False, active_only=True
                ):
                    return found
            except Exception:
                logger.debug("backend hash lookup failed", exc_info=True)
        for existing in self.backend.all():
            existing_hash = existing.content_hash or _content_hash(existing.content)
            if existing_hash == content_hash and memory_matches_scope(
                existing, scope, include_global=False, active_only=True
            ):
                return existing
        return None

    def ingest(
        self,
        text: str,
        tags: list[str] | None = None,
        source: str | None = None,
        metadata: dict | None = None,
        enrich: bool = True,
        importance: float | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        observed_at: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        status: str = "active",
        confidence: float | None = None,
        evidence_quote: str | None = None,
        source_id: str | None = None,
        claim_key: str | None = None,
        supersedes_id: int | None = None,
    ) -> int | None:
        text = str(text or "").strip()
        if not text:
            return None
        if not self.whitelist.accepts(text):
            return None

        content, summary, entities, extra_tags = text, None, [], []
        importance_hint: float | None = importance
        enriched_claims: list[dict] = []
        if enrich and self.enricher is not None:
            enriched = self.enricher.enrich(text)
            if not bool(getattr(enriched, "worth_saving", True)):
                return None
            content, summary, entities, extra_tags = (
                enriched.content, enriched.summary, enriched.entities, enriched.tags,
            )
            raw_claims = getattr(enriched, "claims", []) or []
            enriched_claims = (
                [dict(claim) for claim in raw_claims if isinstance(claim, dict)]
                if isinstance(raw_claims, list)
                else []
            )
            if importance_hint is None:
                importance_hint = getattr(enriched, "importance", None)

        meta: dict = dict(metadata or {})
        if summary:
            meta["summary"] = summary
        if entities:
            meta["entities"] = entities
        if enriched_claims:
            meta["claims"] = enriched_claims

        effective_scope = self._effective_scope(
            user_id=user_id,
            session_id=session_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        now = _utc_now()
        observed = observed_at or meta.get("observed_at") or now
        quote = evidence_quote or meta.get("evidence_quote") or content
        # An extractor-provided quote is evidence only when it is grounded in
        # the original source.  Invalid quotes are discarded rather than
        # presented as provenance.
        if quote and quote not in text and quote not in content:
            quote = content
        source_identifier = source_id or meta.get("source_id") or source
        canonical_claim_key = claim_key or meta.get("claim_key")
        if enriched_claims:
            first_claim = enriched_claims[0]
            if canonical_claim_key is None:
                canonical_claim_key = "|".join(
                    str(first_claim.get(field) or "").strip().casefold()
                    for field in ("subject", "predicate", "polarity")
                )
            if evidence_quote is None and first_claim.get("evidence_quote"):
                quote = str(first_claim["evidence_quote"])
            if confidence is None and first_claim.get("confidence") is not None:
                confidence = first_claim.get("confidence")
            valid_from = valid_from or first_claim.get("valid_from")
            valid_to = valid_to or first_claim.get("valid_to")
        content = str(content or "").strip()
        if not content:
            return None
        if quote and quote not in text and quote not in content:
            quote = content
        confidence_value = _clean_unit_score(
            confidence if confidence is not None else meta.get("confidence", 1.0),
            default=1.0,
        )
        normalized_status = str(status or "active").lower()
        if normalized_status not in _VALID_MEMORY_STATUSES:
            raise ValueError(f"invalid memory status: {status!r}")
        base_tags = _clean_tags(tags)
        enriched_tags = _clean_tags(extra_tags)

        m = Memory(
            content=content,
            metadata=meta,
            source=source,
            tags=base_tags + [tag for tag in enriched_tags if tag not in base_tags],
            ttl_seconds=_clean_ttl(self.settings.ttl_default_seconds),
            embedding=_embed_safely(self.engine, content),
            user_id=effective_scope.get("user_id"),
            session_id=effective_scope.get("session_id"),
            workspace_id=effective_scope.get("workspace_id"),
            agent_id=effective_scope.get("agent_id"),
            observed_at=observed,
            valid_from=valid_from or meta.get("valid_from"),
            valid_to=valid_to or meta.get("valid_to"),
            status=normalized_status,
            confidence=confidence_value,
            evidence_quote=quote,
            source_id=source_identifier,
            claim_key=canonical_claim_key,
            supersedes_id=supersedes_id,
            content_hash=_content_hash(content),
        )
        if importance_hint is not None:
            # Enricher flagged this as a durable rule/fact: honor the hint
            # (overrides auto-estimate, which would otherwise give fresh
            # memories a low score).
            m.importance = _clean_unit_score(importance_hint)
        elif self.settings.importance_auto:
            from luminary_memory.lifecycle.importance import estimate_importance

            m.importance = estimate_importance(m)

        # Exact duplicates are suppressed before any semantic replacement.
        # This is scope-aware and leaves an audit event so health diagnostics
        # can still report repeated write attempts.
        duplicate = self._find_exact_duplicate(m.content_hash, effective_scope)
        if duplicate is not None:
            self._record_event("duplicate_suppressed", duplicate.id, before=duplicate, after=m)
            return duplicate.id

        # Explicit claim keys enable safe versioning.  A new value without an
        # explicit supersession is retained as a conflict instead of erasing
        # the prior claim.
        if canonical_claim_key:
            finder = getattr(self.backend, "find_by_claim_key", None)
            existing_claims = []
            if callable(finder):
                try:
                    existing_claims = finder(canonical_claim_key, scope=effective_scope)
                except Exception:  # noqa: BLE001
                    existing_claims = []
            for existing in existing_claims:
                if not memory_matches_scope(
                    existing, effective_scope, include_global=False, active_only=False
                ):
                    continue
                if existing.status not in {"active", "conflicted"}:
                    continue
                if supersedes_id is not None and existing.id == supersedes_id:
                    existing_before = self.backend.get(existing.id)
                    existing.status = "superseded"
                    existing.valid_to = existing.valid_to or now
                    self.backend.update(existing)
                    self._sync_claim_status(existing.id, "superseded", existing.valid_to)
                    self._record_event("supersede", existing.id, before=existing_before, after=existing)
                elif existing.content_hash != m.content_hash and supersedes_id is not None:
                    existing_before = self.backend.get(existing.id)
                    existing.status = "superseded"
                    existing.valid_to = existing.valid_to or now
                    self.backend.update(existing)
                    self._sync_claim_status(existing.id, "superseded", existing.valid_to)
                    self._record_event(
                        "supersede_chain", existing.id, before=existing_before, after=existing
                    )
                elif existing.content_hash != m.content_hash:
                    m.status = "conflicted"
                    if existing.status == "active":
                        existing_before = self.backend.get(existing.id)
                        existing.status = "conflicted"
                        self.backend.update(existing)
                        self._sync_claim_status(existing.id, "conflicted")
                        self._record_event("conflict", existing.id, before=existing_before, after=existing)

        # Anti-contradiction auto-replace: if a similar memory already exists
        # (embedding cosine >= replace_threshold), replace it instead of
        # adding a duplicate.  The mutation is now event-sourced and
        # scope-aware; callers that need true claim history should use
        # ``claim_key`` + ``supersedes_id`` instead.
        is_rule = contains_rule_keyword(content, self.settings.rule_keywords)
        should_try_replace = self.settings.rule_auto_replace and (
            float(m.importance) >= 0.8 or is_rule
        )
        if should_try_replace:
            replaced = self._maybe_replace_rule(
                content,
                m,
                source_text=text,
                claims=enriched_claims,
            )
            if replaced is not None:
                return replaced

        add_with_status = getattr(self.backend, "add_with_status", None)
        if callable(add_with_status):
            mid, inserted = add_with_status(m)
        else:  # pragma: no cover - compatibility for third-party backends
            mid, inserted = self.backend.add(m), True
        if not inserted:
            existing = self.backend.get(mid)
            self._record_event("duplicate_suppressed", mid, before=existing, after=m)
            return mid
        m.id = mid
        self._record_episode_and_claims(m, text, enriched_claims)
        self._record_event("ingest", mid, after=m)
        self._record_evidence(m, extractor="enricher" if enriched_claims else "direct")
        _try_index_graph(self.backend, m)
        return mid

    def _maybe_replace_rule(
        self,
        content: str,
        new_memory: Memory,
        *,
        source_text: str | None = None,
        claims: list[dict] | None = None,
    ) -> int | None:
        """Replace a similar existing memory with the new one (anti-contradiction).

        Returns the id of the replaced (updated) memory, or None when nothing
        similar exists. Similarity uses embedding cosine against existing
        memories above ``rule_auto_replace_threshold``.

        This path is deliberately scope-aware.  Embedding similarity is only
        a candidate signal; the previous row and the new row are retained in
        the append-only event log so an update cannot erase the evidence trail.
        """
        from luminary_memory.recall.dedup import cosine_similarity

        try:
            new_vec = new_memory.embedding or _embed_safely(self.engine, content)
            if not new_vec:
                return None
            best_id = None
            best_score = 0.0
            for existing in self.backend.all():
                if (
                    existing.embedding is None
                    or existing.id is None
                    or existing.status != "active"
                ):
                    continue
                if not memory_matches_scope(
                    existing,
                    {
                        key: value
                        for key, value in {
                            "user_id": new_memory.user_id,
                            "session_id": new_memory.session_id,
                            "workspace_id": new_memory.workspace_id,
                            "agent_id": new_memory.agent_id,
                        }.items()
                        if value is not None
                    },
                    include_global=False,
                ):
                    continue
                score = cosine_similarity(new_vec, existing.embedding)
                if score > best_score:
                    best_score = score
                    best_id = existing.id
            threshold = float(self.settings.rule_auto_replace_threshold)
            if best_id is not None and best_score >= threshold:
                existing = self.backend.get(best_id)
                if existing is not None:
                    before = self.backend.get(best_id)
                    existing.content = content
                    existing.importance = max(existing.importance, new_memory.importance)
                    existing.embedding = new_vec
                    existing.metadata = dict(new_memory.metadata)
                    existing.tags = list(new_memory.tags)
                    existing.source = new_memory.source
                    existing.updated_at = _utc_now()
                    existing.observed_at = new_memory.observed_at
                    existing.valid_from = new_memory.valid_from
                    existing.valid_to = new_memory.valid_to
                    existing.status = new_memory.status
                    existing.claim_key = new_memory.claim_key
                    existing.supersedes_id = new_memory.supersedes_id
                    existing.evidence_quote = new_memory.evidence_quote
                    existing.source_id = new_memory.source_id
                    existing.content_hash = new_memory.content_hash
                    existing.confidence = new_memory.confidence
                    existing.needs_reindex = False
                    self.backend.update(existing)
                    # Rule replacement is an in-place compatibility path, but
                    # it still represents a new source observation. Preserve
                    # that observation under a stable per-version episode ID
                    # and retire any old structured claims before appending
                    # the new ones. Without this, the memory text changes
                    # while the raw lineage silently remains the old fact.
                    self._sync_claim_status(best_id, "superseded", _utc_now())
                    self._record_episode_and_claims(
                        existing,
                        source_text or content,
                        claims,
                        episode_id=f"memory:{best_id}:replace:{new_memory.content_hash}",
                    )
                    self._record_event("rule_replace", best_id, before=before, after=existing)
                    self._record_evidence(existing, extractor="rule-replace")
                    _try_index_graph(self.backend, existing)
                    return best_id
            return None
        except Exception:  # noqa: BLE001 -- best-effort replace
            return None

    def ingest_batch(
        self,
        texts: list[str],
        tags: list[list[str] | None] | None = None,
        source: str | None = None,
        metadata: list[dict | None] | None = None,
        enrich: bool = True,
        importance: float | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        observed_at: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        status: str = "active",
        confidence: float | None = None,
        evidence_quote: str | None = None,
        source_id: str | None = None,
        claim_key: str | None = None,
        supersedes_id: int | None = None,
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
        if metadata is not None and len(metadata) != n:
            raise ValueError("metadata length must match texts length")
        tag_lists: list[list[str] | None] = list(tags) if tags is not None else [None] * n
        metadata_list: list[dict | None] = list(metadata) if metadata is not None else [None] * n
        normalized_status = str(status or "active").lower()
        if normalized_status not in _VALID_MEMORY_STATUSES:
            raise ValueError(f"invalid memory status: {status!r}")

        # Enrich per item, track which survive whitelist.
        prepared: list[tuple[int, str, str, list[str], dict, dict]] = []
        result: list[int | None] = [None] * n
        enriched_contents: list[str] = []
        enriched_idx_map: list[int] = []  # position in enriched_contents -> orig idx

        for i, raw_text in enumerate(texts):
            raw_text = str(raw_text or "").strip()
            if not self.whitelist.accepts(raw_text):
                continue
            content, summary, entities, extra_tags = raw_text, None, [], []
            enriched_claims: list[dict] = []
            if enrich and self.enricher is not None:
                enriched = self.enricher.enrich(raw_text)
                if not bool(getattr(enriched, "worth_saving", True)):
                    continue
                content, summary, entities, extra_tags = (
                    enriched.content, enriched.summary, enriched.entities, enriched.tags,
                )
            content = str(content or "").strip()
            if not content:
                continue
            raw_metadata = metadata_list[i]
            if raw_metadata is not None and not isinstance(raw_metadata, dict):
                raise ValueError("each metadata item must be a dict or None")
            item_metadata: dict = dict(raw_metadata or {})
            if summary:
                item_metadata["summary"] = summary
            if entities:
                item_metadata["entities"] = entities
            if enrich and self.enricher is not None:
                raw_claims = getattr(enriched, "claims", []) or []
                if isinstance(raw_claims, list):
                    enriched_claims = [dict(claim) for claim in raw_claims if isinstance(claim, dict)]
            if enriched_claims:
                item_metadata["claims"] = enriched_claims
                first_claim = enriched_claims[0]
                if claim_key is None and not item_metadata.get("claim_key"):
                    parts = [
                        str(first_claim.get(field) or "").strip().casefold()
                        for field in ("subject", "predicate", "polarity")
                    ]
                    if all(parts):
                        item_metadata["claim_key"] = "|".join(parts)
                if (
                    confidence is None
                    and item_metadata.get("confidence") is None
                    and first_claim.get("confidence") is not None
                ):
                    item_metadata["confidence"] = first_claim.get("confidence")
                if valid_from is None and item_metadata.get("valid_from") is None:
                    item_metadata["valid_from"] = first_claim.get("valid_from")
                if valid_to is None and item_metadata.get("valid_to") is None:
                    item_metadata["valid_to"] = first_claim.get("valid_to")
                if evidence_quote is None and not item_metadata.get("evidence_quote"):
                    item_metadata["evidence_quote"] = first_claim.get("evidence_quote")
            item_quote = str(item_metadata.get("evidence_quote") or evidence_quote or raw_text)
            if item_quote not in raw_text and item_quote not in str(content or ""):
                item_quote = str(content or raw_text)
            item_metadata["evidence_quote"] = item_quote
            effective_scope = self._effective_scope(
                user_id=user_id,
                session_id=session_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            base_tags = _clean_tags(tag_lists[i])
            enriched_tags = _clean_tags(extra_tags)
            merged_tags = base_tags + [tag for tag in enriched_tags if tag not in base_tags]
            # Keep the immutable raw episode separate from the enriched
            # memory content.  A summary/quote is useful for recall, but it
            # must never replace the original source lineage.
            prepared.append((i, raw_text, content, merged_tags, item_metadata, effective_scope))
            enriched_contents.append(content)
            enriched_idx_map.append(i)

        if not prepared:
            return result
        raw_sources = {item[0]: item[1] for item in prepared}

        # Single embedding pass.
        embeddings: list[list[float]]
        try:
            batch_fn = getattr(self.engine, "embed_batch", None)
            if batch_fn is not None:
                embeddings = batch_fn(enriched_contents)
            else:
                embeddings = [self.engine.embed(t) for t in enriched_contents]
        except Exception:  # noqa: BLE001 -- embedding failure falls back per-item
            embeddings = [_embed_safely(self.engine, t) for t in enriched_contents]
        if len(embeddings) != len(prepared):
            embeddings = [_embed_safely(self.engine, t) for t in enriched_contents]

        # Build memories for surviving items — reuse ingest() semantics per
        # item: importance hint + auto-estimate + rule auto-replace. Each item
        # is still covered by the single embed_batch above (emb already holds
        # the final content's embedding), so this stays batch-efficient while
        # honouring the anti-contradiction + pin contract.
        result: list[int | None]
        memories: list[Memory] = []
        mem_orig_idx: list[int] = []
        for (orig_idx, _raw_text, content, merged_tags, item_metadata, effective_scope), emb in zip(prepared, embeddings):
            importance_hint: float | None = importance
            # Re-run enricher importance hint for this item's content (rule
            # keywords check is cheap and we already have the enriched text).
            if importance_hint is None and enrich and self.enricher is not None and hasattr(self.enricher, "rule_keywords"):
                hint_text = f"{item_metadata.get('summary') or ''} {content}".upper()
                if contains_rule_keyword(hint_text, self.enricher.rule_keywords):
                    importance_hint = float(self.enricher.rule_importance)  # type: ignore[attr-defined]
            confidence_value = _clean_unit_score(
                confidence if confidence is not None else item_metadata.get("confidence", 1.0),
                default=1.0,
            )
            m = Memory(
                content=content,
                metadata=item_metadata,
                source=source,
                tags=merged_tags,
                ttl_seconds=_clean_ttl(self.settings.ttl_default_seconds),
                embedding=_clean_embedding(emb),
                user_id=effective_scope.get("user_id"),
                session_id=effective_scope.get("session_id"),
                workspace_id=effective_scope.get("workspace_id"),
                agent_id=effective_scope.get("agent_id"),
                observed_at=observed_at or item_metadata.get("observed_at") or _utc_now(),
                valid_from=valid_from or item_metadata.get("valid_from"),
                valid_to=valid_to or item_metadata.get("valid_to"),
                status=normalized_status,
                confidence=confidence_value,
                evidence_quote=item_metadata.get("evidence_quote") or content,
                source_id=source_id or item_metadata.get("source_id") or source,
                claim_key=claim_key or item_metadata.get("claim_key"),
                supersedes_id=supersedes_id,
                content_hash=_content_hash(content),
            )
            if importance_hint is not None:
                m.importance = _clean_unit_score(importance_hint)
            elif self.settings.importance_auto:
                from luminary_memory.lifecycle.importance import estimate_importance

                m.importance = estimate_importance(m)
            memories.append(m)
            mem_orig_idx.append(orig_idx)

        # Filter through auto-replace (rule-aware) — matching ingest() guard.
        to_insert: list[Memory] = []
        to_insert_idx: list[int] = []
        for mem, orig_idx in zip(memories, mem_orig_idx):
            duplicate = self._find_exact_duplicate(mem.content_hash, {
                key: value
                for key, value in {
                    "user_id": mem.user_id,
                    "session_id": mem.session_id,
                    "workspace_id": mem.workspace_id,
                    "agent_id": mem.agent_id,
                }.items()
                if value is not None
            })
            if duplicate is not None:
                self._record_event("duplicate_suppressed", duplicate.id, before=duplicate, after=mem)
                result[orig_idx] = duplicate.id
                continue
            if mem.claim_key:
                finder = getattr(self.backend, "find_by_claim_key", None)
                mem_scope = {
                    key: value
                    for key, value in {
                        "user_id": mem.user_id,
                        "session_id": mem.session_id,
                        "workspace_id": mem.workspace_id,
                        "agent_id": mem.agent_id,
                    }.items()
                    if value is not None
                }
                try:
                    existing_claims = finder(mem.claim_key, scope=mem_scope) if finder else []
                except Exception:
                    logger.debug("batch claim lookup failed", exc_info=True)
                    existing_claims = []
                for existing in existing_claims:
                    if not memory_matches_scope(
                        existing, mem_scope, include_global=False, active_only=False
                    ):
                        continue
                    if existing.status not in {"active", "conflicted"}:
                        continue
                    if mem.supersedes_id is not None:
                        before = self.backend.get(existing.id)
                        existing.status = "superseded"
                        existing.valid_to = existing.valid_to or _utc_now()
                        self.backend.update(existing)
                        self._sync_claim_status(existing.id, "superseded", existing.valid_to)
                        self._record_event("supersede", existing.id, before=before, after=existing)
                    elif existing.content_hash != mem.content_hash:
                        mem.status = "conflicted"
                        if existing.status == "active":
                            before = self.backend.get(existing.id)
                            existing.status = "conflicted"
                            self.backend.update(existing)
                            self._sync_claim_status(existing.id, "conflicted")
                            self._record_event("conflict", existing.id, before=before, after=existing)
            content = mem.content
            is_rule = contains_rule_keyword(content, self.settings.rule_keywords)
            should_try = self.settings.rule_auto_replace and (
                float(mem.importance) >= 0.8 or is_rule
            )
            if should_try:
                replaced = self._maybe_replace_rule(
                    content,
                    mem,
                    source_text=raw_sources[orig_idx],
                    claims=list(mem.metadata.get("claims") or []),
                )
                if replaced is not None:
                    result[orig_idx] = replaced
                    continue
            to_insert.append(mem)
            to_insert_idx.append(orig_idx)

        if to_insert:
            add_many_with_status = getattr(self.backend, "add_many_with_status", None)
            if callable(add_many_with_status):
                added = add_many_with_status(to_insert)
            else:  # pragma: no cover - compatibility for third-party backends
                added = [(mid, True) for mid in self.backend.add_many(to_insert)]
            for mem, (mid, inserted), orig_idx in zip(to_insert, added, to_insert_idx):
                mem.id = mid
                if not inserted:
                    existing = self.backend.get(mid)
                    self._record_event(
                        "duplicate_suppressed", mid, before=existing, after=mem
                    )
                    result[orig_idx] = mid
                    continue
                self._record_event("ingest", mid, after=mem)
                self._record_episode_and_claims(
                    mem,
                    raw_sources[orig_idx],
                    list(mem.metadata.get("claims") or []),
                )
                self._record_evidence(mem, extractor="batch")
                _try_index_graph(self.backend, mem)
                result[orig_idx] = mid
        return result

    def get(self, id: int, scope: dict | None = None) -> Memory | None:
        memory = self.backend.get(id)
        effective_scope = self._scope_for(scope)
        if memory is not None and effective_scope and not memory_matches_scope(
            memory,
            effective_scope,
            include_global=bool(getattr(self.settings, "scope_include_global", True)),
            active_only=False,
        ):
            return None
        return memory

    def supersede(
        self,
        memory_id: int,
        content: str,
        *,
        evidence_quote: str | None = None,
        observed_at: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        source: str | None = None,
        source_id: str | None = None,
        metadata: dict | None = None,
        tags: list[str] | None = None,
    ) -> int | None:
        """Create a new version of a claim while preserving the old row."""
        previous = self.get(memory_id)
        if previous is None:
            raise ValueError(f"memory {memory_id} does not exist in this scope")
        self._assert_mutable(previous)
        if not previous.claim_key:
            raise ValueError("supersede requires the previous memory to have a claim_key")
        return self.ingest(
            content,
            tags=list(tags if tags is not None else previous.tags),
            source=source if source is not None else previous.source,
            metadata=dict(metadata or previous.metadata),
            enrich=False,
            importance=previous.importance,
            user_id=previous.user_id,
            session_id=previous.session_id,
            workspace_id=previous.workspace_id,
            agent_id=previous.agent_id,
            observed_at=observed_at,
            valid_from=valid_from,
            valid_to=valid_to,
            evidence_quote=evidence_quote or content,
            source_id=source_id or previous.source_id,
            claim_key=previous.claim_key,
            supersedes_id=memory_id,
        )

    def resolve_conflict(
        self,
        memory_id: int,
        *,
        status: str = "active",
        evidence_quote: str | None = None,
        source_id: str | None = None,
    ) -> None:
        """Explicitly resolve a conflicted claim; never silently merge it."""
        if status not in {"active", "conflicted", "superseded", "expired"}:
            raise ValueError("invalid conflict resolution status")
        memory = self.get(memory_id)
        if memory is None:
            raise ValueError(f"memory {memory_id} does not exist in this scope")
        before = self.backend.get(memory_id)
        memory.status = status
        if evidence_quote:
            memory.evidence_quote = evidence_quote
        if source_id:
            memory.source_id = source_id
        self.update(memory)
        self._sync_claim_status(memory_id, status)
        self._record_event("resolve_conflict", memory_id, before=before, after=memory)

    def retract(self, memory_id: int, *, reason: str | None = None) -> None:
        """Soft-delete a claim while retaining the row and audit history."""
        memory = self.get(memory_id)
        if memory is None:
            raise ValueError(f"memory {memory_id} does not exist in this scope")
        before = self.backend.get(memory_id)
        memory.status = "deleted"
        if reason:
            memory.metadata = dict(memory.metadata or {})
            memory.metadata["retraction_reason"] = reason
        self.update(memory)
        self._record_event("retract", memory_id, before=before, after=memory)

    def update(self, memory: Memory) -> None:
        """Update a memory and keep every derived index/provenance in sync."""
        if memory.id is None:
            raise ValueError("cannot update a memory without an id")
        before = self.backend.get(memory.id)
        if before is None:
            raise ValueError(f"memory {memory.id} does not exist")
        self._assert_mutable(before)
        self._assert_mutable(memory)
        changed_content = before.content != memory.content
        claim_status_after_update: str | None = None
        if changed_content:
            memory.content = str(memory.content or "").strip()
            if not memory.content:
                raise ValueError("memory content cannot be empty")
            memory.embedding = _embed_safely(self.engine, memory.content)
            memory.content_hash = _content_hash(memory.content)
            quote = str(memory.evidence_quote or "").strip()
            memory.evidence_quote = quote if quote and quote in memory.content else memory.content
            memory.needs_reindex = False
            # Updating a row in place must not leave old structured claims
            # attached to new content. Callers that need a new claim lineage
            # should use supersede(); ordinary updates retire the old claim
            # rows and clear the stale canonical key.
            claim_status_after_update = "superseded"
            if memory.claim_key == before.claim_key:
                memory.claim_key = None
                memory.metadata = dict(memory.metadata or {})
                memory.metadata.pop("claims", None)
        memory.updated_at = _utc_now()
        memory.status = memory.status or "active"
        if memory.status in {"deleted", "expired", "superseded"}:
            claim_status_after_update = memory.status
        memory.importance = _clean_unit_score(memory.importance)
        memory.confidence = _clean_unit_score(memory.confidence, default=1.0)
        # Recompute canonical persisted fields even when the caller did not
        # change content. A long-lived caller may hand us a stale/tampered
        # Memory object whose hash, score, embedding, or TTL no longer agrees
        # with its content.
        memory.content = str(memory.content or "").strip()
        if not memory.content:
            raise ValueError("memory content cannot be empty")
        memory.content_hash = _content_hash(memory.content)
        memory.metadata = dict(memory.metadata or {}) if isinstance(memory.metadata, dict) else {}
        memory.tags = _clean_tags(memory.tags)
        memory.embedding = _clean_embedding(memory.embedding)
        memory.ttl_seconds = _clean_ttl(memory.ttl_seconds)
        quote = str(memory.evidence_quote or "").strip()
        memory.evidence_quote = quote if quote and quote in memory.content else memory.content
        if memory.status not in _VALID_MEMORY_STATUSES:
            raise ValueError(f"invalid memory status: {memory.status!r}")
        self.backend.update(memory)
        # Record the mutation only after the durable row update succeeds; an
        # event must never claim a state transition that was rolled back.
        self._record_event("update", memory.id, before=before, after=memory)
        if claim_status_after_update is not None:
            self._sync_claim_status(memory.id, claim_status_after_update, _utc_now())
        self._record_evidence(memory, extractor="update")
        if changed_content or before.tags != memory.tags:
            _try_index_graph(self.backend, memory)

    def delete(self, id: int) -> None:
        """Delete a memory, recording the pre-delete snapshot first."""
        before = self.backend.get(id)
        if before is None:
            return
        self._assert_mutable(before)
        self._record_event("delete", id, before=before)
        self._sync_claim_status(id, "deleted", _utc_now())
        self.backend.delete(id)

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        scope: dict | None = None,
    ) -> list[Memory]:
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
        effective_scope = self._scope_for(scope)
        recent = getattr(self.backend, "recent", None)
        if recent is not None:
            try:
                return recent(
                    limit=eff_limit,
                    offset=o,
                    scope=effective_scope,
                    include_global=bool(getattr(self.settings, "scope_include_global", True)),
                )
            except TypeError:
                if not effective_scope and bool(
                    getattr(self.settings, "scope_include_global", True)
                ):
                    return recent(limit=eff_limit, offset=o)
        # fallback for backends without SQL pagination
        from luminary_memory.recall.temporal import _parse_dt

        all_mem = [
            m for m in self.backend.all()
            if memory_matches_scope(
                m,
                effective_scope,
                include_global=bool(getattr(self.settings, "scope_include_global", True)),
            )
        ]
        all_mem.sort(key=lambda m: (_parse_dt(m.created_at or ""), -(m.id or 0)), reverse=True)
        sliced = all_mem[o:]
        return sliced if eff_limit is None else sliced[:eff_limit]

    def search(
        self,
        query: str,
        limit: int = 10,
        scope: dict | None = None,
    ) -> list[tuple[Memory, float]]:
        """Direct keyword (FTS) search without the full recall pipeline.

        ``limit=0`` means unlimited; negative limits raise ``ValueError``.
        """
        n = int(limit)
        if n < 0:
            raise ValueError("limit must be >= 0 (0 means unlimited)")
        eff = None if n == 0 else n
        if not (query or "").strip():
            return []
        # Resolve scope outside the backend fallback handlers.  A scope
        # violation is a caller error/security boundary, not an empty search
        # result and must never be swallowed as a backend failure.
        effective_scope = self._scope_for(scope)
        try:
            return self.backend.keyword_search(
                query,
                limit=eff,
                scope=effective_scope,
                include_global=bool(getattr(self.settings, "scope_include_global", True)),
            )
        except TypeError:
            try:
                include_global = bool(getattr(self.settings, "scope_include_global", True))
                needs_local_filter = bool(effective_scope) or not include_global
                fallback = self.backend.keyword_search(
                    query,
                    limit=None if needs_local_filter else eff,
                )
                filtered = [
                    row
                    for row in fallback
                    if not needs_local_filter
                    or memory_matches_scope(
                        row[0],
                        effective_scope,
                        include_global=include_global,
                    )
                ]
                return filtered if eff is None else filtered[:eff]
            except Exception:  # noqa: BLE001
                return []
        except Exception:  # noqa: BLE001
            return []

    def stats(self) -> dict:
        """Store statistics: count, oldest/newest, avg importance, tags."""
        import statistics

        all_mem = self.list(limit=0)
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
        """Return active, scope-visible rows in the public client view."""
        # Client count is the active, scope-visible view and therefore stays
        # consistent with list(). Backends still expose raw row counts for
        # low-level diagnostics and migration checks.
        return len(self.list(limit=0))

    def run_lifecycle(self, semantic: bool | None = None) -> dict[str, int]:
        from luminary_memory.lifecycle.runner import run_lifecycle

        # Global rows are visible to a scoped client only for read
        # compatibility. Lifecycle is mutating, so it must never prune,
        # consolidate, or reindex those shared rows on a tenant's behalf.
        mutation_include_global = bool(
            getattr(self.settings, "scope_include_global", True)
        ) and not bool(self.scope)
        return run_lifecycle(
            self.backend,
            self.settings,
            semantic=semantic,
            scope=self.scope,
            include_global=mutation_include_global,
        )

    def _reestimate_accessed_importance(self, ids: list[int]) -> int:
        """Re-estimate importance for *ids* right after a recall access bump.

        Uses the same ``estimate_importance`` as the lifecycle so behavior is
        consistent: access_count and last_accessed_at (both just bumped by
        ``touch_memories``) raise a frequently-recalled memory's importance, so
        ``top_by_importance`` surfaces it in the next turn's query recall
        block. Pinned rules (>= pin threshold) are never downgraded. Batched —
        one read (get_many) + one write (update_importances).
        """
        from luminary_memory.lifecycle.importance import estimate_importance

        pin_threshold = float(getattr(self.settings, "rule_importance", 0.9) or 0.9)
        get_many = getattr(self.backend, "get_many", None)
        if get_many is None:
            return 0
        by_id = get_many(ids)
        if not by_id:
            return 0
        max_access = max(
            (int(getattr(m, "access_count", 0) or 0) for m in by_id.values()),
            default=1,
        )
        changed: list[tuple[float, int]] = []
        for mid, m in by_id.items():
            if float(getattr(m, "importance", 0.0) or 0.0) >= pin_threshold:
                continue
            new_imp = estimate_importance(m, max_access=max_access)
            if abs(float(m.importance or 0) - new_imp) > 1e-6:
                changed.append((float(new_imp), int(mid)))
        if not changed:
            return 0
        bulk = getattr(self.backend, "update_importances", None)
        if bulk is not None:
            bulk(changed)
            return len(changed)
        for new_imp, mid in changed:
            m = by_id.get(mid)
            if m is not None:
                m.importance = new_imp
                self.backend.update(m)
        return len(changed)

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
        # Health is an explicit diagnostic operation, so it must inspect the
        # full active scope. Sampling 500 rows made the report claim a false
        # store size and hide long-tail staleness in long-lived deployments.
        memories = self.list(limit=0)
        total = len(memories)
        if total == 0:
            return {
                "score": 100.0,
                "dimensions": {},
                "recommendations": ["store is empty — nothing to worry about"],
            }

        # --- duplicate_rate -------------------------------------------------
        dup_count = 0
        # Build inverted index: token -> set of memory indices. Two memories
        # whose Jaccard similarity exceeds the threshold MUST share at least
        # one token, so the candidate set is the union of co-occurring tokens.
        # This turns O(N²) into per-token-bucket comparisons, lossless.
        token_to_idx: dict[str, set[int]] = {}
        tokenized: list[set[str] | None] = []
        for i, m in enumerate(memories):
            toks = set(str(m.content).lower().split())
            if not toks:
                tokenized.append(None)
                continue
            tokenized.append(toks)
            for t in toks:
                token_to_idx.setdefault(t, set()).add(i)
        for i, m in enumerate(memories):
            a_tokens = tokenized[i]
            if not a_tokens:
                continue
            candidates: set[int] = set()
            for t in a_tokens:
                candidates.update(token_to_idx.get(t, ()))
            candidates.discard(i)
            for j in candidates:
                if j <= i:
                    continue
                b_tokens = tokenized[j]
                if not b_tokens:
                    continue
                jac = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
                if jac > self.settings.dedup_jaccard_threshold:
                    dup_count += 1
                    # The original broke per-anchor (short-circuited). We
                    # still count each anchor at most once, but now we only
                    # scan candidates instead of the full tail. Mark j so the
                    # outer loop skips spent anchors (simulates the original
                    # break-per-anchor logic).
                    break
        # Exact duplicates are now suppressed at write time.  Count the
        # suppressed attempts as pollution pressure too, otherwise the new
        # safe dedup path would make health look perfect after a duplicate
        # storm simply because only one row survived.
        try:
            from luminary_memory.recall.graph import _exec

            conn = getattr(self.backend, "conn", None)
            if conn is not None:
                scoped_ids = [m.id for m in memories if m.id is not None]
                if self.scope and not scoped_ids:
                    suppressed = 0
                elif self.scope:
                    suppressed = 0
                    # SQLite's default bind limit is commonly 999; count in
                    # chunks so a scoped long-lived store remains auditable.
                    for start in range(0, len(scoped_ids), 900):
                        chunk = scoped_ids[start : start + 900]
                        placeholders = ",".join("?" for _ in chunk)
                        suppressed += _exec(
                            self.backend,
                            "SELECT COUNT(*) FROM memory_events "
                            f"WHERE event_type = 'duplicate_suppressed' AND memory_id IN ({placeholders})",
                            chunk,
                        ).fetchone()[0]
                else:
                    suppressed = _exec(
                        self.backend,
                        "SELECT COUNT(*) FROM memory_events WHERE event_type = 'duplicate_suppressed'"
                    ).fetchone()[0]
                dup_count += min(total, int(suppressed or 0))
        except Exception:
            logger.debug("duplicate event count unavailable for backend", exc_info=True)
        dup_rate = dup_count / total
        dup_health = max(0.0, 100.0 * (1.0 - dup_rate * 5))  # 20% dupes → 0

        # --- staleness ------------------------------------------------------
        from datetime import datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=30)
        stale_count = 0
        for m in memories:
            if not m.last_accessed_at:
                # Never-read memories are stale for this diagnostic; treating
                # them as fresh hides accumulating noise.
                stale_count += 1
                continue
            try:
                ts = datetime.fromisoformat(m.last_accessed_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    stale_count += 1
            except Exception:  # noqa: BLE001 -- malformed timestamps are stale
                # A malformed access timestamp cannot prove freshness.
                stale_count += 1
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
                from luminary_memory.recall.graph import _exec
                from luminary_memory.scope import scope_sql

                scope_where, scope_params = scope_sql(
                    self.scope,
                    alias="m",
                    include_global=bool(getattr(self.settings, "scope_include_global", True)),
                )
                rel_count = _exec(
                    self.backend,
                    "SELECT COUNT(DISTINCT r.memory_id) FROM relations r "
                    f"JOIN memories m ON m.id = r.memory_id WHERE {scope_where}",
                    scope_params,
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

    def _mutable_memories(self, limit: int = 0) -> list[Memory]:
        """Return active rows that this client is allowed to mutate.

        ``list()`` intentionally includes compatibility-visible global rows for
        reads. Maintenance has a different contract: it must review only exact
        ownership, otherwise a shared row can be exposed to a tenant curator or
        repeatedly rejected by the mutation guard.
        """
        n = int(limit)
        if n < 0:
            raise ValueError("limit must be >= 0")
        effective_limit: int | None = None if n == 0 else n
        recent = getattr(self.backend, "recent", None)
        if recent is not None:
            try:
                rows = recent(
                    limit=effective_limit,
                    offset=0,
                    scope=self.scope,
                    include_global=False,
                )
                return [
                    row
                    for row in rows
                    if memory_matches_scope(
                        row,
                        self.scope,
                        include_global=False,
                        active_only=True,
                    )
                ]
            except TypeError:
                pass

        from luminary_memory.recall.temporal import _parse_dt

        rows = [
            memory
            for memory in self.backend.all()
            if memory_matches_scope(
                memory,
                self.scope,
                include_global=False,
                active_only=True,
            )
        ]
        rows.sort(key=lambda m: (_parse_dt(m.created_at or ""), -(m.id or 0)), reverse=True)
        return rows if effective_limit is None else rows[:effective_limit]

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

        # Maintenance can update/delete rows. Do not send compatibility-visible
        # global rows to a tenant's curator; mutation guards alone would make
        # the result dependent on swallowed PermissionErrors and would expose
        # shared data to an LLM unnecessarily.
        memories = self._mutable_memories(limit=0 if review_all else 500)
        if not memories:
            return {"reviewed": 0, "deleted": 0, "updated": 0}

        raw = self.enricher.review_memories(memories)
        data = _parse_enrichment_payload(raw)
        actions = data.get("actions")
        if not isinstance(actions, list):
            return {"reviewed": len(memories), "deleted": 0, "updated": 0, "error": "bad LLM response"}

        deleted = updated = skipped = 0
        by_id = {m.id: m for m in memories}
        for act in actions:
            if not isinstance(act, dict):
                continue
            try:
                mid = int(act.get("id"))
            except (TypeError, ValueError):
                continue
            if mid not in by_id:
                continue
            action = act.get("action")
            if action not in {"delete", "update"}:
                continue
            current = by_id[mid]
            raw_evidence = act.get("evidence_quote")
            evidence_quote = str(raw_evidence).strip() if raw_evidence else None
            source_id = str(act.get("source_id")).strip() if act.get("source_id") else None
            new_content = act.get("content")
            grounded_evidence = bool(
                evidence_quote
                and (
                    evidence_quote in current.content
                    or (isinstance(new_content, str) and evidence_quote in new_content)
                )
            )
            if getattr(self.settings, "evidence_required", False):
                is_core = any(tag in {"core", "rule"} for tag in (current.tags or []))
                if not (grounded_evidence or source_id) or (is_core and not bool(act.get("confirmed", False))):
                    skipped += 1
                    continue
            if action == "delete":
                try:
                    self.delete(int(mid))
                    deleted += 1
                except Exception:  # noqa: BLE001, S110
                    pass
            elif action == "update" and isinstance(new_content, str) and new_content.strip():
                try:
                    m = current
                    m.content = new_content.strip()
                    if grounded_evidence:
                        m.evidence_quote = evidence_quote
                    if source_id:
                        m.source_id = source_id
                    self.update(m)
                    updated += 1
                except Exception:  # noqa: BLE001, S110
                    pass
        result = {"reviewed": len(memories), "deleted": deleted, "updated": updated}
        if getattr(self.settings, "evidence_required", False):
            result["skipped"] = skipped
        return result

    def export(self, path, include_embeddings: bool = True) -> dict:
        """Export all memories to *path* (versioned JSON)."""
        from luminary_memory.export import export_memories

        return export_memories(
            self.backend,
            path,
            include_embeddings=include_embeddings,
            scope=self.scope,
            include_global=bool(getattr(self.settings, "scope_include_global", True)),
        )

    def import_memories(self, path) -> dict:
        """Import memories from *path* (recomputes embeddings when absent)."""
        from luminary_memory.export import import_memories

        try:
            return import_memories(
                self.backend,
                path,
                engine=self.engine,
                scope=self.scope,
                include_global=bool(getattr(self.settings, "scope_include_global", True)),
            )
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
        if getattr(self.backend, "conn", None) is None:
            return {"entities": entities, "relations": relations}
        try:
            from luminary_memory.recall.graph import _exec
            from luminary_memory.scope import scope_sql

            graph_limit = max(0, int(limit))
            scope_where, scope_params = scope_sql(
                self.scope,
                alias="m",
                include_global=bool(getattr(self.settings, "scope_include_global", True)),
                active_only=True,
            )
            rows = _exec(
                self.backend,
                "SELECT e.name, COUNT(DISTINCT r.source_id) + COUNT(DISTINCT r.target_id) AS degree, "
                "COUNT(DISTINCT r.memory_id) AS memories "
                "FROM entities e "
                "JOIN relations r ON r.source_id = e.id OR r.target_id = e.id "
                f"JOIN memories m ON m.id = r.memory_id AND {scope_where} "
                "GROUP BY e.id ORDER BY degree DESC LIMIT ?",
                (*scope_params, graph_limit),
            ).fetchall()
            for r in rows:
                entities.append({
                    "name": r[0], "degree": int(r[1] or 0), "memories": int(r[2] or 0),
                })
            rel_rows = _exec(
                self.backend,
                "SELECT s.name, t.name, MAX(r.weight) AS weight "
                "FROM relations r "
                "JOIN entities s ON s.id = r.source_id "
                "JOIN entities t ON t.id = r.target_id "
                f"JOIN memories m ON m.id = r.memory_id AND {scope_where} "
                "GROUP BY r.source_id, r.target_id "
                "ORDER BY weight DESC LIMIT ?",
                (*scope_params, graph_limit),
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
        tag_mode: str = "any",
        scope: dict | None = None,
        strict: bool | None = None,
        include_conflicted: bool = False,
    ) -> RecallResult:
        query = str(query or "").strip()
        n_limit = int(limit)
        if n_limit < 0:
            raise ValueError("limit must be >= 0 (0 means unlimited)")
        output_limit: int | None = None if n_limit == 0 else n_limit
        from luminary_memory.recall.dedup import dedup_jaccard
        from luminary_memory.recall.fusion import reciprocal_rank_fusion
        from luminary_memory.recall.graph import graph_recall
        from luminary_memory.recall.keyword import keyword_recall
        from luminary_memory.recall.semantic import semantic_recall
        from luminary_memory.recall.temporal import temporal_recall

        effective_scope = self._scope_for(scope)
        include_global = bool(getattr(self.settings, "scope_include_global", True))
        strict_policy = bool(
            getattr(self.settings, "strict_recall", False) if strict is None else strict
        )
        if tag_mode not in {"any", "all", "strict"}:
            raise ValueError("tag_mode must be one of: any, all, strict")
        if not query:
            return RecallResult(
                memories=[],
                scores=[],
                strategies_hit={},
                status="abstain" if strict_policy else "empty",
                reason="empty_query",
            )
        query_for_retrieval = _expand_query_aliases(query)

        budget = token_budget if token_budget is not None else self.settings.token_budget
        rrf_k = self.settings.rrf_k
        dedup_threshold = self.settings.dedup_jaccard_threshold
        cliff_threshold = self.settings.recall_cliff_threshold
        use_planner = bool(getattr(self.settings, "query_planner", True))
        planner_threshold = float(getattr(self.settings, "query_planner_keyword_threshold", 0.9))

        eff = output_limit
        temporal_limit = (eff * 2) if eff is not None else None
        enabled = None

        strategies: list[list[tuple]] = []
        # Order matters for planner temporal guard: keyword first.
        strat_fns = [
            (
                "semantic",
                lambda: semantic_recall(
                    self.backend,
                    self.engine,
                    query_for_retrieval,
                    limit=eff,
                    scope=effective_scope,
                    include_global=include_global,
                ),
            ),
            (
                "keyword",
                lambda: keyword_recall(
                    self.backend,
                    query_for_retrieval,
                    limit=eff,
                    scope=effective_scope,
                    include_global=include_global,
                ),
            ),
            (
                "temporal",
                lambda: temporal_recall(
                    self.backend,
                    limit=temporal_limit,
                    scope=effective_scope,
                    include_global=include_global,
                ),
            ),
            (
                "graph",
                lambda: graph_recall(
                    self.backend,
                    query_for_retrieval,
                    limit=eff,
                    scope=effective_scope,
                    include_global=include_global,
                ),
            ),
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
                kw_rows = strat_map["keyword"] = strat_fns[1][1]()
            except Exception:  # noqa: BLE001
                kw_rows = strat_map["keyword"] = []
            top_kw = float(kw_rows[0][1]) if kw_rows else None
            enabled = _plan(query_for_retrieval, keyword_top_score=top_kw, planner=True,
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

        # Scope/tag/status filtering happens before fusion and before any
        # fallback.  This is intentionally duplicated defensively for custom
        # backends whose search methods do not yet understand scope.
        allowed_ids: set[int] | None = None
        if tags:
            by_tags = getattr(self.backend, "by_tags", None)
            if callable(by_tags):
                try:
                    allowed_ids = by_tags(
                        list(tags),
                        match="all" if tag_mode in {"all", "strict"} else "any",
                        scope=effective_scope,
                        include_global=include_global,
                    )
                except TypeError:
                    candidate_ids = by_tags(list(tags))
                    allowed_ids = {
                        memory.id
                        for memory in self.backend.all()
                        if memory.id in candidate_ids
                        and memory_matches_scope(
                            memory,
                            effective_scope,
                            include_global=include_global,
                            active_only=False,
                        )
                    }
            else:
                wanted = set(tags)
                allowed_ids = {
                    m.id
                    for m in self.backend.all()
                    if m.id is not None
                    and memory_matches_scope(m, effective_scope, include_global=include_global)
                    and (wanted <= set(m.tags or []) if tag_mode in {"all", "strict"} else wanted & set(m.tags or []))
                }

        evidence_required = bool(getattr(self.settings, "evidence_required", False))

        def _has_required_evidence(memory: Memory) -> bool:
            """Accept only a quote grounded in the memory content."""
            quote = " ".join(str(memory.evidence_quote or "").split()).casefold()
            content = " ".join(str(memory.content or "").split()).casefold()
            return bool(quote and content and quote in content)

        def _is_current(memory: Memory) -> bool:
            if memory.status != "active" and not (include_conflicted and memory.status == "conflicted"):
                return False
            if not memory_matches_scope(
                memory,
                effective_scope,
                include_global=include_global,
                active_only=False,
            ):
                return False
            if allowed_ids is not None and memory.id not in allowed_ids:
                return False
            now = datetime.now(UTC)
            if memory.valid_from:
                try:
                    valid_from = datetime.fromisoformat(memory.valid_from)
                    if valid_from.tzinfo is None:
                        valid_from = valid_from.replace(tzinfo=UTC)
                    if valid_from.astimezone(UTC) > now:
                        return False
                except (TypeError, ValueError):
                    # A malformed validity window cannot safely establish
                    # that a memory is current; strict recall fails closed.
                    return False
            if memory.valid_to:
                try:
                    valid_to = datetime.fromisoformat(memory.valid_to)
                    if valid_to.tzinfo is None:
                        valid_to = valid_to.replace(tzinfo=UTC)
                    if valid_to.astimezone(UTC) < now:
                        return False
                except (TypeError, ValueError):
                    return False
            return True

        def _hydrate(memories: list[Memory]) -> list[Memory]:
            """Turn lean backend fallback rows into complete public objects."""
            ids = [memory.id for memory in memories if memory.id is not None]
            get_many = getattr(self.backend, "get_many", None)
            if not ids or get_many is None:
                return memories
            try:
                full = get_many(ids)
            except Exception:
                logger.debug("could not hydrate fallback memories", exc_info=True)
                return memories
            return [full.get(memory.id, memory) for memory in memories]

        evidence_candidates_seen = 0
        if evidence_required:
            evidence_candidates_seen = sum(
                1
                for strat in strategies
                for row in strat
                if row
                and _is_current(row[0])
                and not _has_required_evidence(row[0])
            )

        filtered_strategies: list[list[tuple]] = []
        for strat in strategies:
            filtered_strategies.append([
                row
                for row in strat
                if row
                and _is_current(row[0])
                and (not evidence_required or _has_required_evidence(row[0]))
            ])
        strategies = filtered_strategies

        # Conflict rows are intentionally excluded from normal candidate
        # generation. An explicit diagnostic request may include them, but
        # only after scope/tag/time checks and a direct lexical support check;
        # this prevents unresolved claims from becoming silent answers.
        if include_conflicted:
            import re

            query_terms = set(
                re.findall(r"[a-z0-9][a-z0-9_./:+#@=-]*", query_for_retrieval.casefold())
            )
            existing_ids = {
                memory.id
                for strategy in strategies
                for row in strategy
                for memory in [row[0]]
                if memory.id is not None
            }
            extras: list[tuple] = []
            for memory in self.backend.all():
                if memory.id in existing_ids or memory.status != "conflicted":
                    continue
                if not _is_current(memory) or not query_terms:
                    continue
                if evidence_required and not _has_required_evidence(memory):
                    continue
                content_terms = set(
                    re.findall(r"[a-z0-9][a-z0-9_./:+#@=-]*", memory.content.casefold())
                )
                overlap = len(query_terms & content_terms) / len(query_terms)
                if overlap > 0:
                    extras.append((memory, overlap, "keyword"))
            strategies[1].extend(extras)

        id_to_mem: dict[int, Memory] = {}
        raw_scores: dict[int, dict[str, float]] = {}
        strategies_hit: dict[str, int] = {}
        ranked_lists: list[list[int]] = []
        for strat in strategies:
            ranked_lists.append([m.id for m, _, _ in strat if m.id is not None])
            for m, score, label in strat:
                if m.id is None:
                    continue
                strategies_hit[label] = strategies_hit.get(label, 0) + 1
                id_to_mem[m.id] = m
                per_strategy = raw_scores.setdefault(m.id, {})
                per_strategy[label] = max(float(score), per_strategy.get(label, float("-inf")))

        fused = reciprocal_rank_fusion(
            ranked_lists,
            k=rrf_k,
            weights=self.settings.strategy_weights,
            strategy_labels=[name for name, _ in strat_fns],
        )
        scored: list[tuple[Memory, float]] = [
            (id_to_mem[mid], score) for mid, score in fused if mid in id_to_mem
        ]

        # Importance boost: high-importance memories (durable rules, critical
        # facts) get a ranking bonus so they surface even when the query only
        # loosely matches. Importance alone never tops an exact match, but it
        # lifts critical rules above weak-but-recent noise.
        if scored:
            boost = self.settings.importance_recall_boost
            if boost > 1.0:
                scored = [
                    (m, s * (boost if float(getattr(m, "importance", 0.5)) >= 0.8 else 1.0))
                    for m, s in scored
                ]
                scored.sort(key=lambda x: -x[1])

        if not scored:
            if evidence_required and evidence_candidates_seen:
                return RecallResult(
                    memories=[],
                    scores=[],
                    strategies_hit=strategies_hit,
                    status="abstain" if strict_policy else "empty",
                    reason="missing_evidence",
                )
            if strict_policy:
                return RecallResult(
                    memories=[],
                    scores=[],
                    strategies_hit=strategies_hit,
                    status="abstain",
                    reason="no_supported_candidate",
                )
            imp_min = float(getattr(self.settings, "prune_min_importance", 0.2) or 0.2)
            top_by = getattr(self.backend, "top_by_importance", None)
            try:
                important = top_by(
                    top_n=(eff or 5),
                    min_importance=imp_min,
                    scope=effective_scope,
                    include_global=include_global,
                ) if top_by is not None else []
            except TypeError:
                if top_by:
                    important = [
                        memory
                        for memory in self.backend.all()
                        if float(getattr(memory, "importance", 0.0) or 0.0) >= imp_min
                        and memory_matches_scope(
                            memory,
                            effective_scope,
                            include_global=include_global,
                            active_only=False,
                        )
                    ]
                    important.sort(
                        key=lambda memory: (
                            -float(getattr(memory, "importance", 0.0) or 0.0),
                            -int(getattr(memory, "access_count", 0) or 0),
                            -(int(memory.id) if memory.id is not None else 0),
                        )
                    )
                    important = important[: eff or None]
                else:
                    important = []
            important = _hydrate(important)
            important = [
                m
                for m in important
                if _is_current(m)
                and (not evidence_required or _has_required_evidence(m))
            ]
            if important:
                return RecallResult(
                    memories=important,
                    scores=[float(getattr(m, "importance", 0.5) or 0.5) * 0.1 for m in important],
                    strategies_hit={**strategies_hit, "importance_fallback": len(important)},
                    status="fallback",
                    reason="importance_fallback",
                )
            fallback = temporal_recall(
                self.backend,
                limit=eff or 5,
                scope=effective_scope,
                include_global=include_global,
            )
            fallback = [
                row
                for row in fallback
                if _is_current(row[0])
                and (not evidence_required or _has_required_evidence(row[0]))
            ]
            fallback_pairs: list[tuple] = [(m, s * 0.1) for m, s, _label in fallback]
            if fallback_pairs:
                return RecallResult(
                    memories=[m for m, _s in fallback_pairs],
                    scores=[s for _m, s in fallback_pairs],
                    strategies_hit={**strategies_hit, "temporal_fallback": len(fallback_pairs)},
                    status="fallback",
                    reason="temporal_fallback",
                )
            return RecallResult(memories=[], scores=[], strategies_hit=strategies_hit, status="empty")

        def _token_set(value: str) -> set[str]:
            import re

            stop = {
                "a", "an", "and", "are", "as", "at", "be", "does", "for", "from",
                "how", "i", "is", "it", "of", "on", "or", "the", "to", "use", "was",
                "what", "when", "where", "which", "who", "will", "with", "you", "your",
                "go", "live", "now", "current", "used", "something", "else", "variant",
                "judging", "happen", "deployment", "destination",
            }
            tokens = re.findall(r"[a-z0-9][a-z0-9_./:+#@=-]*", (value or "").casefold())
            return {token for token in tokens if token not in stop and len(token) >= 2}

        query_tokens = _token_set(query_for_retrieval)

        def _signal_confidence(memory: Memory) -> float:
            signals = raw_scores.get(memory.id or -1, {})
            semantic_score = float(signals.get("semantic", 0.0))
            # Constant/degenerate vectors are common in test doubles and do
            # not constitute semantic evidence.
            emb = memory.embedding or []
            if len(emb) < 16 or (emb and len({round(float(v), 7) for v in emb[:16]}) <= 1):
                semantic_score = 0.0
            semantic_score = max(0.0, min(1.0, semantic_score))
            keyword_score = max(0.0, min(1.0, float(signals.get("keyword", 0.0))))
            lexical = 0.0
            content_tokens = _token_set(memory.content)
            if query_tokens:
                lexical = len(query_tokens & content_tokens) / len(query_tokens)
            identifier_tokens = {
                token for token in query_tokens if any(char in token for char in "+-/:.@=#")
            }
            identifier_hit = any(
                token in memory.content.casefold() for token in identifier_tokens
            )
            # One generic-token FTS hit is not enough to support a fact. Treat
            # keyword/semantic signals as strong only with meaningful lexical
            # coverage, unless dense similarity is very high. This is the
            # abstention guard for "office WiFi password" when the store only
            # knows an office coffee machine.
            if lexical < 0.5:
                keyword_score = 0.0
                if semantic_score < 0.78:
                    semantic_score = 0.0
            if identifier_hit:
                lexical = max(lexical, 0.85)
            strategy_bonus = min(1.0, max(0, len(signals) - 1) / 2.0)
            support = max(semantic_score, keyword_score, lexical)
            base = (
                0.75 * (support * support)
                + 0.10 * strategy_bonus
                + 0.15 * float(
                    memory.confidence if memory.confidence is not None else 1.0
                )
            )
            return max(0.0, min(1.0, base))

        confidence_by_id = {m.id: _signal_confidence(m) for m, _ in scored if m.id is not None}
        scored.sort(key=lambda pair: confidence_by_id.get(pair[0].id, 0.0), reverse=True)
        top_confidence = confidence_by_id.get(scored[0][0].id, 0.0) if scored else 0.0
        if strict_policy:
            min_conf = float(getattr(self.settings, "abstention_min_confidence", 0.34))
            min_margin = float(getattr(self.settings, "abstention_min_margin", 0.04))
            candidate_floor = max(min_conf, top_confidence * 0.55)
            scored = [
                (memory, score)
                for memory, score in scored
                if confidence_by_id.get(memory.id, 0.0) >= candidate_floor
            ]
            if not scored:
                return RecallResult(
                    memories=[],
                    scores=[],
                    strategies_hit=strategies_hit,
                    status="abstain",
                    reason="low_confidence_or_ambiguous",
                    confidence=top_confidence,
                )
            scored.sort(key=lambda pair: confidence_by_id.get(pair[0].id, 0.0), reverse=True)
            top_confidence = confidence_by_id.get(scored[0][0].id, 0.0)
            second_confidence = confidence_by_id.get(scored[1][0].id, 0.0) if len(scored) > 1 else 0.0
            if top_confidence < min_conf or (
                top_confidence < 0.6 and top_confidence - second_confidence < min_margin
            ):
                return RecallResult(
                    memories=[],
                    scores=[],
                    strategies_hit=strategies_hit,
                    status="abstain",
                    reason="low_confidence_or_ambiguous",
                    confidence=top_confidence,
                )
        # Adaptive relevance cutoff (cliff detection): walk the fused scores
        # from the top and cut at the first steep drop (>= cliff_threshold,
        # default 45% relative drop between consecutive candidates). This
        # returns "the relevant ones" (fewer than the limit on a sparse store)
        # instead of always padding to the limit with weak matches, while a
        # dense relevant store keeps everything above the cliff (no
        # over-filtering).
        if scored and output_limit is not None:
            from itertools import pairwise

            keep = [scored[0]]
            for prev, cur in pairwise(scored):
                prev_s = confidence_by_id.get(prev[0].id, prev[1])
                cur_s = confidence_by_id.get(cur[0].id, cur[1])
                if prev_s > 0 and (prev_s - cur_s) / prev_s >= cliff_threshold:
                    break
                keep.append(cur)
            scored = keep

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
        final_scores = [float(confidence_by_id.get(m.id, id_to_fused.get(m.id, 0.0))) for m in memories_ordered]

        # Mark recalled memories as accessed (batched — one UPDATE statement
        # instead of N per-row updates per turn).
        touch = getattr(self.backend, "touch_memories", None)
        touched_ids = [
            m.id
            for m in memories_ordered[:output_limit]
            if m.id is not None and self._is_mutable_scope(m)
        ]
        if touch is not None and touched_ids:
            try:
                touch(touched_ids)
            except Exception:  # noqa: BLE001, S110 -- bookkeeping is best-effort
                pass
            # Adaptive importance: a memory that keeps getting recalled should
            # climb toward the top of recall ranking, so
            # top_by_importance (ordered by importance desc) surfaces it next
            # turn. Re-estimate from the freshly-touched access_count +
            # last_accessed_at. Pinned rules are never downgraded.
            if self.settings.importance_auto:
                try:
                    self._reestimate_accessed_importance(touched_ids)
                except Exception:  # noqa: BLE001, S110 -- best-effort, never break recall
                    pass
        else:
            for m in memories_ordered[:output_limit]:
                if not self._is_mutable_scope(m):
                    continue
                m.access_count += 1
                m.last_accessed_at = datetime.now(UTC).isoformat()
                self.backend.update(m)

        trimmed = {k: v for k, v in strategies_hit.items() if v}
        selected = memories_ordered[:output_limit]
        provenance = [
            {
                "memory_id": m.id,
                "source": m.source,
                "source_id": m.source_id,
                "evidence_quote": m.evidence_quote,
                "observed_at": m.observed_at,
                "valid_from": m.valid_from,
                "valid_to": m.valid_to,
                "confidence": float(confidence_by_id.get(m.id, m.confidence)),
                "status": m.status,
            }
            for m in selected
        ]
        return RecallResult(
            memories=selected,
            scores=final_scores[:output_limit],
            strategies_hit=trimmed,
            status="ok",
            confidence=top_confidence,
            provenance=provenance,
        )
