from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()

@dataclass
class Memory:
    id: int | None = None
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    ttl_seconds: int | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_accessed_at: str | None = None
    access_count: int = 0
    embedding: list[float] | None = None
    snippet: str | None = None
    # Ownership and lineage.  These fields are optional for backwards
    # compatibility with legacy/global stores, but every provider-owned
    # memory is written with them populated.
    user_id: str | None = None
    session_id: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    # Claim lifecycle and provenance.  A row is a durable claim only while it
    # is active; old rows remain queryable through the event log instead of
    # being silently destroyed.
    observed_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    status: str = "active"
    confidence: float = 1.0
    evidence_quote: str | None = None
    source_id: str | None = None
    claim_key: str | None = None
    supersedes_id: int | None = None
    content_hash: str | None = None
    needs_reindex: bool = False

@dataclass
class ScoredMemory:
    memory: Memory
    score: float
    strategy: str  # "semantic" | "keyword" | "temporal" | "graph"

@dataclass
class RecallResult:
    memories: list[Memory]
    scores: list[float]
    strategies_hit: dict[str, int]
    status: str = "ok"
    reason: str | None = None
    confidence: float = 0.0
    provenance: list[dict[str, Any]] = field(default_factory=list)
