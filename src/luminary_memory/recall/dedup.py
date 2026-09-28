from __future__ import annotations

from itertools import islice


def _tokens(text: str) -> set[str]:
    return set(text.lower().split())


def jaccard_similarity(a: str, b: str) -> float:
    return _jaccard_tokens(_tokens(a), _tokens(b))


def _jaccard_tokens(ta: set[str], tb: set[str]) -> float:
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
    max_pairs: int = 500,
) -> list[tuple]:
    """Dedup all candidates, comparing against at most ``max_pairs`` retained hits.

    This bounds the work per candidate without silently dropping candidates
    beyond the first window in unlimited recall.
    """
    kept: list[tuple] = []
    kept_tokens: list[set[str]] = []
    for row in scored:
        tokens = _tokens(row[0].content)
        previous_tokens = islice(reversed(kept_tokens), max_pairs if max_pairs > 0 else None)
        if not any(_jaccard_tokens(tokens, previous) >= threshold for previous in previous_tokens):
            kept.append(row)
            kept_tokens.append(tokens)
    return kept
