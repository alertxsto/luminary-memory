import json

from luminary_memory.types import Memory


def test_browse_refresh_does_not_change_store(scenario):
    before = scenario.snapshot()
    settings = dict(vars(scenario.client.settings))
    for _ in range(3):
        result = scenario.request("browse")
        assert result.status == "ok"
        assert [item["id"] for item in result.data["items"]] == [scenario.own_id]
        detail = scenario.request("detail", memory_id=scenario.own_id)
        assert detail.status == "ok"
        assert detail.data["evidence"]
        assert scenario.request("history", memory_id=scenario.own_id).data["items"]
    assert scenario.snapshot() == before
    assert vars(scenario.client.settings) == settings


def test_foreign_detail_and_history_do_not_leak(scenario):
    for memory_id in (scenario.foreign_id, scenario.peer_id, scenario.other_project_id):
        for operation in ("detail", "history"):
            result = scenario.request(operation, memory_id=memory_id)
            assert result.status == "denied"
            assert result.data is None


def test_pages_are_scope_filtered_stable_and_context_bound(scenario):
    backend = scenario.client.backend
    for n in range(4):
        backend.add(Memory(content=f"Own bounded item {n}", tags=["page"],
                    user_id="alice", workspace_id="project-a", agent_id="pi"))
    first = scenario.request("browse", limit=2, tags=["page"])
    assert first.status == "ok"
    assert len(first.data["items"]) == 2
    cursor = first.data["next_cursor"]
    second = scenario.request("browse", limit=2, tags=["page"], cursor=cursor)
    assert len(second.data["items"]) == 2
    assert not ({m["id"] for m in first.data["items"]} & {m["id"] for m in second.data["items"]})
    assert scenario.request("browse", limit=2, tags=["deployment"], cursor=cursor).status == "invalid_request"
    result = scenario.request("browse", statuses=["deleted"])
    assert result.status == "empty" and not result.data["items"]
    assert scenario.request("browse", created_after="2999-01-01T00:00:00+00:00").status == "empty"


def test_query_bounds_and_safe_projection(scenario):
    own = scenario.client.backend.get(scenario.own_id)
    own.content = "é" * 2000
    own.metadata = {"api_key": "DO_NOT_SERIALIZE"}
    scenario.client.update(own)
    result = scenario.request("browse", limit=100000)
    assert len(result.data["items"]) <= 100
    assert len(result.data["items"][0]["content"].encode("utf-8")) <= 512
    assert "DO_NOT_SERIALIZE" not in json.dumps(result.to_dict())


def test_backend_failure_is_not_empty(scenario, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("postgresql://secret:password@private-host")
    monkeypatch.setattr(scenario.client.backend, "inspector_memories", unavailable)
    result = scenario.request("browse")
    assert result.status == "unavailable"
    assert "password" not in json.dumps(result.to_dict())


def test_legacy_inventory_is_read_only_and_excludes_other_owners(scenario):
    backend = scenario.client.backend
    legacy = backend.add(Memory(content="legacy", user_id="alice"))
    backend.add(Memory(content="foreign legacy", user_id="bob"))
    before = scenario.snapshot()
    result = scenario.request("legacy_inventory")
    assert result.status == "ok"
    ids = [item["memory_id"] for item in result.data["items"]]
    # Every partial row that already names this owner is listed; another
    # owner's row is never disclosed.
    assert legacy in ids
    assert all(row["user_id"] in (None, "alice") for row in result.data["items"])
    assert scenario.snapshot() == before
