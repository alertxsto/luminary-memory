"""Source-grounded maintenance suggestions; only native confirmation can apply them.

The list contract is ``items`` containing proposal_id, memory_id, action,
proposed_content and revision. A preview_change with kind
``maintenance_proposal`` and proposal_id returns the ordinary inspector preview.
The caller must route its confirmed commit through :func:`apply` inside the
PreviewManager transaction; model output is never a confirmation.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace

from luminary_memory.ingest.llm import NoopEnricher, _parse_enrichment_payload
from luminary_memory.inspector.identity import digest
from luminary_memory.inspector.mutations import Conflict
from luminary_memory.inspector.queries import memory_view

_SCOPE = ("user_id", "workspace_id", "agent_id")
_MAX_REVIEW = 500
_MAX_PROPOSALS = 100
_MAX_QUOTE = 4096
_PREFIX = "maintenance-proposal:"


def _scope(memory):
    return {field: getattr(memory, field) for field in _SCOPE}


def _prefix(scope):
    return _PREFIX + digest(scope) + ":"


def _source(backend, memory, source_id=None, quote=None, *, lock=False):
    """Return a linked, exactly scoped episode, never an invented source."""
    suffix = " FOR UPDATE" if lock and hasattr(backend, "_psycopg") else ""
    params = [memory.user_id, memory.workspace_id, memory.agent_id, memory.id, memory.id,
              memory.user_id, memory.workspace_id, memory.agent_id, "memory:" + str(memory.id)]
    condition = ""
    if source_id is not None:
        condition = " AND e.id=?"
        params.append(source_id)
    # Lock source rows separately: PostgreSQL does not permit FOR UPDATE on DISTINCT.
    rows = backend._sql(
        "SELECT e.id,e.content FROM episodes e WHERE "
        "COALESCE(e.user_id,'')=COALESCE(?,'') AND COALESCE(e.workspace_id,'')=COALESCE(?,'') "
        "AND COALESCE(e.agent_id,'')=COALESCE(?,'') "
        "AND (e.id IN (SELECT source_id FROM memory_evidence WHERE memory_id=?) "
        "OR e.id IN (SELECT source_episode_id FROM claims WHERE memory_id=? AND user_id=? "
        "AND workspace_id=? AND agent_id=?) OR e.id=?)" + condition + " ORDER BY e.id" + suffix,
        params,
    ).fetchall()
    for eid, content in rows:
        if not isinstance(content, str) or not content:
            continue
        if quote is None:
            return str(eid), content[:_MAX_QUOTE]
        if quote in content:
            return str(eid), content
    return None


def _valid(backend, proposal, *, lock=False):
    memory = backend.get(proposal["memory_id"])
    if (memory is None or memory.status != "active" or memory.revision != proposal["revision"]
            or _scope(memory) != proposal["scope"]):
        raise Conflict("maintenance target changed")
    source = _source(backend, memory, proposal["source_id"], proposal["quote"], lock=lock)
    if source is None:
        raise Conflict("maintenance source changed")
    return memory, source[1]


def generate(client, review_all=True):
    """Review only current own-scope rows and persist bounded suggestions."""
    if client.enricher is None or isinstance(client.enricher, NoopEnricher):
        return {"skipped": "no LLM enricher configured", "reviewed": 0, "proposed": 0}
    scope = {field: client.scope.get(field) for field in _SCOPE}
    if client.scope and any(not isinstance(value, str) or not value for value in scope.values()):
        return {"reviewed": 0, "proposed": 0, "skipped": "complete ownership required"}
    memories = client._mutable_memories(limit=0 if review_all else _MAX_REVIEW)
    candidates, snapshots = [], {}
    for memory in memories:
        if _scope(memory) != scope or memory.status != "active":
            continue
        source = _source(client.backend, memory)
        if source:
            candidates.append(SimpleNamespace(id=memory.id, content=memory.content,
                                              source_id=source[0], evidence_quote=source[1]))
            snapshots[memory.id] = (memory, source)
    if not candidates:
        return {"reviewed": 0, "proposed": 0}
    data = _parse_enrichment_payload(client.enricher.review_memories(candidates))
    actions = data.get("actions")
    if not isinstance(actions, list):
        return {"reviewed": len(candidates), "proposed": 0, "error": "bad LLM response"}
    proposed = 0
    with client.backend.transaction():
        existing = client.backend.inspector_scan(_prefix(scope))
        for key, proposal in existing:
            try:
                _valid(client.backend, proposal, lock=True)
            except (Conflict, KeyError, TypeError):
                client.backend.inspector_remove(key)
        existing = client.backend.inspector_scan(_prefix(scope))
        room = max(0, _MAX_PROPOSALS - len(existing))
        seen = set()
        for action in actions:
            if not room:
                break
            if not isinstance(action, dict):
                continue
            mid, kind = action.get("id"), action.get("action")
            if isinstance(mid, bool) or not isinstance(mid, int) or mid not in snapshots or mid in seen:
                continue
            memory, source = snapshots[mid]
            quote, source_id = action.get("evidence_quote"), action.get("source_id")
            if (not isinstance(kind, str) or kind not in {"update", "delete"} or source_id != source[0]
                    or not isinstance(quote, str) or not quote.strip() or len(quote) > _MAX_QUOTE
                    or quote not in source[1]):
                continue
            content = action.get("content") if kind == "update" else None
            if kind == "update":
                if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 65536:
                    continue
                content = content.strip()
            proposal_id = secrets.token_urlsafe(24)
            proposal = {"proposal_id": proposal_id, "memory_id": mid, "action": kind,
                        "proposed_content": content, "revision": memory.revision, "scope": scope,
                        "source_id": source_id, "quote": quote}
            try:
                _valid(client.backend, proposal, lock=True)
            except Conflict:
                continue
            client.backend.inspector_put(_prefix(scope) + proposal_id, proposal)
            seen.add(mid)
            proposed += 1
            room -= 1
    return {"reviewed": len(candidates), "proposed": proposed}


def _lookup(service, context, request, proposal_id, *, lock=False):
    if not isinstance(proposal_id, str) or not proposal_id or len(proposal_id) > 100:
        raise ValueError("proposal_id is required")
    authorization = service.authorizer(context, request)
    # Suggestions are deliberately restricted to the native exact owner scope.
    if request.selection_handle is not None:
        raise PermissionError("maintenance suggestions require native scope")
    scope = {field: getattr(context, field) for field in _SCOPE}
    key = _prefix(scope) + proposal_id
    if lock and hasattr(service.client.backend, "_psycopg"):
        service.client.backend._sql("SELECT key FROM inspector_metadata WHERE key=? FOR UPDATE", (key,)).fetchone()
    proposal = service.client.backend.inspector_get(key)
    if not proposal or proposal.get("scope") != scope or proposal.get("proposal_id") != proposal_id:
        raise Conflict("maintenance proposal is unavailable")
    memory, source = _valid(service.client.backend, proposal, lock=lock)
    authorization.require("read", memory)
    authorization.require("retract" if proposal["action"] == "delete" else "edit", memory)
    return key, proposal, memory, source, authorization


def list_suggestions(service, context, request):
    authorization = service.authorizer(context, request)
    if request.selection_handle is not None:
        raise PermissionError("maintenance suggestions require native scope")
    scope = {field: getattr(context, field) for field in _SCOPE}
    items = []
    for _, proposal in service.client.backend.inspector_scan(_prefix(scope)):
        try:
            memory, _ = _valid(service.client.backend, proposal)
            authorization.require("read", memory)
            authorization.require("retract" if proposal["action"] == "delete" else "edit", memory)
        except (Conflict, PermissionError, KeyError, TypeError):
            continue
        items.append({field: proposal[field] for field in
                      ("proposal_id", "memory_id", "action", "proposed_content", "revision")})
    return {"items": items}


def preview(service, context, request):
    _, proposal, memory, _, authorization = _lookup(service, context, request, request.arguments.get("proposal_id"))
    return service.previews.prepare(context, request, "maintenance_proposal", {"proposal_id": proposal["proposal_id"]},
        before=memory_view(memory, authorization.permissions(memory), full=True),
        after={"memory_id": memory.id, "action": proposal["action"], "content": proposal["proposed_content"]},
        effects={"count": 1}, checks={"proposal": digest(proposal)})


def apply(service, context, authorization, preview):
    """Apply a confirmed preview; caller owns the transaction and receipt check."""
    from luminary_memory.inspector.contracts import ConsoleRequest

    request = ConsoleRequest(operation="mutate", request_id="maintenance", selection_handle=preview["selection_handle"])
    key, proposal, memory, source, current_authorization = _lookup(
        service, context, request, preview["payload"]["proposal_id"], lock=True)
    if digest(proposal) != preview["checks"]["proposal"]:
        raise Conflict("maintenance proposal changed")
    action = "retract" if proposal["action"] == "delete" else "edit"
    authorization.require(action, memory)
    current_authorization.require(action, memory)
    service.client.backend.lock_claim_set(_scope(memory), memory.claim_key)
    # Recheck after acquiring the same claim-set lock used by normal mutations.
    memory, source = _valid(service.client.backend, proposal, lock=True)
    writer = service.writer(context, memory=memory)
    if proposal["action"] == "delete":
        writer.retract(memory.id)
        result_id = memory.id
    else:
        result_id = writer.supersede(memory.id, proposal["proposed_content"],
            evidence_quote=proposal["quote"], source_id=proposal["source_id"],
            source_text=source, claims=[], session_id=context.session_id)
        if result_id is None or result_id == memory.id:
            raise Conflict("maintenance did not create a successor")
    service.client.backend.inspector_remove(key)
    result = service.client.backend.get(result_id)
    return {"memory_id": result_id, "revision": result.revision, "audit": "committed"}
