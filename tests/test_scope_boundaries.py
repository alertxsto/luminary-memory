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


def test_partial_user_scope_is_not_global():
    private = _memory(user_id="alice")

    assert memory_matches_scope(private, {"user_id": "alice"})
    assert not memory_matches_scope(private, {})
    assert not memory_matches_scope(private, {"user_id": "bob"})
    assert not memory_matches_scope(private, {"workspace_id": "hermes"})


def test_unscoped_sql_reads_only_fully_global_rows():
    where, params = scope_sql({}, alias="m", include_global=True)

    assert params == []
    assert "m.user_id IS NULL" in where
    assert "m.workspace_id IS NULL" in where
    assert "m.agent_id IS NULL" in where
    assert "m.session_id IS NULL" in where


def test_session_is_wildcard_when_identity_scope_matches():
    session_memory = _memory(user_id="alice", session_id="old-session")

    assert memory_matches_scope(session_memory, {"user_id": "alice"})
    assert not memory_matches_scope(
        session_memory,
        {"user_id": "alice", "session_id": "other-session"},
    )
