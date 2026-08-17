from luminary_memory.api import MemoryClient
from luminary_memory.ingest.llm import NoopEnricher


class _FakeEngine:
    def embed(self, t: str) -> list[float]:
        return [0.1] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]


def test_recall_tag_scoped_returns_only_allowed_tags(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    c.ingest("postgres vector index", tags=["a"])
    c.ingest("postgres vector search with postgres", tags=["b"])
    c.ingest("postgres vector fts hybrid", tags=["a", "b"])
    res = c.recall("postgres", tags=["a"], limit=10)
    assert all("a" in (m.tags or []) for m in res.memories)
    assert len(res.memories) == 2


def test_recall_without_tags_returns_all(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    c.ingest("first tagged memory", tags=["a"])
    c.ingest("second tagged memory", tags=["b"])
    res = c.recall("tagged", limit=10)
    assert len(res.memories) == 2
