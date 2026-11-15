import pytest

from luminary_memory.budget import budget_usage, truncate
from luminary_memory.types import Memory


def _mk(content: str) -> Memory:
    return Memory(content=content)


def test_truncate_uses_bytes_when_no_tokenizer_is_available():
    memories = [_mk("x" * 8000), _mk("café"), _mk("ok")]

    assert truncate(memories, token_budget=5) == [memories[1]]
    assert budget_usage("🙂") == (4, "bytes")


def test_truncate_empty_returns_empty():
    assert truncate([], token_budget=10) == []


def test_truncate_budget_larger_than_total_returns_all():
    memories = [_mk("hi"), _mk("there")]
    assert truncate(memories, token_budget=100) == memories


def test_truncate_zero_budget_returns_empty():
    memories = [_mk("hello"), _mk("world")]
    assert truncate(memories, token_budget=0) == []


def test_zero_hard_token_budget_never_requires_a_tokenizer():
    assert truncate([_mk("hello")], token_budget=0, require_tokenizer=True) == []


def test_truncate_preserves_highest_score_order():
    memories = [_mk("keep this one first"), _mk("drop this second one")]
    result = truncate(memories, token_budget=19)
    assert result == [memories[0]]


def test_truncate_custom_tokenizer_skips_oversized_memory():
    memories = [_mk("hello world"), _mk("foo")]
    result = truncate(memories, token_budget=1, tokenizer=lambda text: text.split())
    assert result == [memories[1]]
    assert budget_usage("🙂", tokenizer=list) == (1, "tokens")


def test_truncate_includes_serialized_header_and_unicode_bytes():
    memories = [_mk("a"), _mk("too long to fit"), _mk("猫")]
    serialize = lambda items: 'header[' + ",".join(f'"{m.content}"' for m in items) + ']'

    assert truncate(memories, token_budget=17, serialize=serialize) == [
        memories[0], memories[2]
    ]


def test_hard_token_budget_requires_an_actual_tokenizer():
    with pytest.raises(ValueError, match="tokenizer"):
        truncate([_mk("small")], token_budget=100, require_tokenizer=True)


def test_env_float_invalid_returns_default(monkeypatch):
    """Invalid LUMINARY float env value falls back to the default."""
    from luminary_memory.config import _env_float

    monkeypatch.setenv("LUMINARY_TEST_FLOAT", "not-a-float")
    assert _env_float("LUMINARY_TEST_FLOAT", 0.75) == 0.75
