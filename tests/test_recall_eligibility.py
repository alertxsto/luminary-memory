"""Eligible candidates must survive cutoffs, and failures must not read as abstention."""

from __future__ import annotations

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings


class _Engine:
    """Deterministic vectors: related texts share a direction."""

    def __init__(self, vectors: dict[str, list[float]] | None = None, default=None):
        self.vectors = vectors or {}
        self.default = default

    def embed(self, text: str) -> list[float]:
        probe = str(text).casefold()
        for key, vector in self.vectors.items():
            if key in probe:
                return list(vector)
        if self.default is not None:
            return list(self.default(probe))
        return [0.0] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _unit(index: int, dimension: int = 384) -> list[float]:
    vector = [0.0] * dimension
    vector[index] = 1.0
    return vector


def _client(tmp_path, engine, **settings):
    return MemoryClient(
        settings=Settings(
            db_path=str(tmp_path / "eligibility.db"),
            importance_auto=False,
            rule_auto_replace=False,
            **settings,
        ),
        engine=engine,
    )


def test_ineligible_rows_cannot_consume_the_cutoff(tmp_path):
    # Untagged distractors outnumber the bounded over-fetch window, so only the
    # widened retry can find the tagged answer.
    engine = _Engine(default=lambda text: _unit(1))
    client = _client(tmp_path, engine)
    try:
        for index in range(40):
            client.ingest(f"distractor row {index}", tags=["noise"])
        answer = client.ingest("the release channel is stable", tags=["answer"])

        result = client.recall("release channel", limit=2, tags=["answer"], strict=False)

        assert answer in [memory.id for memory in result.memories]
    finally:
        client.close()


def test_keyword_only_candidate_is_scored_against_the_question(tmp_path):
    related = _unit(2)
    engine = _Engine({"deploy target": related}, default=lambda _text: _unit(3))
    client = _client(tmp_path, engine, strict_recall=True, evidence_required=True)
    try:
        answer = client.ingest("deploy target is production", evidence_quote="deploy target is production")
        # Only the keyword path can surface this row.
        from luminary_memory.recall import semantic

        original = semantic.semantic_recall
        semantic.semantic_recall = lambda *args, **kwargs: []
        try:
            result = client.recall("deploy target", limit=5, strict=True)
        finally:
            semantic.semantic_recall = original

        assert answer in [memory.id for memory in result.memories], (
            "a keyword candidate with true similarity must not be treated as unsupported"
        )
    finally:
        client.close()


def test_unsupported_lexical_hit_cannot_suppress_a_supported_paraphrase(tmp_path):
    query_vector = _unit(4)
    paraphrase = "the fruit is yellow and curved"
    engine = _Engine(
        {
            "banana": _unit(5),  # lexically perfect, semantically unrelated
            paraphrase: query_vector,
            "yellow fruit": query_vector,
        }
    )
    client = _client(tmp_path, engine, strict_recall=True, evidence_required=True)
    try:
        client.ingest("banana", evidence_quote="banana")
        answer = client.ingest(paraphrase, evidence_quote=paraphrase)

        result = client.recall("yellow fruit", limit=5, strict=True)

        assert answer in [memory.id for memory in result.memories]
    finally:
        client.close()


def test_all_strategy_failures_report_unavailable(tmp_path):
    engine = _Engine()
    client = _client(tmp_path, engine, strict_recall=True)
    try:
        from luminary_memory.recall import graph, keyword, semantic, temporal

        def boom(*_args, **_kwargs):
            raise RuntimeError("backend offline")

        saved = (semantic.semantic_recall, keyword.keyword_recall, temporal.temporal_recall, graph.graph_recall)
        semantic.semantic_recall = boom
        keyword.keyword_recall = boom
        temporal.temporal_recall = boom
        graph.graph_recall = boom
        try:
            result = client.recall("anything at all", strict=True)
        finally:
            semantic.semantic_recall, keyword.keyword_recall, temporal.temporal_recall, graph.graph_recall = saved

        assert result.status == "unavailable"
        assert result.reason == "all_strategies_failed"
    finally:
        client.close()


def test_partial_strategy_failure_still_answers(tmp_path):
    engine = _Engine(default=lambda text: _unit(6))
    client = _client(tmp_path, engine)
    try:
        answer = client.ingest("postgres vector search is fast")
        from luminary_memory.recall import semantic

        original = semantic.semantic_recall
        semantic.semantic_recall = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("onnx failed"))
        try:
            result = client.recall("postgres vector search", limit=5, strict=False)
        finally:
            semantic.semantic_recall = original

        assert result.status not in {"unavailable", "abstain"}
        assert answer in [memory.id for memory in result.memories]
    finally:
        client.close()


def test_configured_weights_change_the_ranking(tmp_path):
    engine = _Engine()
    client = _client(tmp_path, engine)
    try:
        lexical = client.ingest("alpha release note")
        relational = client.ingest("beta release note")
        from luminary_memory.recall import graph, keyword, semantic, temporal

        assert lexical is not None and relational is not None
        lexical_memory = client.backend.get(lexical)
        relational_memory = client.backend.get(relational)
        saved = (semantic.semantic_recall, keyword.keyword_recall, temporal.temporal_recall, graph.graph_recall)
        semantic.semantic_recall = lambda *a, **k: []
        temporal.temporal_recall = lambda *a, **k: []
        keyword.keyword_recall = lambda *a, **k: [(lexical_memory, 0.9, "keyword")]
        graph.graph_recall = lambda *a, **k: [(relational_memory, 0.9, "graph")]
        try:
            client.settings.strategy_weights = {"semantic": 0.4, "keyword": 0.9, "graph": 0.1, "temporal": 0.1}
            keyword_first = client.recall("release note", limit=2, strict=False)
            client.settings.strategy_weights = {"semantic": 0.4, "keyword": 0.1, "graph": 0.9, "temporal": 0.1}
            graph_first = client.recall("release note", limit=2, strict=False)
        finally:
            semantic.semantic_recall, keyword.keyword_recall, temporal.temporal_recall, graph.graph_recall = saved

        assert keyword_first.memories[0].id == lexical
        assert graph_first.memories[0].id == relational
    finally:
        client.close()
