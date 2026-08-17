from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def prune(
    backend: MemoryBackend,
    min_importance: float = 0.2,
    max_count: int | None = None,
    now=None,
) -> int:
    removed = 0
    for m in backend.all():
        if float(m.importance) < float(min_importance):
            backend.delete(m.id)  # type: ignore[arg-type]
            removed += 1
    if max_count is not None:
        all_mems = backend.all()
        if len(all_mems) > max_count:
            all_mems.sort(key=lambda m: (float(m.importance), int(m.access_count), m.created_at))
            to_drop = all_mems[: len(all_mems) - max_count]
            for m in to_drop:
                backend.delete(m.id)  # type: ignore[arg-type]
                removed += 1
    return removed
