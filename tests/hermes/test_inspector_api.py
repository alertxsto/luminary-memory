"""The ordinary plugin admits owners, never frontend identity or model confirmations."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _plugin():
    path = Path(__file__).parents[2] / "plugins" / "hermes" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("luminary_hermes_dashboard_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unadmitted_request_does_not_reach_memory(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    admission = types.ModuleType("hermes_cli.plugin_host_http_auth")
    admission.admitted_for_sensitive_route = lambda request: False
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_host_http_auth", admission)
    app = fastapi.FastAPI()
    app.include_router(_plugin().router)
    response = TestClient(app).post("/console", json={"operation": "browse", "session_ref": "s1", "arguments": {}, "request_id": "r1"})
    assert response.status_code == 401


def test_frontend_authority_is_refused_before_any_store_open(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    admission = types.ModuleType("hermes_cli.plugin_host_http_auth")
    admission.admitted_for_sensitive_route = lambda request: True
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_host_http_auth", admission)
    app = fastapi.FastAPI()
    app.include_router(_plugin().router)
    response = TestClient(app).post("/console", json={"operation": "browse", "session_ref": "s1", "arguments": {}, "request_id": "r1", "user_id": "someone-else", "db_path": "foreign.db"})
    assert response.status_code == 400


def test_json_confirmation_does_not_authorize_a_write(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    admission = types.ModuleType("hermes_cli.plugin_host_http_auth")
    admission.admitted_for_sensitive_route = lambda request: True
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_host_http_auth", admission)
    app = fastapi.FastAPI()
    app.include_router(_plugin().router)
    response = TestClient(app).post("/console", json={"operation": "mutate", "session_ref": "s1", "arguments": {"confirmed": True}, "request_id": "r1"})
    assert response.status_code == 400


@pytest.mark.parametrize("operation,arguments", [
    ("set_settings", {"confirmation_receipt": "not-native"}),
    ("explain", {"phase": "commit", "confirmation_receipt": "not-native"}),
])
def test_confirmed_operations_cannot_use_general_console(monkeypatch, operation, arguments):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    admission = types.ModuleType("hermes_cli.plugin_host_http_auth")
    admission.admitted_for_sensitive_route = lambda request: True
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_host_http_auth", admission)
    app = fastapi.FastAPI()
    app.include_router(_plugin().router)
    response = TestClient(app).post("/console", json={
        "operation": operation, "session_ref": "s1", "arguments": arguments, "request_id": "r1"})
    assert response.status_code == 400


def test_upload_limit_is_enforced_before_store_or_file_registration(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    admission = types.ModuleType("hermes_cli.plugin_host_http_auth")
    admission.admitted_for_sensitive_route = lambda request: True
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_host_http_auth", admission)
    app = fastapi.FastAPI()
    app.include_router(_plugin().router)
    response = TestClient(app).post("/upload?session_ref=s1",
                                   content=b"x" * (4 * 1024 * 1024 + 1),
                                   headers={"content-type": "application/octet-stream"})
    assert response.status_code == 413
