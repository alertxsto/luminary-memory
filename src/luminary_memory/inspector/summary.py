"""Deterministic authorized aggregates; no recall, ingestion or model call."""
from luminary_memory.backends.inspector_features import InspectorFeatureQueries
from luminary_memory.inspector import queries


def snapshot(service, context, request):
    authorization = service.authorizer(context, request)
    aggregate = InspectorFeatureQueries(service.client.backend).summary(authorization.scopes("read"))
    totals = aggregate["totals"]
    history = queries.history(service, context, request, memory_changes_only=True)
    issues = []
    if totals["conflicted"]:
        issues.append({"kind": "conflicted", "count": totals["conflicted"]})
    if totals["candidate"]:
        issues.append({"kind": "candidate", "count": totals["candidate"]})
    if aggregate["time_range"]["status"] == "partial":
        issues.append({"kind": "invalid_stored_timestamp", "time_range": "partial"})
    return {**aggregate, "changes": history["items"], "issues": issues,
            "count_basis": "stored lifecycle status; current visibility remains subject to validity and TTL",
            "ai": "off; explanation requires a separate explicit disclosure and confirmation"}
