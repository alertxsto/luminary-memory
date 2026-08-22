"""Long-lived store tests beyond ordinary happy-path unit coverage."""

from __future__ import annotations

import json
import multiprocessing as mp
import sqlite3

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import EnrichedContent, NoopEnricher
from luminary_memory.schema import SCHEMA_SQL, init_schema


class _Engine:
    def embed(self, text: str) -> list[float]:
        value = (sum(ord(char) for char in text) % 97) + 1
        return [float(value), float(len(text) + 1), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _client(path, **kwargs) -> MemoryClient:
    enricher = kwargs.pop("enricher", NoopEnricher())
    return MemoryClient(
        db_path=str(path),
        engine=_Engine(),
        enricher=enricher,
        **kwargs,
    )


def _race_worker(path, barrier, output) -> None:
    client = _client(path, settings=Settings(db_path=str(path), rule_auto_replace=False))
    try:
        barrier.wait(timeout=10)
        output.put(client.ingest("concurrent exact durable fact"))
    finally:
        client.close()


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


def test_cross_process_exact_dedup_is_atomic(tmp_path):
    """Two independent writers must converge on one row and one episode."""
    methods = mp.get_all_start_methods()
    start_method = "forkserver" if "forkserver" in methods else "spawn"
    db = tmp_path / "race.db"
    ctx = mp.get_context(start_method)
    barrier = ctx.Barrier(2)
    output = ctx.Queue()
    processes = [
        ctx.Process(target=_race_worker, args=(db, barrier, output)) for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        ids = sorted(output.get(timeout=15) for _ in processes)
        for process in processes:
            process.join(timeout=15)
        assert all(process.exitcode == 0 for process in processes)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    client = _client(db)
    assert ids == [1, 1]
    assert client.count() == 1
    assert client.backend.count() == 1
    assert client.backend.conn.execute(
        "SELECT COUNT(*) FROM episodes"
    ).fetchone()[0] == 1
    event_types = [
        row[0]
        for row in client.backend.conn.execute(
            "SELECT event_type FROM memory_events ORDER BY id"
        ).fetchall()
    ]
    assert event_types.count("ingest") == 1
    assert event_types.count("duplicate_suppressed") == 1
    client.close()


def test_retracted_rows_are_excluded_from_client_count(tmp_path):
    client = _client(tmp_path / "count.db")
    memory_id = client.ingest("countable durable fact")
    assert client.count() == 1
    client.retract(memory_id, reason="test lifecycle")
    assert client.count() == 0
    assert client.backend.count() == 1
    client.close()


def test_schema_migration_collapses_legacy_active_hash_duplicates(tmp_path):
    db = tmp_path / "legacy-duplicates.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO memories(content, metadata, tags, status, content_hash) "
        "VALUES (?, '{}', '[]', 'active', ?)",
        ("legacy exact fact", "same-hash"),
    )
    conn.execute(
        "INSERT INTO memories(content, metadata, tags, status, content_hash) "
        "VALUES (?, '{}', '[]', 'active', ?)",
        ("legacy exact fact", "same-hash"),
    )
    conn.commit()
    init_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    index_names = {
        row[1] for row in conn.execute("PRAGMA index_list(memories)").fetchall()
    }
    assert "uq_memories_active_scope_hash" in index_names
    conn.close()


def test_rule_replace_preserves_new_raw_episode_and_claim_lineage(tmp_path):
    class RuleEngine:
        def embed(self, _text):
            return [1.0, 0.0, 0.0]

        def embed_batch(self, texts):
            return [self.embed(text) for text in texts]

    class RuleEnricher:
        def enrich(self, text):
            predicate = "deploy_target_alpha" if "alpha" in text else "deploy_target_beta"
            return EnrichedContent(
                content=text,
                importance=0.95,
                claims=[
                    {
                        "subject": "project:luminary",
                        "predicate": predicate,
                        "object": text.casefold(),
                        "evidence_quote": text,
                    }
                ],
            )

    db = tmp_path / "replace-lineage.db"
    settings = Settings(
        db_path=str(db),
        rule_auto_replace=True,
        rule_auto_replace_threshold=0.0,
        strict_recall=True,
        evidence_required=True,
        importance_auto=False,
    )
    client = MemoryClient(
        settings=settings,
        engine=RuleEngine(),
        enricher=RuleEnricher(),
    )
    first = client.ingest("Policy alpha")
    second = client.ingest("Policy beta")
    assert second == first
    episodes = client.backend.conn.execute(
        "SELECT id, content FROM episodes ORDER BY created_at, id"
    ).fetchall()
    assert [row[1] for row in episodes] == ["Policy alpha", "Policy beta"]
    claims = client.backend.conn.execute(
        "SELECT status, source_episode_id FROM claims ORDER BY id"
    ).fetchall()
    assert claims[0][0] == "superseded"
    assert claims[1][0] == "active"
    assert claims[1][1] == episodes[1][0]
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


def test_lifecycle_consolidation_does_not_cross_owner_scope(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "scope-consolidation.db"),
        rule_auto_replace=False,
        importance_auto=False,
        max_memories=None,
        consolidate_jaccard_threshold=0.8,
    )
    client = _client(tmp_path / "scope-consolidation.db", settings=settings)
    alice_id = client.ingest(
        "shared deployment target is staging",
        user_id="alice",
        evidence_quote="shared deployment target is staging",
    )
    bob_id = client.ingest(
        "shared deployment target is staging now",
        user_id="bob",
        evidence_quote="shared deployment target is staging now",
    )

    result = client.run_lifecycle(semantic=False)

    assert result["consolidate"] == 0
    assert client.backend.get(alice_id) is not None
    assert client.backend.get(bob_id) is not None
    assert client.count() == 2
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
