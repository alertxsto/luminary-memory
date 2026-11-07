"""Additional inspector operations through the single authorized service."""
from __future__ import annotations

from luminary_memory.inspector import activity, explanations, settings, summary, transfer


def execute(service, context, request, *, on_external_effect):
    operation = request.operation
    if operation in {"set_settings", "transfer_commit"}:
        return service.previews.commit(context, request, on_external_effect=on_external_effect)
    if operation == "explain":
        try:
            if request.arguments.get("phase") == "preview":
                return service.result(context, request, data=explanations.preview(service, context, request))
            return service.previews.commit(context, request, on_external_effect=on_external_effect)
        except explanations.ExplanationUnavailable:
            return service.result(context, request, status="unavailable", code="explanation_unavailable",
                                  message="Explanation unavailable; deterministic Summary remains usable. Check the configured endpoint and model.")
    handlers = {
        "events": activity.events, "graph": activity.graph,
        "summary": summary.snapshot, "transfer_preview": transfer.preview,
    }
    if operation == "get_settings":
        return service.result(context, request, data=settings.get_settings(service, context))
    handler = handlers.get(operation)
    if handler is None:
        raise ValueError("unknown inspector operation")
    data = handler(service, context, request)
    return service.result(context, request, status="empty" if "items" in data and not data["items"] else "ok", data=data)


def preview_change(service, context, request):
    if request.arguments.get("kind") == "set_settings":
        return settings.preview(service, context, request)
    raise ValueError("unknown inspector change kind")


def apply_preview(service, context, proposal, *, on_external_effect):
    handler = {"set_settings": settings.apply, "transfer": transfer.apply}.get(proposal["kind"])
    if handler is None:
        raise ValueError("unknown confirmed inspector change")
    return handler(service, context, proposal, on_external_effect=on_external_effect)
