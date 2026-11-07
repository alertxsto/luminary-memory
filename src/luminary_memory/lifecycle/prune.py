from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

def prune_candidates(memories, min_importance=0.2, max_count=None, pin_threshold=0.9):
    """Select exactly the existing prune policy without writing any rows."""
    if max_count is not None:
        max_count = max(0, int(max_count))
    low = [memory for memory in memories
           if float(memory.importance) < float(min_importance)
           and float(memory.importance) < float(pin_threshold)]
    removed = {memory.id for memory in low}
    remaining = [memory for memory in memories if memory.id not in removed]
    if max_count is not None and len(remaining) > max_count:
        unpinned = [memory for memory in remaining if float(memory.importance) < float(pin_threshold)]
        unpinned.sort(key=lambda memory: (float(memory.importance), int(memory.access_count), memory.created_at))
        low.extend(unpinned[:len(remaining) - max_count])
    return low



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
    candidates = prune_candidates(all_mems, min_importance=min_importance, max_count=max_count, pin_threshold=pin_threshold)
    _delete_rows(candidates)
    removed = len(candidates)
    logger.info("prune removed=%d min_importance=%s pin_threshold=%s", removed, min_importance, pin_threshold)
    return removed
