import json

from luminary_memory.inspector.identity import resolve_context


def peer_context(scenario):
    from luminary_memory.api import MemoryClient
    client = MemoryClient(settings=scenario.client.settings, backend=scenario.client.backend,
                          engine=scenario.client.engine, scope={"user_id": "alice", "workspace_id": "project-a", "agent_id": "omp"})
    return resolve_context(client, dict(scenario.native, agent_id="omp"), initialize=True)


def grant(scenario, capabilities):
    preview = scenario.preview("grant", recipient_agent_id="omp", capabilities=capabilities)
    result = scenario.commit(preview)
    assert result.status == "ok", result.to_dict()
    return peer_context(scenario)


def test_grants_require_native_confirmation(scenario):
    result = scenario.request("grant", recipient_agent_id="omp", capabilities=["read"], confirmed=True)
    assert result.status == "denied"
    assert scenario.request("detail", context=peer_context(scenario), memory_id=scenario.own_id).status == "denied"


def test_explicit_sharing_preserves_agent_ownership(scenario):
    peer = grant(scenario, ["read", "contribute"])
    assert scenario.request("detail", context=peer, memory_id=scenario.own_id).status == "denied"
    handle = scenario.service.selection_handle(peer, scenario.context.project_id)
    detail = scenario.request("detail", context=peer, selection_handle=handle, memory_id=scenario.own_id)
    assert detail.status == "ok"
    assert detail.data["permissions"] == {"read": True, "contribute": True, "edit": False, "retract": False}
    preview = scenario.request("preview_change", context=peer, selection_handle=handle, kind="create", content="Peer contributed fact")
    receipt = scenario.service.confirm(peer, preview.data["preview_id"])
    result = scenario.request("mutate", context=peer, preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "ok"
    memory = scenario.client.backend.get(result.data["memory_id"])
    assert memory.agent_id == "omp" and memory.user_id == "alice"
    assert scenario.client.backend.get(scenario.own_id).agent_id == "pi"


def test_write_without_read_returns_no_existing_content(scenario):
    peer = grant(scenario, ["edit"])
    handle = scenario.service.selection_handle(peer, scenario.context.project_id)
    preview = scenario.request("preview_change", context=peer, selection_handle=handle,
                               kind="correct", memory_id=scenario.own_id, expected_revision=1, content="Authorized replacement")
    assert preview.status == "ok"
    assert "staging" not in json.dumps(preview.to_dict())
    receipt = scenario.service.confirm(peer, preview.data["preview_id"])
    result = scenario.request("mutate", context=peer, preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "ok"
    assert "content" not in result.data
    assert "staging" not in json.dumps(result.to_dict())
    successor = scenario.client.backend.get(result.data["memory_id"])
    assert successor.content == "Authorized replacement" and successor.agent_id == "pi"
    assert successor.supersedes_id == scenario.own_id
    assert scenario.client.backend.get(scenario.own_id).status == "superseded"
    assert scenario.request("detail", context=peer, selection_handle=handle, memory_id=scenario.own_id).status == "denied"


def test_revocation_blocks_pending_access(scenario):
    peer = grant(scenario, ["read", "edit"])
    handle = scenario.service.selection_handle(peer, scenario.context.project_id)
    page = scenario.request("browse", context=peer, selection_handle=handle, limit=1)
    pending = scenario.request("preview_change", context=peer, selection_handle=handle,
                               kind="tag", memory_id=scenario.own_id, expected_revision=1, tags=["pending"])
    receipt = scenario.service.confirm(peer, pending.data["preview_id"])
    preview = scenario.preview("revoke", recipient_agent_id="omp")
    assert scenario.commit(preview).status == "ok"
    for operation in ("browse", "detail", "history"):
        assert scenario.request(operation, context=peer, selection_handle=handle,
                                memory_id=scenario.own_id).status == "denied"
    result = scenario.request("mutate", context=peer, preview_id=pending.data["preview_id"], confirmation_receipt=receipt)
    assert result.status in {"denied", "conflict"}
    assert scenario.client.backend.get(scenario.own_id).tags == ["deployment"]
    if page.data["next_cursor"]:
        assert scenario.request("browse", context=peer, cursor=page.data["next_cursor"]).status != "ok"
