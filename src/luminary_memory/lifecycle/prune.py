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
) -> int:
    """Prune low-value memories.

    Memories at/above ``pin_threshold`` importance (default 0.9, i.e. durable
    rules flagged by the enricher) are pinned: they are never removed by
    importance pruning or the max-count cap.
    """
    removed = 0

    def _pinned(m) -> bool:
        return float(getattr(m, "importance", 0.0) or 0.0) >= pin_threshold

    from luminary_memory.scope import memory_matches_scope

    all_mems = [m for m in backend.all() if memory_matches_scope(m, scope, active_only=True)]
    low_imp = [m for m in all_mems if float(m.importance) < float(min_importance) and not _pinned(m)]
    if low_imp:
        delete_many = getattr(backend, "delete_many", None)
        if delete_many is not None:
            for m in low_imp:
                try:
                    backend.record_event("prune", m.id, before={"content": m.content, "status": m.status})
                except Exception:
                    logger.debug("could not record prune for %s", m.id, exc_info=True)
            delete_many([m.id for m in low_imp if m.id is not None])  # type: ignore[union-attr]
        else:
            for m in low_imp:
                try:
                    backend.record_event("prune", m.id, before={"content": m.content, "status": m.status})
                except Exception:
                    logger.debug("could not record prune for %s", m.id, exc_info=True)
                backend.delete(m.id)  # type: ignore[arg-type]
        removed += len(low_imp)
    if max_count is not None:
        unpinned = [m for m in all_mems if not _pinned(m)]
        if len(all_mems) > max_count and unpinned:
            unpinned.sort(key=lambda m: (float(m.importance), int(m.access_count), m.created_at))
            to_drop = unpinned[: len(all_mems) - max_count]
            if to_drop:
                delete_many = getattr(backend, "delete_many", None)
                if delete_many is not None:
                    for m in to_drop:
                        try:
                            backend.record_event("prune", m.id, before={"content": m.content, "status": m.status})
                        except Exception:
                            logger.debug("could not record prune for %s", m.id, exc_info=True)
                    delete_many([m.id for m in to_drop if m.id is not None])  # type: ignore[union-attr]
                else:
                    for m in to_drop:
                        try:
                            backend.record_event("prune", m.id, before={"content": m.content, "status": m.status})
                        except Exception:
                            logger.debug("could not record prune for %s", m.id, exc_info=True)
                        backend.delete(m.id)  # type: ignore[arg-type]
                removed += len(to_drop)
    logger.info("prune removed=%d min_importance=%s pin_threshold=%s", removed, min_importance, pin_threshold)
    return removed
