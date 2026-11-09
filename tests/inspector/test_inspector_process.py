"""Inspector process boundary: trusted launcher context, no frontend authority.

Every case is hermetic: the process environment points at ``tmp_path`` and the
operator config file is disabled, so a failing assertion can never open the
real store.
"""
import json
import os

import pytest

from luminary_memory.integrations.inspector_cli import dispatch_inspector, native_context


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINARY_CONFIG_FILE", "none")
    monkeypatch.setenv("LUMINARY_DB_PATH", str(tmp_path / "inspector.db"))
    monkeypatch.setenv("LUMINARY_USER_ID", "owner")
    monkeypatch.delenv("LUMINARY_INSPECTOR_CONTEXT", raising=False)
    monkeypatch.delenv("LUMINARY_INSPECTOR_OPEN", raising=False)
    monkeypatch.delenv("LUMINARY_INSPECTOR_CONFIRM", raising=False)
    monkeypatch.delenv("LUMINARY_INSPECTOR_FILE", raising=False)
    monkeypatch.delenv("LUMINARY_INSPECTOR_DOWNLOAD", raising=False)


def context(tmp_path, **overrides):
    native = {"agent_id": "pi", "workspace": str(tmp_path), "session_id": "session-a",
              "host_id": "host-a", "profile_id": "default", **overrides}
    return {"LUMINARY_INSPECTOR_CONTEXT": json.dumps(native), "LUMINARY_USER_ID": "owner",
            "LUMINARY_DB_PATH": str(tmp_path / "inspector.db"), "LUMINARY_CONFIG_FILE": "none"}


def request(operation="browse", request_id="r1", **arguments):
    return json.dumps({"operation": operation, "arguments": arguments, "request_id": request_id}).encode()


def test_missing_or_malformed_native_context_is_denied(tmp_path):
    with pytest.raises(PermissionError):
        native_context({})
    with pytest.raises(PermissionError):
        native_context({"LUMINARY_INSPECTOR_CONTEXT": "x" * 9000})
    with pytest.raises(PermissionError):
        native_context({"LUMINARY_INSPECTOR_CONTEXT": "[]"})
    for field in ("agent_id", "workspace", "session_id", "host_id", "profile_id"):
        with pytest.raises(PermissionError):
            native_context(context(tmp_path, **{field: "  "}))
    with pytest.raises(PermissionError):
        native_context(context(tmp_path, workspace=str(tmp_path / "missing")))
    with pytest.raises(PermissionError):
        native_context(context(tmp_path, workspace="relative/path"))


def test_native_owner_must_match_the_configured_account(tmp_path):
    with pytest.raises(PermissionError, match="owner mismatch"):
        native_context(context(tmp_path, user_id="someone-else"))


def test_native_context_normalizes_the_verified_location(tmp_path):
    resolved = native_context(context(tmp_path, user_id="owner"))
    assert resolved["workspace"] == os.path.normcase(str(tmp_path.resolve()))
    assert (resolved["user_id"], resolved["agent_id"]) == ("owner", "pi")


def test_invalid_or_oversized_requests_never_reach_storage(tmp_path):
    from luminary_memory.integrations import MAX_REQUEST_BYTES

    environment = context(tmp_path)
    assert dispatch_inspector(b"x" * (MAX_REQUEST_BYTES + 1), environment)["error"]["code"] == "invalid_request"
    assert dispatch_inspector(b"[]", environment)["error"]["code"] == "invalid_request"
    denied = dispatch_inspector(request(db_path="foreign.db"), environment)
    assert denied["status"] == "denied"
    assert not (tmp_path / "foreign.db").exists()
    denied = dispatch_inspector(request(), {})
    assert (denied["status"], denied["request_id"]) == ("denied", "r1")


def test_request_id_is_truncated_and_echoed_on_failure():
    result = dispatch_inspector(request(request_id="r" * 400), {})
    assert result["status"] == "denied"
    assert result["request_id"] == "r" * 128


def test_opening_initializes_the_exact_native_binding_once(tmp_path):
    environment = context(tmp_path)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    first = dispatch_inspector(request(), environment)
    assert first["status"] == "empty"
    assert first["data"]["native_context"]["agent_id"] == "pi"
    assert first["data"]["native_context"]["user_id"] == "owner"
    second = dispatch_inspector(request("summary", "r2"), environment)
    assert second["status"] == "ok"
    assert second["data"]["native_context"]["store_id"] == first["data"]["native_context"]["store_id"]
    assert second["data"]["totals"]["memories"] == 0


def test_unopened_store_requires_an_owner_binding(tmp_path):
    result = dispatch_inspector(request(), context(tmp_path))
    assert (result["status"], result["error"]["code"]) == ("denied", "native_context_denied")


def test_confirmation_channel_cannot_commit_a_guessed_preview(tmp_path):
    environment = context(tmp_path)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    environment["LUMINARY_INSPECTOR_CONFIRM"] = "guessed-preview"
    result = dispatch_inspector(request("mutate"), environment)
    assert result["data"] is None
    assert result["status"] in {"denied", "invalid_request", "unavailable"}


def test_file_channel_rejects_a_forged_descriptor(tmp_path):
    environment = context(tmp_path)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    environment["LUMINARY_INSPECTOR_FILE"] = json.dumps(
        {"path": str(tmp_path / "x.json"), "mode": "read", "extra": True})
    assert dispatch_inspector(request(), environment)["error"]["code"] == "invalid_request"

    environment["LUMINARY_INSPECTOR_FILE"] = json.dumps({"path": "relative.json", "mode": "read"})
    assert dispatch_inspector(request(), environment)["error"]["code"] == "native_context_denied"


def test_file_channel_stages_an_import_handle(tmp_path):
    environment = context(tmp_path)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    staged = tmp_path / "import.json"
    staged.write_text('{"format": "luminary-memory", "version": 1, "memories": []}', encoding="utf-8")
    environment["LUMINARY_INSPECTOR_FILE"] = json.dumps({"path": str(staged), "mode": "read"})
    result = dispatch_inspector(request(), environment)
    assert (result["status"], bool(result["data"]["file_handle"])) == ("ok", True)


def test_unknown_download_handle_is_denied(tmp_path):
    environment = context(tmp_path)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    environment["LUMINARY_INSPECTOR_DOWNLOAD"] = "guessed-handle"
    result = dispatch_inspector(request(), environment)
    assert result["data"] is None
    assert result["status"] in {"denied", "invalid_request", "unavailable"}


def test_unexpected_backend_failure_is_unavailable_without_secrets(tmp_path, monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("dsn=postgresql://owner:hunter2@host/db")

    monkeypatch.setattr("luminary_memory.api.MemoryClient", Broken)
    environment = context(tmp_path)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    result = dispatch_inspector(request(), environment)
    assert (result["status"], result["error"]["code"]) == ("unavailable", "backend_unavailable")
    assert "hunter2" not in json.dumps(result)


def test_sqlite_database_directory_is_created(tmp_path, monkeypatch):
    nested = tmp_path / "nested" / "store" / "memory.db"
    monkeypatch.setenv("LUMINARY_DB_PATH", str(nested))
    environment = context(tmp_path)
    environment["LUMINARY_DB_PATH"] = str(nested)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert nested.parent.is_dir()


def test_supplied_environment_does_not_override_storage_resolution(tmp_path, monkeypatch):
    """Documented current behaviour: only the process environment selects the store.

    ``Settings`` reads ``os.environ``, so a launcher-supplied mapping authorizes
    the native context but does not move the database. This test pins the
    behaviour that exists in this release rather than asserting it is correct.
    """
    process_store = tmp_path / "process.db"
    mapping_store = tmp_path / "mapping.db"
    monkeypatch.setenv("LUMINARY_DB_PATH", str(process_store))
    environment = context(tmp_path)
    environment["LUMINARY_DB_PATH"] = str(mapping_store)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert process_store.exists()
    assert not mapping_store.exists()
