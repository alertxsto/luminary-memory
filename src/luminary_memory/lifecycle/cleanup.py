from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def cleanup_expired(backend: MemoryBackend, now: datetime | None = None) -> int:
    if now is None:
        now = datetime.now(UTC)
    count = 0
    for m in backend.all():
        if m.ttl_seconds is None:
            continue
        created = _parse_dt(m.created_at)
        expiry = created.timestamp() + int(m.ttl_seconds)
        if expiry < now.timestamp():
            backend.delete(m.id)  # type: ignore[arg-type]
            count += 1
    logger.info("cleanup removed=%d", count)
    return count
