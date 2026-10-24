"""Strict-recall calibration for natural paraphrases.

The abstention guard must block a query whose best match is merely
topically adjacent, without also blocking a correct paraphrase that happens to
share no surface tokens with the stored fact. Those two situations are only
separable on the semantic score, and where that boundary sits depends on the
embedding model, so the floor is model-scoped rather than one global constant.
"""

from __future__ import annotations

import math

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings, semantic_support_floor

DIM = 16


def _unit(*components: float) -> list[float]:
    vector = [0.0] * DIM
    for index, value in enumerate(components):
        vector[index] = value
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


class _CalibratedEngine:
    """Returns vectors whose cosine to each memory is chosen by the test."""

    def __init__(self, vectors: dict[str, list[float]], default: list[float]):
        self._vectors = vectors
        self._default = default

    def embed(self, text: str) -> list[float]:
        probe = str(text or "").casefold()
        # Query text arrives expanded, so match the longest configured prefix.
        for prefix in sorted(self._vectors, key=len, reverse=True):
            if probe.startswith(prefix):
                return list(self._vectors[prefix])
        return list(self._default)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


FACT = "Project Luminary deploy target is production."
DISTRACTOR = "The office has a coffee machine on the second floor."


def _client(tmp_path, *, model: str, query_vector: list[float]) -> MemoryClient:
    engine = _CalibratedEngine(
        {
            FACT.casefold(): _unit(1.0),
            DISTRACTOR.casefold(): _unit(0.0, 1.0),
            "current deployment destination": query_vector,
            "what is the office wifi password": query_vector,
        },
        default=_unit(0.0, 0.0, 1.0),
    )
    settings = Settings(
        db_path=str(tmp_path / "calibration.db"),
        embedding_model=model,
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
    )
    return MemoryClient(settings=settings, engine=engine)


def _seed(client: MemoryClient) -> None:
    client.ingest(FACT, source="runbook", evidence_quote="deploy target is production")
    client.ingest(DISTRACTOR, source="facilities", evidence_quote="coffee machine on floor 2")


def test_paraphrase_with_no_shared_tokens_is_not_abstained(tmp_path):
    # cos(query, fact) = 0.73, cos(query, distractor) = 0.45: strong enough to
    # answer, and no shared surface token to corroborate it.
    client = _client(
        tmp_path, model="BAAI/bge-small-en-v1.5", query_vector=_unit(0.73, 0.45, 0.51)
    )
    try:
        _seed(client)
        result = client.recall("Current deployment destination", strict=True)

        assert result.status == "ok"
        assert [memory.content for memory in result.memories] == [FACT]
        assert 0.0 <= result.confidence <= 1.0
    finally:
        client.close()


def test_adjacent_but_unanswered_query_still_abstains(tmp_path):
    # cos(query, fact) = 0.66 sits below the calibrated floor: nothing in the
    # store actually answers this, so the guard must still fire.
    client = _client(
        tmp_path, model="BAAI/bge-small-en-v1.5", query_vector=_unit(0.66, 0.50, 0.56)
    )
    try:
        _seed(client)
        result = client.recall("What is the office WiFi password", strict=True)

        assert result.status == "abstain"
        assert result.memories == []
    finally:
        client.close()


def test_uncalibrated_model_keeps_the_conservative_floor(tmp_path):
    # The same evidence that answers on a calibrated model must not answer on a
    # model whose score distribution was never measured.
    client = _client(
        tmp_path, model="someone/unknown-embedding", query_vector=_unit(0.73, 0.45, 0.51)
    )
    try:
        _seed(client)
        result = client.recall("Current deployment destination", strict=True)

        assert result.status == "abstain"
        assert result.memories == []
    finally:
        client.close()


def test_floor_resolution_is_model_scoped():
    assert semantic_support_floor("BAAI/bge-small-en-v1.5") == 0.70
    assert semantic_support_floor("someone/unknown-embedding") == 0.78
    assert semantic_support_floor(None) == 0.78
