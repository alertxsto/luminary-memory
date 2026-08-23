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


class _MaintenanceEnricher(LLMEnricher):
    """Enricher that returns a fixed actions payload."""

    def __init__(self, raw: str):
        self.raw = raw

    def enrich(self, text: str) -> EnrichedContent:
        return EnrichedContent(content=text)

    def review_memories(self, memories: list) -> str:
        return self.raw


def test_run_maintenance_no_enricher(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    c.ingest("some fact")
    result = c.run_maintenance()
    assert result["skipped"]  # no LLM enricher


def test_run_maintenance_empty_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), enricher=_MaintenanceEnricher("{}"),
                     engine=_FakeEngine())
    result = c.run_maintenance()
    assert result == {"reviewed": 0, "deleted": 0, "updated": 0}


def test_run_maintenance_delete_and_update(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher(
                         '{"actions": [{"id": 1, "action": "delete"}, '
                         '{"id": 2, "action": "update", "content": "new fact"}, '
                         '{"id": 3, "action": "keep"}]}'
                     ),
                     engine=_FakeEngine())
    id1 = c.ingest("old fact one")
    id2 = c.ingest("old fact two")
    id3 = c.ingest("keep this")
    result = c.run_maintenance()
    assert result["reviewed"] == 3
    assert result["deleted"] == 1
    assert result["updated"] == 1
    assert c.get(id1) is None
    assert c.get(id2).content == "new fact"
    assert c.get(id3).content == "keep this"


def test_run_maintenance_accepts_string_ids_from_json_llm(tmp_path):
    c = MemoryClient(
        db_path=str(tmp_path / "t.db"),
        enricher=_MaintenanceEnricher('{"actions": [{"id": "1", "action": "delete"}]}'),
        engine=_FakeEngine(),
    )
    mid = c.ingest("old fact")

    result = c.run_maintenance()

    assert result["deleted"] == 1
    assert c.get(mid) is None


def test_run_maintenance_bad_llm_response(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher("not a list"),
                     engine=_FakeEngine())
    c.ingest("fact")
    result = c.run_maintenance()
    assert result["error"] == "bad LLM response"


def test_run_maintenance_unknown_id_skipped(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher('{"actions": [{"id": 999, "action": "delete"}]}'),
                     engine=_FakeEngine())
    c.ingest("fact")
    result = c.run_maintenance()
    assert result["deleted"] == 0


def test_update_bumps_updated_at_and_reembeds(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    mid = c.ingest("original content")
    m = c.get(mid)
    before = m.updated_at
    m.content = "changed content"
    c.update(m)
    m2 = c.get(mid)
    assert m2.content == "changed content"
    assert m2.updated_at >= before


def test_delete_nonexistent_is_graceful(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    c.ingest("fact")
    c.delete(99999)  # should not raise
    assert c.count() == 1


def test_run_maintenance_delete_error_swallowed(tmp_path, monkeypatch):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher('{"actions": [{"id": 1, "action": "delete"}]}'),
                     engine=_FakeEngine())
    c.ingest("fact to delete")

    def boom_delete(mid):
        raise RuntimeError("delete failed")
    monkeypatch.setattr(c, "delete", boom_delete)

    result = c.run_maintenance()
    assert result["deleted"] == 0  # error swallowed, not raised
    assert result["reviewed"] == 1
    c.close()


def test_run_maintenance_update_error_swallowed(tmp_path, monkeypatch):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher('{"actions": [{"id": 1, "action": "update", "content": "new"}]}'),
                     engine=_FakeEngine())
    c.ingest("old fact")

    def boom_update(m):
        raise RuntimeError("update failed")
    monkeypatch.setattr(c, "update", boom_update)

    result = c.run_maintenance()
    assert result["updated"] == 0
    assert result["reviewed"] == 1
    c.close()
