import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from luminary_memory.types import Memory


def test_two_editors_one_revision(scenario):
    first = scenario.preview("correct", memory_id=scenario.own_id, expected_revision=1, content="First edit")
    second = scenario.preview("correct", memory_id=scenario.own_id, expected_revision=1, content="Stale edit")
    result = scenario.commit(first)
    assert result.status == "ok"
    assert scenario.commit(second).status == "conflict"
    memory = scenario.client.backend.get(scenario.own_id)
    successor = scenario.client.backend.get(result.data["memory_id"])
    assert memory.status == "superseded" and memory.revision == 2
    assert successor.content == "First edit" and successor.supersedes_id == memory.id


def test_access_bookkeeping_does_not_conflict_content_revision(scenario):
    preview = scenario.preview("tag", memory_id=scenario.own_id, expected_revision=1, tags=["reviewed"])
    backend = scenario.client.backend
    memory = backend.get(scenario.own_id)
    memory.access_count += 1
    memory.last_accessed_at = datetime.now(UTC).isoformat()
    backend.update(memory)
    assert backend.get(memory.id).revision == 1
    assert scenario.commit(preview).status == "ok"


def test_provider_content_writer_advances_revision(scenario):
    preview = scenario.preview("tag", memory_id=scenario.own_id, expected_revision=1, tags=["stale"])
    memory = scenario.client.get(scenario.own_id)
    memory.content = "Provider wrote newer fact"
    scenario.client.update(memory)
    assert scenario.client.backend.get(memory.id).revision == 2
    assert scenario.commit(preview).status == "conflict"


def test_audit_failure_rolls_back_change(scenario, monkeypatch):
    backend = scenario.client.backend
    preview = scenario.preview("correct", memory_id=scenario.own_id, expected_revision=1, content="Must roll back")
    before = scenario.snapshot()
    def fail(*args, **kwargs):
        raise OSError("audit unavailable")
    monkeypatch.setattr(backend, "record_event", fail)
    assert scenario.commit(preview).status == "unavailable"
    assert scenario.snapshot() == before
    assert backend.get(scenario.own_id).content == "Own deployment target is staging."


def test_untrusted_confirmation_and_replay_cannot_mutate(scenario):
    preview = scenario.preview("tag", memory_id=scenario.own_id, expected_revision=1, tags=["new"])
    result = scenario.request("mutate", preview_id=preview, confirmed=True)
    assert result.status == "denied"
    assert scenario.commit(preview).status == "ok"
    with pytest.raises(PermissionError):
        scenario.service.confirm(scenario.context, preview)


def test_context_mismatch_cannot_confirm(scenario):
    preview = scenario.preview("retract", memory_id=scenario.own_id, expected_revision=1)
    wrong = replace(scenario.context, session_id="another-session")
    with pytest.raises(PermissionError):
        scenario.service.confirm(wrong, preview)


def test_expired_confirmation_cannot_commit(scenario):
    preview = scenario.preview("retract", memory_id=scenario.own_id, expected_revision=1)
    proposal = scenario.client.backend.inspector_get("preview:" + preview)
    proposal["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    scenario.client.backend.inspector_put("preview:" + preview, proposal)
    with pytest.raises(PermissionError):
        scenario.service.confirm(scenario.context, preview)
    assert scenario.client.backend.get(scenario.own_id).status == "active"


def test_cancelled_preview_cannot_commit(scenario):
    preview = scenario.preview("retract", memory_id=scenario.own_id, expected_revision=1)
    assert scenario.request("mutate", preview_id=preview, cancel=True).status == "cancelled"
    with pytest.raises(PermissionError):
        scenario.service.confirm(scenario.context, preview)


def test_foreign_agent_mutation_denied(scenario):
    result = scenario.request("preview_change", kind="retract", memory_id=scenario.peer_id, expected_revision=1)
    assert result.status == "denied" and result.data is None


def test_new_conflicting_member_invalidates_confirmation(scenario):
    backend = scenario.client.backend
    preview = scenario.preview("resolve_conflict", memory_id=scenario.own_id, expected_revision=1)
    backend.add(Memory(content="A racing deployment target", user_id="alice", workspace_id="project-a",
                       agent_id="pi", claim_key="deploy", status="conflicted"))
    before = scenario.snapshot()
    assert scenario.commit(preview).status == "conflict"
    assert scenario.snapshot() == before


def test_conflict_resolution_audit_failure_rolls_back_all_rows(scenario, monkeypatch):
    backend = scenario.client.backend
    other = backend.add(Memory(content="Second conflicting target", user_id="alice", workspace_id="project-a",
                               agent_id="pi", claim_key="deploy", status="conflicted"))
    preview = scenario.preview("resolve_conflict", memory_id=scenario.own_id, expected_revision=1)
    before = scenario.snapshot()
    original = backend.record_event
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("second audit failed")
        return original(*args, **kwargs)
    monkeypatch.setattr(backend, "record_event", fail_second)
    assert scenario.commit(preview).status == "unavailable"
    assert scenario.snapshot() == before
    assert backend.get(other).status == "conflicted"


def test_maintenance_preview_does_not_write_and_stale_proposal_cannot_commit(scenario):
    backend = scenario.client.backend
    memory = backend.get(scenario.own_id)
    memory.importance = 0.1
    scenario.client.update(memory)
    before = scenario.snapshot()
    preview = scenario.request("maintenance_preview", kind="prune", min_importance=0.2)
    assert preview.status == "ok" and preview.data["effects"]["count"] == 1
    assert scenario.snapshot() == before
    memory = backend.get(scenario.own_id)
    memory.tags = ["changed"]
    scenario.client.update(memory)
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    result = scenario.request("maintenance_commit", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "conflict"
    assert backend.get(scenario.own_id) is not None


def test_core_create_retract_and_maintenance_use_real_engine(scenario):
    created = scenario.commit(scenario.preview("create", content="Inspector created fact", tags=["manual"]))
    assert created.status == "ok"
    memory_id = created.data["memory_id"]
    memory = scenario.client.backend.get(memory_id)
    assert memory.embedding and memory.user_id == "alice" and memory.agent_id == "pi"
    core = scenario.commit(scenario.preview("core", memory_id=memory_id, expected_revision=1, pinned=True))
    assert core.status == "ok" and scenario.client.backend.get(memory_id).importance >= 0.9
    retracted = scenario.commit(scenario.preview("retract", memory_id=memory_id, expected_revision=2))
    assert retracted.status == "ok" and scenario.client.backend.get(memory_id).status == "deleted"


def test_claim_set_lock_serializes_normal_writers(scenario):
    backend = scenario.client.backend
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    def writer():
        entered.set()
        backend.add(Memory(content="Concurrent claim", user_id="alice", workspace_id="project-a",
                           agent_id="pi", claim_key="deploy"))
        finished.set()
    with backend.transaction():
        backend.lock_claim_set({"user_id": "alice", "workspace_id": "project-a", "agent_id": "pi"}, "deploy")
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(writer)
        assert entered.wait(3)
        assert not finished.wait(0.1)
        release.set()
    pool.shutdown(wait=True)
    future.result(timeout=10)
    assert finished.is_set()


def test_changed_preview_digest_and_wrong_receipt_are_denied(scenario):
    preview = scenario.preview("tag", memory_id=scenario.own_id, expected_revision=1, tags=["approved"])
    receipt = scenario.service.confirm(scenario.context, preview)
    assert scenario.request("mutate", preview_id=preview, confirmation_receipt="forged").status == "denied"
    stored = scenario.client.backend.inspector_get("preview:" + preview)
    stored["payload"]["tags"] = ["unapproved"]
    scenario.client.backend.inspector_put("preview:" + preview, stored)
    assert scenario.request("mutate", preview_id=preview, confirmation_receipt=receipt).status == "denied"
    assert scenario.client.backend.get(scenario.own_id).tags == ["deployment"]


def test_new_structured_claim_invalidates_confirmation(scenario):
    backend = scenario.client.backend
    preview = scenario.preview("resolve_conflict", memory_id=scenario.own_id, expected_revision=1)
    backend.add_claim(scenario.own_id, {"subject": "deployment", "predicate": "target", "object": "production",
                      "evidence_quote": "Deployment target is production."},
                      user_id="alice", workspace_id="project-a", agent_id="pi")
    assert backend.get(scenario.own_id).revision == 1
    before = scenario.snapshot()
    assert scenario.commit(preview).status == "conflict"
    assert scenario.snapshot() == before


def test_resolution_requires_observed_conflict_set_token(scenario):
    result = scenario.request("preview_change", kind="resolve_conflict", memory_id=scenario.own_id, expected_revision=1)
    assert result.status == "conflict"


def test_two_real_clients_cannot_commit_one_content_revision(scenario):
    from luminary_memory.api import MemoryClient
    from luminary_memory.backends.sqlite import SQLiteBackend
    from luminary_memory.inspector.contracts import ConsoleRequest
    from luminary_memory.inspector.service import InspectorService
    original = scenario.client.backend
    def new_backend():
        if isinstance(original, SQLiteBackend):
            return SQLiteBackend(original.db_path)
        from luminary_memory.backends.pgvector import PGVectorBackend
        return PGVectorBackend(dsn=original.dsn, embedding_dim=3)
    previews = [scenario.preview("tag", memory_id=scenario.own_id, expected_revision=1, tags=[tag])
                for tag in ("first", "second")]
    receipts = [scenario.service.confirm(scenario.context, preview) for preview in previews]
    barrier = threading.Barrier(2)
    def editor(index):
        backend = new_backend()
        client = MemoryClient(settings=scenario.client.settings, backend=backend,
                              engine=scenario.client.engine, scope=scenario.client.scope)
        try:
            barrier.wait(timeout=10)
            return InspectorService(client).execute(scenario.context, ConsoleRequest(
                operation="mutate", request_id=f"editor-{index}", arguments={
                    "preview_id": previews[index], "confirmation_receipt": receipts[index]})).status
        finally:
            client.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(editor, (0, 1)))
    assert sorted(statuses) == ["conflict", "ok"]
    assert original.get(scenario.own_id).revision == 2


def test_correction_of_unkeyed_fact_preserves_version_lineage(scenario):
    created = scenario.commit(scenario.preview("create", content="Original unkeyed fact"))
    memory_id = created.data["memory_id"]
    corrected = scenario.commit(scenario.preview("correct", memory_id=memory_id, expected_revision=1, content="Corrected unkeyed fact"))
    assert corrected.status == "ok"
    successor = scenario.client.backend.get(corrected.data["memory_id"])
    assert successor.supersedes_id == memory_id
    assert scenario.client.backend.get(memory_id).status == "superseded"


def test_created_memory_and_durable_audit_keep_verified_native_session(scenario):
    preview = scenario.preview("create", content="Created from the verified native session")
    result = scenario.commit(preview)
    assert result.status == "ok", result.to_dict()
    memory_id = result.data["memory_id"]
    detail = scenario.request("detail", memory_id=memory_id)
    assert detail.data["memory"].get("session_id") == scenario.context.session_id
    event = scenario.client.backend._sql(
        "SELECT session_id FROM memory_events WHERE memory_id=? AND event_type='ingest'",
        (memory_id,),
    ).fetchone()
    assert event[0] == scenario.context.session_id


def test_duplicate_create_receipt_does_not_claim_a_second_durable_save(scenario):
    first = scenario.commit(scenario.preview("create", content="One durable fact, repeated request"))
    repeated = scenario.commit(scenario.preview("create", content="One durable fact, repeated request"))
    assert first.status == repeated.status == "ok"
    assert first.data.get("stored") == 1
    assert repeated.data.get("stored") == 0
    assert repeated.data.get("duplicates") == 1
    assert repeated.data["memory_id"] == first.data["memory_id"]
    assert repeated.data["revision"] == first.data["revision"]
    assert scenario.request("summary").data["totals"]["memories"] == 2


@pytest.mark.parametrize("editor_agent", ["pi", "omp"])
def test_correction_records_current_native_observation_without_changing_original_ownership(scenario, editor_agent):
    from luminary_memory.api import MemoryClient
    from luminary_memory.inspector.identity import resolve_context

    backend = scenario.client.backend
    original = backend.get(scenario.own_id)
    original.session_id = "previous-provider-session"
    original.source = "previous-provider"
    original.source_id = "previous-observation"
    backend.update(original)
    original = backend.get(original.id)
    if editor_agent == "omp":
        assert scenario.commit(scenario.preview("grant", recipient_agent_id="omp", capabilities=["read", "edit"])).status == "ok"
    editor = MemoryClient(settings=scenario.client.settings, backend=backend, engine=scenario.client.engine,
                         scope={"user_id": "alice", "workspace_id": "project-a", "agent_id": editor_agent})
    context = resolve_context(editor, {**scenario.native, "agent_id": editor_agent, "session_id": "current-editor-session"}, initialize=True)
    selection = scenario.service.selection_handle(context, scenario.context.project_id) if editor_agent == "omp" else None
    preview = scenario.request("preview_change", context=context, selection_handle=selection, kind="correct",
                               memory_id=original.id, expected_revision=original.revision, content="Current reviewed deployment policy")
    assert preview.status == "ok", preview.to_dict()
    receipt = scenario.service.confirm(context, preview.data["preview_id"])
    result = scenario.request("mutate", context=context, preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "ok", result.to_dict()
    successor = backend.get(result.data["memory_id"])
    predecessor = backend.get(original.id)
    assert (successor.user_id, successor.workspace_id, successor.agent_id) == ("alice", "project-a", "pi")
    assert successor.session_id == context.session_id
    assert successor.source == "inspector"
    assert successor.source_id == "inspector:" + preview.data["preview_id"]
    assert successor.supersedes_id == predecessor.id
    assert (predecessor.session_id, predecessor.source_id, predecessor.status) == (
        "previous-provider-session", "previous-observation", "superseded")
    event = backend._sql("SELECT session_id FROM memory_events WHERE memory_id=? AND event_type='ingest'",
                         (successor.id,)).fetchone()
    assert event[0] == context.session_id


def test_new_observation_session_cannot_escape_a_bound_client_session(scenario):
    from luminary_memory.api import MemoryClient

    backend = scenario.client.backend
    original = backend.get(scenario.own_id)
    original.session_id = "bound-session"
    backend.update(original)
    scoped = MemoryClient(settings=scenario.client.settings, backend=backend, engine=scenario.client.engine,
                          scope={**scenario.client.scope, "session_id": "bound-session"})
    before = scenario.snapshot()
    with pytest.raises(PermissionError):
        scoped.supersede(original.id, "An unauthorized cross-session observation",
                         session_id="another-session", source_id="must-not-be-saved")
    assert scenario.snapshot() == before
