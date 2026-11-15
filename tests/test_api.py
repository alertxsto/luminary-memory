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


class _ProposalEnricher(LLMEnricher):
    """Propose one action grounded in the candidate's own stored source."""

    def __init__(self, action: str = "delete", content: str = "updated fact"):
        self.action = action
        self.content = content

    def enrich(self, text: str) -> EnrichedContent:
        return EnrichedContent(content=text)

    def review_memories(self, memories: list) -> str:
        import json

        memory = memories[0]
        action = {
            "id": memory.id,
            "action": self.action,
            "source_id": memory.source_id,
            "evidence_quote": memory.evidence_quote,
        }
        if self.action == "update":
            action["content"] = self.content
        return json.dumps({"actions": [action]})


def test_run_maintenance_no_enricher(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), engine=_FakeEngine())
    c.ingest("some fact")
    result = c.run_maintenance()
    assert result["skipped"]  # no LLM enricher


def test_run_maintenance_empty_store(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), enricher=_MaintenanceEnricher("{}"),
                     engine=_FakeEngine())
    result = c.run_maintenance()
    assert result == {"reviewed": 0, "proposed": 0}


def test_run_maintenance_proposes_without_mutating(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"), enricher=_ProposalEnricher("delete"),
                     engine=_FakeEngine())
    mid = c.ingest("old fact one")

    result = c.run_maintenance()

    assert result["reviewed"] == 1
    assert result["proposed"] == 1
    # The model's proposal is not authority: the record is untouched until an
    # owner confirms the preview in the inspector.
    assert c.get(mid) is not None
    assert c.get(mid).status == "active"


def test_run_maintenance_update_proposal_keeps_content(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_ProposalEnricher("update", "new fact"),
                     engine=_FakeEngine())
    mid = c.ingest("old fact two")

    result = c.run_maintenance()

    assert result["proposed"] == 1
    assert c.get(mid).content == "old fact two"


def test_run_maintenance_ignores_non_integer_ids(tmp_path):
    c = MemoryClient(
        db_path=str(tmp_path / "t.db"),
        enricher=_MaintenanceEnricher('{"actions": [{"id": "1", "action": "delete"}]}'),
        engine=_FakeEngine(),
    )
    mid = c.ingest("old fact")

    result = c.run_maintenance()

    assert result["proposed"] == 0
    assert c.get(mid) is not None


def test_run_maintenance_bad_llm_response(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher("not a list"),
                     engine=_FakeEngine())
    mid = c.ingest("fact")
    result = c.run_maintenance()
    assert result["error"] == "bad LLM response"
    assert c.get(mid).status == "active"


def test_run_maintenance_unknown_id_skipped(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_MaintenanceEnricher('{"actions": [{"id": 999, "action": "delete"}]}'),
                     engine=_FakeEngine())
    mid = c.ingest("fact")
    result = c.run_maintenance()
    assert result["proposed"] == 0
    assert c.get(mid) is not None


def test_run_maintenance_requires_a_stored_source_quote(tmp_path):
    c = MemoryClient(
        db_path=str(tmp_path / "t.db"),
        enricher=_MaintenanceEnricher(
            '{"actions": [{"id": 1, "action": "update", "content": "invented", '
            '"source_id": "forged", "evidence_quote": "invented"}]}'
        ),
        engine=_FakeEngine(),
    )
    mid = c.ingest("stored fact")

    result = c.run_maintenance()

    assert result["proposed"] == 0
    assert c.get(mid).content == "stored fact"


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


def test_run_maintenance_never_calls_apply_paths(tmp_path, monkeypatch):
    c = MemoryClient(db_path=str(tmp_path / "t.db"),
                     enricher=_ProposalEnricher("delete"),
                     engine=_FakeEngine())
    c.ingest("fact to delete")

    def boom(*_args, **_kwargs):
        raise AssertionError("maintenance must not apply a proposal")

    monkeypatch.setattr(c, "delete", boom)
    monkeypatch.setattr(c, "update", boom)

    result = c.run_maintenance()
    assert result["proposed"] == 1
    assert result["reviewed"] == 1
    c.close()


def test_set_core_promotes_and_demotes(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "core.db"), engine=_FakeEngine())
    mid = c.ingest("release checklist requires two reviewers", tags=["process"])

    promoted = c.set_core(mid)
    assert promoted is not None
    assert promoted.tags.count("core") == 1
    assert promoted.importance >= 0.9
    assert "process" in promoted.tags

    # Idempotent: promoting twice keeps a single core tag.
    c.set_core(mid)
    assert c.get(mid).tags.count("core") == 1

    demoted = c.set_core(mid, pinned=False)
    assert demoted is not None
    assert "core" not in demoted.tags
    assert demoted.importance <= 0.89
    assert "process" in demoted.tags
    c.close()


def test_set_core_cannot_reach_another_owner(tmp_path):
    from luminary_memory.config import Settings
    from luminary_memory.types import Memory

    writer = MemoryClient(db_path=str(tmp_path / "core.db"), engine=_FakeEngine())
    foreign = writer.backend.add(Memory(content="bob keeps this", user_id="bob"))
    writer.close()

    client = MemoryClient(
        settings=Settings(db_path=str(tmp_path / "core.db"), scope_include_global=False),
        engine=_FakeEngine(),
        scope={"user_id": "alice"},
    )
    try:
        try:
            client.set_core(foreign)
        except ValueError as error:
            assert "does not exist in this scope" in str(error)
        else:
            raise AssertionError("another owner's memory must not become core")
        assert "core" not in (client.backend.get(foreign).tags or [])
    finally:
        client.close()


def test_set_core_requires_an_active_memory(tmp_path):
    c = MemoryClient(db_path=str(tmp_path / "core.db"), engine=_FakeEngine())
    mid = c.ingest("withdrawn rule")
    c.retract(mid, reason="superseded")

    try:
        c.set_core(mid)
    except ValueError as error:
        assert "only an active memory" in str(error)
    else:
        raise AssertionError("a retracted memory must not be promoted")
    c.close()
