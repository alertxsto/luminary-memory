from __future__ import annotations

from typing import TYPE_CHECKING

from luminary_memory.backends import get_backend
from luminary_memory.budget import truncate
from luminary_memory.config import Settings
from luminary_memory.embeddings.fastembed import FastembedEngine
from luminary_memory.ingest.llm import LLMEnricher, NoopEnricher
from luminary_memory.ingest.whitelist import WhitelistFilter
from luminary_memory.types import Memory, RecallResult


def _try_index_graph(backend, memory: Memory) -> None:
    from luminary_memory.recall.graph import index_memory_entities

    index_memory_entities(backend, memory)

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

        self.backend = backend or get_backend(self.settings)
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
        mid = self.backend.add(m)
        m.id = mid
        _try_index_graph(self.backend, m)
        return mid

    def get(self, id: int) -> Memory | None:
        return self.backend.get(id)

    def count(self) -> int:
        return self.backend.count()

    def run_lifecycle(self) -> dict[str, int]:
        from luminary_memory.lifecycle.runner import run_lifecycle

        return run_lifecycle(self.backend, self.settings)

    def close(self) -> None:
        self.backend.close()

    def recall(
        self,
        query: str,
        limit: int = 10,
        token_budget: int | None = None,
    ) -> RecallResult:
        from luminary_memory.recall.dedup import dedup_jaccard
        from luminary_memory.recall.fusion import reciprocal_rank_fusion
        from luminary_memory.recall.graph import graph_recall
        from luminary_memory.recall.keyword import keyword_recall
        from luminary_memory.recall.semantic import semantic_recall
        from luminary_memory.recall.temporal import temporal_recall

        budget = token_budget if token_budget is not None else self.settings.token_budget
        rrf_k = self.settings.rrf_k
        dedup_threshold = self.settings.dedup_jaccard_threshold

        strategies: list[list[tuple]] = []
        strategies.append(semantic_recall(self.backend, self.engine, query, limit=limit))
        strategies.append(keyword_recall(self.backend, query, limit=limit))
        strategies.append(temporal_recall(self.backend, limit=limit * 2))
        strategies.append(graph_recall(self.backend, query, limit=limit))

        id_to_mem: dict[int, Memory] = {}
        id_to_best: dict[int, float] = {}
        strategies_hit: dict[str, int] = {}
        ranked_lists: list[list[int]] = []
        for strat in strategies:
            ranked_lists.append([m.id for m, _, _ in strat if m.id is not None])
            for m, score, label in strat:
                if m.id is None:
                    continue
                strategies_hit[label] = strategies_hit.get(label, 0) + 1
                id_to_mem[m.id] = m
                id_to_best[m.id] = max(id_to_best.get(m.id, 0.0), float(score))

        fused = reciprocal_rank_fusion(ranked_lists, k=rrf_k)
        scored: list[tuple[Memory, float]] = [
            (id_to_mem[mid], score) for mid, score in fused if mid in id_to_mem
        ]

        if not scored:
            return RecallResult(memories=[], scores=[], strategies_hit={})

        scored = dedup_jaccard(scored, threshold=dedup_threshold)

        memories_ordered = [m for m, _ in scored]
        memories_ordered = truncate(memories_ordered, token_budget=budget)

        id_to_fused = dict(fused)
        final_scores = [float(id_to_fused.get(m.id, 0.0)) for m in memories_ordered]

        for m in memories_ordered:
            m.access_count += 1
            self.backend.update(m)

        trimmed = {k: v for k, v in strategies_hit.items() if v}
        return RecallResult(
            memories=memories_ordered[:limit],
            scores=final_scores[:limit],
            strategies_hit=trimmed,
        )
