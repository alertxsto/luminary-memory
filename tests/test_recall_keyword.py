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


def test_keyword_recall_keeps_bm25_order_but_reports_normalized_evidence(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="postgres vector index is fast and postgres again"))
    b.add(Memory(content="postgres appears once"))
    backend_order = [m.id for m, _ in b.keyword_search("postgres", limit=10)]
    res = keyword_recall(b, "postgres", limit=10)
    assert [m.id for m, _, _ in res] == backend_order
    assert [score for _, score, _ in res] == [1.0, 1.0]
    b.close()

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


def test_keyword_recall_multi_term_or_not_and(tmp_path):
    """Multi-term queries must match memories that contain ANY term (OR),
    not require all terms in one document (AND).

    Regression: 'laporan pakai tabel' returned 0 hits because FTS5's default
    AND join demanded all three words co-occur in a single memory, leaving
    keyword recall empty while the rule was in the store.
    """
    b = _mk(tmp_path)
    b.add(Memory(content="aturan format tabel markdown untuk laporan"))
    b.add(Memory(content="pakai deploy target production"))
    b.add(Memory(content="membuat sandwich untuk makan siang"))

    # 'laporan pakai tabel' — each term lives in a different memory.
    res = keyword_recall(b, "laporan pakai tabel", limit=10)
    assert len(res) >= 2, "OR join must surface memories matching any term"
    # The memory with the most term overlap ranks first.
    assert res[0][0].content.startswith("aturan format tabel")

    # Planner evidence counts distinct matched terms; BM25 still decides
    # backend ordering rather than being compared with a cross-backend floor.
    assert [score for _, score, _ in res] == [2 / 3, 1 / 3]


def test_keyword_scan_empty_query_returns_empty(tmp_path):
    """A punctuation-only query yields no keyword terms, so no matches."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall.keyword import _legacy_keyword_scan

    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    c.ingest("the database uses postgresql fts5")
    rows = _legacy_keyword_scan(c.backend, "!!!")
    assert rows == []
