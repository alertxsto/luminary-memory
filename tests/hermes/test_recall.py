"""T9: Auto-recall — queue_prefetch, prefetch, recall_status."""

import time

from luminary_memory.hermes.provider import LuminaryMemoryProvider

_HEADER = "# Luminary Memory (persistent cross-session context)"


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


def _seed(p, texts):
    for t in texts:
        p._client.ingest(t, tags=["seed"], source="test")


def test_prefetch_returns_cached_block_and_indicator(tmp_path):
    p = _init_provider(tmp_path)
    _seed(p, ["the database uses sqlite fts5 for search", "vector similarity is fast", "temporal decay ranks recent facts"])

    p.queue_prefetch("database search", session_id="s1")
    block = p.prefetch("database search", session_id="s1")

    assert block, "prefetch returned an empty block"
    assert _HEADER in block
    assert "sqlite fts5" in block

    status = p.recall_status()
    assert status is not None
    assert status.provider_label == "Luminary"
    assert status.count >= 1
    assert status.glyph == "🌙"
    p.shutdown()


def test_recall_sync_returns_without_queue(tmp_path):
    p = _init_provider(tmp_path, recall_sync=True)
    _seed(p, ["postgres vector search is production ready"])

    block = p.prefetch("postgres", session_id="s1")
    assert block and _HEADER in block
    assert "postgres" in block
    p.shutdown()


def test_auto_recall_disabled_returns_empty(tmp_path):
    p = _init_provider(tmp_path, auto_recall=False)
    _seed(p, ["something to recall"])

    block = p.prefetch("something", session_id="s1")
    assert block == ""
    assert p.recall_status() is None
    p.shutdown()


def test_tools_mode_queue_prefetch_is_noop(tmp_path):
    p = _init_provider(tmp_path, mode="tools")
    _seed(p, ["tool only recall data"])

    p.queue_prefetch("tool only", session_id="s1")
    time.sleep(0.4)
    block = p.prefetch("tool only", session_id="s1")
    assert block == ""
    p.shutdown()
