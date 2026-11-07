"""One inspector boundary over the configured MemoryClient, never a second engine."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

from luminary_memory.api import MemoryClient
from luminary_memory.backends.inspector import ContentRevisionConflict
from luminary_memory.inspector import queries
from luminary_memory.inspector.authorization import Authorizer, selection_handle
from luminary_memory.inspector.contracts import ConsoleRequest, ConsoleResult
from luminary_memory.inspector.identity import validate_context
from luminary_memory.inspector.mutations import Conflict, PreviewManager


class InspectorService:
    def __init__(self, client: MemoryClient):
        self.client = client
        self.previews = PreviewManager(self)

    def authorizer(self, context, request):
        return Authorizer(self.client, context, request.selection_handle)

    def selection_handle(self, context, project_id):
        return selection_handle(self.client, context, project_id)

    def writer(self, context, *, memory=None, workspace_id=None):
        # Existing engine/enricher/settings/backend are shared, not recreated.
        scope = {"user_id": context.user_id, "workspace_id": workspace_id or context.workspace_id,
                 "agent_id": context.agent_id}
        if memory is not None:
            scope = {field: getattr(memory, field) for field in scope}
        return MemoryClient(settings=self.client.settings, backend=self.client.backend,
                            engine=self.client.engine, enricher=self.client.enricher, scope=scope)

    def confirm(self, context, preview_id):
        return self.previews.confirm(context, preview_id)

    def result(self, context, request, status="ok", data=None, code=None, message=None):
        store = self.client.backend.inspector_get("store", {})
        return ConsoleResult(status=status, data=data,
            error={"code": code or status, "message": message or status.replace("_", " ")} if code or message else None,
            request_id=request.request_id, context_epoch=context.context_epoch,
            policy_revision=int(store.get("policy_revision", 0)))

    def execute(self, context, request: ConsoleRequest) -> ConsoleResult:
        external_started = False
        pending_commit = False

        def mark_external_effect():
            nonlocal external_started
            external_started = True

        try:
            if not isinstance(request, ConsoleRequest):
                raise TypeError("ConsoleRequest is required")
            # Principal/store fields in model JSON are never identity selectors.
            if set(request.arguments) & {"user_id", "workspace_id", "workspace", "store_id", "agent_id", "host_id", "profile_id", "native_context"}:
                raise PermissionError("request identity fields have no authority")
            # A disclosed model call is a read-only external effect. Its own
            # receipt/snapshot transactions must not hold a DB lock across HTTP.
            readonly_effect = request.operation == "explain" and request.arguments.get("phase") != "preview"
            with (nullcontext() if readonly_effect else self.client.backend.transaction()):
                validate_context(self.client, context)
                if request.session_ref is not None and request.session_ref != context.session_id:
                    raise PermissionError("request session does not match native context")
                if request.arguments.get("project_id") is not None and request.selection_handle is None:
                    project_id = request.arguments["project_id"]
                    if not isinstance(project_id, str):
                        raise ValueError("project_id must be an opaque project reference")
                    request = replace(request, selection_handle=self.selection_handle(context, project_id))
                operation = request.operation
                if operation in {"browse", "detail", "history"}:
                    data = getattr(queries, operation)(self, context, request)
                    status = "empty" if "items" in data and not data["items"] else "ok"
                    return self.result(context, request, status=status, data=data)
                if operation == "preview_change":
                    data = self.previews.preview_change(context, request)
                    return self.result(context, request, data=data)
                if operation in {"mutate", "maintenance_commit"}:
                    response = self.previews.commit(context, request, on_external_effect=mark_external_effect)
                    pending_commit = response.status == "ok"
                    return response
                if operation == "maintenance_preview":
                    return self.result(context, request, data=self.previews.maintenance_preview(context, request))
                if operation in {"grant", "revoke"}:
                    # Policy commands are the commit half only. JSON booleans
                    # and model-generated grant bodies cannot approve a grant.
                    response = self.previews.commit(context, request, on_external_effect=mark_external_effect)
                    pending_commit = response.status == "ok"
                    return response
                from luminary_memory.inspector import features
                response = features.execute(self, context, request, on_external_effect=mark_external_effect)
                pending_commit = operation in {"set_settings", "transfer_commit"} and response.status == "ok"
                return response
        except Exception as error:  # noqa: BLE001 -- protocol boundary must redact backend secrets
            # Files/configuration cannot roll back with SQL. A successful mutation
            # awaiting commit may also have lost its database acknowledgement.
            if external_started or pending_commit:
                return self._failure(context, request, "unknown_outcome",
                    "The operation may have changed data, files or settings; completion is unconfirmed. "
                    "Inspect the selected destination, current settings and Activity before retrying.")
            if isinstance(error, PermissionError):
                return self._failure(context, request, "denied", "Access is not authorized for this context.")
            if isinstance(error, (Conflict, ContentRevisionConflict)):
                return self._failure(context, request, "conflict", "Resource, policy or conflict-set revision changed.")
            if isinstance(error, (ValueError, TypeError, KeyError)):
                return self._failure(context, request, "invalid_request", "Request fields or references are invalid.")
            return self._failure(context, request, "unavailable", "The configured memory backend is unavailable.")

    def _failure(self, context, request, status, message):
        try:
            revision = int(self.client.backend.inspector_get("store", {}).get("policy_revision", 0))
        except Exception:  # noqa: BLE001 -- an unavailable backend must not break error serialization
            revision = 0
        return ConsoleResult(status=status, error={"code": status, "message": message},
            request_id=getattr(request, "request_id", ""), context_epoch=getattr(context, "context_epoch", ""),
            policy_revision=revision)
