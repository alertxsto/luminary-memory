"""Migrating a store to a different embedding model.

Changing ``embedding_model`` changes the vector width, and recall skips any row
whose width does not match the query vector. Without a reindex pass a model
change silently de-indexes the whole store: the rows are still there, they just
never match again. These tests pin the migration path that makes a model change
safe on an existing database.
"""

from __future__ import annotations

import logging

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings


class _FixedWidthEngine:
    """Deterministic engine whose vector width is chosen by the test."""

    def __init__(self, width: int):
        self.width = width

    def embed(self, text: str) -> list[float]:
        seed = sum(ord(char) for char in str(text)) or 1
        return [float((seed + index) % 97 + 1) for index in range(self.width)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _client(tmp_path, engine) -> MemoryClient:
    settings = Settings(
        db_path=str(tmp_path / "migration.db"),
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
    )
    return MemoryClient(settings=settings, engine=engine)


def test_reindex_reembeds_rows_written_by_another_model(tmp_path):
    old = _client(tmp_path, _FixedWidthEngine(3))
    try:
        old.ingest("Deploy target is staging.", evidence_quote="deploy target is staging")
        old.ingest("Deploy target is production.", evidence_quote="deploy target is production")
        assert {len(memory.embedding or []) for memory in old.backend.all()} == {3}
    finally:
        old.close()

    new = _client(tmp_path, _FixedWidthEngine(8))
    try:
        result = new.reindex_embeddings()

        assert result["total"] == 2
        assert result["reindexed"] == 2
        assert result["failed"] == 0
        assert result["dim"] == 8
        assert {len(memory.embedding or []) for memory in new.backend.all()} == {8}
    finally:
        new.close()


def test_reindex_leaves_rows_at_the_current_width_alone(tmp_path):
    client = _client(tmp_path, _FixedWidthEngine(8))
    try:
        client.ingest("Deploy target is staging.", evidence_quote="deploy target is staging")
        before = [list(memory.embedding or []) for memory in client.backend.all()]

        result = client.reindex_embeddings()

        assert result["reindexed"] == 0
        assert result["unchanged"] == 1
        assert [list(memory.embedding or []) for memory in client.backend.all()] == before
    finally:
        client.close()


def test_reindex_repairs_grounding_confidence_written_as_zero(tmp_path):
    # Rows stored before the grounding-confidence fix carry 0.0 even though their
    # evidence was verified, which keeps them below the abstention gate forever.
    client = _client(tmp_path, _FixedWidthEngine(8))
    try:
        memory_id = client.ingest(
            "User wants to be addressed as Sir.",
            evidence_quote="sir",
            confidence=0.0,
            metadata={"native_evidence": {"origin": "user"}},
        )
        assert client.get(memory_id).confidence == 0.0

        result = client.reindex_embeddings()

        assert result["confidence_repaired"] == 1
        assert client.get(memory_id).confidence == 0.9
    finally:
        client.close()


def test_reindex_does_not_invent_confidence_for_unverified_rows(tmp_path):
    client = _client(tmp_path, _FixedWidthEngine(8))
    try:
        memory_id = client.ingest(
            "Deploy target is staging.", evidence_quote="deploy target is staging", confidence=0.0
        )

        result = client.reindex_embeddings()

        assert result["confidence_repaired"] == 0
        assert client.get(memory_id).confidence == 0.0
    finally:
        client.close()


def test_recall_warns_once_when_stored_vectors_predate_the_model(tmp_path, caplog):
    old = _client(tmp_path, _FixedWidthEngine(3))
    try:
        old.ingest("Deploy target is staging.", evidence_quote="deploy target is staging")
    finally:
        old.close()

    new = _client(tmp_path, _FixedWidthEngine(8))
    try:
        with caplog.at_level(logging.WARNING, logger="luminary_memory.api"):
            new.recall("deploy target", limit=5)
            new.recall("deploy target", limit=5)

        warnings = [
            record for record in caplog.records
            if "luminary-memory reindex" in record.getMessage()
        ]
        assert len(warnings) == 1
        assert "3-dimensional" in warnings[0].getMessage()
        assert "8" in warnings[0].getMessage()
    finally:
        new.close()


def test_first_run_warns_before_downloading_the_model(tmp_path, caplog):
    from luminary_memory.embeddings.fastembed import FastembedEngine

    cache = tmp_path / "models"
    engine = FastembedEngine(
        model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        cache_dir=str(cache),
    )

    assert engine._model_is_cached() is False
    cache.mkdir()
    (cache / "models--Xenova--paraphrase-multilingual-mpnet-base-v2").mkdir()
    assert engine._model_is_cached() is True


def test_cached_model_does_not_warn(tmp_path, caplog):
    from luminary_memory.embeddings.fastembed import FastembedEngine

    cache = tmp_path / "models"
    (cache / "models--Xenova--paraphrase-multilingual-mpnet-base-v2").mkdir(parents=True)
    engine = FastembedEngine(
        model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        cache_dir=str(cache),
    )

    with caplog.at_level(logging.WARNING, logger="luminary_memory.embeddings.fastembed"):
        assert engine._model_is_cached() is True
    assert not [r for r in caplog.records if "not cached" in r.getMessage()]
