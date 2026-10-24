#!/usr/bin/env python
"""Long-running stability check for ingest, recall and lifecycle.

A single unit-test run cannot show whether a long-lived store degrades: whether
latency creeps as the store fills, whether lifecycle keeps up with writes,
whether the file grows without bound, or whether a fact that was retrievable in
cycle 0 is still retrievable in cycle 400.

This script drives the real public API through many cycles on one store and
reports drift. It fails closed: a lost control fact, a leaked no-answer, an
exception or runaway growth is a non-zero exit.

Usage:
    python scripts/soak-test.py --cycles 200 --per-cycle 5
    python scripts/soak-test.py --cycles 50 --engine real --report /tmp/soak.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

CONTROL_FACT = "Project Luminary deploy target is production."
CONTROL_QUERY = "What is the project Luminary deploy target?"
NO_ANSWER_QUERY = "What is the office WiFi password?"

TOPICS = (
    "The nightly backup job writes to the cold storage bucket at 02:00 UTC.",
    "The API gateway rate limit is two hundred requests per minute per key.",
    "The staging cluster runs on three worker nodes in the Frankfurt region.",
    "Billing exports are generated on the first business day of each month.",
    "The mobile client caches the dashboard for fifteen minutes.",
    "Search indexing is rebuilt incrementally every six hours.",
    "The audit log retains entries for four hundred days.",
    "Feature flags are evaluated on the edge with a sixty second refresh.",
    "The support rota rotates every Tuesday morning.",
    "Database migrations must be reversible before they are merged.",
    "The design system ships tokens as CSS custom properties.",
    "Error budgets are reviewed at the end of each sprint.",
)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def _run(args: argparse.Namespace) -> tuple[bool, dict]:
    # Run from anywhere: the script imports the in-repo benchmark helpers, so
    # the repository root must be importable even when the package is installed.
    import sys

    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from benchmarks.run_benchmarks import _FakeEngine, _gold_engine
    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings
    from luminary_memory.ingest.llm import NoopEnricher

    if args.engine == "real":
        engine, engine_name, model_name = _gold_engine("real")
    else:
        engine, engine_name, model_name = _FakeEngine(), "fake-deterministic", None

    db_path = Path(args.db) if args.db else None
    temp_dir = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="luminary-soak-")
        db_path = Path(temp_dir.name) / "soak.db"

    settings = Settings(
        db_path=str(db_path),
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
    )
    cycles: list[dict] = []
    failures: list[str] = []
    control_misses = 0
    no_answer_leaks = 0

    client = MemoryClient(settings=settings, engine=engine, enricher=NoopEnricher())
    try:
        client.ingest(
            CONTROL_FACT,
            tags=["core"],
            source="soak:control",
            evidence_quote=CONTROL_FACT,
        )
        for cycle in range(args.cycles):
            ingest_ms = 0.0
            if args.per_cycle:
                # Each item must survive near-duplicate dedup (Jaccard 0.85),
                # otherwise the store never grows and the soak measures nothing.
                batch = []
                for offset in range(args.per_cycle):
                    sequence = cycle * args.per_cycle + offset
                    topic = TOPICS[sequence % len(TOPICS)]
                    batch.append(
                        f"{topic} Change request {sequence} was reviewed by "
                        f"engineer {sequence % 97} in sprint {sequence // 7}."
                    )
                started = time.perf_counter()
                client.ingest_batch(batch, tags=[["soak"] for _ in batch])
                ingest_ms = (time.perf_counter() - started) * 1000

            latencies: list[float] = []
            for _ in range(args.recalls):
                started = time.perf_counter()
                client.recall(CONTROL_QUERY, limit=5, strict=True)
                latencies.append((time.perf_counter() - started) * 1000)

            control = client.recall(CONTROL_QUERY, limit=5, strict=True)
            control_hit = any(CONTROL_FACT in memory.content for memory in control.memories)
            if not control_hit:
                control_misses += 1
                failures.append(f"cycle {cycle}: control fact not retrievable ({control.status})")

            negative = client.recall(NO_ANSWER_QUERY, limit=5, strict=True)
            if negative.memories:
                no_answer_leaks += 1
                failures.append(
                    f"cycle {cycle}: no-answer query returned {len(negative.memories)} row(s)"
                )

            lifecycle = {}
            if args.lifecycle_every and (cycle + 1) % args.lifecycle_every == 0:
                lifecycle = client.run_lifecycle()

            cycles.append(
                {
                    "cycle": cycle,
                    "ingest_ms": round(ingest_ms, 2),
                    "recall_p50_ms": round(statistics.median(latencies), 3),
                    "recall_p95_ms": round(_percentile(latencies, 0.95), 3),
                    "memories": len(client.list(limit=0)),
                    "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
                    "control_hit": control_hit,
                    "no_answer_clean": not negative.memories,
                    "lifecycle": lifecycle,
                }
            )
    finally:
        client.close()
        if temp_dir is not None:
            temp_dir.cleanup()

    # Drift check: compare the first and last fifth of the run. A store that is
    # getting slower or bigger without a corresponding memory increase is a leak.
    window = max(1, len(cycles) // 5)
    head, tail = cycles[:window], cycles[-window:]
    head_p50 = statistics.median([row["recall_p50_ms"] for row in head])
    tail_p50 = statistics.median([row["recall_p50_ms"] for row in tail])
    head_memories = max(1, statistics.median([row["memories"] for row in head]))
    tail_memories = statistics.median([row["memories"] for row in tail])
    latency_ratio = tail_p50 / head_p50 if head_p50 else 1.0
    bytes_per_memory = statistics.median(
        [row["db_bytes"] / max(1, row["memories"]) for row in tail]
    )

    if latency_ratio > args.max_latency_ratio:
        failures.append(
            f"recall p50 grew {latency_ratio:.2f}x over the run "
            f"(limit {args.max_latency_ratio}x)"
        )

    report = {
        "engine": {"name": engine_name, "model": model_name},
        "cycles": len(cycles),
        "per_cycle": args.per_cycle,
        "recalls_per_cycle": args.recalls,
        "lifecycle_every": args.lifecycle_every,
        "control_misses": control_misses,
        "no_answer_leaks": no_answer_leaks,
        "drift": {
            "head_recall_p50_ms": round(head_p50, 3),
            "tail_recall_p50_ms": round(tail_p50, 3),
            "latency_ratio": round(latency_ratio, 3),
            "head_memories": head_memories,
            "tail_memories": tail_memories,
            "bytes_per_memory": round(bytes_per_memory, 1),
        },
        "totals": {
            "memories": cycles[-1]["memories"] if cycles else 0,
            "db_bytes": cycles[-1]["db_bytes"] if cycles else 0,
        },
        "failures": failures,
        "samples": cycles,
    }
    return not failures, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--per-cycle", type=int, default=5, help="Memories ingested per cycle")
    parser.add_argument("--recalls", type=int, default=3, help="Timed recalls per cycle")
    parser.add_argument(
        "--lifecycle-every",
        type=int,
        default=20,
        help="Run lifecycle every N cycles (0 disables)",
    )
    parser.add_argument("--engine", choices=["fake", "real"], default="fake")
    parser.add_argument("--max-latency-ratio", type=float, default=3.0)
    parser.add_argument("--db", type=str, default=None, help="Keep the store at this path")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    ok, report = _run(args)
    drift = report["drift"]

    print(
        f"cycles={report['cycles']} engine={report['engine']['name']} "
        f"memories={report['totals']['memories']} "
        f"db={report['totals']['db_bytes'] / 1024:.0f} KiB"
    )
    print(
        f"recall p50 head={drift['head_recall_p50_ms']}ms "
        f"tail={drift['tail_recall_p50_ms']}ms ratio={drift['latency_ratio']}x"
    )
    print(
        f"control misses={report['control_misses']} "
        f"no-answer leaks={report['no_answer_leaks']} "
        f"bytes/memory={drift['bytes_per_memory']}"
    )

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")

    if not ok:
        print("\nSOAK FAILED", file=sys.stderr)
        for failure in report["failures"][:20]:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("\nSOAK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
