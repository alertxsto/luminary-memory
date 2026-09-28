import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.whitelist import WhitelistFilter


def test_allows_matching_content():
    f = WhitelistFilter(patterns=[r"python", r"database"])
    assert f.accepts("learning python decorators")


def test_rejects_non_matching():
    f = WhitelistFilter(patterns=[r"python"])
    assert not f.accepts("my cat ate a sandwich")


def test_rejects_too_short():
    f = WhitelistFilter(patterns=[r".*"], min_length=10)
    assert not f.accepts("hi")


def test_empty_patterns_allow_all():
    f = WhitelistFilter(patterns=[])
    assert f.accepts("anything at all here")


def test_matching_is_case_insensitive():
    f = WhitelistFilter(patterns=[r"python"])
    assert f.accepts("Learning PYTHON is fun")


def test_rejects_empty_text():
    f = WhitelistFilter(patterns=[r".*"], min_length=0)
    assert not f.accepts("")


def test_whitelist_empty_text_rejected():
    """Blank text is never accepted by the whitelist."""
    from luminary_memory.ingest.whitelist import WhitelistFilter

    f = WhitelistFilter(patterns=["banana"])
    assert f.accepts("   ") is False


def test_whitelist_invalid_regex_fails_closed():
    with pytest.raises(ValueError, match="invalid ingest allowlist pattern"):
        WhitelistFilter(patterns=["[invalid", "ok-pattern"])


def test_client_rejects_invalid_allowlist_before_accepting_content(tmp_path):
    settings = Settings(db_path=str(tmp_path / "invalid.db"), ingest_whitelist=["["])
    with pytest.raises(ValueError, match="invalid ingest allowlist pattern"):
        MemoryClient(settings=settings)

def test_blank_allowlist_rule_is_not_equivalent_to_no_policy():
    with pytest.raises(ValueError, match="invalid ingest allowlist pattern"):
        WhitelistFilter(patterns=[""])


def test_rules_empty_inputs_false():
    """Empty text or empty keywords never match a rule."""
    from luminary_memory.ingest.rules import contains_rule_keyword

    assert contains_rule_keyword("", "MUST") is False
    assert contains_rule_keyword("some text", "") is False
    assert contains_rule_keyword("some text", None) is False
