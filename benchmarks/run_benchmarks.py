"""Run pipeline latency plus an independently labelled accuracy suite.

The old harness used ``client.search(query)`` as its own relevance label. That
can only measure agreement with the implementation under test. This runner
keeps synthetic latency measurements separate and evaluates retrieval against
``gold_micro.jsonl`` labels authored outside the retriever.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from benchmarks.gold import load_gold
from benchmarks.metrics import mrr, percentiles, recall_at_k
from benchmarks.synthetic import generate_memories


class _FakeEngine:
    """Stable bag-of-words vectors for reproducible, dependency-light runs."""

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * 384
        for token in str(text or "").casefold().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % len(vector)
            vector[index] += 1.0
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _scope_kwargs(scope: dict) -> dict:
    return {
        key: scope[key]
        for key in ("user_id", "session_id", "workspace_id", "agent_id")
        if scope.get(key) is not None
    }


def _evaluate_gold(client, memories: list[dict], cases: list[dict]) -> dict:
    id_by_key: dict[str, int] = {}
    for item in memories:
        scope = dict(item.get("scope") or {})
        memory_id = client.ingest(
            item["content"],
            tags=list(item.get("tags") or []),
            source=item.get("source"),
            enrich=False,
            observed_at=item.get("observed_at"),
            valid_from=item.get("valid_from"),
            valid_to=item.get("valid_to"),
            evidence_quote=item.get("evidence_quote"),
            **_scope_kwargs(scope),
        )
        if memory_id is None:
            raise RuntimeError(f"gold fixture was rejected: {item['key']}")
        id_by_key[item["key"]] = memory_id

    case_results: list[dict] = []
    answer_cases = [case for case in cases if case.get("relevant")]
    no_answer_cases = [case for case in cases if case.get("no_answer")]
    retrieved_relevant: list[float] = []
    mrr_values: list[float] = []
    precision_values: list[float] = []
    abstain_correct = 0
    abstain_attempts = 0
    false_positive_no_answer = 0
    leakage_count = 0
    evidence_supported = 0
    returned_count = 0

    for case in cases:
        scope = dict(case.get("scope") or {})
        expected = {id_by_key[key] for key in case.get("relevant") or []}
        result = client.recall(case["query"], limit=10, scope=scope, strict=True)
        retrieved = [memory.id for memory in result.memories if memory.id is not None]
        hits = set(retrieved) & expected
        if expected:
            retrieved_relevant.append(recall_at_k(retrieved, expected, 10))
            mrr_values.append(mrr(retrieved, expected))
            precision_values.append(len(hits) / max(1, len(retrieved)))
        if case.get("no_answer"):
            abstain_attempts += 1
            if not retrieved and result.status == "abstain":
                abstain_correct += 1
            elif retrieved:
                false_positive_no_answer += 1

        for memory in result.memories:
            returned_count += 1
            if memory.evidence_quote or memory.source or memory.source_id:
                evidence_supported += 1
            memory_scope = {
                key: getattr(memory, key, None)
                for key in ("user_id", "session_id", "workspace_id", "agent_id")
            }
            if scope and any(
                memory_scope.get(key) not in (None, value)
                for key, value in scope.items()
            ):
                leakage_count += 1
        case_results.append(
            {
                "key": case["key"],
                "query": case["query"],
                "expected_ids": sorted(expected),
                "retrieved_ids": retrieved,
                "status": result.status,
                "reason": result.reason,
                "confidence": result.confidence,
                "hit_count": len(hits),
            }
        )

    return {
        "protocol": "independent_gold_v1",
        "cases": len(cases),
        "answer_cases": len(answer_cases),
        "no_answer_cases": len(no_answer_cases),
        "recall@10": sum(retrieved_relevant) / len(retrieved_relevant)
        if retrieved_relevant else 0.0,
        "mrr": sum(mrr_values) / len(mrr_values) if mrr_values else 0.0,
        "precision@10": sum(precision_values) / len(precision_values)
        if precision_values else 0.0,
        "abstention_accuracy": abstain_correct / abstain_attempts if abstain_attempts else 0.0,
        "unsupported_answer_rate": false_positive_no_answer / abstain_attempts
        if abstain_attempts else 0.0,
        "evidence_support_precision": evidence_supported / returned_count
        if returned_count else 1.0,
        "cross_scope_leakage": leakage_count,
        "case_results": case_results,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run luminary-memory accuracy/latency benchmarks")
    ap.add_argument("--n", type=int, default=500, help="Synthetic memories for latency smoke")
    ap.add_argument("--backend", choices=["sqlite"], default="sqlite")
    ap.add_argument(
        "--gold-set",
        type=Path,
        default=Path(__file__).with_name("gold_micro.jsonl"),
        help="Versioned JSONL fixture with independent relevance labels",
    )
    ap.add_argument("--report", type=str, default="/tmp/bench.json", help="Output JSON report path")
    args = ap.parse_args()

    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings
    from luminary_memory.ingest.llm import NoopEnricher

    meta, gold_memories, gold_cases = load_gold(args.gold_set)
    with tempfile.TemporaryDirectory(prefix="luminary-bench-") as temp_dir:
        db_path = Path(temp_dir) / "bench.db"
        settings = Settings(
            db_path=str(db_path),
            strict_recall=True,
            evidence_required=True,
            rule_auto_replace=False,
        )
        client = MemoryClient(settings=settings, engine=_FakeEngine(), enricher=NoopEnricher())
        try:
            synthetic = generate_memories(n=args.n, seed=42)
            start = time.perf_counter()
            client.ingest_batch(
                [item["content"] for item in synthetic],
                tags=[item["tags"] for item in synthetic],
            )
            ingest_ms = (time.perf_counter() - start) * 1000

            queries = ["postgres vector search", "deploy target staging", "sanitize FTS"]
            latencies: dict[str, list[float]] = {
                "semantic": [], "keyword": [], "temporal": [], "graph": [], "e2e": []
            }
            from luminary_memory.recall.graph import graph_recall
            from luminary_memory.recall.keyword import keyword_recall
            from luminary_memory.recall.semantic import semantic_recall
            from luminary_memory.recall.temporal import temporal_recall

            for query in queries:
                for name, fn in [
                    ("semantic", lambda q=query: semantic_recall(client.backend, client.engine, q, limit=10)),
                    ("keyword", lambda q=query: keyword_recall(client.backend, q, limit=10)),
                    ("temporal", lambda q=query: temporal_recall(client.backend, limit=10)),
                    ("graph", lambda q=query: graph_recall(client.backend, q, limit=10)),
                ]:
                    start = time.perf_counter()
                    fn()
                    latencies[name].append((time.perf_counter() - start) * 1000)
                start = time.perf_counter()
                client.recall(query, limit=10)
                latencies["e2e"].append((time.perf_counter() - start) * 1000)

            # Evaluate on a clean store. Mixing the latency corpus into the
            # gold corpus would make precision depend on synthetic distractor
            # rows and would obscure the independent labels.
            gold_settings = Settings(
                db_path=str(Path(temp_dir) / "gold.db"),
                strict_recall=True,
                evidence_required=True,
                rule_auto_replace=False,
            )
            gold_client = MemoryClient(
                settings=gold_settings,
                engine=_FakeEngine(),
                enricher=NoopEnricher(),
            )
            try:
                gold_quality = _evaluate_gold(gold_client, gold_memories, gold_cases)
            finally:
                gold_client.close()
            report = {
                "n": args.n,
                "backend": args.backend,
                "ingest_ms": ingest_ms,
                "latency_ms": {key: percentiles(values) for key, values in latencies.items()},
                "quality": gold_quality,
                "evaluation": {
                    "dataset": meta,
                    "config": {
                        "strict_recall": True,
                        "evidence_required": True,
                        "rule_auto_replace": False,
                    },
                    "git_revision": _git_revision(),
                    "labels_are_system_generated": False,
                },
            }
        finally:
            client.close()

    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(f"Benchmark n={args.n} backend={args.backend}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
