"""Hermes native route execution: commit operations are an explicit allowlist."""
from __future__ import annotations

import contextlib

import pytest

from luminary_memory.hermes import inspector


class Recorder:
    def __init__(self):
        self.requests = []

    def confirm(self, context, preview_id):
        return f"receipt-for-{preview_id}"

    def execute(self, context, request):
        self.requests.append(request)

        class Result:
            def to_dict(self):
                return {"operation": request.operation, "arguments": dict(request.arguments),
                        "request_id": request.request_id}

        return Result()


@pytest.fixture
def service(monkeypatch):
    recorder = Recorder()

    @contextlib.contextmanager
    def fake_service(session_ref, *, initialize=False):
        yield recorder, object()

    monkeypatch.setattr(inspector, "_service", fake_service)
    return recorder


def test_plain_payload_is_executed_as_an_inspector_request(service):
    result = inspector.execute_native({"operation": "browse", "arguments": {}, "request_id": "r1",
                                       "session_ref": "s1"})
    assert result["operation"] == "browse"
    assert service.requests[0].request_id == "r1"


def test_a_payload_without_an_operation_is_refused_by_the_envelope(service):
    with pytest.raises(TypeError):
        inspector.execute_native({"arguments": {}, "session_ref": "s1"})
    assert service.requests == []


@pytest.mark.parametrize("operation", ["mutate", "grant", "revoke", "set_settings",
                                      "maintenance_commit", "transfer_commit"])
def test_confirmed_commit_never_returns_the_receipt_to_the_caller(service, operation):
    result = inspector.execute_native({"session_ref": "s1", "request_id": "r1",
                                       "commit_operation": operation}, preview_id="preview-1")
    assert result["operation"] == operation
    assert result["arguments"]["preview_id"] == "preview-1"
    assert result["arguments"]["confirmation_receipt"] == "receipt-for-preview-1"


def test_explain_commit_is_marked_as_the_commit_phase(service):
    result = inspector.execute_native({"session_ref": "s1", "request_id": "r1",
                                       "commit_operation": "explain"}, preview_id="preview-2")
    assert (result["operation"], result["arguments"]["phase"]) == ("explain", "commit")


def test_an_unknown_commit_operation_is_refused(service):
    with pytest.raises(ValueError, match="Invalid commit operation"):
        inspector.execute_native({"session_ref": "s1", "commit_operation": "delete_everything"},
                                 preview_id="preview-3")
    assert service.requests == []


def test_a_commit_operation_outside_a_confirmation_is_refused(service):
    with pytest.raises(ValueError, match="invalid request envelope"):
        inspector.execute_native({"operation": "browse", "arguments": {}, "request_id": "r1",
                                  "session_ref": "s1", "commit_operation": "grant"})
    assert service.requests == []
