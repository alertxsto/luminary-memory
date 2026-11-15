"""Adversarial scope tests for partially-scoped and unscoped reads."""

from types import SimpleNamespace

from luminary_memory.scope import memory_matches_scope, scope_sql


def _memory(**scope):
    values = {
        "status": "active",
        "user_id": None,
        "workspace_id": None,
        "agent_id": None,
        "session_id": None,
    }
    values.update(scope)
    return SimpleNamespace(**values)


def test_partial_user_scope_matches_only_its_own_owner():
    private = _memory(user_id="alice")

    # A user-scoped caller reads its own partially owned rows and nothing else.
    assert memory_matches_scope(private, {"user_id": "alice"})
    assert not memory_matches_scope(private, {})
    assert not memory_matches_scope(private, {"user_id": "bob"})
    # A workspace path is guessable, so it never authorizes a read by itself.
    assert not memory_matches_scope(private, {"workspace_id": "hermes"})
    assert not memory_matches_scope(private, {"workspace_id": "work", "agent_id": "agent"})


def test_unscoped_sql_reads_only_fully_global_rows():
    where, params = scope_sql({}, alias="m", include_global=True)

    assert params == []
    assert "m.user_id IS NULL" in where
    assert "m.workspace_id IS NULL" in where
    assert "m.agent_id IS NULL" in where
    assert "m.session_id IS NULL" in where


def test_session_is_wildcard_when_identity_scope_matches():
    identity = {"user_id": "alice", "workspace_id": "work", "agent_id": "agent"}
    session_memory = _memory(**identity, session_id="old-session")

    assert memory_matches_scope(session_memory, identity)
    assert not memory_matches_scope(
        session_memory,
        {**identity, "session_id": "other-session"},
    )


def test_missing_identity_never_matches_owned_or_partial_rows():
    alice = {"user_id": "alice", "workspace_id": "work", "agent_id": "agent"}
    assert not memory_matches_scope(_memory(user_id="alice"), alice)
    assert not memory_matches_scope(_memory(**alice), {"workspace_id": "work", "agent_id": "agent"})
    assert not memory_matches_scope(_memory(**alice), {}, include_global=False)
    assert not memory_matches_scope(_memory(), alice, include_global=False)
    assert memory_matches_scope(_memory(), alice, include_global=True)


def test_sql_and_python_scope_agree_for_partial_and_global_rows():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE memories (user_id, workspace_id, agent_id, session_id, status)")
    rows = [
        ("alice", "work", "agent", None, "active"),
        ("alice", None, None, None, "active"),
        ("bob", "work", "agent", None, "active"),
        (None, None, None, None, "active"),
    ]
    conn.executemany("INSERT INTO memories VALUES (?, ?, ?, ?, ?)", rows)
    for scope in ({}, {"user_id": "alice"}, {"user_id": "alice", "workspace_id": "work", "agent_id": "agent"}):
        for include_global in (False, True):
            where, params = scope_sql(scope, include_global=include_global)
            actual = conn.execute("SELECT rowid FROM memories WHERE " + where, params).fetchall()
            expected = [(i,) for i, row in enumerate(rows, 1) if memory_matches_scope(
                _memory(**dict(zip(("user_id", "workspace_id", "agent_id", "session_id", "status"), row))),
                scope, include_global=include_global,
            )]
            assert actual == expected
