from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.types import Memory


def _estimate_tokens(text: str) -> int:
    return len(text.split())


def truncate(
    memories: list[Memory],
    token_budget: int,
    tokenizer: Callable[[str], list] | None = None,
) -> list[Memory]:
    if not memories or token_budget <= 0:
        return []
    count_fn: Callable[[str], int]
    if tokenizer is not None:
        def count_fn(s: str) -> int:
            return len(tokenizer(s))
    else:
        count_fn = _estimate_tokens

    result: list[Memory] = []
    total = 0
    for m in memories:
        cost = count_fn(m.content)
        if total + cost > token_budget:
            continue
        total += cost
        result.append(m)
    return result
