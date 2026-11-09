"""Companion HTTP transport: host/origin, session, file and process-failure boundaries."""
import http.client
import json
import subprocess
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest


@pytest.fixture
def companion(tmp_path, monkeypatch):
    from luminary_memory.inspector.web import create_server
    monkeypatch.setenv("LUMINARY_DB_PATH", str(tmp_path / "browser.db"))
    monkeypatch.setenv("LUMINARY_USER_ID", "web-owner")
    server = create_server({"agent_id": "pi", "workspace": str(tmp_path.resolve()), "session_id": "web-session",
                            "host_id": "web-host", "profile_id": "default"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


def sign_in(server):
    request = urllib.request.Request(server.origin + "/api/bootstrap",
                                     data=json.dumps({"token": server.bootstrap_token}).encode(),
                                     headers={"Content-Type": "application/json", "Origin": server.origin})
    response = urllib.request.urlopen(request)
    credentials = {"Cookie": response.headers["Set-Cookie"].split(";", 1)[0]}
    credentials["X-Luminary-CSRF"] = json.loads(response.read())["csrf_token"]
    return credentials


def test_foreign_host_header_is_refused_before_any_work(companion):
    parts = urlsplit(companion.origin)
    connection = http.client.HTTPConnection(parts.hostname, parts.port)
    connection.request("GET", "/", headers={"Host": "attacker.invalid"})
    response = connection.getresponse()
    assert response.status == 403
    assert json.loads(response.read())["error"] == "unexpected host"
    connection.close()


def test_packaged_assets_and_unknown_paths(companion):
    for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
        response = urllib.request.urlopen(companion.origin + path)
        assert response.status == 200
        assert response.headers["Content-Type"].startswith(content_type)
        assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
        assert response.headers["Cache-Control"] == "no-store"
        assert response.read()
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(companion.origin + "/missing.json")
    assert failure.value.code == 404


def test_browse_requires_a_matching_csrf_token_and_sign_out_revokes(companion):
    credentials = sign_in(companion)
    body = json.dumps({"operation": "browse", "arguments": {}, "request_id": "r1"}).encode()
    forged = dict(credentials, **{"X-Luminary-CSRF": "not-the-issued-token"})
    request = urllib.request.Request(companion.origin + "/api/request", data=body,
                                     headers={"Content-Type": "application/json",
                                              "Origin": companion.origin, **forged})
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 401

    request = urllib.request.Request(companion.origin + "/api/request", data=body,
                                     headers={"Content-Type": "application/json",
                                              "Origin": companion.origin, **credentials})
    result = json.loads(urllib.request.urlopen(request).read())
    assert result["status"] == "empty"
    assert result["data"]["items"] == []

    request = urllib.request.Request(companion.origin + "/api/sign-out", data=b"",
                                     headers={"Origin": companion.origin, **credentials})
    response = urllib.request.urlopen(request)
    assert json.loads(response.read())["status"] == "signed_out"
    assert "Max-Age=0" in response.headers["Set-Cookie"]

    request = urllib.request.Request(companion.origin + "/api/request", data=body,
                                     headers={"Content-Type": "application/json",
                                              "Origin": companion.origin, **credentials})
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 401


def test_file_and_confirmation_endpoints_reject_invalid_input(companion):
    credentials = sign_in(companion)
    headers = {"Origin": companion.origin, **credentials}

    request = urllib.request.Request(companion.origin + "/api/file?mode=append", data=b"{}", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 400

    request = urllib.request.Request(companion.origin + "/api/confirm", data=json.dumps({}).encode(),
                                     headers={"Content-Type": "application/json", **headers})
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 400

    request = urllib.request.Request(companion.origin + "/api/file?mode=read",
                                     data=json.dumps({"unused": True}).encode(), headers=headers)
    assert json.loads(urllib.request.urlopen(request).read())["data"]["file_handle"]


def test_download_requires_a_session_and_a_staged_handle(companion):
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(companion.origin + "/api/download/unknown")
    assert failure.value.code == 401

    credentials = sign_in(companion)
    request = urllib.request.Request(companion.origin + "/api/download/guessed-handle", headers=credentials)
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 403


def test_download_refuses_a_file_outside_the_companion_staging_directory(companion, tmp_path, monkeypatch):
    credentials = sign_in(companion)
    outside = tmp_path / "private.json"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(companion, "call", lambda request, **channel: {
        "status": "ok", "data": {"path": str(outside), "digest": "0" * 64}, "request_id": request["request_id"],
        "context_epoch": "", "policy_revision": 0, "as_of": "2026-01-01T00:00:00Z"})
    request = urllib.request.Request(companion.origin + "/api/download/any-handle", headers=credentials)
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 403


def test_download_rejects_changed_content(companion, monkeypatch):
    from pathlib import Path

    credentials = sign_in(companion)
    staged = Path(companion.files.name) / "staged.json"
    staged.write_text('{"memories": []}', encoding="utf-8")
    monkeypatch.setattr(companion, "call", lambda request, **channel: {
        "status": "ok", "data": {"path": str(staged), "digest": "f" * 64}, "request_id": request["request_id"],
        "context_epoch": "", "policy_revision": 0, "as_of": "2026-01-01T00:00:00Z"})
    request = urllib.request.Request(companion.origin + "/api/download/any-handle", headers=credentials)
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 403


def test_stable_download_returns_verified_bytes(companion, monkeypatch):
    import hashlib
    from pathlib import Path

    credentials = sign_in(companion)
    payload = b'{"memories": []}'
    staged = Path(companion.files.name) / "staged.json"
    staged.write_bytes(payload)
    monkeypatch.setattr(companion, "call", lambda request, **channel: {
        "status": "ok", "data": {"path": str(staged), "digest": hashlib.sha256(payload).hexdigest()},
        "request_id": request["request_id"], "context_epoch": "", "policy_revision": 0,
        "as_of": "2026-01-01T00:00:00Z"})
    request = urllib.request.Request(companion.origin + "/api/download/any-handle", headers=credentials)
    response = urllib.request.urlopen(request)
    assert response.read() == payload
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert "luminary-memories.json" in response.headers["Content-Disposition"]


@pytest.mark.parametrize("operation,status", [("browse", "unavailable"), ("mutate", "unknown_outcome")])
def test_process_failure_is_reported_as_an_explicit_outcome(companion, monkeypatch, operation, status):
    def fail(*args, **kwargs):
        raise subprocess.SubprocessError("boom")

    monkeypatch.setattr(subprocess, "run", fail)
    result = companion.call({"operation": operation, "arguments": {}, "request_id": "r1"})
    assert result["status"] == status
    assert result["data"] is None
    assert result["request_id"] == "r1"


def test_process_response_must_match_the_request_and_stay_bounded(companion, monkeypatch):
    class Result:
        returncode = 0

        def __init__(self, payload):
            self.stdout = payload

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result(json.dumps({"request_id": "other"}).encode()))
    assert companion.call({"operation": "browse", "arguments": {}, "request_id": "r1"})["status"] == "unavailable"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result(b"{}" * (100 * 1024)))
    assert companion.call({"operation": "browse", "arguments": {}, "request_id": "r1"})["status"] == "unavailable"


def test_request_requires_an_object(companion):
    with pytest.raises(TypeError):
        companion.call([])


@pytest.mark.parametrize("lifetime", [0, 3601, "900", 900.0, True])
def test_session_lifetime_is_bounded(tmp_path, lifetime):
    from luminary_memory.inspector.web import create_server
    with pytest.raises(ValueError):
        create_server({"workspace": str(tmp_path)}, session_lifetime=lifetime)


def test_bootstrap_after_its_window_is_refused(companion):
    companion.bootstrap_expires = 0
    request = urllib.request.Request(companion.origin + "/api/bootstrap",
                                     data=json.dumps({"token": companion.bootstrap_token}).encode(),
                                     headers={"Content-Type": "application/json", "Origin": companion.origin})
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 401


def test_body_limits_reject_chunked_and_mismatched_lengths(companion):
    credentials = sign_in(companion)
    parts = urlsplit(companion.origin)
    connection = http.client.HTTPConnection(parts.hostname, parts.port)
    connection.request("POST", "/api/request", body=b"{}", headers={
        "Host": parts.netloc, "Origin": companion.origin, "Content-Type": "application/json",
        "Transfer-Encoding": "chunked", **credentials}, encode_chunked=True)
    response = connection.getresponse()
    assert response.status == 400
    response.read()
    connection.close()
