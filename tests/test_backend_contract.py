"""Third-party backend compatibility surface: documented no-op defaults stay usable."""
from __future__ import annotations

import pytest

from luminary_memory.backends.base import MemoryBackend
from luminary_memory.types import Memory


class LightweightBackend(MemoryBackend):
    """A minimal custom backend that implements only the abstract contract."""

    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def add(self, m: Memory) -> int:
        m.id = self.next_id
        self.rows[m.id] = m
        self.next_id += 1
        return m.id

    def get(self, id: int):
        return self.rows.get(id)

    def update(self, m: Memory) -> None:
        self.rows[m.id] = m

    def delete(self, id: int) -> None:
        self.rows.pop(id, None)

    def all(self):
        return list(self.rows.values())

    def keyword_search(self, query, limit, scope=None, include_global=True):
        return [(m, 1.0) for m in self.all()][:limit]

    def vector_search(self, vec, limit, scope=None, include_global=True):
        return [(m, 1.0) for m in self.all()][:limit]

    def count(self) -> int:
        return len(self.rows)


@pytest.fixture
def backend():
    return LightweightBackend()


def memory(**overrides):
    values = {"content": "The deploy target is staging", "user_id": "u1", "workspace_id": "w1", "agent_id": "pi"}
    values.update(overrides)
    return Memory(**values)


def test_transaction_default_is_a_no_op_scope(backend):
    assert backend.in_transaction is False
    with backend.transaction() as entered:
        assert entered is backend
    assert backend.in_transaction is False


def test_single_item_status_reports_a_new_row(backend):
    mid, inserted = backend.add_with_status(memory())
    assert inserted is True
    assert backend.get(mid) is not None


def test_batch_defaults_delegate_to_single_item_operations(backend):
    ids = backend.add_many([memory(content="alpha"), memory(content="beta")])
    assert ids == [1, 2]
    assert backend.add_many_with_status([memory(content="gamma")]) == [(3, True)]
    assert backend.count() == 3
    backend.delete_many([1, 2])
    assert sorted(backend.rows) == [3]
    assert set(backend.get_many([1, 3])) == {3}


def test_optional_audit_and_provenance_defaults_are_explicit_no_ops(backend):
    mid = backend.add(memory())
    assert backend.record_event("create", mid) is None
    assert backend.add_evidence(mid, "The deploy target is staging") is None
    assert backend.record_episode("episode-1", "content") is None
    assert backend.recent_episodes() == []
    assert backend.add_claim(mid, {"subject": "deploy", "predicate": "target"}) is None
    assert backend.sync_claim_status(mid, "superseded") is None
    assert backend.rehome_memory_references(mid, mid) is None


def test_duplicate_lookup_matches_the_full_scoped_observation(backend):
    row = memory(content_hash="hash-1", created_at="2026-01-01T00:00:00+00:00", status="active")
    mid = backend.add(row)
    same = "2026-01-01T00:00:00+00:00"
    assert backend.find_import_duplicate_id(memory(content_hash="hash-1", created_at=same)) == mid
    assert backend.find_import_duplicate_id(memory(content_hash="hash-1",
                                                   created_at="2026-01-02T00:00:00+00:00")) is None
    assert backend.find_import_duplicate_id(memory(content_hash="", created_at=same)) is None
    assert backend.find_import_duplicate_id(memory(content_hash="hash-1", created_at=same,
                                                   session_id="other")) is None


def test_exact_hash_lookup_never_treats_no_scope_as_every_tenant(backend):
    full_scope = {"user_id": "u1", "workspace_id": "w1", "agent_id": "pi"}
    mid = backend.add(memory(content_hash="hash-1"))
    backend.add(memory(content_hash="hash-1", user_id="someone-else"))
    global_id = backend.add(Memory(content="Global fact", content_hash="hash-global"))
    assert backend.find_by_hash("hash-1") is None
    assert backend.find_by_hash("hash-global").id == global_id
    assert backend.find_by_hash("hash-1", full_scope).id == mid
    assert backend.find_by_hash("hash-1", {"user_id": "nobody"}) is None
    assert backend.find_by_hash("absent") is None


def test_claim_key_lookup_includes_superseded_claims_for_history(backend):
    full_scope = {"user_id": "u1", "workspace_id": "w1", "agent_id": "pi"}
    backend.add(memory(claim_key="deploy.target", status="active"))
    backend.add(memory(claim_key="deploy.target", status="superseded"))
    backend.add(memory(claim_key="deploy.target", user_id="someone-else", status="active"))
    statuses = [m.status for m in backend.find_by_claim_key("deploy.target", full_scope)]
    assert sorted(statuses) == ["active", "superseded"]
    assert backend.find_by_claim_key("absent.target", full_scope) == []
