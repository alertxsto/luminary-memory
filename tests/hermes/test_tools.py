"""T10: luminary_recall / luminary_ingest / luminary_list tools."""

import json

from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * 384 for _ in texts]


def _init_provider(tmp_path, **overrides):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    p._config.update(overrides)
    p._client.engine = _FakeEngine()
    return p


def test_get_tool_schemas_hybrid_returns_three(tmp_path):
    p = _init_provider(tmp_path, mode="hybrid")
    schemas = p.get_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {"luminary_recall", "luminary_ingest", "luminary_list"}
    p.shutdown()


def test_get_tool_schemas_context_mode_returns_empty(tmp_path):
    p = _init_provider(tmp_path, mode="context")
    assert p.get_tool_schemas() == []
    p.shutdown()


def test_handle_ingest_stores_memory(tmp_path):
    p = _init_provider(tmp_path)
    out = p.handle_tool_call("luminary_ingest", {"content": "a durable fact", "tags": ["t1"]})
    data = json.loads(out)
    assert "result" in data
    assert "id=1" in data["result"]
    assert p._client.count() >= 1
    p.shutdown()


def test_handle_recall_returns_memories(tmp_path):
    p = _init_provider(tmp_path)
    p._client.ingest("postgres vector search is production ready", tags=["seed"], source="test")
    out = p.handle_tool_call("luminary_recall", {"query": "postgres"})
    data = json.loads(out)
    assert "memories" in data
    assert any("postgres" in m.get("content", "") for m in data["memories"])
    p.shutdown()


def test_handle_recall_missing_query_returns_error(tmp_path):
    p = _init_provider(tmp_path)
    out = p.handle_tool_call("luminary_recall", {})
    data = json.loads(out)
    assert "error" in data
    p.shutdown()


def test_handle_unknown_tool_returns_error(tmp_path):
    p = _init_provider(tmp_path)
    out = p.handle_tool_call("luminary_bogus", {})
    data = json.loads(out)
    assert "error" in data
    p.shutdown()
