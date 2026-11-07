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

def expired_candidates(memories, now=None):
    """Select existing TTL-eligible rows without mutating memory or access."""
    now = now or datetime.now(UTC)
    candidates = []
    for memory in memories:
        if memory.ttl_seconds is None:
            continue
        try:
            created = _parse_dt(memory.observed_at or memory.created_at)
            expiry = created.timestamp() + int(memory.ttl_seconds)
        except (TypeError, ValueError, OverflowError):
            logger.warning("skipping TTL cleanup for memory %s with invalid timestamp or TTL", memory.id)
            continue
        if expiry < now.timestamp():
            candidates.append(memory)
    return candidates



def cleanup_expired(
    backend: MemoryBackend,
    now: datetime | None = None,
    scope: dict | None = None,
    include_global: bool = True,
) -> int:
    if now is None:
        now = datetime.now(UTC)
    from luminary_memory.scope import memory_matches_scope
    candidates = expired_candidates([
        memory for memory in backend.all()
        if memory_matches_scope(memory, scope, include_global=include_global, active_only=True)
    ], now=now)
    for memory in candidates:
        try:
            backend.record_event("expire", memory.id, before={"content": memory.content, "status": memory.status})
        except Exception:
            if backend.in_transaction:
                raise
            logger.debug("could not record expiry for %s", memory.id, exc_info=True)
        try:
            backend.sync_claim_status(memory.id, "expired", now.isoformat())
        except Exception:
            if backend.in_transaction:
                raise
            logger.debug("could not mark claims expired for %s", memory.id, exc_info=True)
        backend.delete(memory.id)
    count = len(candidates)
    logger.info("cleanup removed=%d", count)
    return count
