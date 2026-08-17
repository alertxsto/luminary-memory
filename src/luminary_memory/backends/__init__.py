from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.backends.sqlite import SQLiteBackend

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend
    from luminary_memory.config import Settings


def get_backend(settings: Settings) -> MemoryBackend:
    backend_name = (settings.backend or "sqlite").lower()
    if backend_name == "pgvector":
        from luminary_memory.backends.pgvector import (
            PGVectorBackend,
        )

        return PGVectorBackend(
            dsn=settings.pg_dsn, embedding_dim=int(settings.embedding_dim)
        )
    return SQLiteBackend(db_path=settings.db_path)
