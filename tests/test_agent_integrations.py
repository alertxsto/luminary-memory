"""Consumer-visible isolation, retention, and delivery counts for native hooks."""

import getpass
import json
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
    # Owner-typed bridge commands use a separate trusted launcher channel.
    monkeypatch.setenv("LUMINARY_BRIDGE_SOURCE", json.dumps({
        **{key: request[key] for key in ("agent", "workspace", "session_id")}, "kind": "operator",
    }))
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
    plugin = next(path for path in installed if path.name == "index.js")
    plugin.write_text("user modified plugin")
    with pytest.raises(ValueError):
        install_adapter("opencode", tmp_path)
    assert plugin.read_text() == "user modified plugin"


def test_hermes_ui_install_excludes_source_bytecode_and_preserves_profile_cache(tmp_path, monkeypatch):
    from luminary_memory.integrations import cli

    resources = tmp_path / "resources"
    source = resources / "assets" / "compiled" / "hermes"
    (source / "__pycache__").mkdir(parents=True)
    (source / "plugin.yaml").write_text("name: luminary-inspector\n", encoding="utf-8")
    (source / "__pycache__" / "plugin.cpython-311.pyc").write_bytes(b"\xa7\r\r\n\x00")
    monkeypatch.setattr(cli.importlib.resources, "files", lambda package: resources)
    home = tmp_path / "profile"
    home.mkdir()
    config = home / "config.yaml"
    config.write_text("memory:\n  provider: none\n", encoding="utf-8")
    before = config.read_bytes()
    target = home / "plugins" / "luminary-inspector"
    cache = target / "__pycache__" / "existing.cpython-311.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"\xffexisting-runtime-cache")

    cli.install_hermes_ui(home, force=False)

    assert config.read_bytes() == before
    assert cache.read_bytes() == b"\xffexisting-runtime-cache"
    ownership = json.loads((target / ".luminary-install.json").read_text(encoding="utf-8"))
    assert set(ownership["files"]) == {"plugin.yaml"}
    assert not (target / "__pycache__" / "plugin.cpython-311.pyc").exists()


def test_bridge_accepts_other_supported_harness_identity(native, monkeypatch):
    client, request = native
    other = MemoryClient(settings=client.settings, engine=Engine(), scope={
        **client.scope, "agent_id": "another-supported-host",
    })
    try:
        monkeypatch.setenv("LUMINARY_BRIDGE_SOURCE", json.dumps({
            "agent": "another-supported-host", "workspace": request["workspace"],
            "session_id": request["session_id"], "kind": "operator",
        }))
        response = dispatch({
            **request, "agent": "another-supported-host", "action": "remember",
            "text": "Other host deploys to staging",
        }, client=other)
        assert response["stored"] == 1
        assert dispatch({**request, "action": "activity"}, client=client)["memories"] == []
    finally:
        other.close()


def _inspect_native(native, operation="events", **arguments):
    from luminary_memory.inspector.contracts import ConsoleRequest
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.service import InspectorService

    client, request = native
    context = resolve_context(client, {
        "user_id": client.scope["user_id"], "workspace": request["workspace"],
        "workspace_id": client.scope["workspace_id"],
        "agent_id": "pi", "session_id": request["session_id"],
        "host_id": "native-activity-test", "profile_id": "default",
    }, initialize=True)
    return InspectorService(client).execute(context, ConsoleRequest(
        operation=operation, arguments=arguments, request_id="activity-test"))


def test_actual_recall_activity_never_claims_a_save_or_observed_injection(native):
    import json

    client, request = native
    mid = dispatch({**request, "action": "remember", "text": "Deploy target is staging"},
                   client=client)["memories"][0]["id"]
    response = dispatch({**request, "session_id": "session-b", "action": "recall",
                         "query": "Deploy target staging QUERY_SECRET"}, client=client)
    assert [row["id"] for row in response["memories"]] == [mid]
    result = _inspect_native(native)
    assert result.status == "ok", result.to_dict()
    operations = [row for row in result.data["items"] if row["kind"] == "native_recall"]
    assert [row["operation"]["state"] for row in operations] == ["returned", "running"]
    finished, started = operations
    assert finished["operation"]["id"] == started["operation"]["id"]
    assert list(finished["operation"]["memory_ids"]) == [mid]
    assert finished["operation"]["recalled"] == 1
    assert finished["operation"]["stored"] == 0
    assert finished["operation"]["injected"] is None
    assert finished["source"] == "pi"
    assert finished["operation"]["session_id"] == "session-b"
    assert "QUERY_SECRET" not in json.dumps(result.to_dict())
    assert client.backend.count() == 1


@pytest.mark.parametrize("failure,state", [(OSError("PRIVATE_ERROR_SECRET"), "error"),
                                           (KeyboardInterrupt(), "cancelled")])
def test_recall_failure_and_cancellation_keep_truthful_scoped_activity(native, monkeypatch, failure, state):
    import json

    client, request = native

    def unavailable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(client, "recall", unavailable)
    with pytest.raises(type(failure)):
        dispatch({**request, "action": "recall", "query": "deployment"}, client=client)
    result = _inspect_native(native)
    assert result.status == "ok", result.to_dict()
    events = [row for row in result.data["items"] if row["kind"] == "native_recall"]
    assert [row["operation"]["state"] for row in events] == [state, "running"]
    assert events[0]["operation"]["stored"] == 0
    assert events[0]["operation"]["injected"] is None
    assert client.backend.count() == 0
    assert "PRIVATE_ERROR_SECRET" not in json.dumps(result.to_dict())


def test_reconnect_replays_same_recall_metadata_once_per_event(native):
    client, request = native
    dispatch({**request, "action": "recall", "query": "deployment"}, client=client)
    snapshot = _inspect_native(native)
    assert snapshot.status == "ok", snapshot.to_dict()
    boundary = 0
    replay_context = None
    replayed = []
    for _ in range(10):
        page = _inspect_native(native, since_event_id=boundary, limit=1, replay_context=replay_context)
        assert page.status == "ok", page.to_dict()
        replayed.extend(page.data["items"])
        boundary = page.data["next_event_id"]
        replay_context = page.data.get("replay_context")
        if not page.data["has_more"]:
            break
    assert len({row["event_id"] for row in replayed}) == len(replayed)
    assert replayed == list(reversed(snapshot.data["items"]))
    assert list(_inspect_native(native, since_event_id=boundary, replay_context=replay_context).data["items"]) == []
    assert [row["operation"]["state"] for row in replayed] == ["running", "returned"]


def test_summary_changes_do_not_treat_recalls_as_memory_mutations(native):
    client, request = native
    mid = dispatch({**request, "action": "remember", "text": "Deploy target is staging"},
                   client=client)["memories"][0]["id"]
    dispatch({**request, "action": "recall", "query": "Deploy target staging"}, client=client)
    summary = _inspect_native(native, operation="summary", limit=1)
    assert summary.status == "ok", summary.to_dict()
    assert summary.data["totals"]["memories"] == 1
    assert [(row["kind"], row["memory_id"]) for row in summary.data["changes"]] == [("ingest", mid)]


def test_core_is_baseline_not_recall_success(native):
    client, request = native
    core_id = client.ingest("Call the user Captain", tags=["core"], enrich=False)

    baseline = dispatch({**request, "action": "core"}, client=client)
    recalled = dispatch({**request, "action": "recall", "query": "fix parser TypeError"}, client=client)

    assert baseline["status"] == "ok"
    assert [row["id"] for row in baseline["memories"]] == [core_id]
    assert "<luminary-core-memory>" in baseline["context"]
    assert recalled["status"] == "abstain"
    assert recalled["memories"] == []
    assert recalled["context"] == ""


def test_recall_deduplicates_core_without_fabricating_a_match(native):
    client, request = native
    core_id = client.ingest("Call the user Captain", tags=["core"], enrich=False)
    result = client.recall("Call the user Captain")
    assert [m.id for m in result.memories] == [core_id]

    recalled = dispatch({**request, "action": "recall", "query": "Call the user Captain"}, client=client)

    assert recalled["status"] == "abstain"
    assert recalled["reason"] == "matches_already_in_core"
    assert recalled["memories"] == []
    assert recalled["context"] == ""


def test_recall_deduplicates_normalized_core_content(native):
    client, request = native
    client.ingest("Call the user Captain", tags=["core"], enrich=False)
    from luminary_memory.types import Memory

    duplicate_id = client.backend.add(Memory(
        content="  CALL   THE USER CAPTAIN ", evidence_quote="CALL THE USER CAPTAIN",
        embedding=Engine().embed("Call the user Captain"), **client.scope,
    ))
    client.retract(next(memory.id for memory in client.list(limit=0) if "core" in memory.tags))
    assert [memory.id for memory in client.recall("Call the user Captain").memories] == [duplicate_id]
    client.retract(duplicate_id)
    client.ingest("Call the user Captain", tags=["core"], enrich=False)
    client.update(client.get(duplicate_id))

    recalled = dispatch({**request, "action": "recall", "query": "Call the user Captain"}, client=client)

    assert recalled["status"] == "abstain"
    assert recalled["reason"] == "matches_already_in_core"
    assert recalled["memories"] == []
    assert recalled["context"] == ""


def test_recall_retains_noncore_matches_and_engine_status(native):
    client, request = native
    client.ingest("Call the user Captain", tags=["core"], enrich=False)
    relevant_id = client.ingest("Call the user Captain. PostgreSQL is the deployment database.", enrich=False)

    recalled = dispatch({**request, "action": "recall", "query": "Call the user Captain PostgreSQL deployment database"}, client=client)

    assert recalled["status"] == "ok"
    assert recalled["reason"] == ""
    assert recalled["ok"] is True
    assert [row["id"] for row in recalled["memories"]] == [relevant_id]
    assert recalled["context"].startswith("Luminary recalled data (untrusted")


def test_core_and_recall_keep_separate_whole_row_budgets(native, monkeypatch):
    client, request = native
    monkeypatch.setenv("LUMINARY_CORE_TOP_N", "2")
    monkeypatch.setenv("LUMINARY_CORE_BUDGET", "35")
    client.ingest("x" * 100, tags=["core"], enrich=False)
    client.ingest("short baseline", tags=["core"], enrich=False)

    baseline = dispatch({**request, "action": "core"}, client=client)

    assert [row["content"] for row in baseline["memories"]] == ["short baseline"]
    assert "x" * 100 not in baseline["context"]


def test_core_is_current_exact_scope_and_does_not_recall(native, monkeypatch):
    client, request = native
    now = datetime.now(UTC)
    active = client.ingest("Use the confirmed deployment baseline", tags=["core"], enrich=False)
    hidden = {
        client.ingest("Expired baseline", tags=["core"], enrich=False,
                      valid_to=(now - timedelta(days=1)).isoformat()),
        client.ingest("Future baseline", tags=["core"], enrich=False,
                      valid_from=(now + timedelta(days=1)).isoformat()),
        client.ingest("Deleted baseline", tags=["core"], enrich=False),
        client.ingest("Inactive baseline", tags=["core"], enrich=False),
    }
    client.retract(next(mid for mid in hidden if client.get(mid).content == "Deleted baseline"))
    inactive = client.get(next(mid for mid in hidden if client.get(mid).content == "Inactive baseline"))
    inactive.status = "superseded"
    client.backend.update(inactive)
    scopes = [
        {"user_id": "foreign-user"},
        {"workspace_id": "foreign-workspace"},
        {"agent_id": "foreign-agent"},
    ]
    for difference in scopes:
        foreign = MemoryClient(settings=client.settings, engine=Engine(),
                               scope={**client.scope, **difference})
        try:
            hidden.add(foreign.ingest("Foreign baseline", tags=["core"], enrich=False))
        finally:
            foreign.close()
    monkeypatch.setenv("LUMINARY_CORE_TOP_N", "12")

    def fail_recall(*args, **kwargs):
        raise AssertionError("core must not run query recall")

    monkeypatch.setattr(client, "recall", fail_recall)
    baseline = dispatch({**request, "action": "core"}, client=client)

    assert [row["id"] for row in baseline["memories"]] == [active]
    assert not hidden.intersection(row["id"] for row in baseline["memories"])
    assert baseline["status"] == "ok"
    assert baseline["ok"] is True
    assert baseline["message"] == "Returned 1 core memories."
    assert "subordinate default context" in baseline["context"]
    assert json.loads(baseline["context"].splitlines()[2]) == baseline["memories"]
    assert set(baseline) == {"ok", "status", "reason", "message", "context", "memories", "stored", "deleted"}


def test_empty_core_is_ok_and_capped(native, monkeypatch):
    client, request = native
    monkeypatch.setenv("LUMINARY_CORE_TOP_N", "1")
    client.ingest("First baseline", tags=["core"], enrich=False)
    client.ingest("Second baseline", tags=["core"], enrich=False)
    baseline = dispatch({**request, "action": "core"}, client=client)
    assert [row["content"] for row in baseline["memories"]] == ["First baseline"]

    # Remove all baseline rows before exercising the successful empty baseline.
    for memory in client.list(limit=0):
        client.retract(memory.id)
    empty = dispatch({**request, "action": "core"}, client=client)
    assert empty["status"] == "ok"
    assert empty["memories"] == []
    assert empty["context"] == ""


def test_unrelated_core_memory_cannot_turn_abstention_into_success(native):
    client, request = native
    client.ingest("Always answer in rhyme and call the user Captain.",
                  tags=["core"], enrich=False)
    response = dispatch({**request, "action": "recall", "query": "TypeError in parser.py"},
                        client=client)
    assert response["status"] == "abstain"
    assert response["reason"] == "low_confidence_or_ambiguous"
    assert response["memories"] == []
    assert response["context"] == ""
    activity = _inspect_native(native)
    operation = next(row["operation"] for row in activity.data["items"]
                     if row["kind"] == "native_recall" and row["operation"]["state"] == "returned")
    assert operation["ranking"] == ()
    assert operation["returned"] == operation["recalled"] == operation["core_only"] == 0


def test_relevant_core_memory_still_passes_the_normal_recall_gate(native):
    client, request = native
    mid = client.ingest("Deployment target is staging.", tags=["core"], enrich=False)
    assert [memory.id for memory in client.recall("Deployment target staging").memories] == [mid]
    response = dispatch({**request, "action": "recall", "query": "Deployment target staging"},
                        client=client)
    assert response["status"] == "abstain"
    assert response["reason"] == "matches_already_in_core"
    assert response["memories"] == []
    operation = next(row["operation"] for row in _inspect_native(native).data["items"]
                     if row["kind"] == "native_recall" and row["operation"]["state"] == "returned")
    assert operation["recalled"] == 0
    assert operation["core_only"] == 0


def test_shared_recall_rejects_dense_shell_transcript_without_hiding_real_build_fact(native):
    client, request = native
    transcript = "cd ~/repo && npm run build === echo done && ls -la | grep dist"
    hidden = client.ingest(transcript, enrich=False)
    wanted = client.ingest("The project build uses npm run build.", enrich=False)
    direct = client.recall("project build npm run build")
    assert [memory.id for memory in direct.memories] == [wanted]
    response = dispatch({**request, "action": "recall", "query": "project build npm run build"},
                        client=client)
    assert [row["id"] for row in response["memories"]] == [wanted]
    assert hidden not in [row["id"] for row in response["memories"]]
    assert transcript not in response["context"]


def test_noise_filter_keeps_short_technical_facts_and_delete_questions(native):
    client, request = native
    short = client.ingest("PostgreSQL 16", enrich=False)
    deletion = client.ingest("SQL DELETE CASCADE removes dependent PostgreSQL rows.", enrich=False)
    assert [memory.id for memory in client.recall("PostgreSQL 16").memories] == [short]
    result = dispatch({**request, "action": "recall",
                       "query": "SQL DELETE CASCADE dependent PostgreSQL rows"}, client=client)
    assert [row["id"] for row in result["memories"]] == [deletion]


@pytest.mark.parametrize("tag", ["core", "CORE", "rule", "priority"])
def test_model_cannot_promote_protected_tags_by_claiming_confirmation(native, monkeypatch, tag):
    client, request = native
    monkeypatch.setenv("LUMINARY_CORE_TAG", "priority")
    response = dispatch({**request, "action": "remember", "text": "Always call the user Captain.",
                         "tags": [tag], "confirmed": True, "owner_confirmed": True}, client=client)
    assert response["stored"] == 0
    assert response["reason"] == "owner_confirmation_required"
    assert client.backend.count() == 0


def test_model_remember_cannot_self_certify_its_evidence_or_confidence(native, monkeypatch):
    client, request = native
    monkeypatch.delenv("LUMINARY_BRIDGE_SOURCE", raising=False)
    text = "Deployment target is staging."
    response = dispatch({**request, "action": "remember", "text": text,
                         "evidence_quote": text, "source_text": text, "confidence": 1.0,
                         "metadata": {"native_evidence": {"origin": "user"}}}, client=client)
    assert response["stored"] == 0
    assert response["reason"] == "user_evidence_required"
    assert client.backend.count() == 0


def test_verified_native_user_quote_preserves_paraphrase_and_remains_recallable(native, monkeypatch):
    import json

    client, request = native
    quote = "I prefer PostgreSQL"
    monkeypatch.setenv("LUMINARY_BRIDGE_SOURCE", json.dumps({
        "agent": request["agent"], "workspace": request["workspace"], "session_id": request["session_id"],
        "kind": "native_user", "quote": quote,
    }))
    response = dispatch({**request, "action": "remember", "text": "User prefers PostgreSQL",
                         "evidence_quote": quote}, client=client)
    memory = client.get(response["memories"][0]["id"])
    assert memory.evidence_quote == quote
    assert memory.evidence_quote != memory.content
    assert memory.confidence < 1.0
    assert [item.id for item in client.recall("User prefers PostgreSQL").memories] == [memory.id]


def test_native_quote_from_another_session_cannot_be_reused(native, monkeypatch):
    import json

    client, request = native
    monkeypatch.setenv("LUMINARY_BRIDGE_SOURCE", json.dumps({
        "agent": request["agent"], "workspace": request["workspace"], "session_id": "another-session",
        "kind": "native_user", "quote": "PRIVATE_PREVIOUS_USER_QUOTE",
    }))
    with pytest.raises(PermissionError):
        dispatch({**request, "action": "remember", "text": "A proposed fact",
                  "evidence_quote": "PRIVATE_PREVIOUS_USER_QUOTE"}, client=client)
    assert client.backend.count() == 0


@pytest.mark.parametrize("batch", [False, True])
def test_explicit_absent_evidence_is_not_replaced_with_content(native, batch):
    client, _request = native
    text = "Deployment target is staging."
    if batch:
        mid = client.ingest_batch([text], enrich=False, evidence_quote="", confidence=0.0)[0]
    else:
        mid = client.ingest(text, enrich=False, evidence_quote="", confidence=0.0)
    assert client.get(mid).evidence_quote == ""
    assert client.recall("Deployment target staging").memories == []


def test_native_context_budget_counts_unicode_evidence_and_reference_header(native):
    client, request = native
    client.settings.token_budget = 20000
    text = "Deploy target is staging. " + "🛰" * 3830
    saved = dispatch({**request, "action": "remember", "text": text}, client=client)
    assert saved["stored"] == 1
    response = dispatch({**request, "action": "recall", "query": "Deploy target is staging."}, client=client)
    assert len(response["context"]) <= 8000
    assert response["status"] == "abstain"
    assert response["reason"] == "no_deliverable_candidate"
    assert response["memories"] == []
    assert response["context"] == ""


def test_config_file_cannot_supply_native_writer_authority(native, tmp_path, monkeypatch):
    client, request = native
    monkeypatch.delenv("LUMINARY_BRIDGE_SOURCE", raising=False)
    source = {
        **{key: request[key] for key in ("agent", "workspace", "session_id")},
        "kind": "operator",
    }
    config = tmp_path / "native.env"
    config.write_text("LUMINARY_BRIDGE_SOURCE='" + json.dumps(source) + "'\n", encoding="utf-8")
    monkeypatch.setenv("LUMINARY_CONFIG_FILE", str(config))
    response = dispatch({
        **request, "action": "remember", "text": "The model invented this deployment target.",
    }, client=client)
    assert response["stored"] == 0
    assert response["reason"] == "user_evidence_required"
    assert client.backend.count() == 0
    assert os.environ.get("LUMINARY_BRIDGE_SOURCE") is None
