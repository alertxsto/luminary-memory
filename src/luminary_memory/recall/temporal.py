from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend

HALF_LIFE_HOURS = 72.0


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
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
    limit: int = 10,
    half_life_hours: float = HALF_LIFE_HOURS,
) -> list[tuple]:
    now = datetime.now(UTC)
    scored = [(m, compute_temporal_score(m, now=now, half_life_hours=half_life_hours))
              for m in backend.all()]
    scored.sort(key=lambda x: -x[1])
    return [(m, float(score), "temporal") for m, score in scored[:limit]]
