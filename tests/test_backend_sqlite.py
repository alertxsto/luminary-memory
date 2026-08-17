from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.types import Memory


def _mk(tmp_path):
    return SQLiteBackend(str(tmp_path / "t.db"))

def test_add_and_get(tmp_path):
    b = _mk(tmp_path)
    mid = b.add(Memory(content="The sky is blue", tags=["nature"]))
    m = b.get(mid)
    assert m is not None and m.content == "The sky is blue"
    assert b.count() == 1

def test_keyword_search_ranks(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="database indexing with sqlite fts5"))
    b.add(Memory(content="making a sandwich for lunch"))
    res = b.keyword_search("sqlite fts5", limit=5)
    assert res and res[0][0].content.startswith("database")
