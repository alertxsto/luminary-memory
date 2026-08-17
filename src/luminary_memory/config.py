from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return list(default or [])
    return [p.strip() for p in v.split(",") if p.strip()]


@dataclass
class Settings:
    """Runtime settings for luminary-memory.

    Every field can be overridden via a ``LUMINARY_*`` environment variable
    (e.g. ``LUMINARY_BACKEND``, ``LUMINARY_DB_PATH``, ``LUMINARY_PG_DSN``),
    which makes the library deployment-friendly without code changes.
    """

    backend: str = field(default_factory=lambda: os.environ.get("LUMINARY_BACKEND", "sqlite"))  # "sqlite" | "pgvector"
    db_path: str = field(default_factory=lambda: os.environ.get("LUMINARY_DB_PATH", "luminary_memory.db"))
    # pgvector (only used when backend == "pgvector")
    pg_dsn: str = field(default_factory=lambda: os.environ.get("LUMINARY_PG_DSN", "postgresql://localhost/luminary_memory"))
    # embeddings
    embedding_model: str = field(default_factory=lambda: os.environ.get("LUMINARY_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))
    embedding_dim: int = field(default_factory=lambda: _env_int("LUMINARY_EMBEDDING_DIM", 384))
    # ingest
    ingest_whitelist: list[str] = field(default_factory=lambda: _env_list("LUMINARY_INGEST_WHITELIST"))
    ingest_llm: bool = field(default_factory=lambda: _env_bool("LUMINARY_INGEST_LLM", False))
    # recall fusion
    rrf_k: int = field(default_factory=lambda: _env_int("LUMINARY_RRF_K", 60))
    dedup_jaccard_threshold: float = field(default_factory=lambda: _env_float("LUMINARY_DEDUP_JACCARD_THRESHOLD", 0.85))
    token_budget: int = field(default_factory=lambda: _env_int("LUMINARY_TOKEN_BUDGET", 4096))
    # lifecycle
    ttl_default_seconds: int | None = field(default_factory=lambda: _env_int("LUMINARY_TTL_DEFAULT_SECONDS", 0) or None)
    prune_min_importance: float = field(default_factory=lambda: _env_float("LUMINARY_PRUNE_MIN_IMPORTANCE", 0.2))
    consolidate_jaccard_threshold: float = field(default_factory=lambda: _env_float("LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD", 0.9))

    def as_dict(self) -> dict[str, Any]:
        """Return settings as a plain dict (useful for CLI `show` and config dumps)."""
        return {
            "backend": self.backend,
            "db_path": self.db_path,
            "pg_dsn": self.pg_dsn,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "ingest_whitelist": self.ingest_whitelist,
            "ingest_llm": self.ingest_llm,
            "rrf_k": self.rrf_k,
            "dedup_jaccard_threshold": self.dedup_jaccard_threshold,
            "token_budget": self.token_budget,
            "ttl_default_seconds": self.ttl_default_seconds,
            "prune_min_importance": self.prune_min_importance,
            "consolidate_jaccard_threshold": self.consolidate_jaccard_threshold,
        }
