import json

from luminary_memory.api import MemoryClient
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
