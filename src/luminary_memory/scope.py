"""Scope and lifecycle predicates shared by every retrieval path.

Scope filtering belongs in candidate generation, not as a post-processing
step.  Keeping the predicate in one small module prevents SQLite, pgvector,
graph, and fallback implementations from slowly acquiring different
isolation semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCOPE_FIELDS = ("user_id", "workspace_id", "agent_id", "session_id")
_IDENTITY_FIELDS = ("user_id", "workspace_id", "agent_id")


def normalize_scope(scope: Mapping[str, Any] | None) -> dict[str, str]:
    """Return non-empty identity fields with stable string values."""
    if not scope:
        return {}
    out: dict[str, str] = {}
    for field in SCOPE_FIELDS:
        value = scope.get(field)
        if value is not None and str(value).strip():
            out[field] = str(value)
    return out


def scope_sql(
    scope: Mapping[str, Any] | None = None,
    *,
    alias: str = "",
    include_global: bool = False,
    active_only: bool = True,
    exact_session: bool = False,
) -> tuple[str, list[str]]:
    """Build a parameterized SQL predicate for a memory row.

    Missing identity fields match only absent fields, never arbitrary owners.
    ``include_global`` explicitly adds fully unowned rows to a scoped read.
    Omitted session is a wildcard only for a scoped durable-memory read.
    """
    normalized = normalize_scope(scope)
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[str] = []
    fields = SCOPE_FIELDS if exact_session or not normalized else _IDENTITY_FIELDS
    if normalized.get("session_id"):
        fields = SCOPE_FIELDS
    for field in fields:
        value = normalized.get(field)
        if value is None:
            clauses.append(f"({prefix}{field} IS NULL OR {prefix}{field} = '')")
        else:
            clauses.append(f"{prefix}{field} = ?")
            params.append(value)
    if not exact_session and normalized and "user_id" not in normalized:
        # Without a user identity, workspace paths are guessable; match nothing
        # rather than exposing unowned rows inside a guessed workspace. An
        # exact-session episode read stays exact: a missing user matches the
        # session's own rows whose user is also absent.
        return "1=0", []
    if normalized and include_global:
        global_clause = " AND ".join(
            f"({prefix}{field} IS NULL OR {prefix}{field} = '')"
            for field in SCOPE_FIELDS
        )
        clauses = [f"({' AND '.join(clauses)}) OR ({global_clause})"]
        clauses[0] = f"({clauses[0]})"
    if active_only:
        clauses.append(f"COALESCE({prefix}status, 'active') = 'active'")
    return (" AND ".join(clauses) or "1=1"), params


def memory_matches_scope(
    memory: Any,
    scope: Mapping[str, Any] | None = None,
    *,
    include_global: bool = False,
    active_only: bool = True,
) -> bool:
    """Python fallback equivalent of :func:`scope_sql`."""
    normalized = normalize_scope(scope)
    if active_only and str(getattr(memory, "status", "active") or "active") != "active":
        return False
    fields = SCOPE_FIELDS if not normalized or normalized.get("session_id") else _IDENTITY_FIELDS
    if normalized and "user_id" not in normalized:
        return False
    matches = all(
        (getattr(memory, field, None) in (None, "") if normalized.get(field) is None
         else str(getattr(memory, field, None)) == normalized[field])
        for field in fields
    )
    if matches:
        return True
    return bool(normalized and include_global and all(
        getattr(memory, field, None) in (None, "") for field in SCOPE_FIELDS
    ))
