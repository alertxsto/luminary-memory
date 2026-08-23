"""Deep regressions for single-authority and provider lifecycle behavior."""

import threading

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * 384 for _ in texts]


def test_shutdown_drains_accepted_retain_before_fence(tmp_path):
    """A queued explicit observation survives an immediate provider shutdown."""
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="test",
    )
    provider._client.engine = _FakeEngine()

    blocker_started = threading.Event()
    release_blocker = threading.Event()

    def blocker():
        blocker_started.set()
        assert release_blocker.wait(timeout=5), "writer blocker was not released"

    provider._retain_queue.put((blocker,))
    assert blocker_started.wait(timeout=5)

    provider.on_delegation("durable preference", "confirmed")
    release_blocker.set()
    provider.shutdown()

    backend = SQLiteBackend(str(tmp_path / "luminary" / "memory.db"))
    rows = backend.recent(
        limit=None,
        scope={"agent_id": "test"},
        include_global=False,
    )
    assert any("delegated: durable preference" in row.content for row in rows)
    backend.close()


def test_reinitialize_clears_parent_lineage(tmp_path):
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        parent_session_id="parent-1",
    )
    assert provider._parent_session_id == "parent-1"

    provider.shutdown()
    provider.initialize("session-2", hermes_home=str(tmp_path), platform="cli")
    assert provider._parent_session_id is None
    provider.shutdown()


def test_explicit_tool_path_still_writes_when_native_bridge_is_ignored(tmp_path):
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="test",
    )
    provider._client.engine = _FakeEngine()

    native_before = provider._client.count()
    provider.on_memory_write("add", "user", "native duplicate")
    assert provider._client.count() == native_before

    result = provider.handle_tool_call(
        "luminary_ingest",
        {"content": "explicit durable fact", "tags": ["core"]},
    )
    assert "Memory stored" in result
    assert provider._client.count() == native_before + 1
    provider.shutdown()
