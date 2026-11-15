import sqlite3

import pytest

from luminary_memory.backends.sqlite import SQLiteBackend

ALICE = {"user_id": "alice", "workspace_id": "work", "agent_id": "agent"}
BOB = {"user_id": "bob", "workspace_id": "work", "agent_id": "agent"}


@pytest.fixture
def store():
    backend = SQLiteBackend(":memory:")
    yield backend
    backend.close()


def test_episode_pruning_preserves_all_referenced_sources_and_reports_overflow(store):
    conn = store.conn
    for name in ("memory", "evidence", "claim", "claim_evidence", "free", "bob"):
        owner = "bob" if name == "bob" else "alice"
        conn.execute(
            "INSERT INTO episodes(id, content, user_id, workspace_id, agent_id, created_at) "
            "VALUES (?, ?, ?, 'work', 'agent', '2020-01-01')", (name, name, owner)
        )
    memory = conn.execute(
        "INSERT INTO memories(content, status, source_id, user_id, workspace_id, agent_id) "
        "VALUES ('fact', 'active', 'memory', 'alice', 'work', 'agent') RETURNING id"
    ).fetchone()[0]
    conn.execute("INSERT INTO memory_evidence(memory_id, quote, source_id) VALUES (?, 'quote', 'evidence')", (memory,))
    claim = conn.execute(
        "INSERT INTO claims(memory_id, subject, predicate, object, status, source_episode_id) "
        "VALUES (?, 's', 'p', 'o', 'conflicted', 'claim') RETURNING id", (memory,)
    ).fetchone()[0]
    conn.execute("INSERT INTO claim_evidence(claim_id, quote, source_episode_id) VALUES (?, 'quote', 'claim_evidence')", (claim,))
    conn.commit()

    assert store.prune_episodes(1, ALICE, False) == 1
    assert {row[0] for row in conn.execute("SELECT id FROM episodes")} == {
        "memory", "evidence", "claim", "claim_evidence", "bob"
    }
    assert store.ledger_status("episodes", 1, ALICE, False) == {"count": 4, "cap": 1, "overflow": 3}
    assert store.ledger_status("episodes", 0, ALICE, False) == {"count": 4, "cap": None, "overflow": 0}
    assert store.prune_episodes(0, ALICE, False) == 0


def test_evidence_and_events_prune_only_unprotected_scoped_records(store):
    conn = store.conn
    ids = {}
    for name, status, owner in (("active", "active", "alice"), ("conflict", "conflicted", "alice"),
                                ("old", "superseded", "alice"), ("bob", "superseded", "bob")):
        ids[name] = conn.execute(
            "INSERT INTO memories(content, status, user_id, workspace_id, agent_id) "
            "VALUES (?, ?, ?, 'work', 'agent') RETURNING id", (name, status, owner)
        ).fetchone()[0]
        conn.execute("INSERT INTO memory_evidence(memory_id, quote, created_at) VALUES (?, ?, '2020-01-01')", (ids[name], name))
        conn.execute(
            "INSERT INTO memory_events(memory_id, event_type, user_id, workspace_id, agent_id, created_at) "
            "VALUES (?, ?, ?, 'work', 'agent', '2020-01-01')", (ids[name], name, owner)
        )
    conn.commit()

    assert store.prune_evidence(1, ALICE, False) == 1
    assert {row[0] for row in conn.execute("SELECT quote FROM memory_evidence")} == {"active", "conflict", "bob"}
    assert store.ledger_status("memory_evidence", 1, ALICE, False) == {"count": 2, "cap": 1, "overflow": 1}
    assert store.prune_events(1, ALICE, False) == 1
    assert {row[0] for row in conn.execute("SELECT event_type FROM memory_events")} == {"active", "conflict", "bob"}
    assert store.ledger_status("memory_events", 1, BOB, False) == {"count": 1, "cap": 1, "overflow": 0}


def test_active_claim_protects_evidence_of_inactive_memory(store):
    conn = store.conn
    memory = conn.execute(
        "INSERT INTO memories(content, status, user_id, workspace_id, agent_id) "
        "VALUES ('fact', 'superseded', 'alice', 'work', 'agent') RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO claims(memory_id, subject, predicate, object, status) "
        "VALUES (?, 's', 'p', 'o', 'active')", (memory,)
    )
    conn.executemany(
        "INSERT INTO memory_evidence(memory_id, quote) VALUES (?, ?)",
        [(memory, "one"), (memory, "two")],
    )
    conn.commit()

    assert store.prune_evidence(1, ALICE, False) == 0
    assert store.ledger_status("memory_evidence", 1, ALICE, False)["overflow"] == 1


def test_cross_scope_references_and_unowned_evidence_are_not_deleted(store):
    conn = store.conn
    for name, timestamp in (("shared", "2018-01-01"), ("old", "2019-01-01"),
                            ("new", "2020-01-01")):
        conn.execute(
            "INSERT INTO episodes(id, content, user_id, workspace_id, agent_id, created_at) "
            "VALUES (?, ?, 'alice', 'work', 'agent', ?)", (name, name, timestamp)
        )
    conn.execute(
        "INSERT INTO memories(content, source_id, user_id, workspace_id, agent_id) "
        "VALUES ('bob fact', 'shared', 'bob', 'work', 'agent')"
    )
    conn.execute("INSERT INTO memory_evidence(quote) VALUES ('unknown owner')")
    conn.commit()

    assert store.prune_episodes(2, ALICE, False) == 1
    assert {row[0] for row in conn.execute("SELECT id FROM episodes")} == {"shared", "new"}
    assert store.prune_evidence(1, None, True) == 0
    assert conn.execute("SELECT quote FROM memory_evidence").fetchone()[0] == "unknown owner"


def test_ledger_default_scope_excludes_global_and_unscoped_excludes_owner(store):
    conn = store.conn
    conn.executemany(
        "INSERT INTO episodes(id, content, user_id, workspace_id, agent_id) "
        "VALUES (?, ?, ?, ?, ?)",
        [("global1", "global1", None, None, None),
         ("global2", "global2", None, None, None),
         ("alice", "alice", "alice", "work", "agent")],
    )
    conn.commit()
    assert store.ledger_status("episodes", 1, ALICE)["count"] == 1
    assert store.prune_episodes(1, ALICE) == 0
    assert store.ledger_status("episodes", 1)["count"] == 2
    assert store.prune_episodes(1) == 1
    assert conn.execute("SELECT COUNT(*) FROM episodes WHERE id='alice'").fetchone()[0] == 1


def test_ledger_status_rejects_unknown_table_and_sql_errors_propagate(store):
    with pytest.raises(ValueError):
        store.ledger_status("memories", 1)
    store.conn.executemany(
        "INSERT INTO episodes(id, content, user_id, workspace_id, agent_id) VALUES (?, ?, 'alice', 'work', 'agent')",
        [("one", "one"), ("two", "two")],
    )
    store.conn.commit()
    store.conn.execute("DROP TABLE claim_evidence")
    with pytest.raises(sqlite3.OperationalError):
        store.prune_episodes(1, ALICE, False)
