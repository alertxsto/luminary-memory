from __future__ import annotations


def _tokens(text: str) -> set[str]:
    return set(text.lower().split())


def jaccard_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors (pure math, no deps)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def dedup_jaccard(
    scored: list[tuple],
    threshold: float = 0.85,
) -> list[tuple]:
    kept: list[tuple] = []
    for mem, score in scored:
        duplicate = False
        for k_mem, _ in kept:
            if jaccard_similarity(mem.content, k_mem.content) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append((mem, score))
    return kept
