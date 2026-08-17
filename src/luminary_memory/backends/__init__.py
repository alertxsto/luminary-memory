from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.backends.sqlite import SQLiteBackend

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend
    from luminary_memory.config import Settings


def get_backend(settings: Settings) -> MemoryBackend:
    backend_name = (settings.backend or "sqlite").strip().lower()
    if backend_name == "pgvector":
        from luminary_memory.backends.pgvector import (
            PGVectorBackend,
        )

        if not settings.pg_dsn:
            raise ValueError("pg_dsn is required when backend='pgvector'")
        if int(settings.embedding_dim) <= 0:
            raise ValueError("embedding_dim must be positive")
        return PGVectorBackend(
            dsn=settings.pg_dsn,
            embedding_dim=int(settings.embedding_dim),
            hnsw=bool(getattr(settings, "pg_hnsw_index", False)),
            hnsw_m=int(getattr(settings, "pg_hnsw_m", 16)),
            hnsw_ef_construction=int(getattr(settings, "pg_hnsw_ef_construction", 64)),
        )
    if backend_name == "sqlite":
        return SQLiteBackend(db_path=settings.db_path)
    raise ValueError(f"unsupported backend {settings.backend!r}")
