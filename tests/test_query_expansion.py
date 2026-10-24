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


def test_expansion_cannot_outrank_the_question_itself(tmp_path):
    """A graph-linked but off-topic memory must not beat the real answer.

    Reproduces the reported failure with a scripted engine instead of a real
    model so the ranking inversion is deterministic and offline: the raw
    question points at the deploy fact, while the expanded text — which now
    carries tokens harvested from the off-topic memory's own neighbourhood —
    points at the API reference. Expansion may widen the candidate set, but it
    must not decide that the off-topic row answers the question.
    """
    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings

    def _unit(*components):
        # 16 dimensions because anything shorter is treated as a degenerate
        # vector by the recall scoring guard.
        import math

        vector = [0.0] * 16
        for index, value in enumerate(components):
            vector[index] = value
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]

    class _ScriptedEngine:
        """Raw question -> the answer; expanded question -> the off-topic row."""

        def embed(self, text):
            probe = str(text or "").casefold()
            if "deploy target is production" in probe:
                return _unit(1.0, 0.0)
            if "api reference" in probe:
                return _unit(0.0, 1.0)
            if probe.startswith("where will luminary go live now?"):
                expanded = len(probe.split()) > 6
                return _unit(0.05, 0.99) if expanded else _unit(0.99, 0.05)
            return _unit(0.0, 0.0, 1.0)

        def embed_batch(self, texts):
            return [self.embed(text) for text in texts]

    client = MemoryClient(
        settings=Settings(
            db_path=str(tmp_path / "expansion.db"),
            strict_recall=True,
            evidence_required=True,
            rule_auto_replace=False,
        ),
        engine=_ScriptedEngine(),
    )
    answer = "Project Luminary deploy target is production."
    off_topic = "The canonical API reference is https://docs.example.test/luminary/api."
    try:
        client.ingest(answer, tags=["luminary"], source="t", evidence_quote=answer)
        client.ingest(off_topic, tags=["luminary"], source="t", evidence_quote=off_topic)

        result = client.recall(
            "Where will Luminary go live now?", limit=10, strict=True
        )

        contents = [memory.content for memory in result.memories]
        assert answer in contents, f"expansion hid the real answer: {contents}"
        assert off_topic not in contents, f"expansion promoted an off-topic row: {contents}"
        assert contents[0] == answer
    finally:
        client.close()
