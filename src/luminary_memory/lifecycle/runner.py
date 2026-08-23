from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from luminary_memory.lifecycle.cleanup import cleanup_expired
from luminary_memory.lifecycle.consolidate import consolidate
from luminary_memory.lifecycle.prune import prune

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend
    from luminary_memory.config import Settings


def run_lifecycle(
    backend: MemoryBackend,
    settings: Settings | None = None,
    semantic: bool | None = None,
    scope: dict | None = None,
    include_global: bool = True,
) -> dict[str, int]:
    min_importance = float(settings.prune_min_importance) if settings else 0.2
    consolidate_threshold = float(
        settings.consolidate_jaccard_threshold if settings else 0.9
    )
    if semantic is None:
        semantic = bool(settings.consolidate_semantic) if settings else True

    pin_threshold = float(
        getattr(settings, "rule_importance", 0.9) if settings else 0.9
    )

    # max_memories cap (env LUMINARY_MAX_MEMORIES / Settings / provider config).
    # Pinned rules are exempt inside prune().
    max_count = int(getattr(settings, "max_memories", 0) or 0) if settings else 0
    max_count = max_count or None

    # Repair graph rows explicitly marked by a failed mutation.  A failed
    # secondary index must be observable and recoverable, never silently stale.
    reindexed = 0
    from luminary_memory.recall.graph import index_memory_entities
    from luminary_memory.scope import memory_matches_scope

    for memory in backend.all():
        if not getattr(memory, "needs_reindex", False):
            continue
        if not memory_matches_scope(
            memory,
            scope,
            include_global=include_global,
            active_only=False,
        ):
            continue
        try:
            index_memory_entities(backend, memory)
            memory.needs_reindex = False
            backend.update(memory)
            reindexed += 1
        except Exception:
            logger.warning("reindex failed for memory %s", memory.id, exc_info=True)

    # Re-estimate importance before pruning so values reflect current value.
    # Pinned memories (importance >= pin_threshold, e.g. durable rules) are
    # never downgraded by re-estimation.
    reestimated = 0
    if settings is None or settings.importance_auto:
        from luminary_memory.lifecycle.importance import estimate_importance
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
        max_access = max((int(m.access_count or 0) for m in memories), default=1)
        changed: list[tuple[float, int]] = []
        for m in memories:
            if float(getattr(m, "importance", 0.0) or 0.0) >= pin_threshold:
                continue
            new_imp = estimate_importance(m, max_access=max_access)
            if abs(float(m.importance or 0) - new_imp) > 1e-6:
                changed.append((new_imp, m.id))  # type: ignore[arg-type]
        if changed:
            bulk = getattr(backend, "update_importances", None)
            if bulk is not None:
                bulk(changed)
            else:
                for new_imp, mid in changed:
                    m = backend.get(mid)
                    if m is not None:
                        m.importance = new_imp
                        backend.update(m)
            reestimated = len(changed)
    start = time.monotonic()
    result = {
        "cleanup": int(
            cleanup_expired(
                backend,
                scope=scope,
                include_global=include_global,
            )
        ),
        "consolidate": int(
            consolidate(
                backend,
                threshold=consolidate_threshold,
                semantic=semantic,
                pin_threshold=pin_threshold,
                scope=scope,
                include_global=include_global,
            )
        ),
        "prune": int(
            prune(
                backend,
                min_importance=min_importance,
                pin_threshold=pin_threshold,
                max_count=max_count,
                scope=scope,
                include_global=include_global,
            )
        ),
        "reestimated": reestimated,
        "reindexed": reindexed,
    }
    logger.info("run_lifecycle %s (%.1fs)", result, time.monotonic() - start)
    return result
