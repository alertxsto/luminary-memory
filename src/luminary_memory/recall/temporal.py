from __future__ import annotations

import heapq
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
    popularity = 1.0 + math.log1p(max(0.0, float(m.access_count)))
    return recency * popularity


def temporal_recall(
    backend: MemoryBackend,
    limit: int | None = 10,
    half_life_hours: float = HALF_LIFE_HOURS,
    scope: dict | None = None,
    include_global: bool = True,
) -> list[tuple]:
    if limit == 0:
        return []
    now = datetime.now(UTC)

    # Streaming scans yield lightweight rows; older backends can still return
    # a list through temporal_scan(). Either way, ranking retains only top K.
    scan = getattr(backend, "iter_temporal_scan", None)
    legacy_scan = False
    if scan is None:
        scan = getattr(backend, "temporal_scan", None)
    if scan is not None:
        scored: list[tuple[float, int, int]] = []
        needs_local_filter = bool(normalize_scope(scope)) or not include_global
        try:
            scan_rows = scan(
                scope=scope,
                include_global=include_global,
                include_observed=True,
            )
        except TypeError:
            legacy_scan = True
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
                        memory, scope, include_global=include_global, valid_only=True,
                    ):
                        filtered_rows.append(row)
                scan_rows = filtered_rows
        if needs_local_filter and legacy_scan and not scan_rows:
            # A legacy backend may apply the new global-only default to its
            # unscoped fallback. Rebuild temporal candidates from full rows so
            # a valid tenant memory is not lost before scope filtering.
            scan_rows = [
                (
                    getattr(memory, "id", None),
                    getattr(memory, "observed_at", None) or getattr(memory, "created_at", ""),
                    getattr(memory, "access_count", 0),
                )
                for memory in backend.all()
                if memory_matches_scope(memory, scope, include_global=include_global, valid_only=True)
            ]
        k = int(limit) if limit is not None else None
        bounded = k is not None and k > 0
        for row in scan_rows:
            mid, created_at, access_count = row[:3]
            created = _parse_dt(created_at)
            age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
            recency = math.exp(-age_hours / half_life_hours)
            popularity = 1.0 + math.log1p(max(0.0, float(access_count)))
            candidate = (recency * popularity, -mid, mid)
            if bounded:
                if len(scored) < k:
                    heapq.heappush(scored, candidate)
                elif candidate > scored[0]:
                    heapq.heapreplace(scored, candidate)
            else:
                scored.append(candidate)
        top = sorted(scored, reverse=True)
        if k is not None and k <= 0:
            top = top[:k]
        if not top:
            return []
        ids = [mid for _, _, mid in top]
        get_many = getattr(backend, "get_many", None)
        if get_many is not None:
            by_id = get_many(ids)
            out: list[tuple] = []
            for score, _, mid in top:
                mem = by_id.get(mid)
                if mem is not None:
                    out.append((mem, float(score), "temporal"))
            return out
        out = []
        for score, _, mid in top:
            mem = backend.get(mid)
            if mem is not None:
                out.append((mem, float(score), "temporal"))
        return out

    # Fallback: a backend with only all() has already materialized full rows,
    # but still need not sort and copy every scored candidate for small K.
    scored = []
    k = int(limit) if limit is not None else None
    for order, memory in enumerate(backend.all()):
        if not memory_matches_scope(memory, scope, include_global=include_global, valid_only=True):
            continue
        candidate = (
            compute_temporal_score(memory, now=now, half_life_hours=half_life_hours),
            -order,
            memory,
        )
        if k is not None and k > 0:
            if len(scored) < k:
                heapq.heappush(scored, candidate)
            elif candidate > scored[0]:
                heapq.heapreplace(scored, candidate)
        else:
            scored.append(candidate)
    top = sorted(scored, reverse=True)
    if k is not None and k < 0:
        top = top[:k]
    return [(memory, float(score), "temporal") for score, _, memory in top]
