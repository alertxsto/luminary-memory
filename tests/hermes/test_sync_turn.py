"""T6: sync_turn — buffered, non-blocking auto-save on a single writer."""

import time

from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * 384 for _ in texts]


def _init_provider(tmp_path, **overrides):
    p = LuminaryMemoryProvider()
    p.initialize("sess1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    p._config.update(overrides)
    p._client.engine = _FakeEngine()  # avoid real fastembed model load
    return p


def _wait_for_store(p, expected_count, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if p._client.count() >= expected_count:
            return True
        time.sleep(0.05)
    return False


def _all_memories(p):
    return p._client.list(limit=1000, offset=0)


def test_sync_turn_writes_single_memory(tmp_path):
    p = _init_provider(tmp_path)
    p.sync_turn("hello user message", "assistant reply", session_id="sess1")
    assert _wait_for_store(p, 1), "store never received the memory"

    mems = _all_memories(p)
    assert len(mems) == 1
    m = mems[0]
    assert m.source == "hermes"
    assert any(t == "session:sess1" for t in (m.tags or []))
    assert "hello user message" in m.content
    assert "assistant reply" in m.content
    p.shutdown()


def test_sync_turn_batches_every_n_turns(tmp_path):
    p = _init_provider(tmp_path, retain_every_n_turns=2)
    p.sync_turn("turn one user", "turn one assistant", session_id="sess1")
    time.sleep(0.3)
    assert p._client.count() == 0, "first turn must be buffered only"

    p.sync_turn("turn two user", "turn two assistant", session_id="sess1")
    assert _wait_for_store(p, 1), "second turn must flush the batch"

    mems = _all_memories(p)
    assert len(mems) == 1
    assert "turn one user" in mems[0].content
    assert "turn two user" in mems[0].content
    p.shutdown()


def test_sync_turn_disabled_when_auto_retain_false(tmp_path):
    p = _init_provider(tmp_path, auto_retain=False)
    p.sync_turn("should not persist", "nope", session_id="sess1")
    time.sleep(0.3)
    assert p._client.count() == 0
    p.shutdown()


def test_sync_turn_llm_drops_unworthy(tmp_path, monkeypatch):
    """LLM says not worth saving → turn dropped, no store write."""
    import luminary_memory.ingest.llm as llm_mod
    from luminary_memory.ingest.llm import EnrichedContent

    class _SkipEnricher:
        def __init__(self, *a, **kw):
            pass
        def enrich(self, text):
            return EnrichedContent(content=text, summary=None, worth_saving=False)
    monkeypatch.setattr(llm_mod, "OpenAICompatibleEnricher", _SkipEnricher)

    p = _init_provider(tmp_path)
    p._config.update({"ingest_llm": True, "llm_base_url": "x", "llm_model": "m", "llm_api_key": "k"})

    p.sync_turn("just chit chat", "ok", session_id="s1")
    time.sleep(0.6)
    assert p._client.count() == 0, "unworthy turn must not be stored"
    p.shutdown()


def test_sync_turn_llm_stores_summary(tmp_path, monkeypatch):
    """LLM worth saving → factual summary stored instead of raw."""
    import luminary_memory.ingest.llm as llm_mod
    from luminary_memory.ingest.llm import EnrichedContent

    class _SummaryEnricher:
        def __init__(self, *a, **kw):
            pass
        def enrich(self, text):
            return EnrichedContent(content=text, summary="User prefers X", worth_saving=True)
    monkeypatch.setattr(llm_mod, "OpenAICompatibleEnricher", _SummaryEnricher)

    p = _init_provider(tmp_path)
    p._config.update({"ingest_llm": True, "llm_base_url": "x", "llm_model": "m", "llm_api_key": "k"})

    p.sync_turn("raw turn text", "ok", session_id="s1")
    time.sleep(0.6)
    ms = p._client.list(limit=10)
    assert len(ms) == 1
    assert ms[0].content == "User prefers X", "summary must replace raw content"
    p.shutdown()


def test_sync_turn_noop_when_shutting_down(tmp_path):
    p = _init_provider(tmp_path)
    p._shutting_down.set()
    p.sync_turn("turn after shutdown", "ok", session_id="s1")
    assert p._session_turns == [], "no buffering after shutdown"
    p.shutdown()


def test_sync_turn_parent_session_tag(tmp_path):
    p = _init_provider(tmp_path, retain_every_n_turns=1)
    p.sync_turn("turn with parent", "ok", session_id="s1", parent_session_id="root")
    time.sleep(0.5)
    ms = p._client.list(limit=10)
    assert len(ms) == 1
    tags = ms[0].tags or []
    assert "session:s1" in tags
    assert "parent:root" in tags
    p.shutdown()
