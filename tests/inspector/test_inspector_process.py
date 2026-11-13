"""Inspector process boundary: trusted launcher context, no frontend authority.

Every case is hermetic: the process environment points at ``tmp_path`` and the
operator config file is disabled, so a failing assertion can never open the
real store.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor

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


def test_supplied_environment_selects_its_own_store(tmp_path, monkeypatch):
    process_store = tmp_path / "process.db"
    mapping_store = tmp_path / "mapping.db"
    monkeypatch.setenv("LUMINARY_DB_PATH", str(process_store))
    environment = context(tmp_path)
    environment["LUMINARY_DB_PATH"] = str(mapping_store)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert mapping_store.exists()
    assert not process_store.exists()
    assert os.environ["LUMINARY_DB_PATH"] == str(process_store)


def test_supplied_config_file_selects_store_without_mutating_process(tmp_path, monkeypatch):
    process_store = tmp_path / "process.db"
    mapping_store = tmp_path / "mapping.db"
    config = tmp_path / "launcher.env"
    config.write_text(f"LUMINARY_DB_PATH={mapping_store}\n", encoding="utf-8")
    monkeypatch.setenv("LUMINARY_DB_PATH", str(process_store))
    environment = context(tmp_path)
    del environment["LUMINARY_DB_PATH"]
    environment["LUMINARY_CONFIG_FILE"] = str(config)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert mapping_store.exists()
    assert not process_store.exists()
    assert os.environ["LUMINARY_CONFIG_FILE"] == "none"
    assert os.environ["LUMINARY_DB_PATH"] == str(process_store)


@pytest.mark.parametrize("kind", ["missing", "oversized"])
def test_unavailable_selected_config_does_not_open_default_store(tmp_path, monkeypatch, kind):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    config = tmp_path / "unavailable.env"
    if kind == "oversized":
        config.write_text("#" * (256 * 1024 + 1), encoding="utf-8")
    environment = context(tmp_path)
    del environment["LUMINARY_DB_PATH"]
    environment["LUMINARY_CONFIG_FILE"] = str(config)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "unavailable"
    assert not (home / ".luminary" / "memory.db").exists()


@pytest.mark.parametrize("backend", ["sqlite", " SQLite "])
def test_tilde_database_path_resolves_to_owner_home(tmp_path, monkeypatch, backend):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(tmp_path)
    literal_store = tmp_path / "~" / ".luminary" / "memory.db"
    literal_store.parent.mkdir(parents=True)
    environment = context(tmp_path)
    environment["LUMINARY_DB_PATH"] = "~/.luminary/memory.db"
    environment["LUMINARY_BACKEND"] = backend
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert (home / ".luminary" / "memory.db").exists()
    assert not literal_store.exists()


def test_config_cannot_supply_the_native_launcher_context(tmp_path):
    native = context(tmp_path)["LUMINARY_INSPECTOR_CONTEXT"]
    config = tmp_path / "launcher.env"
    config.write_text(
        f"LUMINARY_INSPECTOR_CONTEXT={native}\nLUMINARY_INSPECTOR_OPEN=1\n",
        encoding="utf-8",
    )
    store = tmp_path / "inspector.db"
    environment = {
        "LUMINARY_CONFIG_FILE": str(config),
        "LUMINARY_DB_PATH": str(store),
        "LUMINARY_USER_ID": "owner",
    }
    assert dispatch_inspector(request(), environment)["status"] == "denied"
    assert not store.exists()


def test_config_cannot_initialize_an_unopened_native_binding(tmp_path):
    config = tmp_path / "launcher.env"
    config.write_text("LUMINARY_INSPECTOR_OPEN=1\n", encoding="utf-8")
    environment = context(tmp_path)
    environment["LUMINARY_CONFIG_FILE"] = str(config)
    assert dispatch_inspector(request(), environment)["status"] == "denied"


def test_missing_mapping_store_uses_default_not_process_store(tmp_path, monkeypatch):
    # Path.home() reads USERPROFILE on Windows and HOME elsewhere; setting only
    # HOME would resolve to the operator's real home and open their store.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    process_store = tmp_path / "process.db"
    monkeypatch.setenv("LUMINARY_DB_PATH", str(process_store))
    environment = context(tmp_path)
    del environment["LUMINARY_DB_PATH"]
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert (tmp_path / ".luminary" / "memory.db").exists()
    assert not process_store.exists()


def test_different_launcher_home_does_not_open_process_default_store(tmp_path, monkeypatch):
    home_variable = "USERPROFILE" if os.name == "nt" else "HOME"
    process_home = tmp_path / "process-home"
    launcher_home = tmp_path / "launcher-home"
    process_home.mkdir()
    launcher_home.mkdir()
    monkeypatch.setenv(home_variable, str(process_home))
    environment = context(tmp_path)
    environment[home_variable] = str(launcher_home)
    del environment["LUMINARY_DB_PATH"]
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "denied"
    assert not (process_home / ".luminary" / "memory.db").exists()
    assert not (launcher_home / ".luminary" / "memory.db").exists()


def test_inherited_environment_loads_config_without_global_mutation(tmp_path, monkeypatch):
    store = tmp_path / "configured.db"
    config = tmp_path / "process.env"
    config.write_text(f"LUMINARY_DB_PATH={store}\n", encoding="utf-8")
    monkeypatch.delenv("LUMINARY_DB_PATH")
    monkeypatch.setenv("LUMINARY_CONFIG_FILE", str(config))
    for key, value in context(tmp_path).items():
        if key not in {"LUMINARY_DB_PATH", "LUMINARY_CONFIG_FILE"}:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("LUMINARY_INSPECTOR_OPEN", "1")
    assert dispatch_inspector(request())["status"] == "empty"
    assert store.exists()
    assert "LUMINARY_DB_PATH" not in os.environ


def test_supplied_backend_cannot_fall_back_to_process_sqlite(tmp_path, monkeypatch):
    process_store = tmp_path / "process.db"
    monkeypatch.setenv("LUMINARY_BACKEND", "sqlite")
    monkeypatch.setenv("LUMINARY_DB_PATH", str(process_store))
    environment = context(tmp_path)
    environment.update(
        LUMINARY_BACKEND="pgvector",
        LUMINARY_PG_DSN="not a valid connection string",
        LUMINARY_INSPECTOR_OPEN="1",
    )
    assert dispatch_inspector(request(), environment)["status"] == "unavailable"
    assert not process_store.exists()
    assert not (tmp_path / "inspector.db").exists()


def test_mapping_ignores_process_config_file(tmp_path, monkeypatch):
    process_store = tmp_path / "from-process-config.db"
    mapping_store = tmp_path / "mapping.db"
    config = tmp_path / "process.env"
    config.write_text(f"LUMINARY_DB_PATH={process_store}\n", encoding="utf-8")
    monkeypatch.setenv("LUMINARY_CONFIG_FILE", str(config))
    monkeypatch.delenv("LUMINARY_DB_PATH")
    environment = context(tmp_path)
    environment["LUMINARY_DB_PATH"] = str(mapping_store)
    environment["LUMINARY_INSPECTOR_OPEN"] = "1"
    assert dispatch_inspector(request(), environment)["status"] == "empty"
    assert mapping_store.exists()
    assert not process_store.exists()
    assert "LUMINARY_DB_PATH" not in os.environ


def test_concurrent_mappings_keep_stores_separate(tmp_path):
    environments = []
    for name in ("first", "second"):
        environment = context(tmp_path)
        environment["LUMINARY_DB_PATH"] = str(tmp_path / f"{name}.db")
        environment["LUMINARY_INSPECTOR_OPEN"] = "1"
        environments.append(environment)
    original = dict(os.environ)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda env: dispatch_inspector(request(), env), environments))
    assert [result["status"] for result in results] == ["empty", "empty"]
    assert results[0]["data"]["native_context"]["store_id"] != results[1]["data"]["native_context"]["store_id"]
    assert all((tmp_path / f"{name}.db").exists() for name in ("first", "second"))
    assert dict(os.environ) == original
