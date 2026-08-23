import json

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import NoopEnricher


class _FakeEngine:
    def embed(self, t: str) -> list[float]:
        return [0.1] * 3

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 3 for _ in texts]


def test_export_import_round_trip(tmp_path):
    src_db = tmp_path / "src.db"
    src = MemoryClient(db_path=str(src_db), engine=_FakeEngine(), enricher=NoopEnricher())
    src.ingest("hello export world", tags=["t-a"], source="s1")
    src.ingest("second memory for export", tags=["t-b"], source="s2")
    src.ingest("third memory export", tags=["t-c"])
    path = tmp_path / "backup.json"
    exported = src.export(path)
    assert path.exists()
    assert exported["count"] == 3
    assert json.loads(path.read_text())["version"] == 1

    dst = MemoryClient(db_path=str(tmp_path / "dst.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    imported = dst.import_memories(path)
    assert imported["imported"] == 3
    assert dst.count() == 3
    contents = {m.content for m in dst.list(limit=0)}
    assert "hello export world" in contents
    assert "second memory for export" in contents


def test_import_recomputes_embeddings_when_absent(tmp_path):
    src = MemoryClient(db_path=str(tmp_path / "src2.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    src.ingest("export without embeddings text")
    path = tmp_path / "noemb.json"
    src.export(path, include_embeddings=False)
    data = json.loads(path.read_text())
    assert all(m.get("embedding") is None for m in data["memories"])

    dst = MemoryClient(db_path=str(tmp_path / "dst2.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    dst.import_memories(path)
    assert dst.count() == 1
    # embedding should have been recomputed on import
    assert dst.list(limit=0)[0].embedding is not None


def test_cli_export_import(tmp_path):
    from typer.testing import CliRunner

    from luminary_memory.cli import app

    runner = CliRunner()
    db = tmp_path / "cli.db"
    dst_db = tmp_path / "cli_dst.db"
    path = tmp_path / "cli.json"
    r = runner.invoke(app, ["add", "cli export memory one", "--db-path", str(db)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["export", "--path", str(path), "--db-path", str(db)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["import", "--path", str(path), "--db-path", str(dst_db)])
    assert r.exit_code == 0, r.output
    assert "imported" in r.output.lower()


def test_import_bare_list_format(tmp_path):
    """Bare JSON list (no wrapper dict) imports fine."""
    import json as _json

    from luminary_memory.api import MemoryClient

    payload = [
        {"content": "bare list memory one", "tags": ["a"]},
        {"content": "bare list memory two", "tags": ["b"]},
    ]
    p = tmp_path / "bare.json"
    p.write_text(_json.dumps(payload))

    dst = MemoryClient(db_path=str(tmp_path / "dst.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    imported = dst.import_memories(p)
    assert imported["imported"] == 2
    contents = {m.content for m in dst.list(limit=0)}
    assert "bare list memory one" in contents


def test_import_fills_missing_timestamps_for_strict_backends(tmp_path):
    payload = [{"content": "timestamp-safe imported memory"}]
    path = tmp_path / "timestamp-safe.json"
    path.write_text(json.dumps(payload))
    dst = MemoryClient(
        db_path=str(tmp_path / "timestamp-safe.db"),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
    )
    assert dst.import_memories(path)["imported"] == 1
    memory = dst.list(limit=0)[0]
    assert memory.created_at
    assert memory.updated_at
    dst.close()


def test_import_missing_file_raises_cleanly(tmp_path):
    """Missing file raises FileNotFoundError (not swallowed)."""
    from luminary_memory.api import MemoryClient

    dst = MemoryClient(db_path=str(tmp_path / "dst2.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    try:
        dst.import_memories(tmp_path / "does-not-exist.json")
        assert False, "should have raised"
    except FileNotFoundError:
        pass


def test_import_engine_embed_failure_falls_back(tmp_path):
    """Engine embed failure falls back to embedding=None instead of crashing."""
    import json as _json

    from luminary_memory.api import MemoryClient

    class _BrokenEngine(_FakeEngine):
        def embed(self, t):
            raise RuntimeError("embed failed")

    payload = [{"content": "no embedding memory"}]
    p = tmp_path / "noemb2.json"
    p.write_text(_json.dumps(payload))

    dst = MemoryClient(db_path=str(tmp_path / "dst3.db"), engine=_BrokenEngine(), enricher=NoopEnricher())
    imported = dst.import_memories(p)  # embed fails -> falls back to None
    assert imported["imported"] == 1
    mems = dst.list(limit=0)
    assert mems[0].content == "no embedding memory"


def test_import_dedup_skips_existing(tmp_path):
    """Importing memories that already exist skips them (no duplicates)."""
    import json as _json

    from luminary_memory.api import MemoryClient

    # Seed store with one memory
    dst = MemoryClient(db_path=str(tmp_path / "dst.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    dst.ingest("existing fact about deploy target", tags=["deploy"])

    # Export file contains 1 duplicate + 1 new
    payload = {
        "memories": [
            {"content": "existing fact about deploy target", "tags": ["deploy"]},
            {"content": "brand new fact about database", "tags": ["db"]},
        ]
    }
    p = tmp_path / "dup.json"
    p.write_text(_json.dumps(payload))

    result = dst.import_memories(p)
    assert result["imported"] == 1
    assert result["skipped_duplicates"] == 1
    # No duplicate in store
    contents = [m.content for m in dst.list(limit=0)]
    assert contents.count("existing fact about deploy target") == 1
    assert "brand new fact about database" in contents


def test_import_dedup_uses_same_normalized_content_hash_as_ingest(tmp_path):
    import json as _json

    dst = MemoryClient(db_path=str(tmp_path / "normalized.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    dst.ingest("normalized   durable   fact")
    path = tmp_path / "normalized.json"
    path.write_text(_json.dumps({"memories": [{"content": "  NORMALIZED durable fact  "}]}))

    result = dst.import_memories(path)
    assert result["imported"] == 0
    assert result["skipped_duplicates"] == 1
    dst.close()


def test_import_can_restore_content_after_retraction(tmp_path):
    """Inactive history must not block an active restore/import."""
    dst = MemoryClient(
        db_path=str(tmp_path / "restore-after-retract.db"),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
    )
    memory_id = dst.ingest("retractable durable fact")
    assert memory_id is not None
    dst.retract(memory_id, reason="source revoked")

    path = tmp_path / "restore-after-retract.json"
    path.write_text(
        json.dumps({"memories": [{"content": "retractable durable fact"}]}),
        encoding="utf-8",
    )
    result = dst.import_memories(path)

    assert result["imported"] == 1
    assert dst.count() == 1
    assert [m.status for m in dst.list(limit=0)] == ["active"]
    assert sum(m.content == "retractable durable fact" for m in dst.backend.all()) == 2
    dst.close()


def test_scoped_import_does_not_dedup_against_global_compatibility_row(tmp_path):
    """Global read compatibility must not block a tenant-owned restore."""
    db = tmp_path / "scoped-restore.db"
    writer = MemoryClient(db_path=str(db), engine=_FakeEngine(), enricher=NoopEnricher())
    writer.ingest("shared global restore fact")
    path = tmp_path / "scoped-restore.json"
    path.write_text(
        json.dumps({"memories": [{"content": "shared global restore fact"}]}),
        encoding="utf-8",
    )
    writer.close()

    scoped = MemoryClient(
        db_path=str(db),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
        settings=Settings(db_path=str(db), scope_include_global=False),
        scope={"user_id": "alice"},
    )
    result = scoped.import_memories(path)

    assert result["imported"] == 1
    assert scoped.count() == 1
    assert [m.user_id for m in scoped.list(limit=0)] == ["alice"]
    assert sum(m.content == "shared global restore fact" for m in scoped.backend.all()) == 2
    scoped.close()


def test_import_race_winner_does_not_duplicate_lineage(tmp_path, monkeypatch):
    """A DB-level duplicate winner must not get a second import episode."""
    from luminary_memory.api import MemoryClient

    dst = MemoryClient(
        db_path=str(tmp_path / "race-import.db"),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
    )
    dst.ingest("concurrent import durable fact")
    path = tmp_path / "race-import.json"
    path.write_text(
        json.dumps({"memories": [{"content": "concurrent import durable fact"}]}),
        encoding="utf-8",
    )

    # Hide the optimistic pre-check so the test exercises the backend's
    # database-enforced conflict resolution path.
    monkeypatch.setattr(dst.backend, "all", list)
    result = dst.import_memories(path)

    assert result["imported"] == 0
    assert result["skipped_duplicates"] == 1
    assert dst.count() == 1
    assert dst.backend.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1
    assert dst.backend.conn.execute(
        "SELECT COUNT(*) FROM memory_events WHERE event_type = 'import'"
    ).fetchone()[0] == 0
    dst.close()


def test_import_recomputes_tampered_content_hash_and_sanitizes_scores(tmp_path):
    import json as _json

    dst = MemoryClient(
        db_path=str(tmp_path / "tampered.db"),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
    )
    path = tmp_path / "tampered.json"
    path.write_text(
        _json.dumps(
            {
                "memories": [
                    {
                        "content": "durable imported fact",
                        "content_hash": "stale-hash",
                        "importance": 99,
                        "confidence": -4,
                        "ttl_seconds": "broken",
                        "tags": "not-a-list",
                        "metadata": ["not", "a", "mapping"],
                        "access_count": "broken",
                    }
                ]
            }
        )
    )

    assert dst.import_memories(path)["imported"] == 1
    memory = dst.list(limit=0)[0]
    assert memory.importance == 1.0
    assert memory.confidence == 0.0
    assert memory.tags == []
    assert memory.metadata == {}
    assert memory.access_count == 0
    assert memory.content_hash == dst.backend.find_by_hash(memory.content_hash).content_hash
    assert memory.ttl_seconds is None
    dst.close()


def test_import_rejects_future_or_malformed_exports(tmp_path):
    import json as _json

    import pytest

    dst = MemoryClient(db_path=str(tmp_path / "validate.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    future = tmp_path / "future.json"
    future.write_text(_json.dumps({"format": "luminary-memory-export", "version": 999, "memories": []}))
    with pytest.raises(ValueError, match="unsupported export version"):
        dst.import_memories(future)

    malformed = tmp_path / "malformed.json"
    malformed.write_text(_json.dumps({"format": "other", "memories": []}))
    with pytest.raises(ValueError, match="unsupported export format"):
        dst.import_memories(malformed)
    dst.close()
