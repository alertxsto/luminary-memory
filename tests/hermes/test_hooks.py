"""T8: on_memory_write, on_pre_compress, on_delegation hooks."""

import time

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


def _wait_for_store(p, expected_count, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if p._client.count() >= expected_count:
            return True
        time.sleep(0.05)
    return False


def test_on_memory_write_add_ingests_with_tags(tmp_path):
    p = _init_provider(tmp_path)
    p.on_memory_write("add", "user", "prefers X", metadata={"k": "v"})
    assert _wait_for_store(p, 1), "on_memory_write did not ingest"

    m = p._client.list(limit=10, offset=0)[0]
    assert m.source == "hermes-builtin"
    assert "user" in (m.tags or [])
    assert "builtin" in (m.tags or [])
    p.shutdown()


def test_on_memory_write_replace_markers(tmp_path):
    p = _init_provider(tmp_path)
    p.on_memory_write("replace", "prefs", "new pref", metadata=None)
    assert _wait_for_store(p, 1)
    m = p._client.list(limit=10, offset=0)[0]
    assert any(t.startswith("replace:") for t in (m.tags or []))
    p.shutdown()


def test_on_delegation_ingests_task(tmp_path):
    p = _init_provider(tmp_path)
    p.on_delegation("research X", "completed result", child_session_id="c1")
    assert _wait_for_store(p, 1), "on_delegation did not ingest"

    m = p._client.list(limit=10, offset=0)[0]
    assert "delegated: research X" in m.content
    assert "delegation" in (m.tags or [])
    assert "child:c1" in (m.tags or [])
    assert m.metadata.get("result") == "completed result"
    p.shutdown()


def test_on_pre_compress_returns_string(tmp_path):
    p = _init_provider(tmp_path)
    out = p.on_pre_compress([])
    assert isinstance(out, str)
    p.shutdown()
