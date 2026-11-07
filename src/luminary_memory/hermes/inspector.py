"""Owner-only Hermes native transport to the single inspector service.

Hermes authenticates and binds a profile before invoking a route. Session IDs
are selectors into that profile's native state DB, never authority supplied by
the frontend. No provider is initialized, and no retention hook runs here.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def native_session_context(session_ref: str) -> dict[str, str]:
    """Resolve a stored session inside the authenticated task-local profile."""
    from hermes_constants import get_hermes_home, profile_name_for_home
    from hermes_state import SessionDB

    if not isinstance(session_ref, str) or not session_ref.strip() or len(session_ref) > 512:
        raise PermissionError("Select an existing native Hermes session")
    home = Path(get_hermes_home()).resolve()
    db = SessionDB(read_only=True)
    try:
        row = db.get_session(session_ref)
    finally:
        db.close()
    if not row or row.get("id") != session_ref:
        raise PermissionError("Session is unavailable in this profile")
    cwd = row.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        raise PermissionError("Native session has no recorded workspace")
    profile = profile_name_for_home(home)
    if not profile or row.get("profile_name") not in (None, "", profile):
        raise PermissionError("Native profile identity is unresolved or disagrees with the session")
    native = {"workspace": cwd, "session_id": session_ref,
              "profile_id": str(home), "agent_id": profile}
    # v0.22.5 agent/agent_init.py::_memory_provider_init_kwargs passes
    # agent_workspace='hermes', NOT cwd, and user_id only when supplied by the
    # native session. A legacy CLI row without that identity is not an owner.
    user_id = row.get("user_id")
    if row.get("profile_name") == profile and isinstance(user_id, str) and user_id.strip():
        native.update(user_id=user_id, workspace_id="hermes")
    return native


def provider_record_scope(native: dict[str, str]) -> dict[str, str]:
    """Use complete native identity, or an explicit owner's exact legacy binding."""
    binding_file = Path(native["profile_id"]) / "luminary" / "inspector.json"
    complete = all(native.get(key) for key in ("user_id", "workspace_id", "agent_id"))
    if not binding_file.is_file():
        if complete:
            return {key: native[key] for key in ("user_id", "workspace_id", "agent_id")}
        raise PermissionError(
            "Native session lacks a complete provider owner mapping. Run hermes luminary-inspector "
            "inspector-bind with the exact existing record scope. Unowned records cannot "
            "be inspected without a separately approved ownership migration."
        )
    try:
        binding = json.loads(binding_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise PermissionError("Repair this profile's luminary/inspector.json with inspector-bind") from None
    scope = binding.get("record_scope") if isinstance(binding, dict) else None
    owner = binding.get("owner_user_id") if isinstance(binding, dict) else None
    if not isinstance(scope, dict) or set(scope) != {"user_id", "workspace_id", "agent_id"}:
        raise PermissionError("Explicit exact record_scope is required; run inspector-bind")
    if any(not isinstance(value, str) or not value.strip() for value in scope.values()):
        raise PermissionError("Incomplete or unowned record scope cannot be reattributed; run inspector-bind")
    if scope["agent_id"] != native["agent_id"] or owner != scope["user_id"]:
        raise PermissionError("Record scope disagrees with native provider profile or owner")
    if complete and any(scope[key] != native[key] for key in scope):
        raise PermissionError("Approved record scope disagrees with the native session mapping")
    return scope


@contextmanager
def _service(session_ref: str, *, initialize: bool = False) -> Iterator[tuple]:
    from hermes_cli.install_identity import get_install_id

    from luminary_memory.api import MemoryClient
    from luminary_memory.hermes.config import load_config
    from luminary_memory.hermes.provider import LuminaryMemoryProvider
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.service import InspectorService

    native = native_session_context(session_ref)
    home = native["profile_id"]
    # Reuse the provider's exact configured store and Settings construction,
    # but never initialize it: initialize would start the retention worker.
    provider = LuminaryMemoryProvider()
    provider._hermes_home = home
    provider._config = load_config(home)
    from agent.secret_scope import get_secret
    provider._config["llm_api_key"] = get_secret("LUMINARY_LLM_API_KEY") or ""
    settings = provider._build_settings(provider._resolve_db_path())
    settings.pg_dsn = get_secret("LUMINARY_PG_DSN") or ""
    scope = provider_record_scope(native)
    native["user_id"] = scope["user_id"]
    native["workspace_id"] = scope["workspace_id"]
    native["host_id"] = get_install_id() or ""
    try:
        client = MemoryClient(settings=settings, scope=scope)
    except Exception as exc:
        # Driver-specific initialization failures (SQLite/psycopg, including a
        # configured path that is a directory) are backend unavailability, not
        # malformed frontend JSON. Keep diagnostics chained, never in HTTP.
        raise RuntimeError("Configured memory backend is unavailable") from exc
    try:
        context = resolve_context(client, native, initialize=initialize)
        service = InspectorService(client)
        from luminary_memory.hermes.inspector_settings import HermesSettingsAdapter
        service.settings_adapter = HermesSettingsAdapter(home)
        yield service, context
    finally:
        client.close()


def execute_native(payload: dict, *, initialize: bool = False, preview_id: str | None = None) -> dict:
    """Execute only after the host's authenticated native route admission."""
    from luminary_memory.inspector.contracts import ConsoleRequest

    session_ref = payload.get("session_ref", "")
    with _service(session_ref, initialize=initialize) as (service, context):
        if preview_id is not None:
            receipt = service.confirm(context, preview_id)
            # Confirm and commit use the same reauthorized native context. The
            # receipt is never returned to the model or a general JSON channel.
            operation = payload.get("commit_operation", "mutate")
            if operation not in {"mutate", "maintenance_commit", "transfer_commit", "set_settings", "grant", "revoke", "explain"}:
                raise ValueError("Invalid commit operation")
            arguments = {"preview_id": preview_id, "confirmation_receipt": receipt}
            if operation == "explain":
                arguments["phase"] = "commit"
            request = ConsoleRequest.from_dict({"operation": operation, "arguments": arguments,
                                                "request_id": payload.get("request_id") or uuid.uuid4().hex})
        else:
            request = ConsoleRequest.from_dict(payload)
        return service.execute(context, request).to_dict()
