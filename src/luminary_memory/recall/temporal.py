from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

HALF_LIFE_HOURS = 72.0


def _parse_dt(s: str) -> datetime:
    if not s:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        # Corrupt or foreign timestamp: treat as "now" so downstream
        # scoring/cleanup never crashes on bad data.
        return datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def compute_temporal_score(
    m,
    now: datetime | None = None,
    half_life_hours: float = HALF_LIFE_HOURS,
) -> float:
    if now is None:
        now = datetime.now(UTC)
    created = _parse_dt(m.created_at)
    age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
    recency = math.exp(-age_hours / half_life_hours)
    popularity = 1.0 + math.log1p(float(m.access_count))
    return recency * popularity


def temporal_recall(
    backend: MemoryBackend,
    limit: int | None = 10,
    half_life_hours: float = HALF_LIFE_HOURS,
) -> list[tuple]:
    now = datetime.now(UTC)

    # Fast path: backends with temporal_scan() return lightweight
    # (id, created_at, access_count) rows — no JSON/embedding parsing.
    scan = getattr(backend, "temporal_scan", None)
    if scan is not None:
        scored: list[tuple] = []
        for mid, created_at, access_count in scan():
            created = _parse_dt(created_at)
            age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
            recency = math.exp(-age_hours / half_life_hours)
            popularity = 1.0 + math.log1p(float(access_count))
            scored.append((mid, recency * popularity))
        scored.sort(key=lambda x: -x[1])
        top = scored if limit is None else scored[:limit]
        out: list[tuple] = []
        for mid, score in top:
            mem = backend.get(mid)
            if mem is not None:
                out.append((mem, float(score), "temporal"))
        return out

    # Fallback: full objects via backend.all().
    scored = [(m, compute_temporal_score(m, now=now, half_life_hours=half_life_hours))
              for m in backend.all()]
    scored.sort(key=lambda x: -x[1])
    return [(m, float(score), "temporal") for m, score in scored] if limit is None else [
        (m, float(score), "temporal") for m, score in scored[:limit]
    ]
