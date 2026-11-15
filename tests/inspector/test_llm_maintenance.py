import json

import pytest

from luminary_memory.inspector import llm_maintenance
from luminary_memory.inspector.contracts import ConsoleRequest
from luminary_memory.inspector.mutations import Conflict


class Reviewer:
    def __init__(self, action="update", source="source-1", quote="Deployment is now production.", confirmed=True):
        self.action, self.source, self.quote, self.confirmed = action, source, quote, confirmed
        self.candidates = []

    def review_memories(self, memories):
        self.candidates = memories
        return json.dumps({"actions": [{"id": memories[0].id, "action": self.action,
            "content": "Deployment target is production.", "source_id": self.source,
            "evidence_quote": self.quote, "confirmed": self.confirmed}]})


def setup_proposal(scenario, reviewer):
    backend = scenario.client.backend
    backend.record_episode("source-1", "Deployment is now production.", user_id="alice",
                           workspace_id="project-a", agent_id="pi")
    backend.add_evidence(scenario.own_id, "Deployment is now production.", source_id="source-1")
    scenario.client.enricher = reviewer
    return llm_maintenance.generate(scenario.client)


def req(**args):
    return ConsoleRequest(operation="preview_change", request_id="maintenance-test", arguments=args)


def proposals(scenario):
    return llm_maintenance.list_suggestions(scenario.service, scenario.context, req())["items"]


def prepare(scenario, proposal_id):
    return llm_maintenance.preview(scenario.service, scenario.context, req(proposal_id=proposal_id))


def commit(scenario, proposal, monkeypatch):
    manager = scenario.service.previews
    original = manager._apply
    def apply(context, request, authorization, preview, *, on_external_effect):
        if preview["kind"] == "maintenance_proposal":
            return llm_maintenance.apply(scenario.service, context, authorization, preview)
        return original(context, request, authorization, preview, on_external_effect=on_external_effect)
    monkeypatch.setattr(manager, "_apply", apply)
    return scenario.commit(proposal["preview_id"])


def test_review_is_only_proposal_until_owner_confirms_and_preserves_lineage(scenario, monkeypatch):
    reviewer = Reviewer()
    result = setup_proposal(scenario, reviewer)
    assert result["proposed"] == 1
    assert reviewer.candidates[0].source_id == "source-1"
    assert reviewer.candidates[0].evidence_quote == "Deployment is now production."
    assert scenario.client.backend.get(scenario.own_id).status == "active"
    item = proposals(scenario)[0]
    assert item["memory_id"] == scenario.own_id and item["revision"] == 1
    assert item["proposed_content"] == "Deployment target is production."
    view = prepare(scenario, item["proposal_id"])
    assert view["kind"] == "maintenance_proposal"
    result = commit(scenario, view, monkeypatch)
    assert result.status == "ok"
    successor = scenario.client.backend.get(result.data["memory_id"])
    assert successor.supersedes_id == scenario.own_id
    assert scenario.client.backend.get(scenario.own_id).status == "superseded"
    assert not proposals(scenario)
    with pytest.raises((PermissionError, Conflict)):
        prepare(scenario, item["proposal_id"])


@pytest.mark.parametrize("source,quote", [("forged", "Deployment is now production."),
    ("source-1", "Deployment target is production."), ("source-1", "")])
def test_forged_evidence_and_model_confirmation_never_mutate(scenario, source, quote):
    result = setup_proposal(scenario, Reviewer(source=source, quote=quote))
    assert result["proposed"] == 0
    assert proposals(scenario) == []
    assert scenario.client.backend.get(scenario.own_id).status == "active"


def test_stale_revision_and_source_change_fail_closed(scenario, monkeypatch):
    setup_proposal(scenario, Reviewer())
    item = proposals(scenario)[0]
    view = prepare(scenario, item["proposal_id"])
    memory = scenario.client.backend.get(scenario.own_id)
    memory.content = "Changed by owner"
    scenario.client.update(memory)
    assert commit(scenario, view, monkeypatch).status == "conflict"
    assert scenario.client.backend.get(scenario.own_id).content == "Changed by owner"


def test_delete_proposal_retracts_instead_of_hard_deleting(scenario, monkeypatch):
    setup_proposal(scenario, Reviewer(action="delete"))
    item = proposals(scenario)[0]
    assert item["action"] == "delete"
    result = commit(scenario, prepare(scenario, item["proposal_id"]), monkeypatch)
    assert result.status == "ok"
    assert scenario.client.backend.get(scenario.own_id).status == "deleted"


def test_source_ownership_change_after_preview_fails(scenario, monkeypatch):
    setup_proposal(scenario, Reviewer())
    view = prepare(scenario, proposals(scenario)[0]["proposal_id"])
    scenario.client.backend._sql("UPDATE episodes SET user_id=? WHERE id=?", ("bob", "source-1"))
    scenario.client.backend._commit()
    assert commit(scenario, view, monkeypatch).status == "conflict"
    assert scenario.client.backend.get(scenario.own_id).status == "active"


def test_duplicate_previews_cannot_apply_one_proposal_twice(scenario, monkeypatch):
    setup_proposal(scenario, Reviewer())
    proposal_id = proposals(scenario)[0]["proposal_id"]
    first, second = prepare(scenario, proposal_id), prepare(scenario, proposal_id)
    assert commit(scenario, first, monkeypatch).status == "ok"
    assert commit(scenario, second, monkeypatch).status == "conflict"


def test_changed_memory_scope_invalidates_confirmed_proposal(scenario, monkeypatch):
    setup_proposal(scenario, Reviewer())
    view = prepare(scenario, proposals(scenario)[0]["proposal_id"])
    scenario.client.backend._sql("UPDATE memories SET agent_id=? WHERE id=?", ("omp", scenario.own_id))
    scenario.client.backend._commit()
    assert commit(scenario, view, monkeypatch).status == "conflict"
    assert scenario.client.backend.get(scenario.own_id).status == "active"


def test_foreign_context_cannot_list_or_preview_proposal(scenario):
    from luminary_memory.api import MemoryClient
    from luminary_memory.inspector.identity import resolve_context

    setup_proposal(scenario, Reviewer())
    proposal_id = proposals(scenario)[0]["proposal_id"]
    scope = {**scenario.client.scope, "agent_id": "omp"}
    foreign_client = MemoryClient(
        settings=scenario.client.settings,
        backend=scenario.client.backend,
        engine=scenario.client.engine,
        scope=scope,
    )
    other = resolve_context(foreign_client, {**scenario.native, "agent_id": "omp"}, initialize=True)
    assert llm_maintenance.list_suggestions(scenario.service, other, req())["items"] == []
    with pytest.raises((PermissionError, Conflict)):
        llm_maintenance.preview(scenario.service, other, req(proposal_id=proposal_id))
