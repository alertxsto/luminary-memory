"""Deep checks for the provider's scoped, redacted troubleshooting log."""

from __future__ import annotations

import json

from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, _text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def test_transparency_log_is_scoped_correlated_and_redacted(tmp_path):
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-7",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="luminary",
        agent_workspace="workspace-main",
        user_id="user-42",
    )
    provider._client.engine = _FakeEngine()

    secret_content = "sensitive user secret should never appear in logs"
    secret_query = "find sensitive user secret"
    provider._do_retain(secret_content, ["durable"], {"session_id": "session-7"}, "test")
    provider._handle_recall({"query": secret_query, "limit": 3})
    provider.on_pre_compress([{"role": "user", "content": "ALWAYS run the release checks."}])
    provider._handle_core_add({"content": "ALWAYS keep release notes current."})

    log_path = tmp_path / "luminary" / "luminary.log"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert events
    assert all(isinstance(event, dict) for event in events)

    completed = [event for event in events if event["event"] == "retain.completed"]
    recalls = [event for event in events if event["event"] == "recall.completed"]
    assert completed and recalls
    assert completed[0]["scope"] == {
        "user_id": "user-42",
        "workspace_id": "workspace-main",
        "agent_id": "luminary",
        "session_id": "session-7",
    }
    assert completed[0]["trace_id"]
    assert any(
        event["trace_id"] == recalls[-1]["trace_id"]
        for event in events
        if event["event"] == "recall.started"
    )
    assert any(
        event["event"] == "precompress.skipped"
        and event.get("reason") == "compaction_is_not_memory_write"
        for event in events
    )
    assert any(event["event"] == "core_add.completed" for event in events)
    assert all(
        event["scope"] == completed[0]["scope"]
        for event in events
        if event["event"].startswith(("provider.", "retain.", "recall.", "precompress.", "core_"))
    )
    assert all("latency_ms" in event for event in completed + recalls)
    serialized = log_path.read_text(encoding="utf-8")
    assert secret_content not in serialized
    assert secret_query not in serialized
    assert "api_key" not in serialized.lower()
    provider.shutdown()


def test_transparency_logs_are_isolated_per_hermes_home(tmp_path):
    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    first = LuminaryMemoryProvider()
    second = LuminaryMemoryProvider()
    first.initialize("first-session", hermes_home=str(first_home), user_id="first-user")
    second.initialize("second-session", hermes_home=str(second_home), user_id="second-user")

    first._log_event("test.first", operation="test", status="ok")
    second._log_event("test.second", operation="test", status="ok")

    first_lines = (first_home / "luminary" / "luminary.log").read_text(encoding="utf-8")
    second_lines = (second_home / "luminary" / "luminary.log").read_text(encoding="utf-8")
    assert '"event": "test.first"' in first_lines
    assert '"event": "test.second"' not in first_lines
    assert '"event": "test.second"' in second_lines
    assert '"event": "test.first"' not in second_lines
    first.shutdown()
    second.shutdown()
