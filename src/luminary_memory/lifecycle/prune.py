from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def prune(
    backend: MemoryBackend,
    min_importance: float = 0.2,
    max_count: int | None = None,
    now=None,
    pin_threshold: float = 0.9,
    scope: dict | None = None,
    include_global: bool = True,
) -> int:
    """Prune low-value memories.

    Memories at/above ``pin_threshold`` importance (default 0.9, i.e. durable
    rules flagged by the enricher) are pinned: they are never removed by
    importance pruning or the max-count cap.
    """
    removed = 0

    def _pinned(m) -> bool:
        return float(getattr(m, "importance", 0.0) or 0.0) >= pin_threshold

    def _delete_rows(rows) -> None:
        if not rows:
            return
        for memory in rows:
            try:
                backend.record_event(
                    "prune",
                    memory.id,
                    before={"content": memory.content, "status": memory.status},
                )
            except Exception:
                logger.debug("could not record prune for %s", memory.id, exc_info=True)
            try:
                backend.sync_claim_status(memory.id, "deleted")
            except Exception:
                logger.debug("could not mark claims deleted for %s", memory.id, exc_info=True)
        delete_many = getattr(backend, "delete_many", None)
        ids = [memory.id for memory in rows if memory.id is not None]
        if delete_many is not None:
            delete_many(ids)  # type: ignore[arg-type]
        else:
            for memory_id in ids:
                backend.delete(memory_id)  # type: ignore[arg-type]

    from luminary_memory.scope import memory_matches_scope

    all_mems = [
        m
        for m in backend.all()
        if memory_matches_scope(
            m,
            scope,
            include_global=include_global,
            active_only=True,
        )
    ]
    if max_count is not None:
        max_count = max(0, int(max_count))
    low_imp = [m for m in all_mems if float(m.importance) < float(min_importance) and not _pinned(m)]
    if low_imp:
        _delete_rows(low_imp)
        removed += len(low_imp)
        removed_ids = {m.id for m in low_imp}
        all_mems = [m for m in all_mems if m.id not in removed_ids]
    if max_count is not None:
        unpinned = [m for m in all_mems if not _pinned(m)]
        if len(all_mems) > max_count and unpinned:
            unpinned.sort(key=lambda m: (float(m.importance), int(m.access_count), m.created_at))
            to_drop = unpinned[: len(all_mems) - max_count]
            if to_drop:
                _delete_rows(to_drop)
                removed += len(to_drop)
    logger.info("prune removed=%d min_importance=%s pin_threshold=%s", removed, min_importance, pin_threshold)
    return removed
