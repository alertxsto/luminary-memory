"""Owner-confirmed logical purge of identifiable records in the active store.

The caller must hold the backend transaction across confirmation, apply, and
proposal consumption. This is not a filesystem, backup, or forensic erasure.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from luminary_memory.inspector.contracts import thaw
from luminary_memory.inspector.identity import digest, validate_context
from luminary_memory.inspector.mutations import Conflict

_SCOPE = ("user_id", "workspace_id", "agent_id")
_EXTERNAL = ["backups and snapshots", "exports and restores", "replicas", "host transcripts", "external providers", "unlinked or unidentifiable copies in the active store"]


def _rows(backend, table, where, params=()):
    name = backend._inspector_table(table)
    cursor = backend._sql(f"SELECT * FROM {name} WHERE {where} ORDER BY id", tuple(params))
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _by_values(backend, table, column, values):
    values = sorted(set(values))
    rows = []
    for offset in range(0, len(values), 400):
        batch = values[offset:offset + 400]
        rows.extend(_rows(backend, table, column + " IN (" + ",".join("?" for _ in batch) + ")", batch))
    return rows

def _scope(row):
    return tuple(row[field] for field in _SCOPE)


def _authorized_scope(authorization, row):
    if any(not row.get(field) for field in _SCOPE):
        raise PermissionError("unowned linked record cannot be purged")
    authorization.require("retract", SimpleNamespace(**{field: row[field] for field in _SCOPE}))


def _refers(value, memory_id):
    if isinstance(value, dict):
        return any((key in {"memory_id", "supersedes_id"} and item == memory_id)
                   or _refers(item, memory_id) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_refers(item, memory_id) for item in value)
    return False


def _snapshot(service, context, authorization, memory, *, expand_shared):
    backend = service.client.backend
    authorization.require("retract", memory)
    mid = memory.id
    claims = _by_values(backend, "claims", "memory_id", [mid])
    evidence = _by_values(backend, "memory_evidence", "memory_id", [mid])
    claim_evidence = _by_values(backend, "claim_evidence", "claim_id", [c["id"] for c in claims])
    source_ids = {memory.source_id, f"memory:{mid}"} | {c["source_episode_id"] for c in claims} | {
        e["source_id"] for e in evidence} | {e["source_episode_id"] for e in claim_evidence}
    source_ids.discard(None)
    source_ids.discard("")
    # Follow source references to a fixed point: deleting a shared claim or
    # evidence row may itself expose another source episode.
    while True:
        episodes = _by_values(backend, "episodes", "id", source_ids)
        episode_ids = [row["id"] for row in episodes]
        linked_evidence = _by_values(backend, "memory_evidence", "source_id", episode_ids)
        linked_claims = _by_values(backend, "claims", "source_episode_id", episode_ids)
        linked_claim_evidence = _by_values(backend, "claim_evidence", "source_episode_id", episode_ids)
        if any(e["claim_id"] is None for e in linked_claim_evidence):
            raise PermissionError("unowned claim evidence cannot be purged")
        linked_claims += _by_values(backend, "claims", "id", [e["claim_id"] for e in linked_claim_evidence])
        claims = list({row["id"]: row for row in claims + linked_claims}.values())
        claim_evidence = list({row["id"]: row for row in claim_evidence + linked_claim_evidence +
                               _by_values(backend, "claim_evidence", "claim_id", [c["id"] for c in claims])}.values())
        evidence = list({row["id"]: row for row in evidence + linked_evidence}.values())
        more = ({c["source_episode_id"] for c in claims} | {e["source_id"] for e in evidence}
                | {e["source_episode_id"] for e in claim_evidence}) - {None, ""}
        if more <= source_ids:
            break
        source_ids.update(more)
    for row in episodes:
        _authorized_scope(authorization, row)
    shared_memories = [row for row in _by_values(backend, "memories", "source_id", episode_ids) if row["id"] != mid]
    affected_ids = {row["id"] for row in shared_memories}
    for row in claims:
        _authorized_scope(authorization, row)
        if row["memory_id"] is None:
            raise PermissionError("unowned claim cannot be purged")
        owner = backend.get(row["memory_id"])
        if owner is None or tuple(getattr(owner, f) for f in _SCOPE) != _scope(row):
            raise PermissionError("claim ownership is inconsistent")
        authorization.require("retract", owner)
        if owner.id != mid:
            affected_ids.add(owner.id)
    for row in evidence:
        if row["memory_id"] is None:
            raise PermissionError("unowned evidence cannot be purged")
        owner = backend.get(row["memory_id"])
        if owner is None:
            raise PermissionError("evidence ownership is unavailable")
        authorization.require("retract", owner)
        if owner.id != mid:
            affected_ids.add(owner.id)
    successors = _by_values(backend, "memories", "supersedes_id", [mid])
    for row in shared_memories + successors:
        _authorized_scope(authorization, row)
        if row["id"] != mid:
            affected_ids.add(row["id"])
    events = _by_values(backend, "memory_events", "memory_id", [mid])
    for row in events:
        scope = _scope(row)
        if any(scope) and scope != tuple(getattr(memory, f) for f in _SCOPE):
            raise PermissionError("audit ownership is inconsistent")
    relations = _by_values(backend, "relations", "memory_id", [mid])
    entity_ids = {row[key] for row in relations for key in ("source_id", "target_id")}
    entities = []
    for row in _by_values(backend, "entities", "id", entity_ids):
        other = _rows(backend, "relations", "(source_id=? OR target_id=?) AND (memory_id IS NULL OR memory_id<>?)", (row["id"], row["id"], mid))
        if not other:
            entities.append(row)
    previews = []
    for key, value in backend.inspector_scan("preview:"):
        if value.get("kind") == "purge" or not _refers(value, mid):
            continue
        if value.get("context_binding") != digest(context.to_dict()):
            raise PermissionError("linked proposal belongs to another context")
        previews.append({"id": key, "value": value})
    tables = {"memories": _by_values(backend, "memories", "id", [mid]), "episodes": episodes,
              "claims": claims, "claim_evidence": claim_evidence, "memory_evidence": evidence,
              "memory_events": events, "relations": relations, "entities": entities,
              "shared_memories": shared_memories, "successors": successors,
              "affected_memories": _by_values(backend, "memories", "id", affected_ids), "previews": previews}
    for rows in tables.values():
        rows.sort(key=lambda row: str(row["id"]))
    # Snapshot content is hashed, never copied into the durable purge proposal.
    serialized = json.dumps(tables, sort_keys=True, default=str, separators=(",", ":"))
    return tables, sorted(affected_ids), hashlib.sha256(serialized.encode()).hexdigest()


def preview(service, context, request):
    validate_context(service.client, context)
    args = thaw(request.arguments)
    memory_id, revision = args.get("memory_id"), args.get("expected_revision")
    if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id <= 0:
        raise ValueError("memory_id is required")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise TypeError("expected_revision must be an integer")
    expanded = args.get("expand_shared", False)
    if not isinstance(expanded, bool):
        raise TypeError("expand_shared must be boolean")
    authorization = service.authorizer(context, request)
    memory = service.client.backend.get(memory_id)
    if memory is None:
        raise PermissionError("memory is unavailable")
    authorization.require("retract", memory)
    if memory.revision != revision:
        raise Conflict("content revision changed")
    tables, shared, snapshot = _snapshot(service, context, authorization, memory, expand_shared=expanded)
    counts = {key: len(rows) for key, rows in tables.items()}
    return service.previews.prepare(context, request, "purge",
        {"memory_id": memory_id, "expected_revision": revision, "expand_shared": expanded},
        before={"memory_id": memory_id, "revision": revision}, after=None,
        effects={"counts": counts, "shared_memory_ids": shared,
                 "shared_impact": {
                     "source_detached_from": [row["id"] for row in tables["shared_memories"]],
                     "supersession_detached_from": [row["id"] for row in tables["successors"] if row["id"] != memory_id],
                     "claims_removed": [row["id"] for row in tables["claims"] if row["memory_id"] != memory_id],
                     "evidence_removed": [row["id"] for row in tables["memory_evidence"] if row["memory_id"] != memory_id],
                 },
                 "unknown_external_copies": _EXTERNAL, "physical_erasure": False},
        checks={"snapshot": snapshot})

def apply(service, context, authorization, preview):
    backend = service.client.backend
    if not backend.in_transaction:
        raise RuntimeError("purge requires the caller's transaction")
    store = validate_context(service.client, context)
    if (authorization.policy_revision != preview["policy_revision"]
            or int(store["policy_revision"]) != preview["policy_revision"]):
        raise Conflict("project policy changed")
    payload = preview["payload"]
    memory = backend.get(payload["memory_id"])
    if memory is None or memory.revision != payload["expected_revision"]:
        raise Conflict("content revision changed")
    tables, shared, snapshot = _snapshot(service, context, authorization, memory, expand_shared=payload["expand_shared"])
    if shared and not payload["expand_shared"]:
        raise PermissionError("shared impact requires explicit expansion")
    if snapshot != preview["checks"]["snapshot"] or shared != preview["effects"]["shared_memory_ids"]:
        raise Conflict("purge impact changed")
    for table in ("claim_evidence", "memory_evidence", "claims", "memory_events", "relations"):
        for row in tables[table]:
            backend._sql(f"DELETE FROM {backend._inspector_table(table)} WHERE id=?", (row["id"],))
    for row in tables["shared_memories"]:
        backend._sql(f"UPDATE {backend._inspector_table('memories')} SET source_id=NULL WHERE id=?", (row["id"],))
    for row in tables["successors"]:
        backend._sql(f"UPDATE {backend._inspector_table('memories')} SET supersedes_id=NULL WHERE id=?", (row["id"],))
    for table in ("episodes", "entities", "memories"):
        for row in tables[table]:
            backend._sql(f"DELETE FROM {backend._inspector_table(table)} WHERE id=?", (row["id"],))
    for row in tables["previews"]:
        backend.inspector_remove(row["id"])
    scope = {field: getattr(memory, field) for field in _SCOPE}
    backend.record_event("inspector_purge", memory.id, after={**scope, "session_id": memory.session_id,
                         "counts": {key: len(rows) for key, rows in tables.items()}}, actor="inspector-owner")
    return {"memory_id": memory.id, "counts": {key: len(rows) for key, rows in tables.items()},
            "unknown_external_copies": _EXTERNAL, "physical_erasure": False, "audit": "committed"}
