"""Long-run behaviour of ingest, recall and lifecycle on a single store.

A single ingest/recall pair proves nothing about a store that runs for weeks.
These cover the properties that only show up across cycles: a fact that was
retrievable stays retrievable as the store fills, an unanswerable query never
starts returning rows, and lifecycle keeps the store from growing without the
memory count growing with it.

The full-scale run lives in ``scripts/soak-test.py``; this keeps a bounded
version in the normal suite.
"""

from __future__ import annotations

import math

from benchmarks.run_benchmarks import _FakeEngine
from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings
from luminary_memory.ingest.llm import NoopEnricher

CONTROL = "Project Luminary deploy target is production."
CONTROL_QUERY = "What is the project Luminary deploy target?"
NO_ANSWER_QUERY = "What is the office WiFi password?"

def _client(tmp_path) -> MemoryClient:
    return MemoryClient(
        settings=Settings(
            db_path=str(tmp_path / "soak.db"),
            strict_recall=True,
            evidence_required=True,
            rule_auto_replace=False,
        ),
        engine=_FakeEngine(),
        enricher=NoopEnricher(),
    )


def _filler(cycle: int, offset: int) -> str:
    # Distinct enough to survive near-duplicate dedup, so the store really grows.
    sequence = cycle * 4 + offset
    return (
        f"The backup job writes shard {sequence} to cold storage in region "
        f"{sequence % 13} and was reviewed by engineer {sequence % 89}."
    )


def test_control_fact_survives_a_filling_store(tmp_path):
    client = _client(tmp_path)
    try:
        client.ingest(CONTROL, tags=["core"], source="soak:control", evidence_quote=CONTROL)
        first = client.recall(CONTROL_QUERY, limit=5, strict=True)
        assert any(CONTROL in memory.content for memory in first.memories)

        for cycle in range(12):
            client.ingest_batch([_filler(cycle, offset) for offset in range(4)])
            result = client.recall(CONTROL_QUERY, limit=5, strict=True)
            assert result.status == "ok", f"cycle {cycle}: control query abstained"
            assert any(CONTROL in memory.content for memory in result.memories), (
                f"cycle {cycle}: control fact became unreachable"
            )

        assert len(client.list(limit=0)) > 40
    finally:
        client.close()


def test_unanswerable_query_never_starts_answering(tmp_path):
    client = _client(tmp_path)
    try:
        client.ingest(CONTROL, source="soak:control", evidence_quote=CONTROL)
        for cycle in range(10):
            client.ingest_batch([_filler(cycle, offset) for offset in range(4)])
            negative = client.recall(NO_ANSWER_QUERY, limit=5, strict=True)
            assert negative.status == "abstain", f"cycle {cycle}: no-answer query answered"
            assert negative.memories == []
    finally:
        client.close()


def test_lifecycle_converges_and_does_not_lose_the_control_fact(tmp_path):
    client = _client(tmp_path)
    try:
        client.ingest(CONTROL, tags=["core"], source="soak:control", evidence_quote=CONTROL)
        for cycle in range(8):
            client.ingest_batch([_filler(cycle, offset) for offset in range(3)])

        # Consolidation clusters greedily in one pass, so a row that is similar
        # to several others can be claimed by one cluster and skip comparison
        # with the rest. Convergence — not one-pass idempotence — is the real
        # invariant: repeated passes must reach a fixed point instead of
        # shrinking the store forever.
        totals = [len(client.list(limit=0))]
        for _ in range(4):
            result = client.run_lifecycle()
            assert all(isinstance(value, int) for value in result.values())
            totals.append(len(client.list(limit=0)))

        assert totals[-1] == totals[-2], f"lifecycle never converged: {totals}"
        assert totals[1] < totals[0], f"first pass merged nothing: {totals}"

        result = client.recall(CONTROL_QUERY, limit=5, strict=True)
        assert any(CONTROL in memory.content for memory in result.memories)
    finally:
        client.close()


def test_recall_latency_does_not_explode_with_store_size(tmp_path):
    client = _client(tmp_path)
    try:
        client.ingest(CONTROL, tags=["core"], source="soak:control", evidence_quote=CONTROL)
        for cycle in range(10):
            client.ingest_batch([_filler(cycle, offset) for offset in range(4)])

        # Not a benchmark: this only asserts the path stays linear-ish rather
        # than degrading into something pathological. scripts/soak-test.py owns
        # the real drift measurement.
        import time

        timings = []
        for _ in range(5):
            started = time.perf_counter()
            client.recall(CONTROL_QUERY, limit=5, strict=True)
            timings.append((time.perf_counter() - started) * 1000)
        median = sorted(timings)[len(timings) // 2]
        assert math.isfinite(median)
        assert median < 500, f"recall p50 {median:.1f}ms on a 40-memory store"
    finally:
        client.close()
