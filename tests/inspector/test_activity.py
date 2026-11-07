"""Activity is scoped durable events, not a snapshot reinterpreted as saves."""
import json


def test_deleted_resource_retains_scoped_audit_without_foreign_events(scenario):
    backend = scenario.client.backend
    backend.record_event("inspector_test", scenario.own_id, after={
        "user_id": "alice", "workspace_id": "project-a", "agent_id": "pi", "content": "Own audit marker",
    })
    backend.delete(scenario.own_id)
    result = scenario.request("events")
    assert result.status == "ok", result.to_dict()
    assert any(event["kind"] == "inspector_test" for event in result.data["items"])
    body = json.dumps(result.to_dict())
    assert all(marker not in body for marker in ("BOB_SECRET", "PEER_SECRET", "GLOBAL_SECRET"))


def test_activity_refresh_does_not_emit_another_write(scenario):
    before = scenario.snapshot()
    first = scenario.request("events")
    second = scenario.request("events")
    assert first.status == "ok", first.to_dict()
    assert [row["event_id"] for row in first.data["items"]] == [row["event_id"] for row in second.data["items"]]
    assert scenario.snapshot() == before


def test_operational_replay_scopes_before_limit_and_hides_unowned_legacy_events(scenario):
    snapshot = scenario.request("events")
    boundary = snapshot.data["snapshot_boundary"]
    payload = {"user_id": "alice", "workspace_id": "project-a", "agent_id": "pi",
               "session_id": "session-1", "operation_id": "own-recall", "status": "returned",
               "memory_ids": [scenario.own_id], "stored": 0, "injected": None}
    backend = scenario.client.backend
    backend.record_event("native_recall", None, after=payload, actor="pi")
    backend.record_event("native_recall", None, after={
        **payload, "user_id": "bob", "operation_id": "FOREIGN_OPERATION_SECRET",
        "memory_ids": [scenario.foreign_id],
    }, actor="FOREIGN_SOURCE_SECRET")
    backend.record_event("native_recall", None, after={
        key: value for key, value in {**payload, "operation_id": "LEGACY_OPERATION_SECRET"}.items()
        if key != "user_id"
    }, actor="legacy")
    result = scenario.request("events", since_event_id=boundary, limit=1,
                              replay_context=snapshot.data.get("replay_context"))
    assert result.status == "ok", result.to_dict()
    assert [row["operation"]["id"] for row in result.data["items"]] == ["own-recall"]
    assert list(result.data["items"][0]["operation"]["memory_ids"]) == [scenario.own_id]
    assert result.data["has_more"] is False
    serialized = json.dumps(result.to_dict())
    assert all(secret not in serialized for secret in (
        "FOREIGN_OPERATION_SECRET", "FOREIGN_SOURCE_SECRET", "LEGACY_OPERATION_SECRET"))


def test_replay_rejects_boundary_from_another_native_session(scenario):
    from luminary_memory.inspector.identity import resolve_context

    snapshot = scenario.request("events")
    switched = resolve_context(scenario.client, {**scenario.native, "session_id": "session-2"})
    scenario.client.backend.record_event("updated", scenario.own_id)
    result = scenario.request("events", context=switched,
                              since_event_id=snapshot.data["snapshot_boundary"],
                              replay_context=snapshot.data.get("replay_context"))
    assert result.status == "invalid_request", result.to_dict()
    assert result.data is None


def test_replay_reports_missing_witnessed_history_instead_of_healthy_empty(scenario):
    snapshot = scenario.request("events")
    boundary = snapshot.data["snapshot_boundary"]
    backend = scenario.client.backend
    with backend.transaction():
        backend._sql("DELETE FROM memory_events WHERE id=?", (boundary,))
    result = scenario.request("events", since_event_id=boundary,
                              replay_context=snapshot.data.get("replay_context"))
    assert result.data["gap"] is True, result.to_dict()
    assert result.data["snapshot_required"] is True
    assert result.data["replay_context"] is None


def test_provider_activity_separates_duplicate_skip_and_session_episode(scenario):
    import threading

    from luminary_memory.hermes.provider import LuminaryMemoryProvider

    provider = LuminaryMemoryProvider()
    provider._client = scenario.client
    provider._thread_clients[threading.get_ident()] = scenario.client
    provider._user_id = "alice"
    provider._agent_workspace = "project-a"
    provider._agent_identity = "pi"
    provider._session_id = "session-1"
    content = "Production deployments require a reviewed migration."
    metadata = {"session_id": "previous-session"}
    provider._do_retain(content, [], metadata, "explicit-hook")
    provider._do_retain(content, [], metadata, "explicit-hook")
    provider._do_retain("RAW_TURN_SECRET", ["session:previous-session"], metadata, "hermes")
    provider._record_session_episode("RAW_EPISODE_SECRET", session_id="session-1")
    provider._record_session_episode("RAW_EPISODE_SECRET", session_id="session-1")

    result = scenario.request("events", limit=100)
    assert result.status == "ok", result.to_dict()
    events = [row for row in reversed(result.data["items"]) if row["kind"] == "hermes_operation"]
    completed = [row["operation"] for row in events
                 if row["operation"]["name"] == "retain" and row["operation"]["state"] != "running"]
    assert [(row["state"], row["stored"], row["duplicates"]) for row in completed] == [
        ("committed", 1, 0), ("duplicate", 0, 1), ("skipped", 0, 0),
    ]
    assert all(row["operation"]["session_id"] == "previous-session"
               for row in events if row["operation"]["name"] == "retain")
    episodes = [row["operation"] for row in events if row["operation"]["name"] == "session_episode"]
    assert [(row["state"], row["episodes"]) for row in episodes] == [("committed", 1), ("duplicate", 0)]
    assert all(row["stored"] == 0 for row in episodes)
    assert all(row["operation"]["injected"] is None for row in events)
    body = json.dumps([row for row in result.to_dict()["data"]["items"] if row["kind"] == "hermes_operation"])
    assert content not in body
    assert "RAW_TURN_SECRET" not in body
    assert "RAW_EPISODE_SECRET" not in body
    summary = scenario.request("summary")
    assert summary.data["totals"]["active"] == 2
    assert all(row["kind"] != "hermes_operation" for row in summary.data["changes"])


def test_provider_tool_duplicate_returns_no_new_save(scenario):
    from luminary_memory.hermes.provider import LuminaryMemoryProvider

    provider = LuminaryMemoryProvider()
    provider._client = scenario.client
    provider._user_id = "alice"
    provider._agent_workspace = "project-a"
    provider._agent_identity = "pi"
    provider._session_id = "session-1"
    arguments = {"content": "The primary deployment region is eu-west-2."}
    first = json.loads(provider.handle_tool_call("luminary_ingest", arguments))
    duplicate = json.loads(provider.handle_tool_call("luminary_ingest", arguments))
    assert first["stored"] == 1
    assert duplicate["stored"] == 0
    assert duplicate["duplicates"] == 1
    assert first["memory_id"] == duplicate["memory_id"]
    events = scenario.request("events", limit=100).data["items"]
    outcomes = [row["operation"] for row in events if row["operation"]
                and row["operation"]["name"] == "tool_ingest" and row["operation"]["state"] != "running"]
    assert [(row["state"], row["stored"]) for row in outcomes] == [("duplicate", 0), ("committed", 1)]
