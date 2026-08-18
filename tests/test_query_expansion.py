def test_query_expansion_adds_related_entities(tmp_path):
    """_expand_query appends co-occurring entity names to short queries."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall.semantic import _expand_query

    class _E:
        def embed(self, t):
            return [0.1, 0.2, 0.3]

        def embed_batch(self, ts):
            return [[0.1, 0.2, 0.3] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "q.db"), engine=_E())
    c.ingest("deploy target is production cluster", tags=["deploy"])
    c.ingest("production database runs on port 5432", tags=["production"])

    expanded = _expand_query(c.backend, "deploy?")
    # should contain related entity from graph (e.g. production/cluster)
    assert "deploy" in expanded
    assert expanded != "deploy?"
    c.close()
