def test_recall_adaptive_returns_only_relevant(tmp_path):
    """Sparse store: recall returns few strong matches, not padded to limit."""
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [float(len(t)), 0.0, 0.0]
        def embed_batch(self, ts): return [[float(len(t)), 0.0, 0.0] for t in ts]

    c = MemoryClient(db_path=str(tmp_path / "a.db"), engine=_E())
    # 3 relevant to "deploy", 20 irrelevant
    for i in range(3):
        c.ingest(f"deploy target production cluster {i}", tags=["deploy"])
    for i in range(20):
        c.ingest(f"banana smoothie recipe number {i}", tags=["food"])
    res = c.recall("deploy target", limit=20)
    assert len(res.memories) > 0
    assert len(res.memories) <= 10  # not padded to 20
    assert all("deploy" in m.content for m in res.memories)
    c.close()


def test_recall_adaptive_dense_keeps_many(tmp_path):
    """Dense relevant store: recall still returns many (not over-filtered)."""
    from luminary_memory.api import MemoryClient

    class _E:
        def embed(self, t): return [float(len(t)), 0.0, 0.0]
        def embed_batch(self, ts): return [[float(len(t)), 0.0, 0.0] for t in ts]

    c = MemoryClient(db_path=str(tmp_path / "b.db"), engine=_E())
    for i in range(15):
        c.ingest(f"deploy target production cluster config {i}", tags=["deploy"])
    res = c.recall("deploy target", limit=20)
    # All are relevant -> adaptive floor keeps many
    assert len(res.memories) >= 10
    c.close()
