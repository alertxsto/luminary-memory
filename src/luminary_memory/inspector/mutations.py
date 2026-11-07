"""Expiring owner-confirmed proposals and single-use atomic audited commits."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from luminary_memory.inspector.authorization import CAPABILITIES, grant_key
from luminary_memory.inspector.contracts import ConsoleRequest, thaw
from luminary_memory.inspector.identity import digest, location_key, validate_context
from luminary_memory.inspector.queries import memory_view


class Conflict(Exception):
    """A confirmed proposal no longer describes the current resource set."""


KINDS = {"create", "correct", "tag", "core", "resolve_conflict", "retract", "grant", "revoke", "bind_location"}


def _context_binding(context):
    return digest(context.to_dict())


def _proposal_digest(preview):
    return digest({key: value for key, value in preview.items()
                   if key not in {"digest", "receipt_hash", "consumed"}})


class PreviewManager:
    def __init__(self, service):
        self.service = service
        self.backend = service.client.backend

    def prepare(self, context, request, kind, payload, *, before=None, after=None, effects=None, checks=None):
        authorization = self.service.authorizer(context, request)
        now = datetime.now(UTC)
        preview = {"preview_id": secrets.token_urlsafe(32), "kind": kind, "payload": thaw(payload),
                   "before": thaw(before), "after": thaw(after), "effects": thaw(effects or {}),
                   "checks": thaw(checks or {}), "selection_handle": request.selection_handle,
                   "context_binding": _context_binding(context), "policy_revision": authorization.policy_revision,
                   "expires_at": (now + timedelta(minutes=5)).isoformat(), "consumed": False}
        preview["digest"] = _proposal_digest(preview)
        self.backend.inspector_put("preview:" + preview["preview_id"], preview)
        return {key: preview[key] for key in ("preview_id", "kind", "before", "after", "effects", "expires_at")}

    def _load(self, context, preview_id):
        validate_context(self.service.client, context)
        if not isinstance(preview_id, str) or not preview_id or len(preview_id) > 200:
            raise PermissionError("valid preview is required")
        preview = self.backend.inspector_get("preview:" + preview_id)
        if (not preview or preview.get("consumed") or preview["context_binding"] != _context_binding(context)
                or datetime.fromisoformat(preview["expires_at"]) <= datetime.now(UTC)
                or not hmac.compare_digest(preview["digest"], _proposal_digest(preview))):
            raise PermissionError("preview is invalid, expired, changed or consumed")
        return preview

    def confirm(self, context, preview_id):
        """Only a trusted native owner interaction may invoke this Python API."""
        with self.backend.transaction():
            preview = self._load(context, preview_id)
            receipt = secrets.token_urlsafe(48)
            preview["receipt_hash"] = hashlib.sha256(receipt.encode()).hexdigest()
            self.backend.inspector_put("preview:" + preview_id, preview)
            return receipt

    def commit(self, context, request, *, on_external_effect):
        if request.operation == "explain":
            return self._commit_explanation(context, request)
        with self.backend.transaction():
            preview_id = request.arguments.get("preview_id")
            preview = self._load(context, preview_id)
            if preview["kind"] == "explain":
                raise ValueError("use the read-only explanation operation")
            if request.arguments.get("cancel") is True:
                preview["consumed"] = True
                self.backend.inspector_put("preview:" + preview_id, preview)
                return self.service.result(context, request, status="cancelled")
            selected_request, authorization = self._confirmed(context, request, preview)
            result = self._apply(context, selected_request, authorization, preview, on_external_effect=on_external_effect)
            preview["consumed"] = True
            self.backend.inspector_put("preview:" + preview_id, preview)
            return self.service.result(context, request, data=result)

    def _confirmed(self, context, request, preview):
        receipt = request.arguments.get("confirmation_receipt")
        if (not isinstance(receipt, str) or not preview.get("receipt_hash")
                or not hmac.compare_digest(preview["receipt_hash"], hashlib.sha256(receipt.encode()).hexdigest())):
            raise PermissionError("native owner confirmation is required")
        selected = ConsoleRequest(operation=request.operation, request_id=request.request_id,
                                  selection_handle=preview["selection_handle"])
        authorization = self.service.authorizer(context, selected)
        if authorization.policy_revision != preview["policy_revision"]:
            raise Conflict("project policy changed")
        return selected, authorization

    def _commit_explanation(self, context, request):
        from luminary_memory.inspector import explanations

        with self.backend.transaction():
            preview = self._load(context, request.arguments.get("preview_id"))
            if preview["kind"] != "explain":
                raise ValueError("an explanation proposal is required")
            if request.arguments.get("cancel") is True:
                preview["consumed"] = True
                self.backend.inspector_put("preview:" + preview["preview_id"], preview)
                return self.service.result(context, request, status="cancelled")
            selected, _ = self._confirmed(context, request, preview)
            explanations.validate_snapshot(self.service, context, preview)
            # Claim exactly once before sending. Provider/transport failure cannot
            # replay the same consent receipt or pretend an outbound call was free.
            preview["consumed"] = True
            self.backend.inspector_put("preview:" + preview["preview_id"], preview)
        data = explanations.apply(self.service, context, preview)
        with self.backend.transaction():
            authorization = self.service.authorizer(context, selected)
            if authorization.policy_revision != preview["policy_revision"]:
                raise Conflict("project policy changed during explanation")
            explanations.validate_snapshot(self.service, context, preview)
            return self.service.result(context, request, data=data)

    def preview_change(self, context, request):
        args = thaw(request.arguments)
        kind = args.get("kind")
        if kind not in KINDS:
            from luminary_memory.inspector import features
            return features.preview_change(self.service, context, request)
        authorization = self.service.authorizer(context, request)
        if kind in {"grant", "revoke", "bind_location"}:
            return self._preview_policy(context, request, kind, args)
        if kind == "create":
            content = self._content(args.get("content"))
            tags = self._tags(args.get("tags", []))
            if not authorization.can_contribute():
                raise PermissionError("contribute capability is required")
            return self.prepare(context, request, kind, {"content": content, "tags": tags},
                                after={"content": content, "tags": tags}, effects={"count": 1})
        memory_id = args.get("memory_id")
        if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id <= 0:
            raise ValueError("memory_id is required")
        memory = self.backend.get(memory_id)
        if memory is None:
            raise PermissionError("memory is not accessible")
        action = "retract" if kind == "retract" else "edit"
        authorization.require(action, memory)
        expected = args.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected != memory.revision:
            raise Conflict("content revision changed")
        payload = {"memory_id": memory_id, "expected_revision": expected}
        if kind == "correct":
            payload["content"] = self._content(args.get("content"))
        elif kind == "tag":
            payload["tags"] = self._tags(args.get("tags"))
        elif kind == "core":
            if not isinstance(args.get("pinned"), bool):
                raise ValueError("pinned must be a boolean")
            payload["pinned"] = args["pinned"]
        checks = {"revisions": {str(memory_id): expected}}
        if kind == "resolve_conflict":
            if not memory.claim_key:
                raise ValueError("memory has no conflict domain")
            self.backend.lock_claim_set(self._scope(memory), memory.claim_key)
            members = self._members(memory)
            claim_members = self.backend.inspector_claim_set(memory)
            from luminary_memory.inspector.queries import conflict_set_token
            if args.get("expected_conflict_set_token") != conflict_set_token(context, memory, members, claim_members):
                raise Conflict("observed conflict-set token is stale")
            for member in members:
                authorization.require("edit", member)
            checks["members"] = [[member.id, member.revision] for member in members]
            checks["claim_key"] = memory.claim_key
            checks["claim_members"] = claim_members
        can_read = authorization.permissions(memory)["read"]
        before = memory_view(memory, authorization.permissions(memory), full=True) if can_read else {"memory_id": memory_id, "revision": expected}
        after = {key: value for key, value in payload.items() if key not in {"expected_revision"}}
        return self.prepare(context, request, kind, payload, before=before, after=after,
                            effects={"count": len(checks.get("members", [memory_id]))}, checks=checks)

    @staticmethod
    def _content(content):
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 65536:
            raise ValueError("content must contain 1–65536 UTF-8 bytes")
        return content.strip()

    @staticmethod
    def _tags(tags):
        if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(tag, str) or not tag.strip() or len(tag.encode()) > 128 for tag in tags):
            raise ValueError("tags must be a bounded string list")
        return list(dict.fromkeys(tag.strip() for tag in tags))

    @staticmethod
    def _scope(memory):
        return {field: getattr(memory, field) for field in ("user_id", "workspace_id", "agent_id")}

    def _members(self, memory):
        return [member for member in self.backend.find_by_claim_key(memory.claim_key, scope=self._scope(memory))
                if member.status in {"active", "conflicted"}]

    def _preview_policy(self, context, request, kind, args):
        # This deployment has one trusted OS owner. Model JSON cannot invoke
        # confirm; preview alone is not authority to alter project policy.
        if request.selection_handle is not None:
            raise PermissionError("policy changes require the native own project")
        if kind == "bind_location":
            location = args.get("location")
            fields = ("workspace", "host_id", "profile_id")
            if not isinstance(location, dict) or set(location) != set(fields) or any(
                    not isinstance(location.get(field), str) or not location[field].strip() or len(location[field]) > 4096 for field in fields):
                raise ValueError("alias workspace, host and profile selectors are required")
            payload = {"location": {**{field: location[field].strip() for field in fields},
                                   "user_id": context.user_id, "agent_id": context.agent_id, "session_id": context.session_id}}
        else:
            recipient = args.get("recipient_agent_id")
            if not isinstance(recipient, str) or not recipient.strip() or len(recipient) > 128 or ":" in recipient:
                raise ValueError("recipient agent is required")
            if recipient == context.agent_id:
                raise ValueError("own-agent rights do not require a grant")
            payload = {"recipient_agent_id": recipient}
            if kind == "grant":
                capabilities = args.get("capabilities")
                if not isinstance(capabilities, list) or not capabilities or any(cap not in CAPABILITIES for cap in capabilities):
                    raise ValueError("explicit independent capabilities are required")
                payload["capabilities"] = sorted(set(capabilities))
        return self.prepare(context, request, kind, payload, after=payload, effects={"policy_change": True})

    def _apply(self, context, request, authorization, preview, *, on_external_effect):
        kind, payload = preview["kind"], preview["payload"]
        if kind in {"grant", "revoke", "bind_location"}:
            return self._apply_policy(context, kind, payload)
        if kind == "maintenance":
            return self._apply_maintenance(context, authorization, preview)
        if kind not in KINDS:
            from luminary_memory.inspector import features
            return features.apply_preview(self.service, context, preview, on_external_effect=on_external_effect)
        if kind == "create":
            if not authorization.can_contribute():
                raise PermissionError("contribute capability was revoked")
            writer = self.service.writer(context, workspace_id=authorization.workspace_id)
            observation = "inspector:" + preview["preview_id"]
            memory_id = writer.ingest(payload["content"], tags=payload["tags"], enrich=False,
                                      evidence_quote=payload["content"], source="inspector",
                                      source_id=observation, session_id=context.session_id)
            if memory_id is None:
                raise ValueError("configured ingestion policy rejected the content")
            memory = self.backend.get(memory_id)
            inserted = memory.source_id == observation
            return {"memory_id": memory_id, "revision": memory.revision, "audit": "committed",
                    "stored": int(inserted), "duplicates": int(not inserted)}
        memory = self.backend.get(payload["memory_id"])
        if memory is None:
            raise Conflict("resource was removed")
        authorization.require("retract" if kind == "retract" else "edit", memory)
        self.backend.lock_claim_set(self._scope(memory), memory.claim_key)
        if memory.revision != payload["expected_revision"]:
            raise Conflict("content revision changed")
        if kind == "resolve_conflict":
            members = self._members(memory)
            if ([[member.id, member.revision] for member in members] != preview["checks"]["members"]
                    or self.backend.inspector_claim_set(memory) != preview["checks"]["claim_members"]):
                raise Conflict("conflict-set membership changed")
            for member in members:
                authorization.require("edit", member)
                self.service.writer(context, memory=member).resolve_conflict(
                    member.id, status="active" if member.id == memory.id else "superseded")
        elif kind == "correct":
            successor_id = self.service.writer(context, memory=memory).supersede(
                memory.id, payload["content"], evidence_quote=payload["content"], claims=[],
                session_id=context.session_id, source="inspector", source_id="inspector:" + preview["preview_id"])
            if successor_id is None or successor_id == memory.id:
                raise Conflict("correction did not create a successor")
            memory = self.backend.get(successor_id)
        elif kind == "tag":
            memory.tags = payload["tags"]
            self.service.writer(context, memory=memory).update(memory)
        elif kind == "core":
            core_tag = str(getattr(self.service.client.settings, "core_tag", "core") or "core")
            memory.tags = [tag for tag in memory.tags if tag != core_tag]
            if payload["pinned"]:
                memory.tags.append(core_tag)
                memory.importance = max(memory.importance, 0.9)
            else:
                memory.importance = min(memory.importance, 0.89)
            self.service.writer(context, memory=memory).update(memory)
        elif kind == "retract":
            self.service.writer(context, memory=memory).retract(memory.id)
        memory = self.backend.get(memory.id)
        return {"memory_id": memory.id, "revision": memory.revision, "audit": "committed"}

    def _apply_policy(self, context, kind, payload):
        if kind == "bind_location":
            key = location_key(payload["location"])
            existing = self.backend.inspector_get(key)
            if existing is not None and existing != context.project_id:
                raise Conflict("alias already belongs to another project")
            self.backend.inspector_put(key, context.project_id)
        else:
            key = grant_key(context.project_id, payload["recipient_agent_id"], context.agent_id)
            if kind == "revoke":
                self.backend.inspector_remove(key)
            else:
                self.backend.inspector_put(key, {"project_id": context.project_id, "user_id": context.user_id,
                    "recipient_agent_id": payload["recipient_agent_id"], "grantor_agent_id": context.agent_id,
                    "capabilities": payload["capabilities"]})
        store = self.backend.inspector_get("store")
        store["policy_revision"] += 1
        self.backend.inspector_put("store", store)
        self.backend.record_event("inspector_" + kind, None, after={"user_id": context.user_id,
            "workspace_id": context.workspace_id, "agent_id": context.agent_id, "session_id": context.session_id}, actor="inspector-owner")
        return {"project_id": context.project_id, "policy_revision": store["policy_revision"], "audit": "committed"}

    def maintenance_preview(self, context, request):
        authorization = self.service.authorizer(context, request)
        args = thaw(request.arguments)
        kind = args.get("kind", "prune")
        if kind not in {"prune", "cleanup_expired"}:
            raise ValueError("manual maintenance supports prune or cleanup_expired")
        # Bound the proposal without changing the existing maintenance rules.
        memories = self.backend.inspector_memories(authorization.scopes("retract"), statuses=["active"], limit=1001)
        if len(memories) > 1000:
            raise ValueError("narrow maintenance scope to at most 1000 candidates")
        now = datetime.now(UTC)
        settings = self.service.client.settings
        if kind == "prune":
            from luminary_memory.lifecycle.prune import prune_candidates
            candidates = prune_candidates(memories, min_importance=args.get("min_importance", settings.prune_min_importance),
                                          max_count=args.get("max_count"), pin_threshold=getattr(settings, "rule_importance", 0.9))
        else:
            from luminary_memory.lifecycle.cleanup import expired_candidates
            candidates = expired_candidates(memories, now=now)
        for memory in candidates:
            authorization.require("retract", memory)
        checks = {"candidates": [{"memory_id": memory.id, "revision": memory.revision,
                                  "eligibility": digest([memory.importance, memory.access_count, memory.ttl_seconds, memory.observed_at, memory.created_at])}
                                 for memory in candidates]}
        visible = [memory_view(memory, authorization.permissions(memory)) if authorization.permissions(memory)["read"]
                   else {"memory_id": memory.id, "revision": memory.revision} for memory in candidates]
        return self.prepare(context, request, "maintenance", {"maintenance_kind": kind},
                            before=visible, after=[], effects={"count": len(candidates)}, checks=checks)

    def _apply_maintenance(self, context, authorization, preview):
        candidates = []
        for check in preview["checks"]["candidates"]:
            memory = self.backend.get(check["memory_id"])
            if memory is None or memory.revision != check["revision"] or check["eligibility"] != digest(
                    [memory.importance, memory.access_count, memory.ttl_seconds, memory.observed_at, memory.created_at]):
                raise Conflict("maintenance proposal is stale")
            authorization.require("retract", memory)
            candidates.append(memory)
        for memory in candidates:
            self.backend.record_event("manual_" + preview["payload"]["maintenance_kind"], memory.id,
                before={"content": memory.content, "status": memory.status, **self._scope(memory)}, actor="inspector-owner")
            self.backend.sync_claim_status(memory.id, "expired" if preview["payload"]["maintenance_kind"] == "cleanup_expired" else "deleted")
            self.backend.delete(memory.id)
        return {"count": len(candidates), "audit": "committed"}
