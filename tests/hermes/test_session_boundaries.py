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


def test_session_end_runs_maintenance_when_enabled(tmp_path, monkeypatch):
    p = _init_provider(tmp_path)
    p._config.update({"auto_maintain": True, "ingest_llm": True})
    p.sync_turn("some durable fact", "ok", session_id="s1")

    called = {"n": 0}
    def fake_maintenance():
        called["n"] += 1
        return {"reviewed": 1, "deleted": 0, "updated": 0}
    monkeypatch.setattr(p._client, "run_maintenance", fake_maintenance)

    p.on_session_end(messages=[{"role": "user", "content": "x"}])
    time.sleep(0.5)
    assert called["n"] == 1, "run_maintenance should be called when auto_maintain+ingest_llm"


def test_session_end_maintenance_exception_logged(tmp_path, monkeypatch, caplog):
    p = _init_provider(tmp_path)
    p._config.update({"auto_maintain": True, "ingest_llm": True})
    p.sync_turn("fact", "ok", session_id="s1")

    def boom():
        raise RuntimeError("maintenance exploded")
    monkeypatch.setattr(p._client, "run_maintenance", boom)

    p.on_session_end(messages=[{"role": "user", "content": "x"}])
    time.sleep(0.5)
    assert "maintenance" in caplog.text.lower() or "failed" in caplog.text.lower(), \
        "exception should be logged, not propagate"


def test_session_end_skips_maintenance_when_disabled(tmp_path, monkeypatch):
    p = _init_provider(tmp_path)
    p._config.update({"auto_maintain": False, "ingest_llm": True})
    p.sync_turn("fact", "ok", session_id="s1")

    called = {"n": 0}
    monkeypatch.setattr(p._client, "run_maintenance", lambda: called.__setitem__("n", called["n"] + 1))

    p.on_session_end(messages=[{"role": "user", "content": "x"}])
    time.sleep(0.5)
    assert called["n"] == 0, "maintenance should NOT run when auto_maintain=false"


def test_shutdown_no_thread_affinity_crash(tmp_path):
    """Regression: shutdown must not raise SQLite thread-affinity errors."""
    p = _init_provider(tmp_path)
    p.sync_turn("fact one", "ok", session_id="s1")
    p.sync_turn("fact two", "ok", session_id="s1")
    time.sleep(0.5)
    p.shutdown()  # must not raise


def test_prefetch_skipped_when_auto_recall_off(tmp_path, monkeypatch):
    p = _init_provider(tmp_path)
    p._config.update({"auto_recall": False})
    p._shutting_down.clear()
    p.queue_prefetch("query", session_id="s1")  # should be a no-op
    assert p._prefetch_cache is None, "no prefetch cache should be set when auto_recall off"
