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


def test_query_expansion_falls_back_to_rules(tmp_path):
    """When the graph yields nothing, rule keywords expand the query.

    AM-T2.1: a durable rule whose topic overlaps the query contributes its
    keywords, so semantic recall can surface it even for a loose query.
    """
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall.semantic import _expand_query

    class _E:
        def embed(self, t):
            return [0.1, 0.2, 0.3]

        def embed_batch(self, ts):
            return [[0.1, 0.2, 0.3] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "r.db"), engine=_E())
    c.settings.rule_auto_replace = False
    # durable rule: topic overlaps "laporan" -> contributes "tabel"
    mid = c.ingest("laporan selalu pakai markdown tabel", tags=["rule"])
    assert mid is not None
    m = c.get(mid)
    m.importance = 0.95  # pin as a rule
    c.backend.update(m)

    expanded = _expand_query(c.backend, "buat laporan")
    assert "buat laporan" in expanded, "original query must remain"
    assert expanded != "buat laporan", "rule expansion must append a keyword"
    assert "tabel" in expanded.lower(), "rule keyword must be appended"
    c.close()


def test_query_expansion_rule_noop_when_no_overlap(tmp_path):
    """A rule that does not share a topic with the query must NOT expand it."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall.semantic import _expand_query

    class _E:
        def embed(self, t):
            return [0.1, 0.2, 0.3]

        def embed_batch(self, ts):
            return [[0.1, 0.2, 0.3] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "rn.db"), engine=_E())
    c.settings.rule_auto_replace = False
    mid = c.ingest("selalu pakai markdown tabel di telegram", tags=["rule"])
    m = c.get(mid)
    m.importance = 0.95
    c.backend.update(m)

    expanded = _expand_query(c.backend, "postgres indexing strategy")
    assert expanded == "postgres indexing strategy", \
        f"unrelated query must stay unchanged, got {expanded!r}"
    c.close()


def test_query_expansion_backend_without_top_by_importance(tmp_path):
    """A backend without top_by_importance leaves the query unchanged."""
    from luminary_memory.backends.sqlite import SQLiteBackend
    from luminary_memory.recall.semantic import _expand_query

    class _NoTopBy(SQLiteBackend):
        top_by_importance = None

    b = _NoTopBy(str(tmp_path / "nb.db"))
    assert _expand_query(b, "buat laporan") == "buat laporan"
    b.close()


def test_query_expansion_rule_short_words_noop(tmp_path):
    """A rule whose content has only tiny words adds nothing (edge)."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall.semantic import _expand_query

    class _E:
        def embed(self, t): return [0.1, 0.2]
        def embed_batch(self, ts): return [[0.1, 0.2] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "sw.db"), engine=_E())
    c.settings.rule_auto_replace = False
    mid = c.ingest("xy ab cd", tags=["rule"])  # all words len <= 2 -> no keyword
    m = c.get(mid)
    m.importance = 0.95
    c.backend.update(m)
    assert _expand_query(c.backend, "xy topik") == "xy topik"
    c.close()


def test_query_expansion_rule_extra_empty_noop(tmp_path):
    """Rule overlaps the query but adds no NEW keyword -> query unchanged."""
    from luminary_memory.api import MemoryClient
    from luminary_memory.recall.semantic import _expand_query

    class _E:
        def embed(self, t): return [0.1, 0.2]
        def embed_batch(self, ts): return [[0.1, 0.2] for _ in ts]

    c = MemoryClient(db_path=str(tmp_path / "ee.db"), engine=_E())
    c.settings.rule_auto_replace = False
    # no tags so the graph has no entity to expand from (rule expansion path only)
    mid = c.ingest("laporan tabel", tags=[])
    m = c.get(mid)
    m.importance = 0.95
    c.backend.update(m)
    # query already contains every rule word -> no NEW keyword to append
    assert _expand_query(c.backend, "laporan tabel") == "laporan tabel"
    c.close()


def test_query_expansion_rule_error_falls_back(tmp_path):
    """If rule expansion raises, the query is returned unchanged."""
    from luminary_memory.recall.semantic import _expand_query

    class _Exploding:
        def top_by_importance(self, top_n, min_importance=0.0):
            raise RuntimeError("boom")

    assert _expand_query(_Exploding(), "buat laporan") == "buat laporan"
