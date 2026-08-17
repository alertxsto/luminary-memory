from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.config import Settings
from luminary_memory.embeddings.fastembed import FastembedEngine
from luminary_memory.ingest.llm import LLMEnricher, NoopEnricher
from luminary_memory.ingest.whitelist import WhitelistFilter
from luminary_memory.types import Memory

if TYPE_CHECKING:
    from luminary_memory.backends.base import MemoryBackend


class MemoryClient:
    def __init__(
        self,
        settings: Settings | None = None,
        db_path: str | None = None,
        ingest_whitelist: list[str] | None = None,
        enricher: LLMEnricher | None = None,
        engine: FastembedEngine | None = None,
        backend: MemoryBackend | None = None,
    ):
        self.settings = settings or Settings()
        if db_path is not None:
            self.settings.db_path = db_path
        if ingest_whitelist is not None:
            self.settings.ingest_whitelist = ingest_whitelist

        self.backend = backend or SQLiteBackend(self.settings.db_path)
        self.whitelist = WhitelistFilter(self.settings.ingest_whitelist)
        self.engine = engine or FastembedEngine(model_name=self.settings.embedding_model)
        self.enricher = enricher or (NoopEnricher() if not self.settings.ingest_llm else None)

    def ingest(self, text: str, tags: list[str] | None = None,
               source: str | None = None) -> int | None:
        if not self.whitelist.accepts(text):
            return None

        content, summary, entities, extra_tags = text, None, [], []
        if self.enricher is not None:
            enriched = self.enricher.enrich(text)
            content, summary, entities, extra_tags = (
                enriched.content, enriched.summary, enriched.entities, enriched.tags,
            )

        metadata: dict = {}
        if summary:
            metadata["summary"] = summary
        if entities:
            metadata["entities"] = entities

        m = Memory(
            content=content,
            metadata=metadata,
            source=source,
            tags=list(dict.fromkeys((tags or []) + extra_tags)),
            ttl_seconds=self.settings.ttl_default_seconds,
            embedding=self.engine.embed(content),
        )
        return self.backend.add(m)

    def get(self, id: int) -> Memory | None:
        return self.backend.get(id)

    def count(self) -> int:
        return self.backend.count()

    def close(self) -> None:
        self.backend.close()
