"""Long-lived store tests beyond ordinary happy-path unit coverage."""

from __future__ import annotations

import json

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import NoopEnricher


class _Engine:
    def embed(self, text: str) -> list[float]:
        value = (sum(ord(char) for char in text) % 97) + 1
        return [float(value), float(len(text) + 1), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _client(path, **kwargs) -> MemoryClient:
    return MemoryClient(
        db_path=str(path),
        engine=_Engine(),
        enricher=NoopEnricher(),
        **kwargs,
    )


def test_reopen_cycles_preserve_fts_graph_and_provenance(tmp_path):
    db = tmp_path / "reopen.db"
    content = "Postgres vector search uses pgvector for deploy retrieval."
    client = _client(
        db, settings=Settings(db_path=str(db), strict_recall=True, evidence_required=True)
    )
    memory_id = client.ingest(content, tags=["postgres", "vector"], evidence_quote=content)
    client.close()

    for _ in range(3):
        client = _client(
            db, settings=Settings(db_path=str(db), strict_recall=True, evidence_required=True)
        )
        assert client.search("pgvector", limit=5)
        assert client.recall("Postgres vector search", strict=True).memories
        graph = client.graph(limit=20)
        assert graph["entities"]
        assert (
            client.backend.conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE id = ?", (f"memory:{memory_id}",)
            ).fetchone()[0]
            == 1
        )
        assert (
            client.backend.conn.execute(
                "SELECT COUNT(*) FROM memory_evidence WHERE memory_id = ?", (memory_id,)
            ).fetchone()[0]
            == 1
        )
        client.close()


def test_repeated_normalized_writes_are_idempotent_and_audited(tmp_path):
    client = _client(tmp_path / "idempotent.db")
    first = client.ingest("  durable   preference: dark mode  ")
    for _ in range(99):
        assert client.ingest("durable preference: dark mode") == first

    assert client.count() == 1
    assert (
        client.backend.conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE event_type = 'duplicate_suppressed'"
        ).fetchone()[0]
        == 99
    )
    assert client.backend.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1
    client.close()


def test_lifecycle_second_run_is_idempotent_after_consolidation(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "lifecycle.db"),
        prune_min_importance=0.0,
        max_memories=None,
        consolidate_jaccard_threshold=0.8,
    )
    client = _client(tmp_path / "lifecycle.db", settings=settings)
    client.ingest(
        "postgres vector search is fast",
        tags=["db"],
        evidence_quote="postgres vector search is fast",
    )
    client.ingest(
        "postgres vector search is really fast",
        tags=["database"],
        evidence_quote="postgres vector search is really fast",
    )
    first = client.run_lifecycle(semantic=False)
    count_after_first = client.count()
    second = client.run_lifecycle(semantic=False)

    assert first["consolidate"] == 1
    assert count_after_first == 1
    assert second["consolidate"] == 0
    assert client.count() == count_after_first
    client.close()


def test_import_marks_rows_for_reindex_when_secondary_index_rebuild_fails(tmp_path, monkeypatch):
    import luminary_memory.recall.graph as graph_module

    path = tmp_path / "import.json"
    path.write_text(
        json.dumps(
            {
                "format": "luminary-memory-export",
                "version": 1,
                "memories": [{"content": "imported durable fact"}],
            }
        ),
        encoding="utf-8",
    )
    client = _client(tmp_path / "import.db")

    def _fail_index(*args, **kwargs):
        raise RuntimeError("graph unavailable")

    monkeypatch.setattr(graph_module, "index_memory_entities", _fail_index)

    result = client.import_memories(path)
    assert result["imported"] == 1
    assert result["needs_reindex"] == 1
    assert client.list(limit=0)[0].needs_reindex is True
    client.close()
