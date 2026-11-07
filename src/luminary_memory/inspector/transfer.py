"""Native-selected files, digest-bound previews and scoped memory-record transfer."""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import tempfile
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

from luminary_memory.api import _content_hash, _snapshot
from luminary_memory.export import EXPORT_FORMAT, EXPORT_VERSION, _lineage_order, _mem_to_dict
from luminary_memory.inspector.contracts import ConsoleRequest
from luminary_memory.inspector.identity import digest, validate_context
from luminary_memory.inspector.mutations import Conflict
from luminary_memory.recall.graph import index_memory_entities
from luminary_memory.types import Memory

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 5000
COVERAGE = "Memory records and included lineage only; not episodes, full evidence, audit, grants or settings backup."


def register_file(service, context, path, mode):
    validate_context(service.client, context)
    if mode not in {"read", "write"} or not isinstance(path, (str, Path)):
        raise ValueError("invalid native file selection")
    selected = Path(path).expanduser()
    if not selected.is_absolute() or selected.is_symlink():
        raise PermissionError("select an absolute non-symlink file")
    parent = selected.parent.resolve(strict=True)
    selected = parent / selected.name
    if mode == "read" and (not selected.is_file() or selected.stat().st_size > MAX_FILE_BYTES):
        raise ValueError("import must be a regular file of at most 4 MiB")
    handle = secrets.token_urlsafe(32)
    service.client.backend.inspector_put("file:" + handle, {
        "path": str(selected), "mode": mode, "context": digest(context.to_dict()),
        "policy_revision": service.client.backend.inspector_get("store")["policy_revision"],
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    })
    return handle


def register_upload(service, context, data: bytes, *, staging_directory: Path):
    validate_context(service.client, context)
    if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
        raise ValueError("upload exceeds transfer budget")
    directory = Path(staging_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".json", delete=False) as handle:
        selected = Path(handle.name)
        handle.write(data)
    try:
        return register_file(service, context, selected, "read")
    except BaseException:
        selected.unlink(missing_ok=True)
        raise


def register_export(service, context, *, staging_directory: Path):
    validate_context(service.client, context)
    directory = Path(staging_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return register_file(service, context, directory / (secrets.token_hex(16) + ".json"), "write")


def read_export(service, context, handle):
    validate_context(service.client, context)
    path = _file(service, context, handle, "write")
    descriptor = service.client.backend.inspector_get("file:" + handle)
    if not descriptor.get("ready") or descriptor.get("digest") != _digest(path):
        raise PermissionError("no unchanged confirmed export is available")
    return _read(path), "luminary-memories.json"


def _file(service, context, handle, mode):
    if not isinstance(handle, str) or len(handle) > 200:
        raise PermissionError("native file handle required")
    descriptor = service.client.backend.inspector_get("file:" + handle)
    if (not descriptor or descriptor["mode"] != mode or descriptor["context"] != digest(context.to_dict())
            or descriptor["policy_revision"] != service.client.backend.inspector_get("store")["policy_revision"]
            or datetime.fromisoformat(descriptor["expires_at"]) <= datetime.now(UTC)):
        raise PermissionError("native file selection expired or was revoked")
    path = Path(descriptor["path"])
    if path.is_symlink() or str(path.parent.resolve(strict=True) / path.name) != descriptor["path"]:
        raise PermissionError("native file location changed")
    return path


def _read(path):
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("file exceeds transfer budget")
    return data


def _digest(path):
    return hashlib.sha256(_read(path)).hexdigest() if path.exists() else None


def _records(data, context, workspace):
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT or payload.get("version") != EXPORT_VERSION:
        raise ValueError("unsupported memory-record format")
    rows = payload.get("memories")
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise ValueError("invalid or oversized record batch")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("content"), str) or not row["content"].strip() or len(row["content"].encode()) > 65536:
            raise ValueError("invalid memory record")
        for key, expected in (("user_id", context.user_id), ("workspace_id", workspace), ("agent_id", context.agent_id)):
            if row.get(key) is not None and row[key] != expected:
                raise PermissionError("file cannot choose another record owner")
        if row.get("status", "active") not in {"active", "candidate", "conflicted", "superseded", "expired", "deleted"}:
            raise ValueError("invalid record lifecycle")
        tags = row.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(tag, str) or len(tag) > 128 for tag in tags):
            raise ValueError("invalid tags")
        for key in ("importance", "confidence"):
            value = row.get(key, 0.5 if key == "importance" else 1.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid record score")
    return [rows[index] for index in _lineage_order(rows)]


def preview(service, context, request):
    args = request.arguments
    if "path" in args or args.get("direction") not in {"import", "export"}:
        raise ValueError("use a native-selected file handle and direction")
    importing = args["direction"] == "import"
    path = _file(service, context, args.get("file_handle"), "read" if importing else "write")
    authorization = service.authorizer(context, request)
    if importing and not authorization.can_contribute():
        raise PermissionError("contribute capability is required")
    if importing:
        rows = _records(_read(path), context, authorization.workspace_id)
        count = len(rows)
    else:
        # Paginate only authorized records; reject oversized exports, never emit a silent subset.
        rows, after = [], None
        while True:
            batch = service.client.backend.inspector_memories(authorization.scopes("read"), after=after, limit=100)
            rows.extend(batch)
            if len(rows) > MAX_RECORDS:
                raise ValueError("export exceeds record budget; choose a smaller authorized project")
            if len(batch) < 100:
                break
            after = (batch[-1].created_at, batch[-1].id)
        count = len(rows)
    checks = {"file_digest": _digest(path)}
    if not importing:
        checks["records"] = [[memory.id, memory.revision] for memory in rows]
    return service.previews.prepare(context, request, "transfer", {
        "direction": args["direction"], "file_handle": args["file_handle"],
    }, after={"name": path.name, "records": count}, checks=checks,
       effects={"count": count, "coverage": COVERAGE, "overwrite": path.exists() and not importing,
                "embedding": "recomputed on explicit import; may load configured local model"})


def apply(service, context, proposal, *, on_external_effect):
    payload = proposal["payload"]
    importing = payload["direction"] == "import"
    path = _file(service, context, payload["file_handle"], "read" if importing else "write")
    if _digest(path) != proposal["checks"]["file_digest"]:
        raise Conflict("selected file changed after preview")
    request = ConsoleRequest(operation="transfer_commit", request_id="transfer-authorization", selection_handle=proposal["selection_handle"])
    authorization = service.authorizer(context, request)
    backend = service.client.backend
    if importing:
        if not authorization.can_contribute():
            raise PermissionError("contribute capability revoked")
        rows = _records(_read(path), context, authorization.workspace_id)
        mapping, stored = {}, 0
        allowed = {field.name for field in fields(Memory)} - {"id", "revision", "embedding", "content_hash", "supersedes_id"}
        for row in rows:
            predecessor = row.get("supersedes_id")
            values = {key: value for key, value in row.items() if key in allowed}
            values.update(user_id=context.user_id, workspace_id=authorization.workspace_id,
                          agent_id=context.agent_id, session_id=context.session_id)
            memory = Memory(**values)
            memory.content_hash = _content_hash(memory.content)
            memory.supersedes_id = mapping.get(predecessor)
            memory.evidence_quote = memory.evidence_quote if memory.evidence_quote and memory.evidence_quote in memory.content else memory.content
            existing_id = backend.find_import_duplicate_id(memory)
            if existing_id is None:
                memory.embedding = service.client.engine.embed(memory.content)
                memory.id, inserted = backend.add_with_status(memory)
            else:
                memory.id, inserted = existing_id, False
            if inserted:
                stored += 1
                backend.add_evidence(memory.id, memory.evidence_quote)
                index_memory_entities(backend, memory)
                backend.record_event("inspector_import", memory.id, after=_snapshot(memory), actor="inspector-owner")
            elif predecessor is not None and backend.get(memory.id).supersedes_id != memory.supersedes_id:
                raise Conflict("duplicate record has incompatible lineage")
            if row.get("id") is not None:
                mapping[row["id"]] = memory.id
        return {"count": len(rows), "stored": stored, "duplicates": len(rows) - stored,
                "coverage": COVERAGE, "lineage_map": mapping, "audit": "committed"}
    rows = []
    for memory_id, revision in proposal["checks"]["records"]:
        memory = backend.get(memory_id)
        if memory is None or memory.revision != revision:
            raise Conflict("export content changed after preview")
        authorization.require("read", memory)
        rows.append({**_mem_to_dict(memory), "embedding": None})
    serialized = json.dumps({"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "memories": rows}, ensure_ascii=False).encode("utf-8")
    if len(serialized) > MAX_FILE_BYTES:
        raise ValueError("export exceeds file budget")
    backend.record_event("inspector_export", None, after={"user_id": context.user_id,
        "workspace_id": context.workspace_id, "agent_id": context.agent_id, "session_id": context.session_id}, actor="inspector-owner")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        # Arm before publication: even a lost filesystem acknowledgement may
        # leave the selected destination changed while SQL subsequently rolls back.
        on_external_effect()
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    descriptor = backend.inspector_get("file:" + payload["file_handle"])
    descriptor.update(ready=True, digest=hashlib.sha256(serialized).hexdigest())
    backend.inspector_put("file:" + payload["file_handle"], descriptor)
    return {"count": len(rows), "file_handle": payload["file_handle"], "coverage": COVERAGE, "audit": "committed"}
