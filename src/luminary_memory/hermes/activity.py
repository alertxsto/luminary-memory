"""Secret-free provider operation snapshots, distinct from durable fact audit."""
from __future__ import annotations

OPERATIONS = frozenset({"retain", "tool_ingest", "session_episode", "prefetch", "tool_recall", "core_load", "session_context", "memory_review"})


def operation_snapshot(event, trace_id, scope, fields):
    """Copy only observed counters and fixed lifecycle codes, never log bodies."""
    name = fields.get("operation")
    if name not in OPERATIONS:
        return None
    suffix = event.rsplit(".", 1)[-1]
    state = {"started": "running", "failed": "error", "discarded": "cancelled",
             "skipped": "skipped", "rejected": "skipped", "recorded": "committed",
             "completed": "returned", "context_ready": "prepared", "loaded": "returned", "duplicate": "duplicate",
             "empty": "returned"}.get(suffix)
    if state is None:
        return None
    stored = fields.get("stored") if name in {"retain", "tool_ingest"} else 0
    duplicates = fields.get("duplicates") if name in {"retain", "tool_ingest"} else 0
    if name == "memory_review":
        stored, duplicates = fields.get("captures_inserted"), None
    if name in {"retain", "tool_ingest"}:
        if state == "skipped":
            stored, duplicates = 0, 0
        elif suffix == "completed":
            state = "committed" if stored == 1 else "duplicate" if duplicates == 1 else "returned"
    if name == "session_episode" and fields.get("episodes") is None and state == "committed":
        state = "returned"
    count = fields.get("memory_count")
    return {
        **scope, "operation_id": trace_id, "operation_name": name, "status": state,
        "memory_count": count if type(count) is int and count >= 0 else None,
        "stored": stored if type(stored) is int and stored >= 0 else None,
        "duplicates": duplicates if type(duplicates) is int and duplicates >= 0 else None,
        "episodes": fields.get("episodes") if name == "session_episode" else 0,
        "context_prepared": fields.get("returned") if name == "prefetch" and type(fields.get("returned")) is bool else None,
        "injected": None,
    }
