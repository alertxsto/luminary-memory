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
