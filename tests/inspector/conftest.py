"""Behavioral inspector tests, selectable against real SQLite or PostgreSQL."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import NoopEnricher
from luminary_memory.types import Memory


def pytest_addoption(parser):
    parser.addoption("--inspector-backend", choices=("sqlite", "pgvector"), default="sqlite")


class Engine:
    def embed(self, text):
        return [1.0, float(len(text) + 1), 0.5]

    def embed_batch(self, texts):
        return [self.embed(text) for text in texts]


@dataclass
class Scenario:
    client: MemoryClient
    service: object
    context: object
    native: dict
    own_id: int
    foreign_id: int
    peer_id: int
    other_project_id: int

    def snapshot(self):
        backend = self.client.backend
        result = {}
        for table in ("memories", "memory_events", "memory_evidence", "claims", "claim_evidence", "episodes", "relations", "entities"):
            rows = backend.conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            result[table] = [tuple(row) for row in rows]
        return result

    def request(self, operation, context=None, selection_handle=None, **arguments):
        from luminary_memory.inspector.contracts import ConsoleRequest
        return self.service.execute(context or self.context, ConsoleRequest(
            operation=operation, arguments=arguments, request_id=uuid.uuid4().hex,
            selection_handle=selection_handle,
        ))

    def preview(self, kind, **arguments):
        if kind == "resolve_conflict" and "expected_conflict_set_token" not in arguments:
            detail = self.request("detail", memory_id=arguments["memory_id"])
            assert detail.status == "ok"
            arguments["expected_conflict_set_token"] = detail.data["conflict_set_token"]
        result = self.request("preview_change", kind=kind, **arguments)
        assert result.status == "ok", result.to_dict()
        return result.data["preview_id"]

    def commit(self, preview_id, context=None):
        receipt = self.service.confirm(context or self.context, preview_id)
        return self.request("mutate", context=context, preview_id=preview_id, confirmation_receipt=receipt)


@pytest.fixture
def scenario(tmp_path, request):
    from luminary_memory.inspector.identity import resolve_context
    from luminary_memory.inspector.service import InspectorService
    if request.config.getoption("--inspector-backend") == "pgvector":
        import psycopg
        from psycopg.conninfo import make_conninfo

        from luminary_memory.backends.pgvector import PGVectorBackend
        dsn = os.environ.get("LUMINARY_PG_DSN") or os.environ.get("PG_DSN")
        if not dsn:
            pytest.fail("Explicit pgvector inspector mode requires an isolated LUMINARY_PG_DSN/PG_DSN")
        admin = psycopg.connect(dsn, autocommit=True)
        schema = "inspector_test_" + uuid.uuid4().hex
        admin.execute(f'CREATE SCHEMA "{schema}"')
        backend = PGVectorBackend(dsn=make_conninfo(dsn, options=f"-c search_path={schema},public"), embedding_dim=3)
    else:
        from luminary_memory.backends.sqlite import SQLiteBackend
        backend = SQLiteBackend(str(tmp_path / "inspector.db"))
    settings = Settings(db_path=str(tmp_path / "inspector.db"), scope_include_global=False)
    client = MemoryClient(settings=settings, backend=backend, engine=Engine(),
                          enricher=NoopEnricher(), scope={"user_id": "alice", "workspace_id": "project-a", "agent_id": "pi"})
    def seed(content, user="alice", workspace="project-a", agent="pi", **kwargs):
        memory = Memory(content=content, user_id=user, workspace_id=workspace, agent_id=agent,
                        evidence_quote=content, **kwargs)
        memory.id = backend.add(memory)
        backend.add_evidence(memory.id, content)
        backend.record_event("create", memory.id, after={"content": content, "user_id": user,
                              "workspace_id": workspace, "agent_id": agent})
        return memory.id
    own = seed("Own deployment target is staging.", tags=["deployment"], claim_key="deploy")
    foreign = seed("Bob private marker BOB_SECRET", user="bob")
    peer = seed("OMP private marker PEER_SECRET", agent="omp")
    other = seed("Other project marker OTHER_SECRET", workspace="project-b")
    seed("Global marker GLOBAL_SECRET", user=None, workspace=None, agent=None)
    seed("Partial marker PARTIAL_SECRET", agent=None)
    native = {"user_id": "alice", "workspace": "project-a", "agent_id": "pi",
              "session_id": "session-1", "host_id": "host-a", "profile_id": "default"}
    context = resolve_context(client, native, initialize=True)
    value = Scenario(client, InspectorService(client), context, native, own, foreign, peer, other)
    yield value
    client.close()
    if request.config.getoption("--inspector-backend") == "pgvector":
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()
