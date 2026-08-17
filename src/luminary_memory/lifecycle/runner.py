from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.lifecycle.cleanup import cleanup_expired
from luminary_memory.lifecycle.consolidate import consolidate
from luminary_memory.lifecycle.prune import prune

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend
    from luminary_memory.config import Settings


def run_lifecycle(
    backend: MemoryBackend,
    settings: Settings | None = None,
) -> dict[str, int]:
    min_importance = float(settings.prune_min_importance) if settings else 0.2
    consolidate_threshold = float(
        settings.consolidate_jaccard_threshold if settings else 0.9
    )
    return {
        "cleanup": int(cleanup_expired(backend)),
        "consolidate": int(consolidate(backend, threshold=consolidate_threshold)),
        "prune": int(prune(backend, min_importance=min_importance)),
    }
