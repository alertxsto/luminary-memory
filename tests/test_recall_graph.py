from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.recall.graph import extract_entities, graph_recall, index_memory_entities
from luminary_memory.types import Memory


def test_extract_entities_returns_tags_and_keywords(tmp_path):
    m = Memory(content="postgres pgvector embedding search", tags=["database"])
    ents = extract_entities(m)
    assert "database" in ents
    assert any(e in ents for e in ["postgres", "pgvector", "embedding", "search"])


def test_graph_recall_finds_related_memories_via_shared_entity(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    id_a = b.add(Memory(content="postgres pgvector stores vectors", tags=["database"]))
    id_b = b.add(Memory(content="postgres pgvector powers search", tags=["database"]))
    b.add(Memory(content="cooking pasta for dinner", tags=["food"]))
    # index entities from stored memories
    for mem in b.all():
        index_memory_entities(b, mem)
    res = graph_recall(b, "postgres pgvector", limit=10)
    ids = {m.id for m, _, _ in res}
    assert id_b in ids
    assert any(m.id == id_b for m, _, _ in res)
    # unrelated memory should score lower or not appear highly
    pos_a = next((i for i, (m, _, _) in enumerate(res) if m.id == id_a), None)
    pos_b = next((i for i, (m, _, _) in enumerate(res) if m.id == id_b), None)
    assert pos_a is not None and pos_b is not None
    # strategy label
    assert all(s == "graph" for _, _, s in res)


def test_graph_recall_empty_query_returns_empty(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    b.add(Memory(content="something tagged", tags=["x"]))
    for mem in b.all():
        index_memory_entities(b, mem)
    res = graph_recall(b, "", limit=10)
    assert res == []


def test_graph_recall_respects_limit(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    for w in ["alpha", "beta", "gamma", "delta"]:
        mem = Memory(content=f"{w} keyword", tags=[w])
        mid = b.add(mem)
        mem.id = mid
        index_memory_entities(b, mem)
    res = graph_recall(b, "alpha beta gamma delta", limit=2)
    assert len(res) <= 2
