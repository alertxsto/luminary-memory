from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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
        logger.warning("invalid int for %s=%r — using default %s", name, v, default)
        return default


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    try:
        return float(v)
    except ValueError:
        logger.warning("invalid float for %s=%r — using default %s", name, v, default)
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
    recall_cliff_threshold: float = field(default_factory=lambda: _env_float("LUMINARY_RECALL_CLIFF_THRESHOLD", 0.45))
    recall_min_score: float = field(default_factory=lambda: _env_float("LUMINARY_RECALL_MIN_SCORE", 0.0))
    importance_recall_boost: float = field(default_factory=lambda: _env_float("LUMINARY_IMPORTANCE_RECALL_BOOST", 1.0))
    strategy_weights: dict[str, float] = field(
        default_factory=lambda: {
            "semantic": _env_float("LUMINARY_WEIGHT_SEMANTIC", 0.4),
            "keyword": _env_float("LUMINARY_WEIGHT_KEYWORD", 0.3),
            "graph": _env_float("LUMINARY_WEIGHT_GRAPH", 0.2),
            "temporal": _env_float("LUMINARY_WEIGHT_TEMPORAL", 0.1),
        }
    )
    token_budget: int = field(default_factory=lambda: _env_int("LUMINARY_TOKEN_BUDGET", 4096))
    max_memories: int | None = field(default_factory=lambda: _env_int("LUMINARY_MAX_MEMORIES", 1000))
    # Safety policy.  Legacy direct clients keep permissive recall unless
    # enabled, while Hermes/CLI accuracy paths opt into strict abstention.
    strict_recall: bool = field(default_factory=lambda: _env_bool("LUMINARY_STRICT_RECALL", False))
    scope_include_global: bool = field(
        default_factory=lambda: _env_bool("LUMINARY_SCOPE_INCLUDE_GLOBAL", True)
    )
    abstention_min_confidence: float = field(
        default_factory=lambda: _env_float("LUMINARY_ABSTENTION_MIN_CONFIDENCE", 0.34)
    )
    abstention_min_margin: float = field(
        default_factory=lambda: _env_float("LUMINARY_ABSTENTION_MIN_MARGIN", 0.04)
    )
    evidence_required: bool = field(
        default_factory=lambda: _env_bool("LUMINARY_EVIDENCE_REQUIRED", False)
    )
    # core memory (DB-backed, auto-loaded into the system prompt every session)
    core_tag: str = field(default_factory=lambda: os.environ.get("LUMINARY_CORE_TAG", "core"))
    core_top_n: int = field(default_factory=lambda: _env_int("LUMINARY_CORE_TOP_N", 12))
    core_budget: int = field(default_factory=lambda: _env_int("LUMINARY_CORE_BUDGET", 8000))
    # lifecycle
    ttl_default_seconds: int | None = field(default_factory=lambda: _env_int("LUMINARY_TTL_DEFAULT_SECONDS", 0) or None)
    prune_min_importance: float = field(default_factory=lambda: _env_float("LUMINARY_PRUNE_MIN_IMPORTANCE", 0.2))
    consolidate_jaccard_threshold: float = field(default_factory=lambda: _env_float("LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD", 0.9))
    consolidate_semantic: bool = field(default_factory=lambda: _env_bool("LUMINARY_CONSOLIDATE_SEMANTIC", True))
    importance_auto: bool = field(default_factory=lambda: _env_bool("LUMINARY_IMPORTANCE_AUTO", True))
    # LLM enrichment (provider-agnostic, stdlib HTTP)
    llm_base_url: str | None = field(default_factory=lambda: os.environ.get("LUMINARY_LLM_BASE_URL") or None)
    llm_api_key: str | None = field(default_factory=lambda: os.environ.get("LUMINARY_LLM_API_KEY") or None)
    llm_model: str = field(default_factory=lambda: os.environ.get("LUMINARY_LLM_MODEL", "gpt-4o-mini"))
    llm_timeout: int = field(default_factory=lambda: _env_int("LUMINARY_LLM_TIMEOUT", 10))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LUMINARY_LLM_MAX_TOKENS", 512))
    rule_keywords: str = field(default_factory=lambda: os.environ.get(
        "LUMINARY_RULE_KEYWORDS",
        "NEVER,ALWAYS,MUST,ALWAYS MUST,NEVER EVER,RULE,REQUIRED,MANDATORY,FORBIDDEN,DO NOT,DON'T",
    ))
    rule_importance: float = field(default_factory=lambda: _env_float("LUMINARY_RULE_IMPORTANCE", 0.9))
    rule_auto_replace: bool = field(default_factory=lambda: _env_bool("LUMINARY_RULE_AUTO_REPLACE", True))
    rule_auto_replace_threshold: float = field(default_factory=lambda: _env_float("LUMINARY_RULE_AUTO_REPLACE_THRESHOLD", 0.85))
    # query planner
    query_planner: bool = field(default_factory=lambda: _env_bool("LUMINARY_QUERY_PLANNER", True))
    query_planner_keyword_threshold: float = field(
        default_factory=lambda: _env_float("LUMINARY_QUERY_PLANNER_KEYWORD_THRESHOLD", 0.9)
    )
    # pgvector HNSW
    pg_hnsw_index: bool = field(default_factory=lambda: _env_bool("LUMINARY_PG_HNSW_INDEX", False))
    pg_hnsw_m: int = field(default_factory=lambda: _env_int("LUMINARY_PG_HNSW_M", 16))
    pg_hnsw_ef_construction: int = field(default_factory=lambda: _env_int("LUMINARY_PG_HNSW_EF_CONSTRUCTION", 64))

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
            "recall_min_score": self.recall_min_score,
            "token_budget": self.token_budget,
            "max_memories": self.max_memories,
            "strict_recall": self.strict_recall,
            "scope_include_global": self.scope_include_global,
            "abstention_min_confidence": self.abstention_min_confidence,
            "abstention_min_margin": self.abstention_min_margin,
            "evidence_required": self.evidence_required,
            "core_tag": self.core_tag,
            "core_top_n": self.core_top_n,
            "core_budget": self.core_budget,
            "ttl_default_seconds": self.ttl_default_seconds,
            "prune_min_importance": self.prune_min_importance,
            "consolidate_jaccard_threshold": self.consolidate_jaccard_threshold,
            "consolidate_semantic": self.consolidate_semantic,
            "importance_auto": self.importance_auto,
            "llm_base_url": self.llm_base_url,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "llm_timeout": self.llm_timeout,
            "llm_max_tokens": self.llm_max_tokens,
            "rule_keywords": self.rule_keywords,
            "rule_importance": self.rule_importance,
            "rule_auto_replace": self.rule_auto_replace,
            "rule_auto_replace_threshold": self.rule_auto_replace_threshold,
            "query_planner": self.query_planner,
            "query_planner_keyword_threshold": self.query_planner_keyword_threshold,
            "pg_hnsw_index": self.pg_hnsw_index,
            "pg_hnsw_m": self.pg_hnsw_m,
            "pg_hnsw_ef_construction": self.pg_hnsw_ef_construction,
        }
