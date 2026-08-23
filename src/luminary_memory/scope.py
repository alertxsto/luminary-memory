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
    include_global: bool = True,
    active_only: bool = True,
) -> tuple[str, list[str]]:
    """Build a parameterized SQL predicate for a memory row.

    ``include_global`` allows legacy/global facts to remain visible to a
    scoped caller, while still preventing a partially-scoped row from being
    treated as global.  An unscoped read sees only fully global rows.  Session
    identity is intentionally a wildcard when omitted so durable facts can be
    recalled across sessions; user/workspace/agent identity is never inferred.
    Provider stores use this compatibility mode during migration; callers can
    disable it for strict tenant isolation.
    """
    normalized = normalize_scope(scope)
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[str] = []
    if include_global:
        if not normalized:
            # No identity is not permission to read every tenant's memory.
            # Only rows with no scope at all are truly global.
            for field in SCOPE_FIELDS:
                clauses.append(f"({prefix}{field} IS NULL OR {prefix}{field} = '')")
        else:
            for field in _IDENTITY_FIELDS:
                value = normalized.get(field)
                if value is None:
                    clauses.append(f"({prefix}{field} IS NULL OR {prefix}{field} = '')")
                else:
                    clauses.append(
                        f"({prefix}{field} = ? OR {prefix}{field} IS NULL OR {prefix}{field} = '')"
                    )
                    params.append(value)
            session_value = normalized.get("session_id")
            if session_value is not None:
                clauses.append(
                    f"({prefix}session_id = ? OR {prefix}session_id IS NULL OR {prefix}session_id = '')"
                )
                params.append(session_value)
    else:
        for field, value in normalized.items():
            clauses.append(f"{prefix}{field} = ?")
            params.append(value)
    if active_only:
        clauses.append(f"COALESCE({prefix}status, 'active') = 'active'")
    return (" AND ".join(clauses) or "1=1"), params


def memory_matches_scope(
    memory: Any,
    scope: Mapping[str, Any] | None = None,
    *,
    include_global: bool = True,
    active_only: bool = True,
) -> bool:
    """Python fallback equivalent of :func:`scope_sql`."""
    normalized = normalize_scope(scope)
    if active_only and str(getattr(memory, "status", "active") or "active") != "active":
        return False
    if include_global:
        if not normalized:
            return all(
                getattr(memory, field, None) in (None, "")
                for field in SCOPE_FIELDS
            )
        for field in _IDENTITY_FIELDS:
            actual = getattr(memory, field, None)
            if actual in (None, ""):
                continue
            expected = normalized.get(field)
            if expected is None or str(actual) != expected:
                return False
        session_actual = getattr(memory, "session_id", None)
        session_expected = normalized.get("session_id")
        return not (
            session_actual not in (None, "")
            and session_expected is not None
            and str(session_actual) != session_expected
        )
    for field, value in normalized.items():
        actual = getattr(memory, field, None)
        if str(actual) != value:
            return False
    return True
