from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from luminary_memory.scope import memory_matches_scope, normalize_scope

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
    created = _parse_dt(getattr(m, "observed_at", None) or m.created_at)
    age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
    recency = math.exp(-age_hours / half_life_hours)
    popularity = 1.0 + math.log1p(float(m.access_count))
    return recency * popularity


def temporal_recall(
    backend: MemoryBackend,
    limit: int | None = 10,
    half_life_hours: float = HALF_LIFE_HOURS,
    scope: dict | None = None,
    include_global: bool = True,
) -> list[tuple]:
    now = datetime.now(UTC)

    # Fast path: backends with temporal_scan() return lightweight
    # (id, created_at, access_count) rows — no JSON/embedding parsing.
    scan = getattr(backend, "temporal_scan", None)
    if scan is not None:
        scored: list[tuple] = []
        needs_local_filter = bool(normalize_scope(scope)) or not include_global
        try:
            scan_rows = scan(
                scope=scope,
                include_global=include_global,
                include_observed=True,
            )
        except TypeError:
            # Legacy scans are unscoped. Fetch all lightweight rows and defer
            # top-k selection until after object-level scope filtering; taking
            # top-k first could permanently hide a tenant's valid memories.
            scan_rows = scan()
            if needs_local_filter:
                get_many = getattr(backend, "get_many", None)
                ids = [row[0] for row in scan_rows]
                by_id = get_many(ids) if get_many is not None else {}
                filtered_rows = []
                for row in scan_rows:
                    memory = by_id.get(row[0]) if by_id else backend.get(row[0])
                    if memory is not None and memory_matches_scope(
                        memory,
                        scope,
                        include_global=include_global,
                    ):
                        filtered_rows.append(row)
                scan_rows = filtered_rows
        for row in scan_rows:
            mid, created_at, access_count = row[:3]
            created = _parse_dt(created_at)
            age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
            recency = math.exp(-age_hours / half_life_hours)
            popularity = 1.0 + math.log1p(float(access_count))
            scored.append((mid, recency * popularity))
        scored.sort(key=lambda x: -x[1])
        top = scored if limit is None else scored[:limit]
        if not top:
            return []
        # Batch fetch the top ids (one SELECT) instead of N per-id queries.
        ids = [mid for mid, _ in top]
        get_many = getattr(backend, "get_many", None)
        if get_many is not None:
            by_id = get_many(ids)
            out: list[tuple] = []
            for mid, score in top:
                mem = by_id.get(mid)
                if mem is not None:
                    out.append((mem, float(score), "temporal"))
            return out
        out = []
        for mid, score in top:
            mem = backend.get(mid)
            if mem is not None:
                out.append((mem, float(score), "temporal"))
        return out

    # Fallback: full objects via backend.all().
    scored = [
        (m, compute_temporal_score(m, now=now, half_life_hours=half_life_hours))
        for m in backend.all()
        if memory_matches_scope(m, scope, include_global=include_global)
    ]
    scored.sort(key=lambda x: -x[1])
    return [(m, float(score), "temporal") for m, score in scored] if limit is None else [
        (m, float(score), "temporal") for m, score in scored[:limit]
    ]
