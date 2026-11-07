"""Real loopback HTTP security boundary, no mocked browser authentication."""
import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def companion(tmp_path, monkeypatch):
    from luminary_memory.inspector.web import create_server
    monkeypatch.setenv("LUMINARY_DB_PATH", str(tmp_path / "browser.db"))
    monkeypatch.setenv("LUMINARY_USER_ID", "web-owner")
    server = create_server({"agent_id": "pi", "workspace": str(tmp_path.resolve()), "session_id": "web-session", "host_id": "web-host", "profile_id": "default"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_companion_unauthenticated_and_cross_origin_requests_are_denied(companion):
    root = f"http://127.0.0.1:{companion.server_address[1]}"
    request = urllib.request.Request(root + "/api/request", data=json.dumps({"operation": "browse", "arguments": {}, "request_id": "no-auth"}).encode(), headers={"Content-Type": "application/json", "Origin": root})
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 401
    request = urllib.request.Request(root + "/api/bootstrap", data=json.dumps({"token": companion.bootstrap_token}).encode(), headers={"Content-Type": "application/json", "Origin": "https://attacker.invalid"})
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 403


def test_companion_bootstrap_is_single_use_and_tokens_are_not_in_html(companion):
    root = f"http://127.0.0.1:{companion.server_address[1]}"
    html = urllib.request.urlopen(root + "/").read().decode()
    assert companion.bootstrap_token not in html
    request = urllib.request.Request(root + "/api/bootstrap", data=json.dumps({"token": companion.bootstrap_token}).encode(), headers={"Content-Type": "application/json", "Origin": root})
    response = urllib.request.urlopen(request)
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    session = json.loads(response.read())
    assert session["csrf_token"]
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 401


def test_companion_rejects_non_loopback_bind(tmp_path):
    from luminary_memory.inspector.web import create_server
    with pytest.raises(ValueError):
        create_server({"workspace": str(tmp_path)}, host="0.0.0.0")


@pytest.mark.parametrize("endpoint", ["/api/bootstrap", "/api/request", "/api/confirm"])
def test_non_object_json_is_bad_request_not_a_dropped_connection(companion, endpoint):
    root = companion.origin
    headers = {"Content-Type": "application/json", "Origin": root}
    if endpoint != "/api/bootstrap":
        response = urllib.request.urlopen(urllib.request.Request(
            root + "/api/bootstrap", data=json.dumps({"token": companion.bootstrap_token}).encode(),
            headers=headers,
        ))
        headers["Cookie"] = response.headers["Set-Cookie"].split(";", 1)[0]
        headers["X-Luminary-CSRF"] = json.loads(response.read())["csrf_token"]
    request = urllib.request.Request(root + endpoint, data=b"[]", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request)
    assert failure.value.code == 400
    assert urllib.request.urlopen(root + "/").status == 200
