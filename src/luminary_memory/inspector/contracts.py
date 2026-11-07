"""Secret-safe protocol values. Native identity is never a ConsoleRequest field."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

STATUSES = frozenset({"ok", "empty", "invalid_request", "denied", "conflict", "unavailable",
                      "unsupported", "cancelled", "unknown_outcome"})


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@dataclass(frozen=True, slots=True)
class TrustedContext:
    store_id: str
    user_id: str
    project_id: str
    workspace_id: str
    agent_id: str
    session_id: str
    host_id: str
    profile_id: str
    context_epoch: str
    identity_token: str = field(repr=False)

    def to_dict(self):
        # The bearer identity token stays server-side.
        return {key: value for key, value in asdict(self).items() if key != "identity_token"}


@dataclass(frozen=True, slots=True)
class ConsoleRequest:
    operation: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = ""
    session_ref: str | None = None
    selection_handle: str | None = None

    def __post_init__(self):
        if not isinstance(self.operation, str) or not self.operation or len(self.operation) > 80:
            raise ValueError("invalid operation")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be an object")
        if not isinstance(self.request_id, str) or not self.request_id or len(self.request_id) > 200:
            raise ValueError("request_id is required")
        for value in (self.session_ref, self.selection_handle):
            if value is not None and (not isinstance(value, str) or len(value) > 512):
                raise ValueError("invalid reference")
        object.__setattr__(self, "arguments", freeze(self.arguments))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {"operation", "arguments", "request_id", "session_ref", "selection_handle"}:
            raise ValueError("invalid request envelope")
        return cls(**value)

    def to_dict(self):
        return {"operation": self.operation, "arguments": thaw(self.arguments), "request_id": self.request_id,
                "session_ref": self.session_ref, "selection_handle": self.selection_handle}


@dataclass(frozen=True, slots=True)
class ConsoleResult:
    status: str
    data: Any = None
    error: Mapping[str, str] | None = None
    request_id: str = ""
    context_epoch: str = ""
    policy_revision: int = 0
    as_of: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError("invalid result status")
        object.__setattr__(self, "data", freeze(self.data))
        object.__setattr__(self, "error", freeze(self.error))

    @classmethod
    def from_dict(cls, value):
        return cls(**value)

    def to_dict(self):
        return {"status": self.status, "data": thaw(self.data), "error": thaw(self.error),
                "request_id": self.request_id, "context_epoch": self.context_epoch,
                "policy_revision": self.policy_revision, "as_of": self.as_of}
