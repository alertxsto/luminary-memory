from luminary_memory.api import MemoryClient
from luminary_memory.ingest.llm import NoopEnricher


class _FakeEngine:
    def __init__(self):
        self.embed_batch_calls = 0

    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.embed_batch_calls += 1
        return [[0.25] * 384 for _ in texts]


def test_ingest_batch_with_whitelist_rejection(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), ingest_whitelist=[r"postgres"],
                     engine=_FakeEngine(), enricher=NoopEnricher())
    ids = c.ingest_batch(["postgres vector index", "cooking pasta tonight", "postgres fts5 search"])
    assert ids[0] is not None and ids[2] is not None
    assert ids[1] is None
    assert c.count() == 2
    accepted = [c.get(mid) for mid in ids if mid is not None]
    assert all(m.embedding == [0.25] * 384 for m in accepted if m)


def test_ingest_batch_uses_embed_batch_once(tmp_path):
    engine = _FakeEngine()
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=engine, enricher=NoopEnricher())
    c.ingest_batch(["hello one", "hello two", "hello three"])
    assert engine.embed_batch_calls == 1


def test_ingest_batch_tags_and_source(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine(), enricher=NoopEnricher())
    ids = c.ingest_batch(["alpha beta gamma", "alpha delta epsilon"],
                         tags=[["t1"], ["t2"]])
    assert c.count() == 2
    assert set(c.get(ids[0]).tags) == {"t1"}
    assert set(c.get(ids[1]).tags) == {"t2"}
