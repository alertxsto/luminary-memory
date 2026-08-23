from luminary_memory.budget import truncate
from luminary_memory.types import Memory


def _mk(content: str) -> Memory:
    return Memory(content=content)


def test_truncate_respects_budget():
    memories = [_mk("hello world"), _mk("foo bar baz"), _mk("something else here")]
    # budget = 2 tokens (word-level)
    result = truncate(memories, token_budget=2)
    assert len(result) <= 2
    # total tokens in result must fit budget
    total = sum(len(m.content.split()) for m in result)
    assert total <= 2


def test_truncate_empty_returns_empty():
    assert truncate([], token_budget=10) == []


def test_truncate_budget_larger_than_total_returns_all():
    memories = [_mk("hi"), _mk("there")]
    assert truncate(memories, token_budget=100) == memories


def test_truncate_zero_budget_returns_empty():
    memories = [_mk("hello"), _mk("world")]
    assert truncate(memories, token_budget=0) == []


def test_truncate_preserves_highest_score_order():
    memories = [_mk("keep this one first"), _mk("drop this second one")]
    result = truncate(memories, token_budget=4)
    assert result[0].content == "keep this one first"


def test_truncate_custom_tokenizer():
    memories = [_mk("hello world"), _mk("foo")]
    result = truncate(memories, token_budget=1, tokenizer=lambda s: list(s))
    # tokenizer counts chars here, budget 1 => first memory too long, falls through
    assert isinstance(result, list)


def test_env_float_invalid_returns_default(monkeypatch):
    """Invalid LUMINARY float env value falls back to the default."""
    from luminary_memory.config import _env_float

    monkeypatch.setenv("LUMINARY_TEST_FLOAT", "not-a-float")
    assert _env_float("LUMINARY_TEST_FLOAT", 0.75) == 0.75
