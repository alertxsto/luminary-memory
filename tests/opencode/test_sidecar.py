import io
import json

import pytest

from luminary_memory.config import Settings
from luminary_memory.ingest.llm import EnrichedContent, LLMEnricher
from luminary_memory.opencode.sidecar import Sidecar, run_jsonl
from luminary_memory.types import RecallResult


class FakeEngine:
    def embed(self, text):
        return [1.0, 0.0, 0.0]


class FakeEnricher(LLMEnricher):
    def enrich(self, text):
        return EnrichedContent(content=text, tags=["fake"])


def scope(user_id="user-1"):
    return {
        "user_id": user_id,
        "workspace_id": "workspace-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
    }


def request(request_id, operation, payload, request_scope=None):
    return {
        "protocol_version": "1",
        "request_id": request_id,
        "operation": operation,
        "scope": request_scope or scope(),
        "payload": payload,
    }


@pytest.fixture
def sidecar(tmp_path):
    settings = Settings(db_path=str(tmp_path / "memory.db"), importance_auto=False)
    return Sidecar(settings=settings, enricher=FakeEnricher(), engine=FakeEngine())


def decode(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_sidecar_dispatches_health_scoped_ingest_recall_and_list(sidecar):
    lines = "\n".join(
        [
            json.dumps(request("health-1", "health", {})),
            json.dumps(request("ingest-1", "ingest", {"content": "SQLite is used", "tags": ["db"]})),
            json.dumps(request("recall-1", "recall", {"query": "SQLite", "limit": 5})),
            json.dumps(request("list-1", "list", {"limit": 5})),
        ]
    )
    stdout, stderr = io.StringIO(), io.StringIO()

    run_jsonl(io.StringIO(lines), stdout, stderr, sidecar=sidecar)

    responses = decode(stdout)
    assert [response["request_id"] for response in responses] == [
        "health-1",
        "ingest-1",
        "recall-1",
        "list-1",
    ]
    assert all(response["status"] == "ok" for response in responses)
    assert responses[1]["result"]["accepted"] is True
    assert responses[2]["result"]["memories"][0]["content"] == "SQLite is used"
    assert responses[3]["result"]["memories"][0]["user_id"] == "user-1"
    assert stderr.getvalue() == ""


def test_sidecar_returns_structured_errors_with_request_id_and_no_payload_logging(sidecar):
    lines = "\n".join(
        [
            "not-json",
            json.dumps(request("unknown-1", "purge", {})),
            json.dumps(request("scope-1", "list", {}, {"user_id": "", "workspace_id": "w", "agent_id": "a"})),
        ]
    )
    stdout, stderr = io.StringIO(), io.StringIO()

    run_jsonl(io.StringIO(lines), stdout, stderr, sidecar=sidecar)

    responses = decode(stdout)
    assert len(responses) == 3
    assert all(response["status"] == "error" for response in responses)
    assert all("request_id" in response for response in responses)
    assert responses[0]["request_id"] == "unknown"
    assert responses[1]["request_id"] == "unknown-1"
    assert responses[2]["request_id"] == "scope-1"
    assert "not-json" not in stderr.getvalue()


def test_sidecar_rejects_ingest_that_attempts_to_change_bound_ownership(sidecar):
    stdout, stderr = io.StringIO(), io.StringIO()
    line = json.dumps(
        request(
            "ownership-1",
            "ingest",
            {"content": "private", "user_id": "other-user"},
        )
    )

    run_jsonl(io.StringIO(line), stdout, stderr, sidecar=sidecar)

    response = decode(stdout)[0]
    assert response["request_id"] == "ownership-1"
    assert response["status"] == "error"
    assert response["error"]["code"] == "invalid_request"
    assert sidecar.client_for(scope()).list(limit=0) == []
    assert stderr.getvalue() == ""


def test_sidecar_preserves_durable_scope_when_session_is_omitted(sidecar):
    stdout, stderr = io.StringIO(), io.StringIO()
    run_jsonl(
        io.StringIO(json.dumps(request("durable-1", "ingest", {"content": "durable"}, {
            "user_id": "user-1",
            "workspace_id": "workspace-1",
            "agent_id": "agent-1",
        }))),
        stdout,
        stderr,
        sidecar=sidecar,
    )

    result = decode(stdout)[0]["result"]
    assert result["accepted"] is True
    memory = sidecar.client_for(scope()).list(limit=1)[0]
    assert memory.session_id is None


def test_sidecar_uses_strict_recall_and_preserves_diagnostic_status():
    class RecallClient:
        strict = None

        def recall(self, query, *, limit, tags, strict):
            self.strict = strict
            return RecallResult(
                memories=[],
                scores=[],
                strategies_hit={},
                status="abstain",
                reason="low confidence",
                confidence=0.1,
            )

        def close(self):
            return None

    client = RecallClient()
    sidecar = Sidecar()
    sidecar.client_for = lambda request_scope: client

    stdout, stderr = io.StringIO(), io.StringIO()
    run_jsonl(
        io.StringIO(json.dumps(request("strict-1", "recall", {"query": "uncertain", "strict": True}))),
        stdout,
        stderr,
        sidecar=sidecar,
    )

    response = decode(stdout)[0]
    assert client.strict is True
    assert response["status"] == "ok"
    assert response["result"]["status"] == "abstain"
    assert response["result"]["reason"] == "low confidence"


def test_sidecar_recalls_durable_memory_across_sessions(tmp_path):
    settings = Settings(db_path=str(tmp_path / "cross-session.db"), importance_auto=False)
    first = Sidecar(settings=settings, enricher=FakeEnricher(), engine=FakeEngine())
    second = Sidecar(settings=settings, enricher=FakeEnricher(), engine=FakeEngine())
    stdout, stderr = io.StringIO(), io.StringIO()

    run_jsonl(
        io.StringIO(json.dumps(request("ingest-cross", "ingest", {"content": "SQLite survives sessions"}, {
            **scope(), "session_id": "session-one"
        }))),
        stdout,
        stderr,
        sidecar=first,
    )
    run_jsonl(
        io.StringIO(json.dumps(request("recall-cross", "recall", {"query": "SQLite survives", "limit": 5}, {
            **scope(), "session_id": "session-two"
        }))),
        stdout,
        stderr,
        sidecar=second,
    )

    responses = decode(stdout)
    assert responses[0]["result"]["accepted"] is True
    assert responses[1]["result"]["memories"][0]["content"] == "SQLite survives sessions"
    assert stderr.getvalue() == ""
