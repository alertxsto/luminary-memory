from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.recall.keyword import keyword_recall
from luminary_memory.types import Memory


def _mk(tmp_path):
    return SQLiteBackend(str(tmp_path / "t.db"))


def test_keyword_recall_finds_matching_memory(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="postgres vector index is fast"))
    b.add(Memory(content="making a sandwich for lunch"))
    res = keyword_recall(b, "postgres vector", limit=10)
    assert len(res) == 1
    assert res[0][0].content.startswith("postgres")
    assert res[0][2] == "keyword"


def test_keyword_recall_scoring_is_bm25_negated(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="postgres vector index is fast and postgres again"))
    b.add(Memory(content="postgres appears once"))
    res = keyword_recall(b, "postgres", limit=10)
    assert res[0][1] > res[1][1]


def test_keyword_recall_no_match_returns_empty(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="something about dogs"))
    res = keyword_recall(b, "postgres", limit=10)
    assert res == []


def test_keyword_recall_respects_limit(tmp_path):
    b = _mk(tmp_path)
    for t in ["hello world"] * 5:
        b.add(Memory(content=t))
    res = keyword_recall(b, "hello", limit=2)
    assert len(res) == 2
