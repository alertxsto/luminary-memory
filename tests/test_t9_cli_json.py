import json

from typer.testing import CliRunner

from luminary_memory.cli import app

runner = CliRunner()


def _invoke(args, db_path):
    return runner.invoke(app, args + ["--db-path", str(db_path)])


def test_list_json_returns_parseable_list(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "hello json list memory"], db)
    _invoke(["add", "second json list memory", "--tags", "alpha"], db)
    r = _invoke(["list", "--json"], db)
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert isinstance(data, list)
    assert len(data) == 2
    assert all("id" in d and "content" in d and "tags" in d for d in data)


def test_search_json_returns_list_with_score(tmp_path):
    db = tmp_path / "t.db"
    _invoke(["add", "postgresql indexing for search json"], db)
    r = _invoke(["search", "postgresql", "--json"], db)
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "score" in data[0]
    assert "postgresql" in data[0]["content"].lower()
