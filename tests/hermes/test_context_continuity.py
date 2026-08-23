"""Regression tests for active-task continuity and scoped session episodes."""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * 384 for _ in texts]


def _provider(tmp_path, **overrides):
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-current",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="agent-a",
    )
    provider._config.update(overrides)
    provider._client.engine = _FakeEngine()
    return provider


def test_ambiguous_follow_up_keeps_the_active_store_topic(tmp_path):
    provider = _provider(tmp_path, recall_sync=True)
    try:
        provider.sync_turn(
            "We are debugging why the Luminary store rarely fills.",
            "The curation and continuity path need to be inspected.",
            session_id="session-current",
        )

        block = provider.prefetch("MENDING LU AUDIT SESINYA DEH", session_id="")

        assert "why the Luminary store rarely fills" in block
        assert "curation and continuity path" in block
        assert "Luminary Session Continuity" in block
        assert "history-wide operation" in provider.system_prompt_block()
        assert provider._client.count() == 0, "raw continuity must not become durable memory"
    finally:
        provider.shutdown()


def test_session_continuity_does_not_cross_session_or_identity(tmp_path):
    provider = _provider(tmp_path, recall_sync=True)
    try:
        backend = provider._client.backend
        backend.record_episode(
            "current",
            "current session topic",
            source="hermes-session",
            metadata={"sequence": 1},
            user_id="",
            session_id="session-current",
            agent_id="agent-a",
        )
        backend.record_episode(
            "other-session",
            "other session secret topic",
            source="hermes-session",
            metadata={"sequence": 2},
            user_id="",
            session_id="session-other",
            agent_id="agent-a",
        )
        backend.record_episode(
            "other-agent",
            "other agent secret topic",
            source="hermes-session",
            metadata={"sequence": 3},
            user_id="",
            session_id="session-current",
            agent_id="agent-b",
        )

        block = provider._recent_session_context("session-current")

        assert "current session topic" in block
        assert "other session secret topic" not in block
        assert "other agent secret topic" not in block
    finally:
        provider.shutdown()


def test_async_prefetch_uses_provider_session_when_hermes_omits_id(tmp_path):
    provider = _provider(tmp_path, recall_sync=False)
    try:
        provider._client.ingest("The store uses a scoped episode ledger.", source="test")

        provider.queue_prefetch("scoped episode ledger", session_id="")
        block = provider.prefetch("scoped episode ledger", session_id="")

        assert "scoped episode ledger" in block
    finally:
        provider.shutdown()
