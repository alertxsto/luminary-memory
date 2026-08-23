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


def cleanup_expired(
    backend: MemoryBackend,
    now: datetime | None = None,
    scope: dict | None = None,
    include_global: bool = True,
) -> int:
    if now is None:
        now = datetime.now(UTC)
    count = 0
    for m in backend.all():
        from luminary_memory.scope import memory_matches_scope

        if not memory_matches_scope(
            m,
            scope,
            include_global=include_global,
            active_only=True,
        ):
            continue
        if m.ttl_seconds is None:
            continue
        try:
            created = _parse_dt(m.observed_at or m.created_at)
        except (TypeError, ValueError):
            # A corrupt timestamp must not make the entire lifecycle fail or
            # cause an accidental deletion. Leave it for explicit repair.
            logger.warning("skipping TTL cleanup for memory %s with invalid timestamp", m.id)
            continue
        try:
            expiry = created.timestamp() + int(m.ttl_seconds)
        except (TypeError, ValueError, OverflowError):
            logger.warning("skipping TTL cleanup for memory %s with invalid TTL", m.id)
            continue
        if expiry < now.timestamp():
            try:
                backend.record_event("expire", m.id, before={"content": m.content, "status": m.status})
            except Exception:
                logger.debug("could not record expiry for %s", m.id, exc_info=True)
            try:
                backend.sync_claim_status(m.id, "expired", now.isoformat())
            except Exception:
                logger.debug("could not mark claims expired for %s", m.id, exc_info=True)
            backend.delete(m.id)  # type: ignore[arg-type]
            count += 1
    logger.info("cleanup removed=%d", count)
    return count
