"""Host-neutral JSON contracts for the OpenCode memory sidecar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "1"
OPERATIONS = frozenset({"health", "recall", "ingest", "list"})


class ProtocolValidationError(ValueError):
    """Raised when a protocol value cannot be decoded or validated."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolValidationError(f"{name} must be an object")
    return value


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolValidationError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class OpenCodeScope:
    user_id: str
    workspace_id: str
    agent_id: str
    session_id: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> OpenCodeScope:
        data = _object(value, "scope")
        session_id = data.get("session_id")
        if session_id is not None:
            session_id = _required_string(session_id, "scope.session_id")
        return cls(
            user_id=_required_string(data.get("user_id"), "scope.user_id"),
            workspace_id=_required_string(data.get("workspace_id"), "scope.workspace_id"),
            agent_id=_required_string(data.get("agent_id"), "scope.agent_id"),
            session_id=session_id,
        )

    def to_dict(self) -> dict[str, str]:
        value = {
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
        }
        if self.session_id is not None:
            value["session_id"] = self.session_id
        return value


def _validate_payload(operation: str, payload: Any) -> dict[str, Any]:
    data = _object(payload, "payload")
    if operation == "health":
        if data:
            raise ProtocolValidationError("health payload must be empty")
    elif operation == "recall":
        _required_string(data.get("query"), "payload.query")
        if "limit" in data and (
            isinstance(data["limit"], bool)
            or not isinstance(data["limit"], int)
            or data["limit"] < 1
        ):
            raise ProtocolValidationError("payload.limit must be a positive integer")
    elif operation == "ingest":
        _required_string(data.get("content"), "payload.content")
        if "tags" in data and (
            not isinstance(data["tags"], list)
            or not all(isinstance(tag, str) and tag.strip() for tag in data["tags"])
        ):
            raise ProtocolValidationError("payload.tags must be a list of non-empty strings")
    elif operation == "list":
        if "limit" in data and (
            isinstance(data["limit"], bool)
            or not isinstance(data["limit"], int)
            or data["limit"] < 1
        ):
            raise ProtocolValidationError("payload.limit must be a positive integer")
        if "cursor" in data and not isinstance(data["cursor"], str):
            raise ProtocolValidationError("payload.cursor must be a string")
    return data


@dataclass(frozen=True)
class OpenCodeRequest:
    protocol_version: str
    request_id: str
    operation: str
    scope: OpenCodeScope
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: Any) -> OpenCodeRequest:
        data = _object(value, "request")
        required = ("protocol_version", "request_id", "operation", "scope", "payload")
        missing = [field for field in required if field not in data]
        if missing:
            raise ProtocolValidationError(f"request missing required field(s): {', '.join(missing)}")
        version = _required_string(data["protocol_version"], "protocol_version")
        if version != PROTOCOL_VERSION:
            raise ProtocolValidationError(f"unsupported protocol version: {version!r}")
        request_id = _required_string(data["request_id"], "request_id")
        operation = _required_string(data["operation"], "operation")
        if operation not in OPERATIONS:
            raise ProtocolValidationError(f"unknown operation: {operation!r}")
        return cls(
            protocol_version=version,
            request_id=request_id,
            operation=operation,
            scope=OpenCodeScope.from_dict(data["scope"]),
            payload=_validate_payload(operation, data["payload"]),
        )

    @classmethod
    def from_json(cls, value: str) -> OpenCodeRequest:
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProtocolValidationError("request is not valid JSON") from exc
        return cls.from_dict(decoded)

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "operation": self.operation,
            "scope": self.scope.to_dict(),
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class OpenCodeResponse:
    request_id: str
    status: str
    result: Any = None
    error: dict[str, str] | None = None
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def ok(cls, request_id: str, result: Any = None) -> OpenCodeResponse:
        return cls(request_id=_required_string(request_id, "request_id"), status="ok", result=result)

    @classmethod
    def from_error(cls, request_id: str, code: str, message: str) -> OpenCodeResponse:
        return cls(
            request_id=_required_string(request_id, "request_id"),
            status="error",
            error={
                "code": _required_string(code, "error.code"),
                "message": _required_string(message, "error.message"),
            },
        )

    @classmethod
    def from_dict(cls, value: Any) -> OpenCodeResponse:
        data = _object(value, "response")
        version = data.get("protocol_version")
        if version != PROTOCOL_VERSION:
            raise ProtocolValidationError("unsupported or missing response protocol version")
        request_id = _required_string(data.get("request_id"), "request_id")
        status = data.get("status")
        if status not in {"ok", "error"}:
            raise ProtocolValidationError("response.status must be 'ok' or 'error'")
        if status == "error":
            error = _object(data.get("error"), "response.error")
            return cls.from_error(request_id, error.get("code"), error.get("message"))
        return cls(request_id=request_id, status="ok", result=data.get("result"))

    @classmethod
    def from_json(cls, value: str) -> OpenCodeResponse:
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProtocolValidationError("response is not valid JSON") from exc
        return cls.from_dict(decoded)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "status": self.status,
        }
        if self.status == "ok":
            value["result"] = self.result
        else:
            value["error"] = self.error
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


Scope = OpenCodeScope
Request = OpenCodeRequest
Response = OpenCodeResponse
