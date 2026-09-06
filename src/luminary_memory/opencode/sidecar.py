"""JSONL process boundary for the OpenCode memory integration."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import LLMEnricher
from luminary_memory.opencode.protocol import ProtocolValidationError, Request, Response
from luminary_memory.types import Memory, RecallResult

logger = logging.getLogger(__name__)
_SCOPE_FIELDS = ("user_id", "workspace_id", "agent_id", "session_id")


def _memory_to_dict(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "content": memory.content,
        "metadata": memory.metadata,
        "source": memory.source,
        "tags": memory.tags,
        "importance": memory.importance,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "user_id": memory.user_id,
        "session_id": memory.session_id,
        "workspace_id": memory.workspace_id,
        "agent_id": memory.agent_id,
        "observed_at": memory.observed_at,
        "valid_from": memory.valid_from,
        "valid_to": memory.valid_to,
        "status": memory.status,
        "confidence": memory.confidence,
        "evidence_quote": memory.evidence_quote,
        "source_id": memory.source_id,
        "claim_key": memory.claim_key,
    }


def _recall_to_dict(result: RecallResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "reason": result.reason,
        "confidence": result.confidence,
        "memories": [_memory_to_dict(memory) for memory in result.memories],
        "scores": result.scores,
        "strategies_hit": result.strategies_hit,
        "provenance": result.provenance,
    }


def _request_id(value: str) -> str:
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ""
    return data.get("request_id", "") if isinstance(data, dict) and isinstance(data.get("request_id"), str) else ""


def _error_response(request_id: str, exc: Exception) -> Response:
    if isinstance(exc, ProtocolValidationError):
        code = "invalid_request"
    elif isinstance(exc, PermissionError):
        code = "permission_denied"
    elif isinstance(exc, (ValueError, TypeError)):
        code = "operation_failed"
    else:
        code = "internal_error"
    message = str(exc) if code != "internal_error" else "sidecar operation failed"
    return Response.from_error(request_id or "unknown", code, message or code)


class Sidecar:
    """Build scoped clients and dispatch the four initial operations."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        enricher: LLMEnricher | None = None,
        engine: Any = None,
    ) -> None:
        self.settings = settings or Settings()
        self.enricher = enricher
        self.engine = engine

    def client_for(self, scope: dict[str, str]) -> MemoryClient:
        return MemoryClient(
            settings=self.settings,
            scope=scope,
            enricher=self.enricher,
            engine=self.engine,
        )

    def dispatch(self, request: Request) -> Response:
        scope = request.scope.to_dict()
        if request.operation in {"ingest", "recall", "list"}:
            scope.pop("session_id", None)
        client = self.client_for(scope)
        try:
            payload = request.payload
            if request.operation == "health":
                return Response.ok(request.request_id, client.health_score())
            if request.operation == "ingest":
                if any(field in payload for field in _SCOPE_FIELDS):
                    raise ProtocolValidationError(
                        "ingest payload cannot set ownership fields"
                    )
                memory_id = client.ingest(
                    payload["content"],
                    tags=payload.get("tags"),
                    source=payload.get("source"),
                    metadata=payload.get("metadata"),
                )
                return Response.ok(
                    request.request_id,
                    {"accepted": memory_id is not None, "id": memory_id},
                )
            if request.operation == "recall":
                result = client.recall(
                    payload["query"],
                    limit=payload.get("limit", 10),
                    tags=payload.get("tags"),
                    strict=payload.get("strict"),
                )
                return Response.ok(request.request_id, _recall_to_dict(result))
            if request.operation == "list":
                limit = payload.get("limit", 100)
                offset = _cursor_offset(payload.get("cursor"))
                memories = client.list(limit=limit, offset=offset)
                next_cursor = None
                if limit and len(memories) == limit:
                    next_cursor = str(offset + len(memories))
                return Response.ok(
                    request.request_id,
                    {
                        "memories": [_memory_to_dict(memory) for memory in memories],
                        "count": len(memories),
                        "next_cursor": next_cursor,
                    },
                )
            raise ProtocolValidationError(f"unknown operation: {request.operation!r}")
        finally:
            client.close()


def _cursor_offset(cursor: Any) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError) as exc:
        raise ProtocolValidationError("payload.cursor must be a numeric cursor") from exc
    if offset < 0:
        raise ProtocolValidationError("payload.cursor must not be negative")
    return offset


def run_jsonl(
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    *,
    sidecar: Sidecar | None = None,
) -> None:
    service = sidecar or Sidecar()
    for line in stdin:
        if not line.strip():
            continue
        request_id = _request_id(line)
        try:
            response = service.dispatch(Request.from_json(line))
        except Exception as exc:  # noqa: BLE001 - isolate every JSONL request
            response = _error_response(request_id, exc)
        stdout.write(response.to_json() + "\n")
        stdout.flush()


def main() -> int:
    try:
        run_jsonl()
    except Exception as exc:  # noqa: BLE001 - process setup boundary
        print(f"luminary-memory-opencode: setup failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
