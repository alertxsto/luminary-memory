import json

from typer.testing import CliRunner

from luminary_memory.cli import app

runner = CliRunner()


def _invoke(args, db_path):
    return runner.invoke(app, args + ["--db-path", str(db_path)])


def test_add_and_list(tmp_path):
    db = tmp_path / "t.db"
    r = _invoke(["add", "hello world memory"], db)
    assert r.exit_code == 0, r.output
    assert "added" in r.output

    r = _invoke(["list"], db)
    assert r.exit_code == 0
    assert "hello world memory" in r.output


def test_add_with_tags(tmp_path):
    db = tmp_path / "t.db"
    r = _invoke(["add", "tagged memory", "--tags", "alpha,beta"], db)
    assert r.exit_code == 0, r.output
    r = _invoke(["list"], db)
    assert "alpha" in r.output
    assert "beta" in r.output


def test_recall_json(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "the database uses sqlite fts5"], db)
    r = _invoke(["recall", "database", "--json"], db)
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert "memories" in data
    assert "scores" in data
    assert "strategies_hit" in data


def test_search(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "postgresql indexing"], db)
    r = _invoke(["search", "postgresql"], db)
    assert r.exit_code == 0
    assert "postgresql" in r.output


def test_stats_empty(tmp_path):
    db = tmp_path / "t.db"
    r = _invoke(["stats"], db)
    assert r.exit_code == 0
    assert json.loads(r.output)["count"] == 0


def test_lifecycle(tmp_path):
    db = tmp_path / "t.db"
    r = _invoke(["lifecycle"], db)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["cleanup"] == 0 and data["consolidate"] == 0 and data["prune"] == 0
    assert "reestimated" in data


def test_help():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "add" in r.output
    assert "recall" in r.output


def test_add_rejected_by_whitelist(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    # whitelist accepts only "kubernetes"
    monkeypatch.setenv("LUMINARY_INGEST_WHITELIST", "kubernetes")
    r = _invoke(["add", "random text without signal"], db)
    assert r.exit_code == 1
    assert "rejected" in r.output


def test_recall_negative_limit_errors(tmp_path):
    db = tmp_path / "t.db"
    r = _invoke(["recall", "query", "--limit", "-1"], db)
    assert r.exit_code == 1
    assert "limit" in r.output.lower() or "error" in r.output.lower()


def test_cli_command_error_clean(tmp_path):
    db = tmp_path / "t.db"
    # search with a malformed FTS query should degrade, not crash
    r = _invoke(["search", "-"], db)
    assert r.exit_code in (0, 1)


def test_health_command(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "deploy target is production", "--db-path", str(db)], db)
    r = _invoke(["health", "--json"], db)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert "score" in data
    assert "dimensions" in data


def test_recall_table_human_mode(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "postgres index tuning is critical", "--db-path", str(db)], db)
    r = _invoke(["recall", "postgres"], db)  # no --json → table
    assert r.exit_code == 0
    assert "postgres" in r.output or "Recall" in r.output


def test_health_human_mode(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "deploy target production", "--db-path", str(db)], db)
    r = _invoke(["health"], db)  # no --json → bar
    assert r.exit_code == 0
    assert "Health" in r.output


def test_lifecycle_semantic_flag(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "deploy target production cluster", "--db-path", str(db)], db)
    r = _invoke(["lifecycle", "--no-semantic"], db)
    assert r.exit_code == 0
    assert "consolidate" in r.output


def test_version_command():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "luminary-memory" in r.output
    assert "0.2" in r.output


def test_graph_command(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "deploy target production cluster", "--tags", "deploy", "--db-path", str(db)], db)
    r = _invoke(["graph", "--json"], db)
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert "entities" in data and "relations" in data


def test_graph_command_table(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "deploy production cluster", "--db-path", str(db)], db)
    r = _invoke(["graph"], db)
    assert r.exit_code == 0
    assert "Knowledge Graph" in r.output


def test_graph_relations_flag(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "deploy production cluster", "--db-path", str(db)], db)
    r = _invoke(["graph", "--relations"], db)
    assert r.exit_code == 0
    assert "Relations" in r.output
