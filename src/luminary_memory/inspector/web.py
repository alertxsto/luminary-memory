"""Explicitly launched loopback companion. Importing never starts a server."""
from __future__ import annotations

import hashlib
import hmac
import importlib.resources
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from luminary_memory.integrations.inspector_cli import native_context

MAX_UPLOAD = 4 * 1024 * 1024
MUTATIONS = {"mutate", "maintenance_commit", "set_settings", "transfer_commit", "grant", "revoke"}


class CompanionServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, native, host, port, session_lifetime):
        environment = {**os.environ, "LUMINARY_INSPECTOR_CONTEXT": json.dumps(native)}
        native_context(environment)  # verify native location before binding; never open a guessed DB
        self.native = dict(native)
        self.environment = os.environ.copy()
        for key in ("LUMINARY_INSPECTOR_CONFIRM", "LUMINARY_INSPECTOR_FILE", "LUMINARY_INSPECTOR_DOWNLOAD"):
            self.environment.pop(key, None)
        self.bootstrap_token = secrets.token_urlsafe(32)
        self.bootstrap_expires = time.monotonic() + 60
        self.session_lifetime = session_lifetime
        self.sessions = {}
        self.auth_lock = threading.Lock()
        self.files = tempfile.TemporaryDirectory(prefix="luminary-inspector-transfer-")
        super().__init__((host, port), CompanionHandler)
        self.origin = f"http://127.0.0.1:{self.server_address[1]}"
        self.bootstrap_url = self.origin + "/#token=" + self.bootstrap_token

    def server_close(self):
        super().server_close()
        self.files.cleanup()
        self.sessions.clear()

    def call(self, request, **channel):
        if not isinstance(request, dict):
            raise TypeError("request must be an object")
        environment = {**self.environment, "LUMINARY_INSPECTOR_CONTEXT": json.dumps(self.native),
                       "LUMINARY_INSPECTOR_OPEN": "1", **channel}
        try:
            result = subprocess.run([sys.executable, "-m", "luminary_memory.integrations", "inspector"],
                                    input=json.dumps(request).encode(), capture_output=True, check=False,
                                    env=environment, cwd=self.native["workspace"], timeout=60)
            if result.returncode != 0 or len(result.stdout) > 192 * 1024:
                raise ValueError("invalid process response")
            payload = json.loads(result.stdout)
            if payload.get("request_id") != request.get("request_id"):
                raise ValueError("mismatched request")
            return payload
        except (subprocess.SubprocessError, OSError, ValueError):
            status = "unknown_outcome" if request.get("operation") in MUTATIONS else "unavailable"
            return {"status": status, "data": None, "error": {"code": status,
                    "message": "Inspector process did not complete; inspect activity before retrying a change."},
                    "request_id": request.get("request_id", ""), "context_epoch": "", "policy_revision": 0,
                    "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


class CompanionHandler(BaseHTTPRequestHandler):
    server: CompanionServer
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # request URLs/headers may carry sensitive owner context; no access-log telemetry

    def send(self, status, data, content_type="application/json", cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if status >= 400:
            self.close_connection = True
            self.send_header("Connection", "close")
        if content_type == "application/octet-stream":
            self.send_header("Content-Disposition", 'attachment; filename="luminary-memories.json"')
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            self.send(403, {"error": "unexpected host"})
            return False
        return True

    def body(self, maximum):
        length = self.headers.get("Content-Length")
        if (self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1
                or not length or not length.isdecimal() or int(length) > maximum):
            raise ValueError("invalid content length")
        data = self.rfile.read(int(length))
        if len(data) != int(length):
            raise ValueError("incomplete body")
        return data

    def json_object(self, maximum):
        value = json.loads(self.body(maximum))
        if not isinstance(value, dict):
            raise TypeError("request must be an object")
        return value

    def authenticated(self, *, csrf=True):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        entry = cookies.get("luminary_inspector")
        token = entry.value if entry else ""
        with self.server.auth_lock:
            session = self.server.sessions.get(token)
            if not session or session["expires"] <= time.monotonic():
                return None
            if csrf and not hmac.compare_digest(self.headers.get("X-Luminary-CSRF", ""), session["csrf"]):
                return None
            return session

    def do_GET(self):
        if not self.host_ok():
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/download/"):
            if not self.authenticated():
                self.send(401, {"error": "authentication required"})
                return
            handle = path.removeprefix("/api/download/")
            request = {"operation": "browse", "arguments": {}, "request_id": uuid.uuid4().hex}
            response = self.server.call(request, LUMINARY_INSPECTOR_DOWNLOAD=handle)
            if response["status"] != "ok":
                self.send(403, {"error": "download unavailable or revoked"})
                return
            selected = Path(response["data"]["path"])
            try:
                if selected.parent.resolve() != Path(self.server.files.name).resolve():
                    raise PermissionError("file not staged by this companion")
                content = selected.read_bytes()
                if len(content) > MAX_UPLOAD or hashlib.sha256(content).hexdigest() != response["data"]["digest"]:
                    raise PermissionError("export changed")
                self.send(200, content, "application/octet-stream")
            except (OSError, PermissionError):
                self.send(403, {"error": "download unavailable"})
            return
        names = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        resource = names.get(path)
        if resource is None:
            self.send(404, {"error": "not found"})
            return
        try:
            data = importlib.resources.files("luminary_memory.inspector").joinpath("assets", "browser", resource[0]).read_bytes()
            self.send(200, data, resource[1])
        except (OSError, FileNotFoundError):
            self.send(503, {"error": "Packaged companion assets are unavailable; rebuild/install the complete artifact."})

    def do_POST(self):
        if not self.host_ok():
            return
        if self.headers.get("Origin") != self.server.origin:
            self.send(403, {"error": "same-origin request required"})
            return
        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/api/bootstrap":
                supplied = self.json_object(8192).get("token")
                with self.server.auth_lock:
                    if (not isinstance(supplied, str) or time.monotonic() > self.server.bootstrap_expires
                            or not self.server.bootstrap_token or not hmac.compare_digest(supplied, self.server.bootstrap_token)):
                        self.send(401, {"error": "one-use sign-in expired; launch the companion again"})
                        return
                    self.server.bootstrap_token = ""
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    self.server.sessions[token] = {"csrf": csrf, "expires": time.monotonic() + self.server.session_lifetime}
                self.send(200, {"csrf_token": csrf}, cookie=f"luminary_inspector={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={self.server.session_lifetime}")
                return
            if not self.authenticated():
                self.send(401, {"error": "authentication required"})
                return
            if parsed.path == "/api/file":
                mode = parse_qs(parsed.query).get("mode", [""])[0]
                selected = Path(self.server.files.name) / (secrets.token_hex(16) + ".json")
                if mode == "read":
                    selected.write_bytes(self.body(MAX_UPLOAD))
                elif mode == "write":
                    self.body(1)
                else:
                    raise ValueError("invalid file mode")
                request = {"operation": "browse", "arguments": {}, "request_id": uuid.uuid4().hex}
                result = self.server.call(request, LUMINARY_INSPECTOR_FILE=json.dumps({"path": str(selected), "mode": mode}))
            elif parsed.path == "/api/confirm":
                data = self.json_object(8192)
                if not isinstance(data.get("preview_id"), str):
                    raise ValueError("preview required")
                request = {"operation": "preview_change", "arguments": {}, "request_id": uuid.uuid4().hex}
                result = self.server.call(request, LUMINARY_INSPECTOR_CONFIRM=data["preview_id"])
            elif parsed.path == "/api/request":
                result = self.server.call(self.json_object(128 * 1024))
            elif parsed.path == "/api/sign-out":
                with self.server.auth_lock:
                    self.server.sessions.clear()
                self.send(200, {"status": "signed_out"}, cookie="luminary_inspector=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                return
            else:
                self.send(404, {"error": "not found"})
                return
            self.send(200, result)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            self.send(400, {"error": "invalid request"})


def create_server(native, *, host="127.0.0.1", port=0, session_lifetime=900):
    if host != "127.0.0.1":
        raise ValueError("the companion is loopback-only; public hosting is not supported")
    if type(session_lifetime) is not int or not 1 <= session_lifetime <= 3600:
        raise ValueError("session lifetime must be 1–3600 seconds")
    return CompanionServer(native, host, port, session_lifetime)
