import pytest

from luminary_memory.inspector import purge
from luminary_memory.inspector.contracts import ConsoleRequest
from luminary_memory.inspector.mutations import Conflict
from luminary_memory.types import Memory


def proposal(scenario, **extra):
    request = ConsoleRequest(operation="preview_change", request_id="purge-test", arguments={
        "kind": "purge", "memory_id": scenario.own_id, "expected_revision": 1, **extra,
    })
    return purge.preview(scenario.service, scenario.context, request)


def commit(scenario, result):
    manager = scenario.service.previews
    receipt = manager.confirm(scenario.context, result["preview_id"])
    request = ConsoleRequest(operation="mutate", request_id="commit-test", arguments={
        "preview_id": result["preview_id"], "confirmation_receipt": receipt,
    })
    with scenario.client.backend.transaction():
        stored = manager._load(scenario.context, result["preview_id"])
        _, auth = manager._confirmed(scenario.context, request, stored)
        data = purge.apply(scenario.service, scenario.context, auth, stored)
        stored["consumed"] = True
        scenario.client.backend.inspector_put("preview:" + result["preview_id"], stored)
        return data


def episode(scenario, name="ep"):
    backend = scenario.client.backend
    with backend.transaction():
        backend._sql("INSERT INTO episodes(id,content,user_id,workspace_id,agent_id) VALUES (?,?,?,?,?)",
                     (name, "private source", "alice", "project-a", "pi"))
        backend._sql("UPDATE memories SET source_id=? WHERE id=?", (name, scenario.own_id))
    # Setting source_id advances the content revision.
    return backend.get(scenario.own_id).revision


def test_preview_does_not_mutate_records_and_confirmed_purge_removes_copies(scenario):
    backend = scenario.client.backend
    before = scenario.snapshot()
    result = proposal(scenario)
    assert scenario.snapshot() == before
    assert result["effects"]["counts"]["memories"] == 1
    assert result["effects"]["unknown_external_copies"]
    stored = backend.inspector_get("preview:" + result["preview_id"])
    assert "Own deployment target is staging." not in str(stored)
    data = commit(scenario, result)
    assert data["audit"] == "committed"
    assert backend.get(scenario.own_id) is None
    assert backend._sql("SELECT COUNT(*) FROM memory_evidence WHERE memory_id=?", (scenario.own_id,)).fetchone()[0] == 0
    assert backend._sql("SELECT COUNT(*) FROM memory_events WHERE memory_id=? AND event_type<>'inspector_purge'", (scenario.own_id,)).fetchone()[0] == 0
    assert backend.get(scenario.foreign_id) is not None
    with pytest.raises(PermissionError):
        scenario.service.confirm(scenario.context, result["preview_id"])


def test_confirmation_receipt_is_required(scenario):
    result = proposal(scenario)
    request = ConsoleRequest(operation="mutate", request_id="forged", arguments={
        "preview_id": result["preview_id"], "confirmation_receipt": "forged"})
    with scenario.client.backend.transaction():
        stored = scenario.service.previews._load(scenario.context, result["preview_id"])
        with pytest.raises(PermissionError):
            scenario.service.previews._confirmed(scenario.context, request, stored)
    assert scenario.client.backend.get(scenario.own_id) is not None


def test_shared_episode_requires_explicit_expansion_and_deletes_shared_evidence(scenario):
    backend = scenario.client.backend
    revision = episode(scenario)
    other = backend.add(Memory(content="Another fact", user_id="alice", workspace_id="project-a", agent_id="pi", source_id="ep"))
    unexpanded = proposal(scenario, expected_revision=revision)
    assert unexpanded["effects"]["shared_memory_ids"] == [other]
    with pytest.raises(PermissionError):
        commit(scenario, unexpanded)
    result = proposal(scenario, expected_revision=revision, expand_shared=True)
    assert result["effects"]["shared_memory_ids"] == [other]
    commit(scenario, result)
    assert backend.get(other) is not None
    assert backend.get(other).source_id is None
    assert backend._sql("SELECT COUNT(*) FROM episodes WHERE id=?", ("ep",)).fetchone()[0] == 0


def test_shared_cross_owner_episode_rejected_even_with_expansion(scenario):
    backend = scenario.client.backend
    revision = episode(scenario)
    backend.add(Memory(content="Foreign shared", user_id="bob", workspace_id="project-a", agent_id="pi", source_id="ep"))
    with pytest.raises(PermissionError):
        proposal(scenario, expected_revision=revision, expand_shared=True)
    assert backend.get(scenario.own_id) is not None


def test_changed_revision_or_impact_prevents_purge(scenario):
    backend = scenario.client.backend
    result = proposal(scenario)
    memory = backend.get(scenario.own_id)
    memory.content = "new content"
    scenario.client.update(memory)
    with pytest.raises(Conflict):
        commit(scenario, result)
    assert backend.get(scenario.own_id).content == "new content"


def test_audit_failure_rolls_back_every_deletion(scenario, monkeypatch):
    backend = scenario.client.backend
    result = proposal(scenario)
    before = scenario.snapshot()
    def fail(*args, **kwargs):
        raise OSError("audit unavailable")
    monkeypatch.setattr(backend, "record_event", fail)
    with pytest.raises(OSError):
        commit(scenario, result)
    assert scenario.snapshot() == before


def test_linked_claim_episode_and_prior_preview_are_removed(scenario):
    backend = scenario.client.backend
    revision = episode(scenario)
    backend.add_claim(scenario.own_id, {
        "subject": "deployment", "predicate": "uses", "object": "staging",
        "evidence_quote": "private source", "source_episode_id": "ep",
    }, user_id="alice", workspace_id="project-a", agent_id="pi")
    old = scenario.preview("tag", memory_id=scenario.own_id, expected_revision=revision, tags=["tag"])
    result = proposal(scenario, expected_revision=revision)
    assert result["effects"]["counts"]["claims"] == 1
    assert result["effects"]["counts"]["claim_evidence"] == 1
    commit(scenario, result)
    assert backend._sql("SELECT COUNT(*) FROM claims WHERE memory_id=?", (scenario.own_id,)).fetchone()[0] == 0
    assert backend._sql("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == 0
    assert backend._sql("SELECT COUNT(*) FROM episodes WHERE id=?", ("ep",)).fetchone()[0] == 0
    assert backend.inspector_get("preview:" + old) is None


def test_new_linked_evidence_invalidates_confirmation(scenario):
    backend = scenario.client.backend
    result = proposal(scenario)
    backend.add_evidence(scenario.own_id, "new evidence")
    with pytest.raises(Conflict):
        commit(scenario, result)
    assert backend.get(scenario.own_id) is not None


def test_purge_cannot_target_another_owner(scenario):
    request = ConsoleRequest(operation="preview_change", request_id="foreign", arguments={
        "kind": "purge", "memory_id": scenario.foreign_id, "expected_revision": 1,
    })
    with pytest.raises(PermissionError):
        purge.preview(scenario.service, scenario.context, request)
    assert scenario.client.backend.get(scenario.foreign_id) is not None


def test_revoked_policy_invalidates_confirmation(scenario):
    result = proposal(scenario)
    backend = scenario.client.backend
    store = backend.inspector_get("store")
    store["policy_revision"] += 1
    backend.inspector_put("store", store)
    with pytest.raises(Conflict):
        commit(scenario, result)
    assert backend.get(scenario.own_id) is not None


def test_ingested_memory_without_claims_removes_implicit_source_episode(scenario):
    backend = scenario.client.backend
    memory_id = scenario.client.ingest("A unique source observation to purge", enrich=False)
    assert memory_id is not None
    episode_id = f"memory:{memory_id}"
    assert backend._sql("SELECT COUNT(*) FROM episodes WHERE id=?", (episode_id,)).fetchone()[0] == 1
    assert backend._sql("SELECT COUNT(*) FROM claims WHERE memory_id=?", (memory_id,)).fetchone()[0] == 0
    result = proposal(scenario, memory_id=memory_id, expected_revision=backend.get(memory_id).revision)
    assert result["effects"]["counts"]["episodes"] == 1
    commit(scenario, result)
    assert backend.get(memory_id) is None
    assert backend._sql("SELECT COUNT(*) FROM episodes WHERE id=?", (episode_id,)).fetchone()[0] == 0
