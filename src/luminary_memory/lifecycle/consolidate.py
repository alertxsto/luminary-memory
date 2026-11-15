from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend




def consolidate(
    backend: MemoryBackend,
    threshold: float = 0.9,
    semantic: bool = True,
    semantic_threshold: float = 0.85,
    pin_threshold: float = 0.9,
    scope: dict | None = None,
    include_global: bool = False,
) -> int:
    """Merge exact duplicates with compatible ownership and provenance.

    Similarity options remain accepted for caller compatibility, but never
    authorize deletion. Pinned memories are never deleted.
    """
    from luminary_memory.recall.graph import index_memory_entities
    from luminary_memory.scope import memory_matches_scope

    memories = [
        m
        for m in backend.all()
        if memory_matches_scope(
            m,
            scope,
            include_global=include_global,
            active_only=True,
        )
    ]
    merged = 0
    visited: set[int] = set()

    def _pinned(m) -> bool:
        return float(getattr(m, "importance", 0.0) or 0.0) >= pin_threshold
    claims_by_id = {}

    def _claims(memory):
        if memory.id not in claims_by_id:
            sql = getattr(backend, "_sql", None)
            table = getattr(backend, "_inspector_table", None)
            if not callable(sql) or not callable(table):
                claims_by_id[memory.id] = None
            else:
                try:
                    rows = sql(
                        f"SELECT subject, predicate, object, polarity, status, confidence, "
                        f"observed_at, valid_from, valid_to FROM {table('claims')} WHERE memory_id = ?",
                        (memory.id,),
                    ).fetchall()
                    claims_by_id[memory.id] = {tuple(row) for row in rows}
                except Exception:
                    logger.warning("could not inspect claims for %s; keeping memory", memory.id, exc_info=True)
                    claims_by_id[memory.id] = None
        return claims_by_id[memory.id]


    def _compatible(a, b) -> bool:
        fields = (
            "content", "user_id", "workspace_id", "agent_id", "session_id",
            "source", "source_id", "evidence_quote", "claim_key",
            "observed_at", "valid_from", "valid_to", "status", "confidence",
            "supersedes_id", "ttl_seconds", "metadata",
        )
        if not all(getattr(a, field, None) == getattr(b, field, None) for field in fields):
            return False
        if a.ttl_seconds and a.created_at != b.created_at:
            return False
        a_claims, b_claims = _claims(a), _claims(b)
        return a_claims is not None and b_claims is not None and (
            not a_claims or not b_claims or a_claims == b_claims
        )

    for i, m in enumerate(memories):
        if m.id in visited:
            continue
        cluster = [m]
        for n in memories[i + 1:]:
            if n.id in visited:
                continue
            if all(_compatible(member, n) for member in cluster):
                cluster.append(n)
        if len(cluster) < 2:
            continue
        # Pinned members are never dropped; if any cluster member is pinned,
        # only the unpinned ones may be removed as duplicates.
        pinned_members = [c for c in cluster if _pinned(c)]
        if pinned_members:
            cluster = [c for c in cluster if not _pinned(c)]
            if len(cluster) < 2:
                for c in pinned_members:
                    visited.add(c.id)  # type: ignore[arg-type]
                continue
        master = max(cluster, key=lambda x: len(x.content))
        duplicates = [c for c in cluster if c.id != master.id]
        try:
            sql = backend._sql
            table = backend._inspector_table
            if any(
                sql(
                    f"SELECT 1 FROM {table('memories')} WHERE supersedes_id = ? LIMIT 1",
                    (duplicate.id,),
                ).fetchone()
                for duplicate in duplicates
            ):
                continue
        except Exception:
            logger.warning("could not inspect lineage; keeping duplicates", exc_info=True)
            continue
        from luminary_memory.backends.base import MemoryBackend

        rehome = getattr(backend, "rehome_memory_references", None)
        if not callable(rehome) or getattr(rehome, "__func__", None) is MemoryBackend.rehome_memory_references:
            # A no-op reference transfer cannot establish that deletion is safe.
            continue
        if callable(rehome):
            rehome_failed = False
            for duplicate in duplicates:
                try:
                    rehome(duplicate.id, master.id)
                except Exception:
                    rehome_failed = True
                    logger.warning(
                        "could not rehome references from %s to %s; keeping duplicate",
                        duplicate.id,
                        master.id,
                        exc_info=True,
                    )
            if rehome_failed:
                # Do not hard-delete a row while its evidence/claim lineage
                # may still point at it. A later lifecycle pass can retry.
                visited.update(c.id for c in cluster if c.id is not None)
                continue
        total_access = sum(c.access_count for c in cluster)
        merged_tags: list[str] = []
        seen: set[str] = set()
        for c in cluster:
            for t in c.tags or []:
                if t not in seen:
                    seen.add(t)
                    merged_tags.append(t)
        master.access_count = total_access
        master.tags = merged_tags
        before_master = backend.get(master.id) if master.id is not None else None
        backend.update(master)  # type: ignore[arg-type]
        try:
            backend.record_event(
                "consolidate",
                master.id,
                before={"content": getattr(before_master, "content", None)} if before_master else None,
                after={"content": master.content, "merged_ids": [c.id for c in cluster]},
            )
        except Exception:
            logger.debug("could not record consolidation for %s", master.id, exc_info=True)
        try:
            index_memory_entities(backend, master)
        except Exception:  # noqa: BLE001
            master.needs_reindex = True
            try:
                backend.update(master)
            except Exception:
                logger.debug("could not mark consolidated memory for reindex", exc_info=True)
        for c in duplicates:
            if c.id != master.id:
                try:
                    backend.record_event("consolidate_delete", c.id, before={"content": c.content})
                except Exception:
                    logger.debug("could not record consolidation delete for %s", c.id, exc_info=True)
                backend.delete(c.id)  # type: ignore[arg-type]
                visited.add(c.id)  # type: ignore[arg-type]
                merged += 1
        visited.add(master.id)  # type: ignore[arg-type]
    logger.info(
        "consolidate merged=%d reviewed=%d", merged, len(memories),
    )
    return merged
