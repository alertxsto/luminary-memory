"""Consumer-visible subprocess protocol, with real scoped storage."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def invoke(tmp_path: Path, request: dict, *, native: dict | None = None):
    env = os.environ.copy()
    env["LUMINARY_DB_PATH"] = str(tmp_path / "memory.db")
    env["LUMINARY_USER_ID"] = "transport-owner"
    env["LUMINARY_INSPECTOR_OPEN"] = "1"
    env["LUMINARY_INSPECTOR_CONTEXT"] = json.dumps(native or {
        "agent_id": "pi", "workspace": str(tmp_path.resolve()),
        "session_id": "native-session", "host_id": "test-host", "profile_id": "test-profile",
    })
    result = subprocess.run(
        [sys.executable, "-m", "luminary_memory.integrations", "inspector"],
        input=json.dumps(request), capture_output=True, text=True, check=False,
        env=env, cwd=tmp_path, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_inspector_subprocess_preserves_full_result_envelope(tmp_path):
    result = invoke(tmp_path, {"operation": "browse", "arguments": {}, "request_id": "browse-1"})
    assert result["status"] == "empty"
    assert result["data"]["items"] == []
    assert result["request_id"] == "browse-1"
    assert result["context_epoch"]
    assert isinstance(result["policy_revision"], int)
    assert result["as_of"]
    assert result["error"] is None


def test_frontend_identity_cannot_override_native_context(tmp_path):
    result = invoke(tmp_path, {
        "operation": "browse", "arguments": {"user_id": "victim", "workspace": "/foreign"},
        "request_id": "forged-1",
    })
    assert result["status"] in {"denied", "invalid_request"}
    assert "victim" not in json.dumps(result["data"])


def test_inspector_unknown_operation_is_a_domain_error(tmp_path):
    result = invoke(tmp_path, {"operation": "raw_sql", "arguments": {}, "request_id": "invalid-1"})
    assert result["status"] == "invalid_request"
    assert result["request_id"] == "invalid-1"
    assert result["error"]["code"]


def test_inspector_missing_native_context_fails_closed(tmp_path):
    env = os.environ.copy()
    env.pop("LUMINARY_INSPECTOR_CONTEXT", None)
    env["LUMINARY_DB_PATH"] = str(tmp_path / "must-not-open.db")
    result = subprocess.run(
        [sys.executable, "-m", "luminary_memory.integrations", "inspector"],
        input=json.dumps({"operation": "browse", "arguments": {}, "request_id": "missing"}),
        capture_output=True, text=True, env=env, timeout=30, check=False,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "denied"
    assert not (tmp_path / "must-not-open.db").exists()


def test_root_cli_does_not_accept_inspector_authority_from_config(tmp_path):
    native = {
        "agent_id": "pi", "workspace": str(tmp_path.resolve()), "session_id": "session",
        "host_id": "host", "profile_id": "default",
    }
    store = tmp_path / "must-not-open.db"
    config = tmp_path / "luminary.env"
    config.write_text(
        f"LUMINARY_INSPECTOR_CONTEXT={json.dumps(native)}\n"
        f"LUMINARY_INSPECTOR_OPEN=1\nLUMINARY_DB_PATH={store}\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("LUMINARY_INSPECTOR_CONTEXT", None)
    env.pop("LUMINARY_INSPECTOR_OPEN", None)
    env.pop("LUMINARY_DB_PATH", None)
    env["LUMINARY_CONFIG_FILE"] = str(config)
    env["LUMINARY_USER_ID"] = "owner"
    result = subprocess.run(
        [sys.executable, "-m", "luminary_memory.cli", "hook", "inspector"],
        input=json.dumps({"operation": "browse", "arguments": {}, "request_id": "config-authority"}),
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "denied"
    assert not store.exists()


def test_inspector_uses_operator_config_for_owner_and_store(tmp_path):
    from luminary_memory.backends.sqlite import SQLiteBackend
    from luminary_memory.types import Memory

    store = tmp_path / "configured.db"
    backend = SQLiteBackend(str(store))
    try:
        backend.add(Memory(content="Configured OpenCode store", user_id="file-owner",
                           workspace_id=os.path.normcase(str(tmp_path.resolve())), agent_id="opencode"))
    finally:
        backend.close()
    config = tmp_path / "luminary.env"
    config.write_text(f"LUMINARY_DB_PATH={store}\nLUMINARY_USER_ID=file-owner\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("LUMINARY_DB_PATH", None)
    env.pop("LUMINARY_USER_ID", None)
    env["LUMINARY_CONFIG_FILE"] = str(config)
    env["LUMINARY_INSPECTOR_OPEN"] = "1"
    env["LUMINARY_INSPECTOR_CONTEXT"] = json.dumps({
        "agent_id": "opencode", "workspace": str(tmp_path.resolve()), "session_id": "configured-session",
        "host_id": "configured-host", "profile_id": "configured-profile",
    })
    result = subprocess.run(
        [sys.executable, "-m", "luminary_memory.integrations", "inspector"],
        input=json.dumps({"operation": "browse", "arguments": {}, "request_id": "operator-config"}),
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30, check=False,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok", payload
    assert [row["content"] for row in payload["data"]["items"]] == ["Configured OpenCode store"]


def test_installed_wheel_controller_preserves_permissions_errors_and_revision_conflicts():
    """CI supplies a clean wheel environment; this must never use repo imports."""
    import pytest

    interpreter = os.environ.get("INSPECTOR_INSTALLED_PYTHON")
    if not interpreter:
        pytest.skip("requires a separately installed wheel via INSPECTOR_INSTALLED_PYTHON")
    node = shutil.which("node")
    if node is None:
        pytest.fail("configured installed-wheel gate requires Node 22 and npm ci")
    project = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(project / "scripts" / "test-installed-inspector.mjs"), interpreter],
        cwd=project, env=os.environ.copy(), capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
