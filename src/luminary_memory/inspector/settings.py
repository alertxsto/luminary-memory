"""Secret-free effective settings and profile-local inspector preferences."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from luminary_memory.inspector.identity import digest
from luminary_memory.inspector.mutations import Conflict

DEFAULT_PREFERENCES = {"page_size": 50, "activity_limit": 50}


def safe_destination(value):
    if not value:
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if not host or parts.scheme not in {"http", "https"}:
            return None
        authority = f"[{host}]" if ":" in host else host
        if parts.port:
            authority += f":{parts.port}"
        return urlunsplit((parts.scheme, authority, parts.path, "", ""))
    except (ValueError, TypeError):
        return None


def preference_key(context):
    return "preferences:" + digest([context.user_id, context.host_id, context.profile_id, context.agent_id])


def get_settings(service, context):
    adapter = getattr(service, "settings_adapter", None)
    config = service.client.settings
    native = adapter.read(context) if adapter is not None else None
    values = {"backend": config.backend, "embedding_model": config.embedding_model,
              "ingest_llm": config.ingest_llm, "strict_recall": config.strict_recall,
              "evidence_required": config.evidence_required, "llm_model": config.llm_model,
              "llm_destination": safe_destination(config.llm_base_url)}
    if native is not None:
        values.update(native["values"])
    model = values.get("llm_model")
    configured = bool(values.get("llm_destination") and isinstance(model, str) and model.strip())
    readiness = {"backend": "connected", "embedding": "configured; not probed or downloaded",
                 "explanation": "configured; connectivity not probed" if configured else "unconfigured",
                 "data_quality": "not evaluated; open Summary for stored-state counts"}
    if native is not None:
        return {**native, "values": values, "readiness": {**readiness, **native.get("readiness", {})},
                "source": native.get("source", "authenticated native profile config; existing providers require restart")}
    stored = service.client.backend.inspector_get(preference_key(context), {"revision": 0, "values": {}})
    return {
        "values": {**DEFAULT_PREFERENCES, **{key: value for key, value in stored["values"].items() if key in DEFAULT_PREFERENCES}, **values},
        "revision": stored["revision"], "editable": list(DEFAULT_PREFERENCES),
        "secret_presence": {"llm_api_key": bool(config.llm_api_key), "pg_dsn": bool(config.pg_dsn)},
        "readiness": readiness,
        "source": "current process/operator config; only inspector preferences are editable on this host",
    }


def preview(service, context, request):
    if request.selection_handle is not None:
        raise PermissionError("settings require own native profile")
    args = request.arguments
    changes = dict(args.get("changes") or {})
    current = get_settings(service, context)
    if not changes or set(changes) - set(current["editable"]):
        raise ValueError("unsupported setting")
    if args.get("expected_revision") != current["revision"]:
        raise Conflict("settings changed")
    if getattr(service, "settings_adapter", None) is None:
        for name, value in changes.items():
            if name in {"page_size", "activity_limit"} and (type(value) is not int or not 1 <= value <= 100):
                raise ValueError("page size must be 1–100")
    return service.previews.prepare(context, request, "set_settings", {
        "changes": changes, "expected_revision": current["revision"],
    }, before={key: current["values"].get(key) for key in changes}, after=changes,
       effects={"profile_local": True, "explicit_settings_change": True})


def apply(service, context, proposal, *, on_external_effect):
    payload = proposal["payload"]
    current = get_settings(service, context)
    if current["revision"] != payload["expected_revision"]:
        raise Conflict("settings changed after preview")
    adapter = getattr(service, "settings_adapter", None)
    if adapter is not None:
        adapter.apply(context, payload["changes"], payload["expected_revision"], on_external_effect=on_external_effect)
        return get_settings(service, context)
    values = {key: current["values"][key] for key in DEFAULT_PREFERENCES}
    values.update(payload["changes"])
    service.client.backend.inspector_put(preference_key(context), {
        "revision": current["revision"] + 1, "values": values,
    })
    service.client.backend.record_event("inspector_settings", None, after={
        "user_id": context.user_id, "workspace_id": context.workspace_id,
        "agent_id": context.agent_id, "session_id": context.session_id,
    }, actor="inspector-owner")
    return get_settings(service, context)
