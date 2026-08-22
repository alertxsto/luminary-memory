"""Adversarial correctness tests for the accuracy-first memory path."""

from __future__ import annotations

import json
import sqlite3

import pytest

from luminary_memory.api import MemoryClient
from luminary_memory.backends.sqlite import SQLiteBackend
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import EnrichedContent, LLMEnricher, NoopEnricher
from luminary_memory.ingest.rules import contains_rule_keyword
from luminary_memory.recall.keyword import keyword_recall
from luminary_memory.recall.semantic import semantic_recall
from luminary_memory.recall.temporal import temporal_recall
from luminary_memory.schema import init_schema
from luminary_memory.types import Memory


class _Engine:
    def embed(self, text: str) -> list[float]:
        # Stable, non-degenerate vector; the tests focus on scope and state,
        # while keyword/graph paths remain deterministic.
        value = sum(ord(char) for char in text) % 97
        return [float(value + 1), float(len(text) + 1), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class _ClaimEnricher(LLMEnricher):
    def enrich(self, text: str) -> EnrichedContent:
        value = "production" if "production" in text.casefold() else "staging"
        return EnrichedContent(
            content=text,
            claims=[
                {
                    "subject": "project:luminary",
                    "predicate": "deploy_target",
                    "object": value,
                    "polarity": "positive",
                    "confidence": 0.9,
                    "evidence_quote": text,
                }
            ],
        )


class _SummaryEnricher(LLMEnricher):
    def enrich(self, text: str) -> EnrichedContent:
        return EnrichedContent(
            content="Deploy target is staging.",
            summary="Deploy target is staging.",
            claims=[
                {
                    "subject": "project:luminary",
                    "predicate": "deploy_target",
                    "object": "staging",
                    "polarity": "positive",
                    "confidence": 0.9,
                    "evidence_quote": "deploy target is staging",
                }
            ],
        )


def _client(tmp_path, *, scope=None, settings=None, enricher=None):
    config = settings or Settings(
        db_path=str(tmp_path / "memory.db"),
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
    )
    return MemoryClient(
        settings=config,
        engine=_Engine(),
        enricher=enricher or NoopEnricher(),
        scope=scope,
    )


def test_schema_migration_adds_accuracy_tables_and_hashes_legacy_rows(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, tags TEXT)")
    conn.execute("INSERT INTO memories(id, content, tags) VALUES (1, 'legacy fact', '[]')")
    conn.commit()
    init_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"user_id", "status", "confidence", "content_hash", "needs_reindex"} <= columns
    assert {"memory_events", "memory_evidence", "episodes", "claims", "claim_evidence"} <= tables
    assert conn.execute("SELECT content_hash FROM memories WHERE id=1").fetchone()[0]
    conn.close()


def test_schema_repairs_partial_fts_table_before_keyword_recall(tmp_path):
    path = tmp_path / "partial-fts.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, tags TEXT)")
    conn.execute("INSERT INTO memories(id, content, tags) VALUES (1, 'legacy postgres fact', '[]')")
    conn.execute("CREATE TABLE memories_fts (rowid INTEGER PRIMARY KEY, broken TEXT)")
    conn.commit()
    init_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories_fts)")}
    assert {"content", "tags"} <= columns
    conn.close()

    client = MemoryClient(
        db_path=str(path),
        engine=_Engine(),
        enricher=NoopEnricher(),
    )
    assert client.search("postgres", limit=5)
    client.close()


def test_scope_isolation_applies_to_get_list_recall_and_fallback(tmp_path):
    writer = _client(tmp_path)
    alice_id = writer.ingest(
        "Alice private deployment secret is alpha.",
        user_id="alice",
        workspace_id="w",
        evidence_quote="Alice private deployment secret is alpha.",
    )
    bob_id = writer.ingest(
        "Bob private deployment secret is beta.",
        user_id="bob",
        workspace_id="w",
        evidence_quote="Bob private deployment secret is beta.",
    )
    writer.close()

    alice = _client(tmp_path, scope={"user_id": "alice", "workspace_id": "w"})
    assert alice.get(alice_id) is not None
    assert alice.get(bob_id) is None
    assert {m.id for m in alice.list(limit=0)} == {alice_id}
    result = alice.recall("private deployment secret", limit=10, strict=True)
    assert {m.user_id for m in result.memories} <= {"alice", None}
    assert bob_id not in {m.id for m in result.memories}
    alice.close()


def test_scoped_graph_excludes_orphan_entities_from_other_scope(tmp_path):
    """Graph/debug output must not expose stale entity names across tenants."""
    client = _client(tmp_path)
    alice_id = client.ingest(
        "AliceOnly deployment alpha",
        user_id="alice",
        evidence_quote="AliceOnly deployment alpha",
    )
    bob_id = client.ingest(
        "BobOnly deployment beta",
        user_id="bob",
        evidence_quote="BobOnly deployment beta",
    )
    # Simulate normal hard deletion after an earlier tenant-owned memory. The
    # current schema removes relations but deliberately keeps entity rows, so
    # the graph query must scope through visible memory links rather than
    # treating orphan entities as globally visible.
    client.backend.delete(bob_id)

    alice = _client(tmp_path, scope={"user_id": "alice"})
    graph = alice.graph(limit=50)
    names = {row["name"] for row in graph["entities"]}
    assert "aliceonly" in names
    assert "bobonly" not in names
    assert alice.get(alice_id) is not None
    alice.close()
    client.close()


def test_duplicate_fallback_ignores_deleted_rows(tmp_path):
    """A legacy backend fallback must dedup only active memories."""
    client = _client(tmp_path)
    first = client.ingest("reusable durable fact")
    client.retract(first, reason="test retraction")

    # Simulate a third-party backend that has not implemented find_by_hash().
    client.backend.find_by_hash = None
    second = client.ingest("reusable durable fact")

    assert second != first
    assert client.get(second).status == "active"
    assert client.count() == 1
    client.close()


def test_bound_scope_cannot_be_overridden_by_write_or_read_arguments(tmp_path):
    client = _client(tmp_path, scope={"user_id": "alice"})

    with pytest.raises(PermissionError, match="bound scope"):
        client.ingest("private bob fact", user_id="bob")

    alice_id = client.ingest("private alice fact")
    with pytest.raises(PermissionError, match="bound scope"):
        client.get(alice_id, scope={"user_id": "bob"})
    with pytest.raises(PermissionError, match="bound scope"):
        client.list(scope={"user_id": "bob"})
    with pytest.raises(PermissionError, match="bound scope"):
        client.search("private", scope={"user_id": "bob"})
    with pytest.raises(PermissionError, match="bound scope"):
        client.recall("private", scope={"user_id": "bob"})

    # Adding a narrower session scope is valid as long as the bound user is
    # preserved.
    session_id = client.ingest("alice session fact", session_id="s1")
    assert client.get(session_id, scope={"user_id": "alice", "session_id": "s1"})
    client.close()


def test_global_rows_are_readable_but_not_mutable_from_bound_scope(tmp_path):
    writer = _client(tmp_path)
    global_id = writer.backend.add(Memory(content="shared global policy"))
    writer.close()

    client = _client(tmp_path, scope={"user_id": "alice"})
    visible = client.get(global_id)
    assert visible is not None
    visible.content = "alice rewrote global policy"
    with pytest.raises(PermissionError, match="mutable scope"):
        client.update(visible)
    assert client.get(global_id).content == "shared global policy"

    owned_id = client.ingest("alice-owned policy")
    owned = client.get(owned_id)
    owned.user_id = "bob"
    with pytest.raises(PermissionError, match="mutable scope"):
        client.update(owned)
    assert client.get(owned_id).user_id == "alice"
    client.close()


def test_scoped_recall_does_not_touch_read_compatible_global_row(tmp_path):
    writer = _client(tmp_path)
    global_memory = Memory(
        content="shared global deployment policy",
        evidence_quote="shared global deployment policy",
        embedding=_Engine().embed("shared global deployment policy"),
        importance=0.35,
    )
    global_id = writer.backend.add(global_memory)
    writer.close()

    client = _client(tmp_path, scope={"user_id": "alice"})
    before = client.backend.get(global_id)
    assert before is not None
    result = client.recall("shared global deployment policy", strict=True)
    assert global_id in {memory.id for memory in result.memories}
    after = client.backend.get(global_id)
    assert after is not None
    assert after.access_count == before.access_count == 0
    assert after.importance == before.importance == 0.35
    client.close()


def test_strict_scope_lifecycle_does_not_touch_global_rows(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "lifecycle-scope.db"),
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
        scope_include_global=False,
        max_memories=1,
        importance_auto=False,
    )
    client = _client(tmp_path, scope={"user_id": "alice"}, settings=settings)
    global_id = client.backend.add(Memory(content="global low-value policy", importance=0.1))
    alice_id = client.ingest("alice low-value policy", importance=0.1)

    result = client.run_lifecycle(semantic=False)

    assert result["prune"] >= 1
    assert client.backend.get(global_id) is not None
    assert client.backend.get(alice_id) is None
    client.close()


def test_default_scoped_lifecycle_never_mutates_global_rows(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "lifecycle-scope-default.db"),
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
        scope_include_global=True,
        max_memories=1,
        importance_auto=False,
    )
    client = _client(tmp_path, scope={"user_id": "alice"}, settings=settings)
    global_id = client.backend.add(Memory(content="global shared policy", importance=0.1))
    alice_id = client.ingest("alice private policy", importance=0.1)

    result = client.run_lifecycle(semantic=False)

    assert result["prune"] >= 1
    assert client.backend.get(global_id) is not None
    assert client.backend.get(alice_id) is None
    client.close()


def test_legacy_backend_fallbacks_filter_before_applying_top_k(tmp_path):
    """Old backend signatures must not let another tenant consume top-k."""

    class _LegacyBackend(SQLiteBackend):
        def keyword_search(self, query, limit=10):
            return super().keyword_search(query, limit=limit)

        def vector_search(self, vec, limit=10):
            return super().vector_search(vec, limit=limit)

        def temporal_scan(self):
            return super().temporal_scan()

    path = tmp_path / "legacy-recall.db"
    writer = SQLiteBackend(str(path))
    writer.add(
        Memory(
            content="secret secret secret",
            user_id="bob",
            embedding=[1.0, 0.0],
        )
    )
    writer.add(
        Memory(
            content="secret",
            user_id="alice",
            embedding=[0.8, 0.2],
        )
    )
    writer.close()

    backend = _LegacyBackend(str(path))
    scope = {"user_id": "alice"}
    keyword = keyword_recall(
        backend,
        "secret",
        limit=1,
        scope=scope,
        include_global=False,
    )
    semantic = semantic_recall(
        backend,
        type(
            "_QueryEngine",
            (),
            {"embed": lambda self, text: [1.0, 0.0]},
        )(),
        "secret",
        limit=1,
        scope=scope,
        include_global=False,
    )
    temporal = temporal_recall(
        backend,
        limit=1,
        scope=scope,
        include_global=False,
    )

    assert [row[0].user_id for row in keyword] == ["alice"]
    assert [row[0].user_id for row in semantic] == ["alice"]
    assert [row[0].user_id for row in temporal] == ["alice"]
    backend.close()


def test_batch_keeps_raw_episode_lineage_when_enrichment_summarizes(tmp_path):
    client = _client(tmp_path, enricher=_SummaryEnricher())
    raw = "The release review confirmed that the deploy target is staging before Friday."
    ids = client.ingest_batch([raw])

    assert ids[0] is not None
    memory = client.get(ids[0])
    assert memory.content == "Deploy target is staging."
    episode = client.backend.conn.execute(
        "SELECT content FROM episodes WHERE id = ?", (f"memory:{ids[0]}",)
    ).fetchone()
    assert episode[0] == raw
    claim_evidence = client.backend.conn.execute(
        "SELECT quote FROM claim_evidence JOIN claims ON claims.id = claim_evidence.claim_id "
        "WHERE claims.memory_id = ?",
        (ids[0],),
    ).fetchone()
    assert claim_evidence[0] == "deploy target is staging"
    client.close()


def test_strict_recall_abstains_on_unrelated_query(tmp_path):
    client = _client(tmp_path)
    client.ingest(
        "The deploy target is staging.",
        source="test:deploy",
        evidence_quote="The deploy target is staging.",
    )
    result = client.recall("What is the office WiFi password?", strict=True)
    assert result.status == "abstain"
    assert result.reason in {"low_confidence_or_ambiguous", "no_supported_candidate"}
    assert result.memories == []
    client.close()


def test_strict_recall_requires_quote_not_just_source_label(tmp_path):
    client = _client(tmp_path)
    memory = Memory(
        content="The deploy target is staging.",
        source_id="ticket:42",
        embedding=_Engine().embed("The deploy target is staging."),
    )
    memory.id = client.backend.add(memory)
    result = client.recall("deploy target staging", strict=True)
    assert result.memories == []
    assert result.reason == "missing_evidence"
    client.close()


def test_evidence_required_blocks_ungrounded_candidates_even_when_not_strict(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "permissive-evidence.db"),
        strict_recall=False,
        evidence_required=True,
        rule_auto_replace=False,
    )
    client = _client(tmp_path, settings=settings)
    memory = Memory(
        content="The deploy target is staging.",
        evidence_quote="fabricated quote",
        source_id="ticket:42",
        embedding=_Engine().embed("The deploy target is staging."),
    )
    memory.id = client.backend.add(memory)
    result = client.recall("deploy target staging", strict=False)
    assert result.memories == []
    assert result.status == "empty"
    assert result.reason == "missing_evidence"
    client.close()


def test_malformed_validity_window_is_excluded_from_strict_recall(tmp_path):
    client = _client(tmp_path)
    memory = Memory(
        content="The deploy target is staging.",
        evidence_quote="The deploy target is staging.",
        valid_to="not-a-timestamp",
        embedding=_Engine().embed("The deploy target is staging."),
    )
    memory.id = client.backend.add(memory)
    result = client.recall("deploy target staging", strict=True)
    assert result.memories == []
    client.close()


def test_all_tag_mode_survives_fallback_without_leaking_other_tags(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "memory.db"),
        strict_recall=False,
        rule_auto_replace=False,
    )
    client = _client(tmp_path, settings=settings)
    both = client.ingest("Important database rule for postgres.", tags=["core", "db"], importance=0.95)
    only_core = client.ingest("Important unrelated core rule.", tags=["core"], importance=0.95)
    result = client.recall("zzzz-no-keyword", tags=["core", "db"], tag_mode="all", limit=10)
    assert both in {m.id for m in result.memories}
    assert only_core not in {m.id for m in result.memories}
    client.close()


def test_update_reembeds_and_reindexes_graph(tmp_path):
    client = _client(tmp_path)
    memory_id = client.ingest("Postgres database relation.")
    memory = client.get(memory_id)
    memory.content = "Redis cache relation."
    client.update(memory)
    assert client.search("Redis", limit=5)
    assert client.search("Postgres", limit=5) == []
    assert client.recall("Redis cache", strict=True).memories
    assert client.recall("Postgres database", strict=True).memories == []
    memory = client.get(memory_id)
    memory.content = "42"
    memory.tags = []
    client.update(memory)
    relation_count = client.backend.conn.execute(
        "SELECT COUNT(*) FROM relations WHERE memory_id = ?", (memory_id,)
    ).fetchone()[0]
    assert relation_count == 0
    client.close()


def test_exact_dedup_is_scope_aware_and_audited(tmp_path):
    client = _client(tmp_path, scope={"user_id": "u1"})
    first = client.ingest("same durable fact", evidence_quote="same durable fact")
    duplicate = client.ingest("  SAME   durable fact ", evidence_quote="same durable fact")
    assert duplicate == first
    assert client.count() == 1
    row = client.backend.conn.execute(
        "SELECT COUNT(*) FROM memory_events WHERE event_type='duplicate_suppressed'"
    ).fetchone()[0]
    assert row == 1
    client.close()


def test_update_repairs_tampered_hash_before_future_dedup(tmp_path):
    client = _client(tmp_path)
    memory_id = client.ingest("canonical durable fact")
    memory = client.get(memory_id)
    assert memory is not None
    memory.content_hash = "tampered-hash"
    client.update(memory)

    repaired = client.get(memory_id)
    assert repaired is not None
    assert repaired.content_hash != "tampered-hash"
    assert client.ingest("  CANONICAL   durable fact ") == memory_id
    suppressed = client.backend.conn.execute(
        "SELECT COUNT(*) FROM memory_events WHERE event_type = 'duplicate_suppressed'"
    ).fetchone()[0]
    assert suppressed == 1
    client.close()


def test_update_repairs_tampered_evidence_and_tag_container(tmp_path):
    client = _client(tmp_path)
    memory_id = client.ingest(
        "canonical evidence fact",
        tags=["fact"],
        evidence_quote="canonical evidence fact",
    )
    memory = client.get(memory_id)
    assert memory is not None
    memory.evidence_quote = "fabricated quote"
    memory.tags = "fact"  # type: ignore[assignment]
    client.update(memory)

    repaired = client.get(memory_id)
    assert repaired is not None
    assert repaired.evidence_quote == repaired.content
    assert repaired.tags == ["fact"]
    client.close()


def test_claim_write_failure_does_not_block_later_claims(tmp_path):
    client = _client(tmp_path)
    memory_id = client.ingest("source with two independent claims", enrich=False)
    original_add_claim = client.backend.add_claim
    calls: list[str] = []

    def flaky_add_claim(memory_id, claim, **scope):
        calls.append(str(claim["object"]))
        if len(calls) == 1:
            raise RuntimeError("simulated malformed claim")
        return original_add_claim(memory_id, claim, **scope)

    client.backend.add_claim = flaky_add_claim
    client._record_episode_and_claims(
        client.get(memory_id),
        "source with two independent claims",
        [
            {
                "subject": "project:luminary",
                "predicate": "first",
                "object": "bad-but-isolated",
                "evidence_quote": "first",
            },
            {
                "subject": "project:luminary",
                "predicate": "second",
                "object": "retained",
                "evidence_quote": "second",
            },
        ],
    )

    assert calls == ["bad-but-isolated", "retained"]
    assert client.backend.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    assert client.backend.conn.execute(
        "SELECT object FROM claims"
    ).fetchone()[0] == "retained"
    client.close()


def test_rule_keyword_matching_uses_word_boundaries(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "rules.db"),
        rule_keywords="MUST",
        rule_auto_replace=False,
    )
    client = _client(tmp_path, settings=settings)
    assert not contains_rule_keyword("the recipe uses mustard seeds", settings.rule_keywords)
    assert contains_rule_keyword("the release MUST use a review", settings.rule_keywords)
    client.ingest("the recipe uses mustard seeds")
    client.ingest("the release MUST use a review")
    client.close()


def test_conflict_history_and_explicit_supersede(tmp_path):
    client = _client(tmp_path, scope={"user_id": "u1", "workspace_id": "w"})
    key = "project|deploy_target|positive"
    old_id = client.ingest(
        "Deploy target is staging.",
        claim_key=key,
        evidence_quote="Deploy target is staging.",
        source_id="ticket:1",
    )
    conflict_id = client.ingest(
        "Deploy target is production.",
        claim_key=key,
        evidence_quote="Deploy target is production.",
        source_id="ticket:2",
    )
    assert client.get(old_id).status == "conflicted"
    assert client.get(conflict_id).status == "conflicted"
    new_id = client.supersede(
        old_id,
        "Deploy target is production after approval.",
        evidence_quote="Deploy target is production after approval.",
        source_id="ticket:3",
    )
    assert new_id not in {old_id, conflict_id}
    assert client.get(new_id).status == "active"
    assert client.get(old_id).status == "superseded"
    assert client.get(conflict_id).status == "superseded"
    result = client.recall("current deploy target", strict=True)
    assert [m.id for m in result.memories] == [new_id]
    assert result.provenance[0]["evidence_quote"]

    diagnostic_dir = tmp_path / "diagnostic"
    diagnostic_dir.mkdir()
    diagnostic = _client(diagnostic_dir, scope={"user_id": "u1", "workspace_id": "w"})
    left = diagnostic.ingest(
        "Deploy target is staging.",
        claim_key=key,
        evidence_quote="Deploy target is staging.",
    )
    right = diagnostic.ingest(
        "Deploy target is production.",
        claim_key=key,
        evidence_quote="Deploy target is production.",
    )
    conflicted = diagnostic.recall("deploy target", include_conflicted=True, strict=False)
    assert {m.id for m in conflicted.memories} >= {left, right}
    diagnostic.close()
    client.close()


def test_claim_ledger_follows_conflict_and_update_status(tmp_path):
    client = _client(
        tmp_path,
        scope={"user_id": "u1"},
        enricher=_ClaimEnricher(),
    )
    first = client.ingest("Deploy target is staging.")
    second = client.ingest("Deploy target is production.")
    rows = client.backend.conn.execute(
        "SELECT memory_id, status FROM claims ORDER BY id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        (first, "conflicted"),
        (second, "conflicted"),
    ]

    memory = client.get(second)
    memory.content = "Deploy target is a private cluster."
    client.update(memory)
    status = client.backend.conn.execute(
        "SELECT status FROM claims WHERE memory_id = ?", (second,)
    ).fetchone()[0]
    assert status == "superseded"
    assert client.get(second).claim_key is None
    client.close()


class _Maintenance(LLMEnricher):
    def __init__(self, payload: str):
        self.payload = payload

    def enrich(self, text: str):
        return EnrichedContent(content=text)

    def review_memories(self, memories: list) -> str:
        return self.payload


def test_strict_maintenance_requires_evidence_and_confirmation(tmp_path):
    enricher = _Maintenance(
        json.dumps(
            {
                "actions": [
                    {
                        "id": 1,
                        "action": "update",
                        "content": "unverified replacement",
                        "evidence_quote": "fabricated quote",
                    },
                    {
                        "id": 2,
                        "action": "delete",
                        "reason": "obsolete",
                        "evidence_quote": "core rule",
                    },
                ]
            }
        )
    )
    client = _client(tmp_path, enricher=enricher)
    first = client.ingest("ordinary fact")
    core = client.ingest("core rule", tags=["core"], importance=0.95)
    # IDs are deterministic in this isolated store.
    assert (first, core) == (1, 2)
    result = client.run_maintenance()
    assert result["skipped"] == 2
    assert client.get(first).content == "ordinary fact"
    assert client.get(core) is not None
    client.close()
