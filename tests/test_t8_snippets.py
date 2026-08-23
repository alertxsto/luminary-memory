from luminary_memory.api import MemoryClient
from luminary_memory.recall.snippets import extract_snippet


def test_extract_snippet_contains_term_and_is_shorter():
    content = "the database uses postgresql fts5 for full text search indexing"
    out = extract_snippet(content, "postgresql", width=30)
    assert "postgresql" in out.lower()
    assert len(out) < len(content)


def test_extract_snippet_fallback_to_leading_excerpt():
    content = "hello world, this is a long memory without the query term present here"
    out = extract_snippet(content, "absentxyz", width=20)
    assert out.lower().startswith("hello world")


def test_recall_attaches_snippet(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    c.ingest("the database uses postgresql fts5")
    res = c.recall("postgresql", limit=5)
    assert res.memories
    assert hasattr(res.memories[0], "snippet")
    assert res.memories[0].snippet and "postgresql" in res.memories[0].snippet.lower()


def test_extract_snippet_empty_query_returns_leading_excerpt():
    """An empty query falls back to the leading excerpt of the content."""
    out = extract_snippet("a b c d e f g", "", width=4)
    assert out == "a b"
