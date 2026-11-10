"""Dedicated inspector process boundary; frontend input never supplies authority."""
from __future__ import annotations

import contextlib
import getpass
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from luminary_memory.integrations import MAX_REQUEST_BYTES

MAX_RESPONSE_BYTES = 192 * 1024


def _failure(status: str, code: str, request_id: str = "") -> dict:
    return {
        "status": status, "data": None,
        "error": {"code": code, "message": {
            "denied": "Verified native context is required for this operation.",
            "invalid_request": "The inspector request is invalid.",
            "unavailable": "Inspector unavailable; check the configured runtime and backend.",
        }.get(status, "Inspector operation did not complete.")},
        "request_id": request_id, "context_epoch": "", "policy_revision": 0,
        "as_of": datetime.now(UTC).isoformat(),
    }


def native_context(environment: Mapping[str, str]) -> dict:
    """Read only the separate trusted launcher channel, before opening storage."""
    raw = environment.get("LUMINARY_INSPECTOR_CONTEXT", "")
    if not raw or len(raw.encode("utf-8")) > 8192:
        raise PermissionError("native context missing")
    native = json.loads(raw)
    if not isinstance(native, dict):
        raise PermissionError("native context invalid")
    required = ("agent_id", "workspace", "session_id", "host_id", "profile_id")
    if any(not isinstance(native.get(key), str) or not native[key].strip() for key in required):
        raise PermissionError("native context incomplete")
    workspace = Path(native["workspace"]).expanduser()
    if not workspace.is_absolute() or not workspace.is_dir():
        raise PermissionError("native location unavailable")
    # Only the owner account/server configuration may bind this native launch.
    owner = environment.get("LUMINARY_USER_ID") or getpass.getuser()
    if "user_id" in native and native["user_id"] != owner:
        raise PermissionError("native owner mismatch")
    return {**native, "workspace": os.path.normcase(str(workspace.resolve())), "user_id": owner}


def run_inspector(context, request, *, client=None, confirmation: str | None = None):
    """Embedded path: authority was already resolved by the trusted native host."""
    from luminary_memory.inspector.service import InspectorService

    if client is None:
        raise ValueError("an explicitly configured scoped client is required")
    service = InspectorService(client)
    if confirmation:
        receipt = service.confirm(context, confirmation)
        return service.result(context, request, data={
            "preview_id": confirmation, "confirmation_receipt": receipt,
        })
    return service.execute(context, request)


def dispatch_inspector(raw: bytes, environment: Mapping[str, str] | None = None) -> dict:
    launcher_environment = dict(os.environ if environment is None else environment)
    environment = launcher_environment.copy()
    request_id = ""
    client = None
    try:
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise TypeError("request must be an object")
        if isinstance(data.get("request_id"), str):
            request_id = data["request_id"][:128]
        home_keys = ("USERPROFILE", "HOMEDRIVE", "HOMEPATH") if os.name == "nt" else ("HOME",)
        if any(key in launcher_environment and launcher_environment[key] != os.environ.get(key)
               for key in home_keys):
            raise PermissionError("launcher home differs from process home")
        from luminary_memory.config import load_config_file

        load_config_file(environment=environment, fail_on_error=True)
        native = native_context(environment)
        from luminary_memory.api import MemoryClient
        from luminary_memory.config import Settings
        from luminary_memory.inspector.contracts import ConsoleRequest
        from luminary_memory.inspector.identity import resolve_context
        from luminary_memory.inspector.service import InspectorService

        request = ConsoleRequest.from_dict(data)
        settings = Settings.from_environment(environment, scope_include_global=False)
        if not environment.get("LUMINARY_DB_PATH"):
            settings.db_path = str(Path.home() / ".luminary" / "memory.db")
        if (settings.backend or "sqlite").strip().lower() == "sqlite":
            settings.db_path = str(Path(settings.db_path).expanduser())
            Path(settings.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        client = MemoryClient(settings=settings, scope={
            "user_id": native["user_id"], "workspace_id": native["workspace"],
            "agent_id": native["agent_id"],
        })
        context = resolve_context(
            client, native, initialize=environment.get("LUMINARY_INSPECTOR_OPEN") == "1",
        )
        service = InspectorService(client)
        confirmation = environment.get("LUMINARY_INSPECTOR_CONFIRM")
        if confirmation:
            receipt = service.confirm(context, confirmation)
            result = service.result(context, request, data={
                "preview_id": confirmation, "confirmation_receipt": receipt,
            })
        elif environment.get("LUMINARY_INSPECTOR_FILE"):
            from luminary_memory.inspector.transfer import register_file

            descriptor = json.loads(environment["LUMINARY_INSPECTOR_FILE"])
            if not isinstance(descriptor, dict) or set(descriptor) != {"path", "mode"}:
                raise ValueError("invalid native file selection")
            handle = register_file(service, context, descriptor["path"], descriptor["mode"])
            result = service.result(context, request, data={"file_handle": handle})
        elif environment.get("LUMINARY_INSPECTOR_DOWNLOAD"):
            import hashlib

            from luminary_memory.inspector.transfer import _file, read_export

            handle = environment["LUMINARY_INSPECTOR_DOWNLOAD"]
            contents, filename = read_export(service, context, handle)
            result = service.result(context, request, data={
                "path": str(_file(service, context, handle, "write")),
                "filename": filename, "digest": hashlib.sha256(contents).hexdigest(),
            })
        else:
            result = service.execute(context, request)
        response = result.to_dict() if hasattr(result, "to_dict") else result
        if not isinstance(response, dict):
            raise TypeError("invalid inspector response")
        if len(json.dumps(response, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            return _failure("unavailable", "response_budget_exceeded", request_id)
        return response
    except PermissionError:
        return _failure("denied", "native_context_denied", request_id)
    except (ValueError, TypeError, UnicodeDecodeError):
        return _failure("invalid_request", "invalid_request", request_id)
    except Exception as exc:  # noqa: BLE001 -- process boundary must not expose backend secrets
        print(f"Inspector failed: {type(exc).__name__}", file=sys.stderr)
        return _failure("unavailable", "backend_unavailable", request_id)
    finally:
        if client is not None:
            client.close()


def inspector_main() -> None:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    with contextlib.redirect_stdout(sys.stderr):
        result = dispatch_inspector(raw)
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
