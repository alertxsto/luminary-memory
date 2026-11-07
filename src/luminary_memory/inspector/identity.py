"""Resolve native owner identity against the configured engine store only."""
from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import asdict

from luminary_memory.inspector.contracts import TrustedContext

NATIVE_FIELDS = ("user_id", "workspace", "agent_id", "session_id", "host_id", "profile_id")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def location_key(native):
    return "location:" + digest({key: native[key] for key in ("user_id", "workspace", "host_id", "profile_id")})


def resolve_context(client, native: Mapping, *, initialize: bool = False) -> TrustedContext:
    if not isinstance(native, Mapping):
        raise TypeError("native context must be a mapping")
    values = {}
    for field in NATIVE_FIELDS:
        value = native.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError("complete native identity is required")
        values[field] = value.strip()
    record_workspace = native.get("workspace_id", values["workspace"])
    if not isinstance(record_workspace, str) or not record_workspace.strip() or len(record_workspace) > 4096:
        raise ValueError("record workspace must be an explicit nonempty scope")
    values["workspace_id"] = record_workspace.strip()
    for bound, native_field in (("user_id", "user_id"), ("workspace_id", "workspace_id"), ("agent_id", "agent_id")):
        if client.scope.get(bound) and client.scope[bound] != values[native_field]:
            raise PermissionError("native identity disagrees with configured binding")
    backend = client.backend
    with backend.transaction():
        store = backend.inspector_get("store")
        if store is None:
            if not initialize:
                raise PermissionError("store has no owner binding")
            store = {"store_id": secrets.token_hex(24), "owner": values["user_id"], "policy_revision": 1}
            backend.inspector_put("store", store)
        if store["owner"] != values["user_id"]:
            raise PermissionError("native principal is not the configured store owner")
        project_id = backend.inspector_get(location_key(values))
        if project_id is None:
            if not initialize:
                raise PermissionError("location requires explicit owner binding")
            projects = backend.inspector_scan("project:")
            if any(project["workspace_id"] == values["workspace_id"] for _, project in projects):
                raise PermissionError("an existing project location requires explicit alias binding")
            project_id = secrets.token_hex(20)
            backend.inspector_put("project:" + project_id,
                                  {"project_id": project_id, "workspace_id": values["workspace_id"], "owner": store["owner"]})
            backend.inspector_put(location_key(values), project_id)
        project = backend.inspector_get("project:" + project_id)
        if not project or project["owner"] != store["owner"]:
            raise PermissionError("project is not owned by this deployment")
        if "workspace_id" in native and project["workspace_id"] != values["workspace_id"]:
            raise PermissionError("record scope disagrees with the approved project binding")
        context_key = "context:" + digest(values)
        persisted = backend.inspector_get(context_key)
        if persisted is not None:
            context = TrustedContext(**persisted)
            validate_context(client, context)
            return context
        context = TrustedContext(store_id=store["store_id"], user_id=values["user_id"], project_id=project_id,
                                 workspace_id=project["workspace_id"], agent_id=values["agent_id"],
                                 session_id=values["session_id"], host_id=values["host_id"], profile_id=values["profile_id"],
                                 context_epoch=secrets.token_hex(16), identity_token=secrets.token_urlsafe(32))
        backend.inspector_put(context_key, asdict(context))
        backend.inspector_put("identity:" + context.identity_token, asdict(context))
        return context


def validate_context(client, context):
    if not isinstance(context, TrustedContext):
        raise PermissionError("trusted context is required")
    backend = client.backend
    store = backend.inspector_get("store")
    persisted = backend.inspector_get("identity:" + context.identity_token)
    if not store or persisted != asdict(context) or store["store_id"] != context.store_id or store["owner"] != context.user_id:
        raise PermissionError("context is not bound to this store owner")
    project = backend.inspector_get("project:" + context.project_id)
    if not project or project["workspace_id"] != context.workspace_id or project["owner"] != context.user_id:
        raise PermissionError("context project is no longer bound")
    return store
