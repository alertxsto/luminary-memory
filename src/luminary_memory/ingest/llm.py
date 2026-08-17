from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EnrichedContent:
    content: str
    summary: str | None = None
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class LLMEnricher:
    def enrich(self, text: str) -> EnrichedContent:
        raise NotImplementedError


class NoopEnricher(LLMEnricher):
    def enrich(self, text: str) -> EnrichedContent:
        return EnrichedContent(content=text)
