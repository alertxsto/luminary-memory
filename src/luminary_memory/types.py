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
