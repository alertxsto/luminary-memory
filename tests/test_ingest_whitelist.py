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


def test_whitelist_invalid_regex_ignored():
    """A malformed regex pattern is skipped, not fatal."""
    from luminary_memory.ingest.whitelist import WhitelistFilter

    f = WhitelistFilter(patterns=["[invalid", "ok-pattern"])
    assert f.accepts("ok-pattern here") is True


def test_rules_empty_inputs_false():
    """Empty text or empty keywords never match a rule."""
    from luminary_memory.ingest.rules import contains_rule_keyword

    assert contains_rule_keyword("", "MUST") is False
    assert contains_rule_keyword("some text", "") is False
    assert contains_rule_keyword("some text", None) is False
