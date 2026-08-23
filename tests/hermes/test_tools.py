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


def test_get_tool_schemas_hybrid_returns_all(tmp_path):
    p = _init_provider(tmp_path, mode="hybrid")
    schemas = p.get_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {
        "luminary_recall", "luminary_ingest", "luminary_list",
        "luminary_core_add", "luminary_core_remove", "luminary_core_list",
    }
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


def test_handle_recall_reports_core_match_instead_of_false_empty(tmp_path):
    from luminary_memory.types import RecallResult

    p = _init_provider(tmp_path)
    mid = p._client.ingest("a stable fact already loaded in core", tags=[p._core_tag()], source="test")
    core = p._client.get(mid)
    p._client.recall = lambda *args, **kwargs: RecallResult(
        memories=[core],
        scores=[1.0],
        strategies_hit={"semantic": 1},
        status="ok",
        confidence=1.0,
    )

    data = json.loads(p.handle_tool_call("luminary_recall", {"query": "stable fact"}))

    assert data["memories"] == []
    assert data["reason"] == "matches_already_in_core"
    assert data["deduplicated_core_count"] == 1
    assert data["deduplicated_core_ids"] == [mid]
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


def test_handle_ingest_empty_content_returns_error(tmp_path):
    p = _init_provider(tmp_path)
    out = p.handle_tool_call("luminary_ingest", {})
    data = json.loads(out)
    assert "error" in data
    p.shutdown()


def test_handle_ingest_whitelist_reject(tmp_path):
    p = _init_provider(tmp_path)
    p._client.whitelist = type("W", (), {"accepts": lambda self, t: False})()
    out = p.handle_tool_call("luminary_ingest", {"content": "blocked fact"})
    data = json.loads(out)
    assert "rejected" in data.get("result", "").lower()
    p.shutdown()


def test_handle_list_returns_memories(tmp_path):
    p = _init_provider(tmp_path)
    p._client.ingest("alpha memory", tags=["t"])
    out = p.handle_tool_call("luminary_list", {"limit": 10})
    data = json.loads(out)
    assert len(data["memories"]) >= 1
    p.shutdown()


def test_handle_tool_call_uninitialized():
    from luminary_memory.hermes.provider import LuminaryMemoryProvider
    p = LuminaryMemoryProvider()
    out = p.handle_tool_call("luminary_recall", {"query": "x"})
    data = json.loads(out)
    assert "error" in data
