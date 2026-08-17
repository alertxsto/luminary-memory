"""T4: Provider lifecycle — is_available, initialize, shutdown."""



from luminary_memory.hermes.provider import LuminaryMemoryProvider


def _make_provider(tmp_path, **cfg_overrides):
    p = LuminaryMemoryProvider()
    p.initialize("sess1", hermes_home=str(tmp_path), platform="cli", **cfg_overrides)
    return p


def test_initialize_creates_client_and_db(tmp_path):
    p = _make_provider(tmp_path)
    assert p._client is not None
    assert p._session_id == "sess1"
    db = tmp_path / "luminary" / "memory.db"
    assert db.exists(), "memory.db was not created by initialize"
    p.shutdown()


def test_initialize_stores_agent_identity(tmp_path):
    p = _make_provider(tmp_path, agent_identity="coder")
    assert p._agent_identity == "coder"
    p.shutdown()


def test_is_available_true_normal_path(tmp_path):
    p = LuminaryMemoryProvider()
    assert p.is_available() is True
    p.shutdown()


def test_is_available_false_when_import_fails(tmp_path, monkeypatch):
    import importlib.util

    p = LuminaryMemoryProvider()

    def _no_spec(*args, **kwargs):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", _no_spec)
    assert p.is_available() is False
    assert p.unavailable_reason() != ""
    p.shutdown()


def test_shutdown_drains_retain_queue(tmp_path):
    p = _make_provider(tmp_path)
    p._retain_queue.put(("item",))
    p.shutdown()
    assert p._shutting_down.is_set()
    assert p._retain_queue.empty()
    assert p._writer_thread is None or not p._writer_thread.is_alive()


def test_initialize_does_not_load_embedding_model(tmp_path, monkeypatch):
    """initialize() must stay fast: no embedding/vector work happens here."""
    from luminary_memory.api import FastembedEngine

    p = LuminaryMemoryProvider()

    def _no_embed(*args, **kwargs):
        raise AssertionError("embedding must not be computed in initialize()")

    monkeypatch.setattr(FastembedEngine, "embed", _no_embed)
    p.initialize("s1", hermes_home=str(tmp_path))
    p.shutdown()


def test_is_available_pgvector_missing_deps(tmp_path, monkeypatch):
    import importlib.util
    p = LuminaryMemoryProvider()
    p._config["backend"] = "pgvector"
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name in ("psycopg", "pgvector") else object())
    assert p.is_available() is False
    reason = p.unavailable_reason()
    assert "pgvector" in reason


def test_recall_sync_uses_sync_path(tmp_path, monkeypatch):
    """recall_sync=true must recall synchronously in prefetch()."""
    p = _make_provider(tmp_path)
    p._config["recall_sync"] = True
    p._config["auto_recall"] = True
    p._shutting_down.clear()

    import luminary_memory.hermes.provider as prov_mod
    from luminary_memory.api import RecallResult

    class _M:
        content = "sync recalled fact"
        def __init__(self):
            self.tags: list = []
    fake_result = RecallResult(memories=[_M()], scores=[1.0], strategies_hit={"semantic": 1})
    monkeypatch.setattr(prov_mod.MemoryClient, "recall", lambda self, q, **kw: fake_result)

    out = p.prefetch("sync query", session_id="s1")
    assert "sync recalled fact" in out
    assert p._last_recall_count == 1
    p.shutdown()
