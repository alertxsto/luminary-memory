from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from luminary_memory.recall.dedup import cosine_similarity, jaccard_similarity

logger = logging.getLogger(__name__)

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
            # Degenerate embeddings (all-equal values) carry no semantic
            # signal — cosine of identical constant vectors is 1.0 for any
            # content. Fall back to Jaccard in that case.
            if _is_degenerate(ea) or _is_degenerate(eb):
                return jaccard_similarity(a.content, b.content) >= jaccard_threshold
            return cosine_similarity(ea, eb) >= semantic_threshold
        # Missing/invalid embeddings → fall back to token overlap.
    return jaccard_similarity(a.content, b.content) >= jaccard_threshold


def _is_degenerate(vec: list[float]) -> bool:
    """True when the vector carries no directional signal (all values equal)."""
    if not vec:
        return True
    first = vec[0]
    # Sample a few positions — full scan is overkill for typical 384-dim.
    return all(v == first for v in vec[:16])


def consolidate(
    backend: MemoryBackend,
    threshold: float = 0.9,
    semantic: bool = True,
    semantic_threshold: float = 0.85,
    pin_threshold: float = 0.9,
) -> int:
    """Merge near-duplicate memories.

    Pinned memories (importance >= ``pin_threshold``, e.g. durable rules)
    are never deleted by consolidation: they are excluded from clusters that
    would merge them away. A pinned member can still become the cluster
    master (its content is kept), but it is never a duplicate that gets
    dropped.
    """
    memories = backend.all()
    merged = 0
    visited: set[int] = set()

    def _pinned(m) -> bool:
        return float(getattr(m, "importance", 0.0) or 0.0) >= pin_threshold

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
    logger.info(
        "consolidate mode=%s merged=%d reviewed=%d",
        "semantic" if semantic else "jaccard", merged, len(memories),
    )
    return merged
