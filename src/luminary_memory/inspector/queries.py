"""Non-mutating engine projections, scoped before SQL ordering or limits."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
from datetime import datetime

from luminary_memory.inspector.contracts import thaw
from luminary_memory.inspector.identity import digest

VALID_STATUSES = {"active", "candidate", "conflicted", "superseded", "expired", "deleted"}


def bounded(value, byte_limit):
    return str(value or "").encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def conflict_set_token(context, memory, members, claim_members):
    return encode_token(context, {"domain": digest([memory.user_id, memory.workspace_id, memory.agent_id, memory.claim_key]),
                                  "members_digest": digest([[[member.id, member.revision] for member in members], claim_members])})


def memory_view(memory, permissions, *, full=False):
    view = {"id": memory.id, "content": bounded(memory.content, 65536 if full else 512),
            "tags": [bounded(tag, 128) for tag in memory.tags[:100]], "status": memory.status,
            "revision": memory.revision, "user_id": memory.user_id, "workspace_id": memory.workspace_id,
            "agent_id": memory.agent_id, "created_at": memory.created_at, "updated_at": memory.updated_at,
            "importance": memory.importance, "permissions": permissions, "claim_key": bounded(memory.claim_key, 512) or None}
    if full:
        view.update(
            session_id=bounded(memory.session_id, 4096) or None,
            source=bounded(memory.source, 1024) or None,
            source_id=bounded(memory.source_id, 1024) or None,
            observed_at=bounded(memory.observed_at, 128) or None,
            valid_from=bounded(memory.valid_from, 128) or None,
            valid_to=bounded(memory.valid_to, 128) or None,
            ttl_seconds=memory.ttl_seconds, confidence=memory.confidence,
        )
    return view


def encode_token(context, payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(context.identity_token.encode(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")


def decode_token(context, token):
    if not isinstance(token, str) or len(token) > 8192:
        raise ValueError("invalid cursor")
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        signature, body = raw[:32], raw[32:]
        if not hmac.compare_digest(signature, hmac.new(context.identity_token.encode(), body, hashlib.sha256).digest()):
            raise ValueError("invalid cursor")
        return json.loads(body)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def _page(service, context, request, authorization):
    from luminary_memory.inspector.settings import DEFAULT_PREFERENCES, preference_key

    preferences = service.client.backend.inspector_get(preference_key(context), {"values": {}})["values"]
    preference = "activity_limit" if request.operation == "events" else "page_size"
    arguments = thaw(request.arguments)
    limit = arguments.get("limit", preferences.get(preference, DEFAULT_PREFERENCES[preference]))
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    limit = min(limit, 100)
    filters = {key: value for key, value in arguments.items() if key != "cursor"}
    binding = digest({"operation": request.operation, "filters": filters, "selection": request.selection_handle,
                      "context_epoch": context.context_epoch, "policy_revision": authorization.policy_revision, "limit": limit})
    after = None
    if arguments.get("cursor"):
        cursor = decode_token(context, arguments["cursor"])
        if cursor.get("binding") != binding:
            raise ValueError("cursor context or filters changed")
        after = cursor["after"]
    return limit, binding, after


def _cursor(context, binding, after):
    return encode_token(context, {"binding": binding, "after": after})


def browse(service, context, request):
    authorization = service.authorizer(context, request)
    args = thaw(request.arguments)
    limit, binding, after = _page(service, context, request, authorization)
    if args.get("view") == "sharing":
        if after is not None and not isinstance(after, str):
            raise ValueError("invalid grant cursor")
        grants = service.client.backend.inspector_grants(
            authorization.project_id, context.user_id, context.agent_id, after=after, limit=limit + 1,
        )
        page = grants[:limit]
        return {
            "project": {"project_id": authorization.project_id, "workspace_id": authorization.workspace_id},
            "grants": [{key: grant[key] for key in ("grantor_agent_id", "recipient_agent_id", "capabilities")}
                       for _, grant in page],
            "next_cursor": _cursor(context, binding, page[-1][0]) if len(grants) > limit else None,
        }
    statuses = args.get("statuses", ["active", "candidate", "conflicted"])
    if not isinstance(statuses, list) or not statuses or any(status not in VALID_STATUSES for status in statuses):
        raise ValueError("invalid statuses")
    tags = args.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(tag, str) or len(tag) > 128 for tag in tags):
        raise ValueError("invalid tag filter")
    query = args.get("query")
    if query is not None and (not isinstance(query, str) or len(query) > 512):
        raise ValueError("invalid query")
    for key in ("created_after", "created_before"):
        if args.get(key):
            datetime.fromisoformat(args[key])
    memories = service.client.backend.inspector_memories(
        authorization.scopes("read"), statuses=statuses, tags=tags, query=query,
        created_after=args.get("created_after"), created_before=args.get("created_before"),
        after=after, limit=limit + 1,
    )
    page = memories[:limit]
    next_cursor = _cursor(context, binding, [page[-1].created_at, page[-1].id]) if len(memories) > limit else None
    projects = []
    for _, project in service.client.backend.inspector_scan("project:"):
        if project["owner"] != context.user_id:
            continue
        grants = service.client.backend.inspector_scan("grant:" + project["project_id"] + ":")
        if project["project_id"] == context.project_id or any(grant["recipient_agent_id"] == context.agent_id for _, grant in grants):
            projects.append({"project_id": project["project_id"], "workspace_id": project["workspace_id"],
                             "selection_handle": service.selection_handle(context, project["project_id"])})
    return {"items": [memory_view(memory, authorization.permissions(memory)) for memory in page],
            "next_cursor": next_cursor, "projects": projects}


def detail(service, context, request):
    authorization = service.authorizer(context, request)
    memory_id = request.arguments.get("memory_id")
    if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id <= 0:
        raise ValueError("memory_id must be a positive integer")
    memory = service.client.backend.get(memory_id)
    if memory is None:
        raise PermissionError("memory is not accessible")
    authorization.require("read", memory)
    permissions = authorization.permissions(memory)
    members = []
    if memory.claim_key:
        scope = {field: getattr(memory, field) for field in ("user_id", "workspace_id", "agent_id")}
        members = [member for member in service.client.backend.find_by_claim_key(memory.claim_key, scope=scope)
                   if member.status in {"active", "conflicted"}]
    expansion = request.arguments.get("expand")
    if expansion not in {None, "evidence", "claims", "episodes", "lineage"}:
        raise ValueError("unknown detail expansion")
    limit = request.arguments.get("limit", 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("invalid expansion limit")
    provenance = service.client.backend.inspector_provenance(memory_id, limit=min(limit, 100) if expansion else 5)
    for row in provenance["evidence"]:
        row["quote"] = bounded(row["quote"], 8192 if expansion == "evidence" else 512)
        row["observed_at"] = str(row["observed_at"]) if row["observed_at"] else None
    for row in provenance["claims"]:
        for key in ("subject", "predicate", "object", "evidence_quote"):
            row[key] = bounded(row[key], 8192 if expansion == "claims" else 512)
    return {"memory": memory_view(memory, permissions, full=True), "permissions": permissions,
            "revision": memory.revision, "conflict_set_token": conflict_set_token(
                context, memory, members, service.client.backend.inspector_claim_set(memory)) if memory.claim_key else None,
            "lineage": service.client.backend.inspector_lineage(authorization.scopes("read"), memory),
            "episodes": [{**{key: str(value) if value is not None else None for key, value in row.items() if key != "content"},
                          "content": bounded(row["content"], 16384)}
                         for row in service.client.backend.inspector_episodes(memory, limit=min(limit, 20))] if expansion == "episodes" else [],
            **provenance}


def _event_counter(snapshot, key):
    value = snapshot.get(key)
    return value if type(value) is int and value >= 0 else None


def event_view(row, authorization):
    payload = {}
    operation = None
    for key in ("before", "after"):
        snapshot = row[key]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        if not isinstance(snapshot, dict):
            continue
        if not any(all(snapshot.get(field) == scope[field] for field in ("user_id", "workspace_id", "agent_id"))
                   for scope in authorization.scopes("read")):
            continue
        payload[key] = {"content": bounded(snapshot.get("content"), 8192), "status": snapshot.get("status")}
        if (key == "after" and row["kind"] == "native_recall"
                and isinstance(snapshot.get("operation_id"), str)
                and snapshot.get("status") in {"running", "returned", "error", "cancelled", "unknown_outcome"}):
            references = snapshot.get("memory_ids")
            references = [value for value in references[:32] if type(value) is int and value > 0] if isinstance(references, list) else []
            operation = {
                "id": bounded(snapshot["operation_id"], 128), "name": "recall", "state": snapshot["status"],
                "session_id": bounded(snapshot.get("session_id"), 256),
                "memory_ids": references, "returned": len(references), "stored": 0, "injected": None,
            }
            ranking = snapshot.get("ranking")
            operation["ranking"] = []
            operation["ranking_status"] = "recorded" if isinstance(ranking, list) else "not_recorded"
            for signal in ranking[:32] if isinstance(ranking, list) else []:
                if (not isinstance(signal, dict) or type(signal.get("memory_id")) is not int or signal["memory_id"] not in references
                        or signal.get("basis") not in {"core", "recall", "core_and_recall"}):
                    continue
                score = signal.get("score")
                operation["ranking"].append({
                    "memory_id": signal["memory_id"], "basis": signal["basis"],
                    "returned_position": _event_counter(signal, "returned_position"),
                    "recall_rank": _event_counter(signal, "recall_rank"),
                    "score": score if type(score) in {int, float} and math.isfinite(score) else None,
                })
            complete_ranking = isinstance(ranking, list) and len(operation["ranking"]) == len(references)
            operation["recalled"] = sum(signal["basis"] != "core" for signal in operation["ranking"]) if complete_ranking else None
            operation["core_only"] = sum(signal["basis"] == "core" for signal in operation["ranking"]) if complete_ranking else None
            operation["score_basis"] = "Recorded retriever output, not an inferred probability; core-only context has no query rank."
        elif (key == "after" and row["kind"] == "hermes_operation"
              and isinstance(snapshot.get("operation_id"), str)
              and isinstance(snapshot.get("operation_name"), str)
              and snapshot.get("status") in {"running", "returned", "prepared", "committed",
                                             "duplicate", "skipped", "error", "cancelled", "unknown_outcome"}):
            operation = {
                "id": bounded(snapshot["operation_id"], 128),
                "name": bounded(snapshot["operation_name"], 64), "state": snapshot["status"],
                "session_id": bounded(snapshot.get("session_id"), 256), "memory_ids": [],
                "recalled": _event_counter(snapshot, "memory_count") if snapshot["operation_name"] in {"prefetch", "tool_recall"} else 0,
                "stored": _event_counter(snapshot, "stored"), "duplicates": _event_counter(snapshot, "duplicates"),
                "episodes": _event_counter(snapshot, "episodes"), "injected": None,
                "context_prepared": snapshot.get("context_prepared") if type(snapshot.get("context_prepared")) is bool else None,
            }
    if operation is not None:
        operation.setdefault("ranking_status", "not_recorded")
        operation.setdefault("ranking", [])
        counts = " · ".join(f"{label} {operation.get(key) if operation.get(key) is not None else 'unknown'}"
                            for key, label in (("recalled", "recalled"), ("stored", "saved"),
                                               ("duplicates", "duplicates"), ("episodes", "episodes")))
        state = "started" if operation["state"] == "running" else operation["state"]
        preparation = "prepared" if operation.get("context_prepared") is True else "not observed"
        if "returned" in operation:
            core = operation["core_only"] if operation.get("core_only") is not None else "unknown"
            counts = f"returned {operation['returned']} · core-only {core} · {counts}"
        operation["summary"] = f"{operation['name']} {state} · {counts} · context {preparation} · injection unverified"
    return {"event_id": row["event_id"], "memory_id": row["memory_id"], "kind": row["kind"],
            "created_at": str(row["created_at"]), "scope": {"project_id": authorization.project_id},
            "source": bounded(row.get("actor"), 128), "payload": payload, "operation": operation}


def _event_memory(service, authorization, request):
    memory_id = request.arguments.get("memory_id")
    if memory_id is not None:
        if type(memory_id) is not int or memory_id <= 0:
            raise ValueError("invalid memory reference")
        memory = service.client.backend.get(memory_id)
        if memory is not None:
            authorization.require("read", memory)
        elif not service.client.backend.inspector_events(authorization.scopes("read"), memory_id=memory_id, limit=1):
            raise PermissionError("memory history is not accessible")
    return memory_id


def history(service, context, request, *, memory_changes_only=False):
    authorization = service.authorizer(context, request)
    memory_id = _event_memory(service, authorization, request)
    limit, binding, after = _page(service, context, request, authorization)
    rows = service.client.backend.inspector_events(authorization.scopes("read"),
        memory_id=memory_id, after=after, limit=limit + 1,
        exclude_kinds=("native_recall", "hermes_operation") if memory_changes_only else ())
    items = [event_view(row, authorization) for row in rows[:limit]]
    return {"items": items, "next_cursor": _cursor(context, binding, rows[limit - 1]["event_id"]) if len(rows) > limit else None}
