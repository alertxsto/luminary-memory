from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luminary_memory.types import Memory


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_current(
    memory: Memory,
    *,
    now: datetime | None = None,
    include_conflicted: bool = False,
) -> bool:
    """Determine whether a memory may be exposed as current context."""
    status = memory.status or "active"
    if status != "active" and not (include_conflicted and status == "conflicted"):
        return False
    try:
        current = _utc(now if now is not None else datetime.now(UTC))
        valid_from = memory.valid_from
        if valid_from and _utc(valid_from) > current:
            return False
        valid_to = memory.valid_to
        if valid_to and _utc(valid_to) <= current:
            return False
        ttl = memory.ttl_seconds
        if ttl is not None:
            ttl_seconds = int(ttl)
            if ttl_seconds < 0:
                return False
            observed = memory.observed_at or memory.created_at
            if current >= _utc(observed) + timedelta(seconds=ttl_seconds):
                return False
    except (TypeError, ValueError, OverflowError):
        return False
    return True
