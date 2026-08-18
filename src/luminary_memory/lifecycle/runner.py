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
) -> dict[str, int]:
    min_importance = float(settings.prune_min_importance) if settings else 0.2
    consolidate_threshold = float(
        settings.consolidate_jaccard_threshold if settings else 0.9
    )
    if semantic is None:
        semantic = bool(settings.consolidate_semantic) if settings else True

    # Re-estimate importance before pruning so values reflect current value.
    reestimated = 0
    if settings is None or settings.importance_auto:
        from luminary_memory.lifecycle.importance import estimate_importance

        memories = backend.all()
        max_access = max((int(m.access_count or 0) for m in memories), default=1)
        for m in memories:
            new_imp = estimate_importance(m, max_access=max_access)
            if abs(float(m.importance or 0) - new_imp) > 1e-6:
                m.importance = new_imp
                backend.update(m)  # type: ignore[arg-type]
                reestimated += 1

    start = time.monotonic()
    result = {
        "cleanup": int(cleanup_expired(backend)),
        "consolidate": int(consolidate(backend, threshold=consolidate_threshold, semantic=semantic)),
        "prune": int(prune(backend, min_importance=min_importance)),
        "reestimated": reestimated,
    }
    logger.info("run_lifecycle %s (%.1fs)", result, time.monotonic() - start)
    return result
