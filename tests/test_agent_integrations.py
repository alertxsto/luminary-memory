"""Consumer-visible isolation, retention, and delivery counts for native hooks."""

import getpass
import os
from datetime import UTC, datetime, timedelta

import pytest

from luminary_memory import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import EnrichedContent, OpenAICompatibleEnricher
from luminary_memory.integrations import dispatch
from luminary_memory.integrations.cli import install_adapter


class Engine:
    def embed(self, text):
        return [0.25] * 384

    def embed_batch(self, texts):
        return [self.embed(text) for text in texts]


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.delenv("LUMINARY_USER_ID", raising=False)
    monkeypatch.delenv("LUMINARY_INGEST_LLM", raising=False)
    workspace = os.path.normcase(str(tmp_path.resolve()))
    client = MemoryClient(
        settings=Settings(db_path=str(tmp_path / "native.db"), scope_include_global=False,
                          strict_recall=True, evidence_required=True, rule_auto_replace=False),
        engine=Engine(),
        scope={"workspace_id": workspace, "user_id": getpass.getuser(), "agent_id": "pi"},
    )
    request = {"agent": "pi", "workspace": str(tmp_path), "session_id": "session-a"}
    yield client, request
    client.close()


def test_committed_counts_and_forget_stop_recall(native):
    client, request = native
    remembered = dispatch({**request, "action": "remember", "text": "Deploy target is staging"},
                          client=client)
    duplicate = dispatch({**request, "action": "remember", "text": "Deploy target is staging"},
                         client=client)
    assert remembered["stored"] == 1
    assert duplicate["stored"] == 0
    assert duplicate["status"] == "duplicate"
    mid = remembered["memories"][0]["id"]
    # A new session can use the same durable workspace memory.
    recalled = dispatch({**request, "session_id": "session-b", "action": "recall",
                         "query": "Deploy target staging"}, client=client)
    assert [row["id"] for row in recalled["memories"]] == [mid]
    assert dispatch({**request, "action": "forget", "memory_id": mid}, client=client)["deleted"] == 1
    assert dispatch({**request, "action": "recall", "query": "Deploy target staging"},
                    client=client)["memories"] == []
    assert client.backend.get(mid).status == "deleted"


def test_activity_never_leaks_other_scope_or_expired_rows(native):
    client, request = native
    active = client.ingest("Project release uses staging", enrich=False)
    expired = client.ingest("Project release used legacy", enrich=False,
                            valid_to=(datetime.now(UTC) - timedelta(days=1)).isoformat())
    other = MemoryClient(settings=client.settings, engine=Engine(), scope={
        **client.scope, "user_id": "another-user",
    })
    try:
        hidden = other.ingest("Private release secret", enrich=False)
    finally:
        other.close()
    rows = dispatch({**request, "action": "activity"}, client=client)["memories"]
    assert [row["id"] for row in rows] == [active]
    assert expired != active
    assert dispatch({**request, "action": "forget", "memory_id": hidden},
                    client=client)["status"] == "not_found"
    assert client.backend.get(hidden).status == "active"


def test_native_scope_cannot_be_replaced_by_request(native):
    client, request = native
    with pytest.raises(PermissionError):
        dispatch({**request, "agent": "omp", "action": "activity"}, client=client)


def test_disabled_automatic_retention_does_not_store_transcript(native):
    client, request = native
    response = dispatch({**request, "action": "turn", "user": "hello", "assistant": "hi"},
                        client=client)
    assert response["reason"] == "curation_disabled"
    assert client.backend.count() == 0


def test_automatic_retention_rejects_assistant_only_claims(native, monkeypatch):
    client, request = native
    monkeypatch.setenv("LUMINARY_INGEST_LLM", "true")
    monkeypatch.setenv("LUMINARY_LLM_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setattr(OpenAICompatibleEnricher, "enrich", lambda self, text: EnrichedContent(
        content=text, summary="User lives in Tokyo", claims=[{
            "subject": "user", "predicate": "lives", "object": "Tokyo",
            "evidence_quote": "You live in Tokyo",
        }],
    ))
    response = dispatch({**request, "action": "turn", "user": "Where should we deploy?",
                         "assistant": "You live in Tokyo"}, client=client)
    assert response["reason"] == "no_grounded_fact"
    assert client.backend.count() == 0


def test_curated_fact_keeps_user_evidence_not_raw_assistant(native, monkeypatch):
    client, request = native
    monkeypatch.setenv("LUMINARY_INGEST_LLM", "true")
    monkeypatch.setenv("LUMINARY_LLM_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setattr(OpenAICompatibleEnricher, "enrich", lambda self, text: EnrichedContent(
        content=text, summary="User prefers PostgreSQL", tags=["core", "database"], claims=[{
            "subject": "user", "predicate": "prefers", "object": "PostgreSQL",
            "evidence_quote": "I prefer PostgreSQL", "confidence": 0.9,
        }],
    ))
    response = dispatch({**request, "action": "turn", "user": "I prefer PostgreSQL",
                         "assistant": "An arbitrary assistant work log", "tags": ["message:123"]},
                        client=client)
    assert response["stored"] == 1
    memory = client.get(response["memories"][0]["id"])
    assert memory.content == "User prefers PostgreSQL"
    assert memory.evidence_quote == "I prefer PostgreSQL"
    assert set(memory.tags) == {"message:123", "database"}
    assert memory.session_id == "session-a"


def test_install_preserves_config_and_refuses_unapproved_replacement(tmp_path):
    package = tmp_path / "package.json"
    package.write_text('{"name":"existing","dependencies":{"unrelated":"1.0.0"}}')
    installed = install_adapter("opencode", tmp_path)
    import json

    config = json.loads(package.read_text())
    assert config["name"] == "existing"
    assert config["dependencies"]["unrelated"] == "1.0.0"
    plugin = next(path for path in installed if path.suffix == ".ts")
    plugin.write_text("user modified plugin")
    with pytest.raises(ValueError):
        install_adapter("opencode", tmp_path)
    assert plugin.read_text() == "user modified plugin"


def test_bridge_accepts_other_supported_harness_identity(native):
    client, request = native
    other = MemoryClient(settings=client.settings, engine=Engine(), scope={
        **client.scope, "agent_id": "another-supported-host",
    })
    try:
        response = dispatch({
            **request, "agent": "another-supported-host", "action": "remember",
            "text": "Other host deploys to staging",
        }, client=other)
        assert response["stored"] == 1
        assert dispatch({**request, "action": "activity"}, client=client)["memories"] == []
    finally:
        other.close()
