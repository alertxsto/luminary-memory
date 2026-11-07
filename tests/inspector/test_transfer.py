"""Native-selected transfer handles bind context, mode, digest and lineage."""
import json
from contextlib import contextmanager

import pytest


def test_guessed_file_handle_and_frontend_path_are_denied(scenario):
    result = scenario.request("transfer_preview", direction="import", file_handle="guessed")
    assert result.status == "denied", result.to_dict()
    raw = scenario.request("transfer_preview", direction="export", path="/arbitrary/file.json")
    assert raw.status in {"denied", "invalid_request"}


def test_import_digest_change_prevents_commit(scenario, tmp_path):
    from luminary_memory.inspector.transfer import register_file
    path = tmp_path / "selected.json"
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [{"content": "Imported original"}]}))
    handle = register_file(scenario.service, scenario.context, path, "read")
    preview = scenario.request("transfer_preview", direction="import", file_handle=handle)
    assert preview.status == "ok", preview.to_dict()
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [{"content": "Changed after approval"}]}))
    result = scenario.request("transfer_commit", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "conflict", result.to_dict()
    assert scenario.request("summary").data["totals"]["memories"] == 1


def test_import_does_not_accept_foreign_record_ownership(scenario, tmp_path):
    from luminary_memory.inspector.transfer import register_file
    path = tmp_path / "foreign.json"
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [{
        "content": "Do not reattribute another owner", "user_id": "bob", "workspace_id": "project-b", "agent_id": "omp",
    }]}))
    handle = register_file(scenario.service, scenario.context, path, "read")
    result = scenario.request("transfer_preview", direction="import", file_handle=handle)
    assert result.status == "denied", result.to_dict()


def test_import_rejects_unresolvable_legacy_lineage(scenario, tmp_path):
    from luminary_memory.inspector.transfer import register_file
    path = tmp_path / "lineage.json"
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [{
        "content": "A successor without its predecessor", "supersedes_id": 987654,
    }]}))
    handle = register_file(scenario.service, scenario.context, path, "read")
    result = scenario.request("transfer_preview", direction="import", file_handle=handle)
    assert result.status in {"unsupported", "invalid_request"}, result.to_dict()


def test_registered_output_cannot_download_unconfirmed_file(scenario, tmp_path):
    import pytest

    from luminary_memory.inspector.transfer import read_export, register_file

    path = tmp_path / "not-exported.json"
    path.write_text("This is not an authorized export")
    handle = register_file(scenario.service, scenario.context, path, "write")
    with pytest.raises(PermissionError):
        read_export(scenario.service, scenario.context, handle)


def test_cyclic_lineage_rejected_before_confirmation(scenario, tmp_path):
    from luminary_memory.inspector.transfer import register_file

    path = tmp_path / "cycle.json"
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [
        {"id": 1, "content": "First cycle member", "supersedes_id": 2},
        {"id": 2, "content": "Second cycle member", "supersedes_id": 1},
    ]}), encoding="utf-8")
    handle = register_file(scenario.service, scenario.context, path, "read")
    before = scenario.snapshot()
    result = scenario.request("transfer_preview", direction="import", file_handle=handle)
    assert result.status == "invalid_request", result.to_dict()
    assert scenario.snapshot() == before


def test_import_maps_history_and_reports_only_actual_saves(scenario, tmp_path):
    from luminary_memory.inspector.transfer import register_file

    duplicate = scenario.client.ingest("Previously saved imported policy", session_id=scenario.context.session_id)
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [
        {"id": 1000002, "content": "Imported reviewed policy", "supersedes_id": 1000001, "created_at": "2025-01-02T00:00:00+00:00"},
        {"id": 1000003, "content": "Previously saved imported policy"},
        {"id": 1000001, "content": "Imported previous policy", "status": "superseded", "created_at": "2025-01-01T00:00:00+00:00"},
    ]}), encoding="utf-8")
    handle = register_file(scenario.service, scenario.context, path, "read")
    preview = scenario.request("transfer_preview", direction="import", file_handle=handle)
    assert preview.status == "ok", preview.to_dict()
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    result = scenario.request("transfer_commit", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "ok", result.to_dict()
    assert (result.data["count"], result.data["stored"], result.data["duplicates"]) == (3, 2, 1)
    mapping = result.data["lineage_map"]
    older = scenario.client.backend.get(mapping["1000001"])
    newer = scenario.client.backend.get(mapping["1000002"])
    assert mapping["1000003"] == duplicate
    assert older.status == "superseded"
    assert newer.supersedes_id == older.id
    assert (older.user_id, older.workspace_id, older.agent_id) == (
        scenario.context.user_id, scenario.context.workspace_id, scenario.context.agent_id)
    assert newer.session_id == scenario.context.session_id
    before_reimport = scenario.snapshot()
    repeated_preview = scenario.request("transfer_preview", direction="import", file_handle=handle)
    assert repeated_preview.status == "ok", repeated_preview.to_dict()
    repeated_receipt = scenario.service.confirm(scenario.context, repeated_preview.data["preview_id"])
    repeated = scenario.request("transfer_commit", preview_id=repeated_preview.data["preview_id"], confirmation_receipt=repeated_receipt)
    assert repeated.status == "ok", repeated.to_dict()
    assert (repeated.data["stored"], repeated.data["duplicates"]) == (0, 3)
    assert repeated.data["lineage_map"] == mapping
    assert scenario.snapshot() == before_reimport


def test_invalid_native_context_cannot_create_transfer_staging_files(scenario, tmp_path):
    from dataclasses import replace

    import pytest

    from luminary_memory.inspector.transfer import register_export, register_upload

    wrong = replace(scenario.context, user_id="forged-owner")
    directory = tmp_path / "must-not-be-created"
    with pytest.raises(PermissionError):
        register_upload(scenario.service, wrong, b"{}", staging_directory=directory)
    with pytest.raises(PermissionError):
        register_export(scenario.service, wrong, staging_directory=directory)
    assert not directory.exists()


@pytest.mark.parametrize("failure", ["before_publication", "publication_ack", "after_publication", "database_commit"])
def test_export_reports_uncertain_publication_without_claiming_audit_commit(scenario, tmp_path, monkeypatch, failure):
    from luminary_memory.inspector import transfer

    backend = scenario.client.backend
    destination = tmp_path / "selected-export.json"
    destination.write_bytes(b"original selected file")
    handle = transfer.register_file(scenario.service, scenario.context, destination, "write")
    preview = scenario.request("transfer_preview", direction="export", file_handle=handle)
    assert preview.status == "ok", preview.to_dict()
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    before = scenario.snapshot()
    original_replace, original_put, original_transaction = transfer.os.replace, backend.inspector_put, backend.transaction

    def publication_ack_lost(source, target):
        original_replace(source, target)
        raise OSError("PRIVATE_FAILURE_DETAIL after publication")

    def metadata_failed(key, value):
        if key == "file:" + handle and value.get("ready"):
            raise OSError("PRIVATE_FAILURE_DETAIL after publication")
        return original_put(key, value)

    def staging_failed(*args, **kwargs):
        raise OSError("PRIVATE_FAILURE_DETAIL before publication")

    @contextmanager
    def commit_failed():
        outer = not backend.in_transaction
        with original_transaction():
            yield backend
            if outer:
                raise OSError("PRIVATE_FAILURE_DETAIL at database commit")

    with monkeypatch.context() as faults:
        if failure == "before_publication":
            faults.setattr(transfer.tempfile, "NamedTemporaryFile", staging_failed)
        elif failure == "publication_ack":
            faults.setattr(transfer.os, "replace", publication_ack_lost)
        elif failure == "after_publication":
            faults.setattr(backend, "inspector_put", metadata_failed)
        else:
            faults.setattr(backend, "transaction", commit_failed)
        result = scenario.request("transfer_commit", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)

    assert result.status == ("unavailable" if failure == "before_publication" else "unknown_outcome"), result.to_dict()
    assert "PRIVATE_FAILURE_DETAIL" not in json.dumps(result.to_dict())
    assert scenario.snapshot() == before
    if failure == "before_publication":
        assert destination.read_bytes() == b"original selected file"
    else:
        records = json.loads(destination.read_bytes())["memories"]
        assert [record["id"] for record in records] == [scenario.own_id]
    with pytest.raises(PermissionError):
        transfer.read_export(scenario.service, scenario.context, handle)


@pytest.mark.parametrize("invalidation", ["expired", "another_session"])
def test_native_file_selection_cannot_outlive_its_expiry_or_session(scenario, tmp_path, invalidation):
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.transfer import register_file

    path = tmp_path / "selected.json"
    path.write_text('{"format":"luminary-memory-export","version":1,"memories":[{"content":"Scoped import"}]}', encoding="utf-8")
    handle = register_file(scenario.service, scenario.context, path, "read")
    context = scenario.context
    if invalidation == "expired":
        descriptor = scenario.client.backend.inspector_get("file:" + handle)
        descriptor["expires_at"] = "2000-01-01T00:00:00+00:00"
        scenario.client.backend.inspector_put("file:" + handle, descriptor)
    else:
        context = resolve_context(scenario.client, {**scenario.native, "session_id": "another-session"}, initialize=True)
    before = scenario.snapshot()
    result = scenario.request("transfer_preview", context=context, direction="import", file_handle=handle)
    assert result.status == "denied", result.to_dict()
    assert scenario.snapshot() == before


def test_revoked_project_read_cannot_publish_a_previously_previewed_export(scenario, tmp_path):
    from luminary_memory.api import MemoryClient
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.transfer import register_file

    assert scenario.commit(scenario.preview("grant", recipient_agent_id="omp", capabilities=["read"])).status == "ok"
    peer = MemoryClient(settings=scenario.client.settings, backend=scenario.client.backend, engine=scenario.client.engine,
                        scope={"user_id": "alice", "workspace_id": "project-a", "agent_id": "omp"})
    context = resolve_context(peer, {**scenario.native, "agent_id": "omp"}, initialize=True)
    selection = scenario.service.selection_handle(context, scenario.context.project_id)
    destination = tmp_path / "previously-authorized.json"
    destination.write_bytes(b"untouched selected destination")
    handle = register_file(scenario.service, context, destination, "write")
    preview = scenario.request("transfer_preview", context=context, selection_handle=selection, direction="export", file_handle=handle)
    assert preview.status == "ok", preview.to_dict()
    assert preview.data["effects"]["count"] == 2
    receipt = scenario.service.confirm(context, preview.data["preview_id"])
    assert scenario.commit(scenario.preview("revoke", recipient_agent_id="omp")).status == "ok"
    before = scenario.snapshot()
    result = scenario.request("transfer_commit", context=context, preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert result.status == "denied", result.to_dict()
    assert destination.read_bytes() == b"untouched selected destination"
    assert scenario.snapshot() == before


def test_cancelled_export_never_publishes_and_cannot_reuse_confirmation(scenario, tmp_path):
    from luminary_memory.inspector.transfer import register_file

    destination = tmp_path / "cancelled-export.json"
    handle = register_file(scenario.service, scenario.context, destination, "write")
    preview = scenario.request("transfer_preview", direction="export", file_handle=handle)
    assert preview.status == "ok", preview.to_dict()
    receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
    before = scenario.snapshot()
    result = scenario.request("transfer_commit", preview_id=preview.data["preview_id"], cancel=True)
    assert result.status == "cancelled", result.to_dict()
    replay = scenario.request("transfer_commit", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
    assert replay.status == "denied", replay.to_dict()
    assert not destination.exists()
    assert scenario.snapshot() == before


@pytest.mark.parametrize("distinct_field", ["created_at", "source_id"])
def test_import_keeps_distinct_historical_observations_and_ignores_foreign_duplicates(scenario, tmp_path, distinct_field):
    from luminary_memory.api import _content_hash
    from luminary_memory.inspector.transfer import register_file
    from luminary_memory.types import Memory

    first = {"id": 1001, "content": "Repeated historical deployment policy", "status": "superseded",
             "created_at": "2024-01-01T00:00:00+00:00", "source_id": "source-note-a"}
    second = {**first, "id": 1002, distinct_field: "2025-01-01T00:00:00+00:00" if distinct_field == "created_at" else "source-note-b"}
    backend = scenario.client.backend
    foreign_id = backend.add(Memory(content=first["content"], content_hash=_content_hash(first["content"]),
        status=first["status"], created_at=first["created_at"], source_id=first["source_id"],
        user_id="bob", workspace_id="project-a", agent_id="pi", session_id=scenario.context.session_id))
    path = tmp_path / "historical-observations.json"
    path.write_text(json.dumps({"format": "luminary-memory-export", "version": 1, "memories": [first, second]}), encoding="utf-8")
    handle = register_file(scenario.service, scenario.context, path, "read")
    mappings = []
    for expected in ((2, 0), (0, 2)):
        preview = scenario.request("transfer_preview", direction="import", file_handle=handle)
        assert preview.status == "ok", preview.to_dict()
        receipt = scenario.service.confirm(scenario.context, preview.data["preview_id"])
        result = scenario.request("transfer_commit", preview_id=preview.data["preview_id"], confirmation_receipt=receipt)
        assert result.status == "ok", result.to_dict()
        assert (result.data["stored"], result.data["duplicates"]) == expected
        mappings.append(dict(result.data["lineage_map"]))
    assert mappings[0] == mappings[1]
    assert len(set(mappings[0].values())) == 2
    assert foreign_id not in mappings[0].values()
    assert all(backend.get(memory_id).user_id == "alice" for memory_id in mappings[0].values())
    assert backend.get(foreign_id).user_id == "bob"
