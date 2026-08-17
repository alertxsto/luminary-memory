"""T7: Session boundary — on_session_end flush + on_session_switch rebind."""

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


def _tags_of(p):
    return [set(m.tags or []) for m in p._client.list(limit=1000, offset=0)]


def test_session_switch_flushes_old_session_lineage(tmp_path):
    p = _init_provider(tmp_path, retain_every_n_turns=5)
    p.sync_turn("hello under s1", "reply", session_id="s1")
    # ensure the buffered turn is staged before switching
    assert p._session_turns, "expected a buffered turn"

    p.on_session_switch("s2", parent_session_id="s1")
    assert _wait_for_store(p, 1), "old session turn was not flushed"
    assert p._session_id == "s2"
    assert p._parent_session_id == "s1"

    tags = _tags_of(p)
    assert any("session:s1" in t for t in tags), f"expected session:s1 tag, got {tags}"
    p.shutdown()


def test_session_switch_reset_clears_buffer(tmp_path):
    p = _init_provider(tmp_path, retain_every_n_turns=5)
    p.sync_turn("orphan turn", "reply", session_id="s1")
    p.on_session_switch("s2", reset=True)
    time.sleep(0.3)
    assert p._session_turns == [], "reset must clear buffered turns"
    p.shutdown()


def test_session_end_flushes_pending_turns(tmp_path):
    p = _init_provider(tmp_path, retain_every_n_turns=5)
    p.sync_turn("final turn", "reply", session_id="s1")
    p.on_session_end(messages=[{"role": "user", "content": "final turn"}])
    assert _wait_for_store(p, 1), "on_session_end did not flush"
    p.shutdown()
