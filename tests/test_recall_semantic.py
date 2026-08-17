from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.recall.semantic import semantic_recall
from luminary_memory.types import Memory


def _fake_engine(vec: list[float]):
    class _E:
        def embed(self, t):
            return vec
    return _E()


def _mk(tmp_path):
    return SQLiteBackend(str(tmp_path / "t.db"))


def test_semantic_recall_ranks_most_similar_first(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="cat sitting on a mat", embedding=[1.0, 0.0, 0.0]))
    b.add(Memory(content="database indexing with postgres", embedding=[0.0, 1.0, 0.0]))
    query_vec = [1.0, 0.0, 0.0]
    res = semantic_recall(b, _fake_engine(query_vec), "a query", limit=10)
    assert len(res) == 2
    assert res[0][0].content == "cat sitting on a mat"
    assert res[0][1] > res[1][1]
    assert res[0][2] == "semantic"


def test_semantic_recall_respects_limit(tmp_path):
    b = _mk(tmp_path)
    for i in range(4):
        b.add(Memory(content=f"memory {i}", embedding=[float(i), 0.0, 1.0]))
    res = semantic_recall(b, _fake_engine([1.0, 0.0, 1.0]), "q", limit=2)
    assert len(res) == 2


def test_semantic_recall_skips_memories_without_embedding(tmp_path):
    b = _mk(tmp_path)
    b.add(Memory(content="has embedding", embedding=[1.0, 0.0]))
    b.add(Memory(content="no embedding"))
    res = semantic_recall(b, _fake_engine([1.0, 0.0]), "q", limit=10)
    assert all(m.content != "no embedding" for m, _, _ in res)
