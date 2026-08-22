"""Adversarial correctness tests for the accuracy-first memory path."""

from __future__ import annotations

import json
import sqlite3

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import EnrichedContent, LLMEnricher, NoopEnricher
from luminary_memory.schema import init_schema


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


def test_scope_isolation_applies_to_get_list_recall_and_fallback(tmp_path):
    writer = _client(tmp_path, scope={"user_id": "writer"})
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
