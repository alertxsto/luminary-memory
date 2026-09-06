import json

import pytest

from luminary_memory.opencode.protocol import (
    OpenCodeRequest,
    OpenCodeResponse,
    OpenCodeScope,
    ProtocolValidationError,
)


def scope_dict() -> dict[str, str]:
    return {
        "user_id": "user-1",
        "workspace_id": "repo-1",
        "agent_id": "build",
        "session_id": "session-1",
    }


def test_request_round_trips_with_operation_payload_and_deterministic_json():
    request = OpenCodeRequest.from_dict(
        {
            "protocol_version": "1",
            "request_id": "request-1",
            "operation": "recall",
            "scope": scope_dict(),
            "payload": {"query": "deployment preference", "limit": 3},
        }
    )

    encoded = request.to_json()
    assert encoded == (
        '{"operation":"recall","payload":{"limit":3,"query":"deployment preference"},'
        '"protocol_version":"1","request_id":"request-1",'
        '"scope":{"agent_id":"build","session_id":"session-1",'
        '"user_id":"user-1","workspace_id":"repo-1"}}'
    )
    assert OpenCodeRequest.from_json(encoded) == request


@pytest.mark.parametrize(
    "operation, payload",
    [
        ("health", {}),
        ("recall", {"query": "remember this"}),
        ("ingest", {"content": "The build uses SQLite", "tags": ["project"]}),
        ("list", {"limit": 10, "cursor": "page-2"}),
    ],
)
def test_each_initial_operation_round_trips(operation, payload):
    request = OpenCodeRequest.from_dict(
        {
            "protocol_version": "1",
            "request_id": f"{operation}-1",
            "operation": operation,
            "scope": scope_dict(),
            "payload": payload,
        }
    )

    assert OpenCodeRequest.from_json(request.to_json()) == request


@pytest.mark.parametrize(
    "missing",
    ["protocol_version", "request_id", "operation", "scope", "payload"],
)
def test_request_requires_envelope_fields(missing):
    value = {
        "protocol_version": "1",
        "request_id": "request-1",
        "operation": "health",
        "scope": scope_dict(),
        "payload": {},
    }
    del value[missing]

    with pytest.raises(ProtocolValidationError):
        OpenCodeRequest.from_dict(value)


def test_request_rejects_unknown_operation():
    value = {
        "protocol_version": "1",
        "request_id": "request-1",
        "operation": "purge",
        "scope": scope_dict(),
        "payload": {},
    }

    with pytest.raises(ProtocolValidationError, match="unknown operation"):
        OpenCodeRequest.from_dict(value)


@pytest.mark.parametrize(
    "operation, payload",
    [
        ("recall", {}),
        ("ingest", {}),
        ("list", {"limit": "many"}),
        ("health", {"unexpected": True}),
    ],
)
def test_request_validates_operation_payload(operation, payload):
    value = {
        "protocol_version": "1",
        "request_id": "request-1",
        "operation": operation,
        "scope": scope_dict(),
        "payload": payload,
    }

    with pytest.raises(ProtocolValidationError):
        OpenCodeRequest.from_dict(value)


def test_scope_serializes_to_luminary_identity_fields():
    scope = OpenCodeScope.from_dict(scope_dict())

    assert scope.to_dict() == scope_dict()
    assert OpenCodeScope.from_dict(scope.to_dict()) == scope


def test_scope_allows_durable_cross_session_requests_without_session_id():
    scope = OpenCodeScope.from_dict(
        {"user_id": "user-1", "workspace_id": "repo-1", "agent_id": "build"}
    )

    assert scope.session_id is None
    assert scope.to_dict() == {
        "user_id": "user-1",
        "workspace_id": "repo-1",
        "agent_id": "build",
    }


def test_response_round_trips_structured_error_without_diagnostics():
    response = OpenCodeResponse.from_error(
        request_id="request-1",
        code="invalid_request",
        message="payload is malformed",
    )

    decoded = json.loads(response.to_json())
    assert decoded == {
        "error": {"code": "invalid_request", "message": "payload is malformed"},
        "protocol_version": "1",
        "request_id": "request-1",
        "status": "error",
    }
    assert "diagnostics" not in decoded
    assert OpenCodeResponse.from_json(response.to_json()) == response


def test_success_response_has_no_error_value():
    response = OpenCodeResponse.ok(request_id="request-1", result={"healthy": True})

    assert response.error is None
    assert response.to_dict()["result"] == {"healthy": True}


def test_malformed_input_raises_public_validation_exception():
    with pytest.raises(ProtocolValidationError):
        OpenCodeRequest.from_json("not-json")

    with pytest.raises(ProtocolValidationError):
        OpenCodeScope.from_dict({"user_id": "user-1"})
