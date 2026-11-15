from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.types import Memory


def budget_usage(
    text: str,
    tokenizer: Callable[[str], list] | None = None,
    *,
    require_tokenizer: bool = False,
) -> tuple[int, str]:
    """Measure tokens with the consumer's tokenizer, or UTF-8 bytes as an estimate."""
    if tokenizer is not None:
        return len(tokenizer(text)), "tokens"
    if require_tokenizer:
        raise ValueError("a tokenizer is required for a hard token budget")
    return len(text.encode("utf-8")), "bytes"


def truncate(
    memories: list[Memory],
    token_budget: int,
    tokenizer: Callable[[str], list] | None = None,
    *,
    serialize: Callable[[list[Memory]], str] | None = None,
    require_tokenizer: bool = False,
) -> list[Memory]:
    """Select whole memories under the measured serialized-context budget."""
    if not memories or token_budget <= 0:
        return []
    if require_tokenizer and tokenizer is None:
        raise ValueError("a tokenizer is required for a hard token budget")

    result: list[Memory] = []
    if tokenizer is None and serialize is None:
        total = 0
        for memory in memories:
            cost = len(memory.content.encode("utf-8")) + bool(result)
            if total + cost <= token_budget:
                total += cost
                result.append(memory)
        return result

    for memory in memories:
        result.append(memory)
        text = (
            serialize(result)
            if serialize is not None
            else "\n".join(item.content for item in result)
        )
        used, _mode = budget_usage(text, tokenizer, require_tokenizer=require_tokenizer)
        if used > token_budget:
            result.pop()
    return result
