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


def test_close_from_other_thread_does_not_crash(tmp_path):
    """close() called from a different thread than the connection owner must
    not raise (regression for provider writer-thread shutdown)."""
    import threading

    from luminary_memory.backends.sqlite import SQLiteBackend

    holder: dict = {}

    def create_in_thread():
        b = SQLiteBackend(str(tmp_path / "t.db"))
        # connection created on THIS thread
        b.conn.execute("SELECT 1").fetchone()
        holder["backend"] = b

    t = threading.Thread(target=create_in_thread)
    t.start()
    t.join()
    b = holder["backend"]
    # Connection was created in another thread; closing here must not crash.
    b.close()  # should not raise
def test_thread_local_connections(tmp_path):
    """Connections are thread-local: recall from a background thread must not
    raise ProgrammingError (regression: provider prefetch recall crashed)."""
    import threading

    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [0.1, 0.1, 0.1]
        def embed_batch(self, ts): return [[0.1, 0.1, 0.1] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "tl.db"), engine=_E())
    c.ingest("deploy target production", tags=["deploy"])
    c.ingest("banana smoothie recipe", tags=["food"])

    result = {}

    def worker():
        res = c.recall("deploy", limit=10)
        result["n"] = len(res.memories)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["n"] == 1  # recall from other thread worked
    c.close()


def test_top_by_importance_lean_and_ordered(tmp_path):
    """top_by_importance returns top-N by importance desc, then access desc,
    without decoding embedding blobs."""
    b = _mk(tmp_path)
    b.add(Memory(content="low value fact", importance=0.3))
    b.add(Memory(content="medium fact", importance=0.6, access_count=5))
    b.add(Memory(content="high rule", importance=0.95, access_count=1))
    b.add(Memory(content="high rule 2", importance=0.9, access_count=9))

    top = b.top_by_importance(2, min_importance=0.5)
    assert [m.content for m in top] == ["high rule", "high rule 2"]
    # embeddings are not loaded (lean scan) — memory has no embedding attr set
    assert all(getattr(m, "embedding", None) is None for m in top)

    # min_importance filters below-threshold (0.3 excluded)
    top_all = b.top_by_importance(10, min_importance=0.5)
    assert len(top_all) == 3
    assert all(m.importance >= 0.5 for m in top_all)


def test_touch_memories_batches_access(tmp_path):
    b = _mk(tmp_path)
    a = b.add(Memory(content="fact one"))
    bb = b.add(Memory(content="fact two"))
    cid = b.add(Memory(content="untouched"))

    b.touch_memories([a, bb])
    touched = {m.id: m.access_count for m in b.all()}
    assert touched[a] == 1
    assert touched[bb] == 1
    assert touched[cid] == 0  # untouched stays 0

    b.touch_memories([a])
    assert {m.id: m.access_count for m in b.all()}[a] == 2


def test_delete_many_batches(tmp_path):
    b = _mk(tmp_path)
    ids = [b.add(Memory(content=f"fact {i}")) for i in range(4)]
    assert b.count() == 4
    b.delete_many(ids[:3])
    assert b.count() == 1
    assert b.get(ids[3]) is not None


def test_update_importances_bulk(tmp_path):
    b = _mk(tmp_path)
    ids = [b.add(Memory(content=f"fact {i}", importance=0.3)) for i in range(3)]
    b.update_importances([(0.9, ids[0]), (0.5, ids[1])])
    by_id = {m.id: m.importance for m in b.all()}
    assert by_id[ids[0]] == 0.9
    assert by_id[ids[1]] == 0.5
    assert by_id[ids[2]] == 0.3  # untouched


def test_scan_embeddings_matrix_shape(tmp_path):
    b = _mk(tmp_path)
    for i in range(3):
        b.add(Memory(content=f"fact {i}", embedding=[float(i), 0.0, 0.0]))
    mid, mat = b.scan_embeddings_matrix()
    assert len(mid) == 3
    assert mat.shape == (3, 3)
    assert mat.dtype.name == "float32"
