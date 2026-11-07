"""Project resource grants never clear or weaken an agent's native scope."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from luminary_memory.inspector.identity import validate_context

CAPABILITIES = ("read", "contribute", "edit", "retract")


def grant_key(project_id, recipient, grantor):
    return "grant:" + project_id + ":" + recipient + ":" + grantor


class Authorizer:
    def __init__(self, client, context, selection_handle=None):
        self.client = client
        self.backend = client.backend
        self.context = context
        self.store = validate_context(client, context)
        self.policy_revision = int(self.store["policy_revision"])
        self.project_id = context.project_id
        self.workspace_id = context.workspace_id
        self.shared = selection_handle is not None
        if self.shared:
            from luminary_memory.inspector.queries import decode_token
            try:
                handle = decode_token(context, selection_handle)
            except ValueError as exc:
                raise PermissionError("selection is invalid") from exc
            if (not handle or handle["context_epoch"] != context.context_epoch
                    or handle["policy_revision"] != self.policy_revision
                    or datetime.fromisoformat(handle["expires_at"]) <= datetime.now(UTC)):
                raise PermissionError("selection is expired or revoked")
            project = self.backend.inspector_get("project:" + handle["project_id"])
            if not project or project["owner"] != context.user_id:
                raise PermissionError("project is unavailable")
            self.project_id = project["project_id"]
            self.workspace_id = project["workspace_id"]
        self.grants = [grant for _, grant in self.backend.inspector_scan("grant:" + self.project_id + ":")
                       if grant["recipient_agent_id"] == context.agent_id and grant["user_id"] == context.user_id]
        if self.shared and self.project_id != context.project_id and not self.grants:
            raise PermissionError("project has no selected grant")

    def permissions(self, memory):
        rights = {capability: False for capability in CAPABILITIES}
        if memory.user_id != self.context.user_id or memory.workspace_id != self.workspace_id or not memory.agent_id:
            return rights
        if self.project_id == self.context.project_id and memory.agent_id == self.context.agent_id:
            return dict.fromkeys(CAPABILITIES, True)
        if self.shared:
            for grant in self.grants:
                if grant["grantor_agent_id"] == memory.agent_id:
                    for capability in grant["capabilities"]:
                        rights[capability] = True
        return rights

    def require(self, action, memory):
        if action not in CAPABILITIES or not self.permissions(memory)[action]:
            raise PermissionError("resource capability is not granted")

    def scopes(self, action):
        if action not in CAPABILITIES:
            raise ValueError("unknown resource capability")
        agents = set()
        if self.project_id == self.context.project_id:
            agents.add(self.context.agent_id)
        if self.shared:
            agents.update(grant["grantor_agent_id"] for grant in self.grants if action in grant["capabilities"])
        return [{"user_id": self.context.user_id, "workspace_id": self.workspace_id, "agent_id": agent}
                for agent in sorted(agents)]

    def can_contribute(self):
        return self.project_id == self.context.project_id or any("contribute" in grant["capabilities"] for grant in self.grants)


def authorize(context, action, resource, *, client, selection_handle=None):
    authorization = Authorizer(client, context, selection_handle)
    authorization.require(action, resource)
    return authorization.permissions(resource)


def selection_handle(client, context, project_id):
    store = validate_context(client, context)
    project = client.backend.inspector_get("project:" + project_id)
    if not project or project["owner"] != context.user_id:
        raise PermissionError("project is not accessible")
    if project_id != context.project_id:
        grants = client.backend.inspector_scan("grant:" + project_id + ":")
        if not any(grant["recipient_agent_id"] == context.agent_id for _, grant in grants):
            raise PermissionError("project has no grant")
    from luminary_memory.inspector.queries import encode_token
    return encode_token(context, {
        "context_epoch": context.context_epoch, "project_id": project_id,
        "policy_revision": store["policy_revision"], "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    })
