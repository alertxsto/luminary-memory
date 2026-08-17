from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Settings:
    backend: str = "sqlite"                 # "sqlite" | "pgvector"
    db_path: str = "luminary_memory.db"
    # pgvector (only used when backend == "pgvector")
    pg_dsn: str = "postgresql://localhost/luminary_memory"
    # embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # ingest
    ingest_whitelist: list[str] = field(default_factory=list)  # regex patterns
    ingest_llm: bool = False
    # recall fusion
    rrf_k: int = 60
    dedup_jaccard_threshold: float = 0.85
    token_budget: int = 4096
    # lifecycle
    ttl_default_seconds: int | None = None
    prune_min_importance: float = 0.2
    consolidate_jaccard_threshold: float = 0.9
