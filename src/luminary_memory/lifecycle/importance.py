from __future__ import annotations

import math
from datetime import UTC, datetime


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        ts = datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001 -- malformed timestamps treated as now
        return datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def estimate_importance(
    memory,
    max_access: int = 1,
    max_centrality: int = 1,
    now=None,
    half_life_hours: float = 24.0,
    access_weight: float = 0.4,
    recency_weight: float = 0.3,
    centrality_weight: float = 0.3,
) -> float:
    """Estimate a memory's importance from behavior: access, recency, centrality.

    ``importance = access_norm*access_weight + recency_norm*recency_weight
    + centrality_norm*centrality_weight``, clamped to [0, 1].

    - ``access_norm`` — ``log1p(access_count) / log1p(max_access)``.
    - ``recency_norm`` — ``exp(-age_hours / half_life_hours)`` (same decay shape
      as temporal recall).
    - ``centrality_norm`` — relation degree / ``max_centrality`` (0 when no graph).
    """
    if now is None:
        now = datetime.now(UTC)

    access_norm = (
        math.log1p(int(memory.access_count or 0)) / math.log1p(max(1, max_access))
        if max_access > 0
        else 0.0
    )

    age_hours = max(0.0, (now - _parse_dt(getattr(memory, "last_accessed_at", None))).total_seconds() / 3600.0)
    recency_norm = math.exp(-age_hours / max(1e-9, half_life_hours))

    meta = getattr(memory, "metadata", None)
    centrality = 0
    if isinstance(meta, dict):
        try:
            centrality = int(meta.get("centrality", 0) or 0)
        except (TypeError, ValueError):
            centrality = 0
    centrality_norm = centrality / max(1, max_centrality) if max_centrality > 0 else 0.0

    value = (
        access_norm * access_weight
        + recency_norm * recency_weight
        + centrality_norm * centrality_weight
    )
    return max(0.0, min(1.0, value))
