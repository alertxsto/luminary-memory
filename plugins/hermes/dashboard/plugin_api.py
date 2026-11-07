"""Hermes mounts this module's router under /api/plugins/luminary-inspector.

The host's ordinary-plugin enablement and auth middleware remain authoritative.
A plain def handler uses Starlette's context-preserving worker, not the gateway
loop; each operation opens and closes its own engine client in that worker.
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()
_ALLOWED = {"operation", "session_ref", "selection_handle", "arguments", "request_id"}
_FORBIDDEN = {"confirmed", "user_id", "workspace", "workspace_id", "agent_id", "profile_id", "host_id", "db_path", "store", "store_id", "pg_dsn"}


def _admit(request: Request) -> None:
    from hermes_cli.plugin_host_http_auth import admitted_for_sensitive_route

    if not admitted_for_sensitive_route(request):
        raise HTTPException(status_code=401, detail="Authenticated native owner required")


def _run(body: dict, *, initialize: bool = False, preview_id: str | None = None) -> dict:
    try:
        from luminary_memory.hermes.inspector import execute_native

        return execute_native(body, initialize=initialize, preview_id=preview_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Native owner/session/workspace binding is unavailable") from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid inspector request") from None
    except (ImportError, OSError, RuntimeError):
        raise HTTPException(status_code=503, detail="Inspector backend unavailable; check profile installation and restart Hermes") from None


def _validate(body: dict) -> None:
    if set(body) - _ALLOWED or not isinstance(body.get("arguments", {}), dict):
        raise HTTPException(status_code=400, detail="Only inspector request selectors are accepted")
    if _FORBIDDEN.intersection(body.get("arguments", {})):
        raise HTTPException(status_code=400, detail="Frontend identity and confirmation are not authority")
    if body.get("operation") in {"mutate", "maintenance_commit", "transfer_commit", "grant", "revoke", "set_settings"}:
        raise HTTPException(status_code=400, detail="Use the separately confirmed native operation")
    if body.get("operation") == "explain" and body.get("arguments", {}).get("phase") != "preview":
        raise HTTPException(status_code=400, detail="AI disclosure requires a preview and separate native confirmation")


@router.post("/open")
def open_inspector(body: dict, request: Request):
    _admit(request)
    _validate(body)
    if body.get("operation") != "browse":
        raise HTTPException(status_code=400, detail="Opening the inspector starts with a read")
    return _run(body, initialize=True)


@router.post("/console")
def console(body: dict, request: Request):
    _admit(request)
    _validate(body)
    return _run(body)


@router.post("/confirm")
def confirm(body: dict, request: Request):
    """Native renderer calls only after displaying the exact preview to its owner."""
    _admit(request)
    if set(body) - {"preview_id", "session_ref", "request_id", "commit_operation"}:
        raise HTTPException(status_code=400, detail="Only the selected opaque preview is accepted")
    preview_id = body.get("preview_id")
    if not isinstance(preview_id, str) or not preview_id or len(preview_id) > 512:
        raise HTTPException(status_code=400, detail="A native preview is required")
    return _run(body, preview_id=preview_id)


@router.get("/sessions")
def sessions(request: Request):
    """Selectable native sessions, not user/store/profile authority."""
    _admit(request)
    from hermes_state import SessionDB
    db = SessionDB(read_only=True)
    try:
        rows = db.list_sessions_rich(limit=100)
        return {"items": [{"id": row["id"], "title": row.get("title") or row["id"]}
                          for row in rows if row.get("cwd")]}
    finally:
        db.close()


_MAX_UPLOAD = 4 * 1024 * 1024


def _transfer(session_ref: str, action: str, data=None):
    """Resolve native owner before any durable file registration or read."""
    try:
        from luminary_memory.hermes.inspector import _service
        from luminary_memory.inspector.transfer import read_export, register_export, register_upload

        with _service(session_ref) as (service, context):
            directory = Path(context.profile_id) / "luminary" / "inspector-transfers"
            if action == "upload":
                return {"file_handle": register_upload(service, context, data, staging_directory=directory)}
            if action == "export":
                return {"file_handle": register_export(service, context, staging_directory=directory)}
            return read_export(service, context, data)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Native transfer scope or ready export is unavailable") from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid native transfer") from None
    except (ImportError, OSError, RuntimeError):
        raise HTTPException(status_code=503, detail="Native transfer backend is unavailable") from None


@router.post("/upload")
async def upload(request: Request, session_ref: str):
    _admit(request)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        # Desktop ctx.rest(upload) uses one multipart field named "file".
        # Bound the ENTIRE stream as well as the file so chunked requests cannot
        # bypass the size check or fill the spool with arbitrary multipart data.
        from starlette.formparsers import MultiPartException, MultiPartParser

        async def bounded_stream():
            total = 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > _MAX_UPLOAD + 8192:
                    raise MultiPartException("Upload exceeds the native limit")
                yield chunk

        try:
            form = await MultiPartParser(request.headers, bounded_stream(), max_files=1, max_fields=0).parse()
        except MultiPartException:
            raise HTTPException(status_code=413, detail="One file up to 4 MiB is accepted") from None
        try:
            file = form.get("file")
            if len(form) != 1 or not hasattr(file, "read"):
                raise HTTPException(status_code=400, detail="One file field is required")
            data = await file.read(_MAX_UPLOAD + 1)
        finally:
            await form.close()
    else:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > _MAX_UPLOAD:
                raise HTTPException(status_code=413, detail="Maximum upload is 4 MiB")
        data = bytes(data)
    if not data or len(data) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Choose a nonempty file up to 4 MiB")
    return await asyncio.to_thread(_transfer, session_ref, "upload", data)


@router.post("/export-handle")
def export_handle(body: dict, request: Request):
    _admit(request)
    if set(body) != {"session_ref"}:
        raise HTTPException(status_code=400, detail="Only the native session selector is accepted")
    return _transfer(body["session_ref"], "export")


@router.get("/download/{handle}")
def download(handle: str, request: Request, session_ref: str, encoding: str = "binary"):
    _admit(request)
    if encoding not in {"binary", "base64"}:
        raise HTTPException(status_code=400, detail="Unknown download encoding")
    data, filename = _transfer(session_ref, "download", handle)
    if encoding == "base64":
        # Desktop ctx.rest is JSON-only. No stored server path is exposed.
        return {"bytes_base64": base64.b64encode(data).decode("ascii"), "filename": filename}
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="luminary-export.json"',
                             "Cache-Control": "no-store"})
