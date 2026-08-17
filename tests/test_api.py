from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import EnrichedContent, LLMEnricher, NoopEnricher


class _FakeEngine:
    def __init__(self):
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [0.25] * 384


class _FakeEnricher(LLMEnricher):
    def enrich(self, text: str) -> EnrichedContent:
        return EnrichedContent(
            content=f"{text} (enriched)",
            summary="a short summary",
            entities=["entity_a"],
            tags=["extra"],
        )


def test_ingest_stores_and_recalls(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), enricher=NoopEnricher(),
                     engine=_FakeEngine())
    mid = c.ingest("postgres vector similarity search is fast", tags=["db"])
    assert mid is not None
    assert c.count() == 1
    m = c.get(mid)
    assert m is not None and m.content == "postgres vector similarity search is fast"
    assert m.embedding == [0.25] * 384


def test_ingest_rejected_by_whitelist(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), ingest_whitelist=[r"kubernetes"],
                     engine=_FakeEngine())
    mid = c.ingest("postgres vector search")
    assert mid is None
    assert c.count() == 0


def test_ingest_applies_enrichment(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), enricher=_FakeEnricher(),
                     engine=_FakeEngine())
    mid = c.ingest("raw text", tags=["orig"])
    m = c.get(mid)
    assert m.content == "raw text (enriched)"
    assert m.metadata["summary"] == "a short summary"
    assert m.metadata["entities"] == ["entity_a"]
    assert set(m.tags) == {"orig", "extra"}


def test_ingest_noop_enricher_passthrough(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    mid = c.ingest("plain content")
    m = c.get(mid)
    assert m.content == "plain content"
    assert m.tags == []


def test_ingest_applies_ttl_default(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"), ttl_default_seconds=60)
    c = MemoryClient(settings=settings, engine=_FakeEngine())
    mid = c.ingest("ephemeral fact")
    m = c.get(mid)
    assert m.ttl_seconds == 60
