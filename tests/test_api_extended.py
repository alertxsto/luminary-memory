
import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings


@pytest.fixture()
def client(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"))
    yield c
    c.close()


def test_config_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINARY_BACKEND", "sqlite")
    monkeypatch.setenv("LUMINARY_DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("LUMINARY_RRF_K", "42")
    monkeypatch.setenv("LUMINARY_TOKEN_BUDGET", "2048")
    monkeypatch.setenv("LUMINARY_INGEST_WHITELIST", "port,config")
    s = Settings()
    assert s.backend == "sqlite"
    assert s.db_path == str(tmp_path / "env.db")
    assert s.rrf_k == 42
    assert s.token_budget == 2048
    assert s.ingest_whitelist == ["port", "config"]


def test_config_env_bool(monkeypatch):
    monkeypatch.setenv("LUMINARY_INGEST_LLM", "true")
    assert Settings().ingest_llm is True
    monkeypatch.setenv("LUMINARY_INGEST_LLM", "0")
    assert Settings().ingest_llm is False


def test_update(client):
    mid = client.ingest("initial content here", tags=["a"])
    assert mid is not None
    m = client.get(mid)
    assert m is not None
    m.content = "updated content here"
    m.importance = 0.9
    client.update(m)
    got = client.get(mid)
    assert got is not None
    assert got.content == "updated content here"
    assert got.importance == 0.9


def test_delete(client):
    mid = client.ingest("delete me please")
    assert mid is not None
    client.delete(mid)
    assert client.get(mid) is None
    assert client.count() == 0


def test_list_ordering(client):
    client.ingest("first memory item")
    client.ingest("second memory item")
    mems = client.list(limit=10)
    assert len(mems) == 2
    # most recent first
    assert mems[0].content == "second memory item"
    assert mems[1].content == "first memory item"


def test_search_keyword(client):
    client.ingest("postgresql indexing with fts5")
    client.ingest("cooking pasta for lunch")
    res = client.search("postgresql", limit=5)
    assert res and "postgresql" in res[0][0].content.lower()


def test_stats(client):
    s = client.stats()
    assert s["count"] == 0
    client.ingest("first memory with tag alpha", tags=["alpha"])
    client.ingest("second memory with tag beta", tags=["beta"])
    s = client.stats()
    assert s["count"] == 2
    assert "alpha" in s["top_tags"]
    assert "beta" in s["top_tags"]
