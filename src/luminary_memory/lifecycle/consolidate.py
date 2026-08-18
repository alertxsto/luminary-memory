from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.recall.dedup import cosine_similarity, jaccard_similarity

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def _similar(
    a,
    b,
    semantic: bool,
    semantic_threshold: float,
    jaccard_threshold: float,
) -> bool:
    """Semantic (embedding cosine) similarity with Jaccard fallback."""
    if semantic:
        ea = getattr(a, "embedding", None)
        eb = getattr(b, "embedding", None)
        if ea and eb and len(ea) == len(eb):
            return cosine_similarity(ea, eb) >= semantic_threshold
        # Missing/invalid embeddings → fall back to token overlap.
    return jaccard_similarity(a.content, b.content) >= jaccard_threshold


def consolidate(
    backend: MemoryBackend,
    threshold: float = 0.9,
    semantic: bool = True,
    semantic_threshold: float = 0.85,
) -> int:
    memories = backend.all()
    merged = 0
    visited: set[int] = set()
    for i, m in enumerate(memories):
        if m.id in visited:
            continue
        cluster = [m]
        for n in memories[i + 1:]:
            if n.id in visited:
                continue
            if _similar(m, n, semantic, semantic_threshold, threshold):
                cluster.append(n)
        if len(cluster) < 2:
            continue
        master = max(cluster, key=lambda x: len(x.content))
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
        backend.update(master)  # type: ignore[arg-type]
        for c in cluster:
            if c.id != master.id:
                backend.delete(c.id)  # type: ignore[arg-type]
                visited.add(c.id)  # type: ignore[arg-type]
                merged += 1
        visited.add(master.id)  # type: ignore[arg-type]
    return merged
