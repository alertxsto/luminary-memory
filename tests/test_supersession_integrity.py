"""Observable ownership, lineage, and transaction invariants for versioned claims."""

import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings


class ConstantEngine:
    def embed(self, text):
        return [1.0, 0.0]

    def embed_batch(self, texts):
        return [self.embed(text) for text in texts]


def client_at(tmp_path, name="claims.db", **settings):
    db = tmp_path / name
    return MemoryClient(settings=Settings(db_path=str(db), **settings), engine=ConstantEngine())


def test_explicit_version_preserves_other_claim_and_appends_new_row(tmp_path):
    client = client_at(tmp_path)
    alice = client.ingest("Alice works at Acme", enrich=False, claim_key="alice-employer", user_id="alice")
    bob = client.ingest("Bob likes green", enrich=False, claim_key="bob-color", user_id="alice")
    replacement = client.ingest(
        "Alice works at Beta", enrich=False, claim_key="alice-employer",
        user_id="alice", supersedes_id=alice,
    )
    assert replacement not in (alice, bob)
    assert client.backend.get(alice).status == "superseded"
    assert client.backend.get(bob).content == "Bob likes green"
    assert client.backend.get(bob).status == "active"
    assert client.backend.get(replacement).supersedes_id == alice
    assert client.backend.get(replacement).status == "active"
    client.close()


@pytest.mark.parametrize("reference", ["missing", "other_owner", "other_key", "retired"])
def test_invalid_predecessor_rejected_without_writes(tmp_path, reference):
    client = client_at(tmp_path)
    current = client.ingest("Alice works at Acme", enrich=False, claim_key="employer", user_id="alice")
    other_owner = client.ingest("Bob works at Beta", enrich=False, claim_key="employer", user_id="bob")
    other_key = client.ingest("Alice likes red", enrich=False, claim_key="color", user_id="alice")
    retired = client.ingest("Alice's old address", enrich=False, claim_key="address", user_id="alice", status="superseded")
    target = {"missing": 99999, "other_owner": other_owner, "other_key": other_key, "retired": retired}[reference]
    with pytest.raises(ValueError, match="supersed"):
        client.ingest("Alice works at Gamma", enrich=False, claim_key="employer", user_id="alice", supersedes_id=target)
    assert [(m.id, m.content, m.status) for m in client.backend.all()] == [
        (current, "Alice works at Acme", "active"),
        (other_owner, "Bob works at Beta", "active"),
        (other_key, "Alice likes red", "active"),
        (retired, "Alice's old address", "superseded"),
    ]
    client.close()


def test_insert_failure_rolls_back_predecessor_and_derived_claim(tmp_path):
    client = client_at(tmp_path)
    parent = client.ingest(
        "Alice works at Acme", enrich=False, claim_key="employer",
        metadata={"claims": [{"subject": "Alice", "predicate": "works at", "object": "Acme", "evidence_quote": "Alice works at Acme"}]},
    )
    client.backend.conn.execute(
        "CREATE TRIGGER block_beta BEFORE INSERT ON memories "
        "WHEN NEW.content = 'Alice works at Beta' BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )
    with pytest.raises(Exception, match="blocked"):
        client.ingest("Alice works at Beta", enrich=False, claim_key="employer", supersedes_id=parent)
    assert client.backend.get(parent).status == "active"
    assert client.backend.get(parent).valid_to is None
    assert client.backend.count() == 1
    assert client.backend.conn.execute("SELECT status FROM claims WHERE memory_id = ?", (parent,)).fetchone()[0] == "active"
    client.close()


def test_batch_same_key_matches_sequential_conflicts_and_duplicates(tmp_path):
    client = client_at(tmp_path)
    ids = client.ingest_batch(
        ["Alice works at Acme", "Alice works at Beta", "Alice works at Acme"],
        metadata=[{"claim_key": "employer"}] * 3, enrich=False,
    )
    assert ids[0] == ids[2]
    assert ids[0] != ids[1]
    assert [(m.content, m.status) for m in client.backend.all()] == [
        ("Alice works at Acme", "conflicted"),
        ("Alice works at Beta", "conflicted"),
    ]
    client.close()


def test_batch_explicit_reference_rejected_before_any_retirement(tmp_path):
    client = client_at(tmp_path)
    parent = client.ingest("Alice works at Acme", claim_key="employer", enrich=False)
    with pytest.raises(ValueError, match="supersed"):
        client.ingest_batch(["Alice works at Beta"], metadata=[{"claim_key": "employer"}], enrich=False, supersedes_id=99999)
    assert client.backend.get(parent).status == "active"
    assert client.backend.count() == 1
    client.close()


def test_invalid_predecessor_fails_before_duplicate_and_checks_all_scope_fields(tmp_path):
    client = client_at(tmp_path)
    parent = client.ingest(
        "Alice works at Acme", claim_key="employer", enrich=False,
        user_id="alice", workspace_id="workspace", agent_id="assistant", session_id="first",
    )
    with pytest.raises(ValueError, match="supersed"):
        client.ingest(
            "Alice works at Acme", claim_key="employer", enrich=False,
            user_id="alice", workspace_id="workspace", agent_id="assistant",
            session_id="first", supersedes_id=99999,
        )
    with pytest.raises(ValueError, match="supersed"):
        client.ingest(
            "Alice works at Beta", claim_key="employer", enrich=False,
            user_id="alice", workspace_id="workspace", agent_id="assistant",
            session_id="second", supersedes_id=parent,
        )
    assert client.backend.get(parent).status == "active"
    assert client.backend.count() == 1
    client.close()


def test_batch_explicit_supersession_keeps_other_same_key_conflict(tmp_path):
    client = client_at(tmp_path)
    first = client.ingest("Alice works at Acme", claim_key="employer", enrich=False)
    other = client.ingest("Alice works at Beta", claim_key="employer", enrich=False)
    [new] = client.ingest_batch(
        ["Alice works at Gamma"], metadata=[{"claim_key": "employer"}],
        enrich=False, supersedes_id=first,
    )
    assert client.backend.get(first).status == "superseded"
    assert client.backend.get(other).status == "conflicted"
    assert client.backend.get(new).status == "active"
    assert client.backend.get(new).supersedes_id == first
    client.close()


def test_successor_cannot_claim_unrelated_identical_content(tmp_path):
    client = client_at(tmp_path)
    parent = client.ingest("Alice works at Acme", claim_key="employer", enrich=False)
    unrelated = client.ingest("Alice likes blue", claim_key="color", enrich=False)
    with pytest.raises(ValueError, match="supersed"):
        client.ingest(
            "Alice likes blue", claim_key="employer", enrich=False,
            supersedes_id=parent,
        )
    assert client.backend.get(parent).status == "active"
    assert client.backend.get(unrelated).content == "Alice likes blue"
    assert client.backend.count() == 2
    client.close()
