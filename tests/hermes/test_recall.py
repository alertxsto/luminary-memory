"""T9: Auto-recall — queue_prefetch, prefetch, recall_status.

Persistent-context injection (top-N by importance) is merged into every
turn's prefetch, so important rules are always in context regardless of
query match, with anti-duplication against the query-recall block.
"""

import time

from luminary_memory.hermes.provider import LuminaryMemoryProvider

_RECALL_HEADER = "# Luminary Memory (persistent cross-session context)"


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        return [0.25] * 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * 384 for _ in texts]


def _init_provider(tmp_path, **overrides):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    p._config.update(overrides)
    p._client.engine = _FakeEngine()
    return p


def _seed(p, texts):
    for t in texts:
        p._client.ingest(t, tags=["seed"], source="test")


def test_prefetch_returns_cached_block_and_indicator(tmp_path):
    p = _init_provider(tmp_path)
    _seed(p, ["the database uses sqlite fts5 for search", "vector similarity is fast", "temporal decay ranks recent facts"])

    p.queue_prefetch("database search", session_id="s1")
    block = p.prefetch("database search", session_id="s1")

    assert block, "prefetch returned an empty block"
    # Persistent context is always present (top-N by importance)
    assert "Key memories" in block
    # The recall block (header) may appear when non-injected memories match
    assert "sqlite fts5" in block

    status = p.recall_status()
    # status may be None when all recalled memories were already injected via
    # persistent context (anti-dup) — that's the intended no-duplicate behavior
    assert status is None or (status.provider_label == "Luminary" and status.glyph == "🌙")
    p.shutdown()


def test_recall_sync_returns_without_queue(tmp_path):
    p = _init_provider(tmp_path, recall_sync=True)
    _seed(p, ["postgres vector search is production ready"])

    block = p.prefetch("postgres", session_id="s1")
    assert block and "Key memories" in block
    assert "postgres" in block
    p.shutdown()


def test_persistent_context_merged_and_anti_duplicated(tmp_path):
    """Important rule is always injected, and never duplicated by recall."""
    p = _init_provider(tmp_path)
    # A high-importance rule + a lower-importance fact
    _seed(p, ["rule: always use markdown tables in telegram replies"])
    rule_id = None
    for m in p._client.list(limit=0):
        if "markdown tables" in m.content:
            rule_id = m.id
    assert rule_id is not None
    m = p._client.get(rule_id)
    m.importance = 0.95  # pin it like the enricher would
    p._client.update(m)
    p._client.ingest("the staging cluster deploy target uses docker compose", tags=["seed"])

    # Query only matches the deploy fact, not the rule
    p.queue_prefetch("deploy docker compose", session_id="s1")
    block = p.prefetch("deploy docker compose", session_id="s1")

    # Rule is present via persistent context even though query doesn't match it
    assert "markdown tables" in block
    # Deploy fact present via query recall
    assert "deploy target" in block
    # Anti-dup: rule content appears exactly once
    assert block.count("markdown tables") == 1
    p.shutdown()


def test_auto_recall_disabled_returns_empty(tmp_path):
    p = _init_provider(tmp_path, auto_recall=False)
    _seed(p, ["something to recall"])

    block = p.prefetch("something", session_id="s1")
    assert block == ""
    assert p.recall_status() is None
    p.shutdown()


def test_tools_mode_queue_prefetch_is_noop(tmp_path):
    p = _init_provider(tmp_path, mode="tools")
    _seed(p, ["tool only recall data"])

    p.queue_prefetch("tool only", session_id="s1")
    time.sleep(0.4)
    block = p.prefetch("tool only", session_id="s1")
    assert block == ""
    p.shutdown()


def test_do_retain_drops_raw_when_curation_yields_no_summary(tmp_path):
    """With ingest_llm on, a turn whose LLM curation produced no distilled
    summary must NOT be stored as a raw transcript (store hygiene)."""
    from luminary_memory.ingest.llm import EnrichedContent

    class _NoSummaryEnricher:
        def enrich(self, text):
            return EnrichedContent(content=text, summary=None, worth_saving=True)

    p = _init_provider(tmp_path, ingest_llm=True)
    p._client.enricher = _NoSummaryEnricher()
    client = p._writer_client()
    client.enricher = _NoSummaryEnricher()

    p._do_retain("User: bikin PLAN dong\nAssistant: ok gw buat", [], {}, source="test")
    p._writer_thread.join(timeout=5.0)

    assert p._client.count() == 0, "raw transcript without curated summary must be dropped"
    p.shutdown()


def test_do_retain_stores_curated_summary(tmp_path):
    """With ingest_llm on, a turn whose LLM curation produced a summary is
    stored as the summary, never the raw transcript."""
    from luminary_memory.ingest.llm import EnrichedContent

    class _SummaryEnricher:
        def enrich(self, text):
            return EnrichedContent(
                content=text,
                summary="User WAJIB pakai markdown table di Telegram",
                worth_saving=True,
            )

    p = _init_provider(tmp_path, ingest_llm=True)
    p._client.enricher = _SummaryEnricher()
    client = p._writer_client()
    client.enricher = _SummaryEnricher()

    p._do_retain("User: tolong pakai table ya\nAssistant: siap", [], {}, source="test")
    p._writer_thread.join(timeout=5.0)

    mems = p._client.list(limit=0)
    assert len(mems) == 1
    assert "markdown table" in mems[0].content
    assert "tolong pakai table" not in mems[0].content
    p.shutdown()
