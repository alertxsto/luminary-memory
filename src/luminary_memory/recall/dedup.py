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
