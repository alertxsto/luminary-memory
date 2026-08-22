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
    scoped caller, while still preventing another non-global user's rows from
    entering the candidate set.  Provider stores use this compatibility mode
    during migration; callers can disable it for strict tenant isolation.
    """
    normalized = normalize_scope(scope)
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[str] = []
    for field, value in normalized.items():
        if include_global:
            clauses.append(f"({prefix}{field} = ? OR {prefix}{field} IS NULL)")
        else:
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
    for field, value in normalized.items():
        actual = getattr(memory, field, None)
        if actual is None and include_global:
            continue
        if str(actual) != value:
            return False
    return True

