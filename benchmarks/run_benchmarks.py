"""Measure labelled retrieval quality and separate fake/real latency arms."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.gold import anchor_time, load_gold, rebase_timestamps
from benchmarks.metrics import cost_per_correct_answer, mrr, percentiles, recall_at_k
from benchmarks.synthetic import generate_memories


class _FakeEngine:
    """Stable bag-of-words vectors for reproducible, dependency-light runs.

    Tokens get their own coordinate instead of being hashed into a fixed table.
    Hashing collides, and a collision between two words of an exact
    query/answer pair drops their cosine to 0.6172 where the true overlap is
    0.7716 — below a support floor calibrated on a real model, which would make
    every caller assert against an artefact of the double rather than against
    recall behaviour.
    """

    _DIM = 512

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._DIM
        for token in re.findall(r"[a-z0-9]+", str(text or "").casefold()):
            index = self._vocab.setdefault(token, len(self._vocab))
            if index < self._DIM:
                vector[index] = 1.0
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


def _module_version(name: str) -> str | None:
    try:
        module = __import__(name)
    except ImportError:
        return None
    return getattr(module, "__version__", None)


def _gold_engine(kind: str) -> tuple[object, str, str | None]:
    """Return the embedding engine for gold evaluation plus its identity."""
    if kind == "fake":
        return _FakeEngine(), "fake-deterministic", None
    from luminary_memory.config import Settings
    from luminary_memory.embeddings.fastembed import FastembedEngine

    model = Settings().embedding_model
    return FastembedEngine(model_name=model), "fastembed", model


def _scope_kwargs(scope: dict) -> dict:
    return {
        key: scope[key]
        for key in ("user_id", "session_id", "workspace_id", "agent_id")
        if scope.get(key) is not None
    }


def _evaluate_gold(client, memories: list[dict], cases: list[dict]) -> dict:
    id_by_key: dict[str, int] = {}
    construction_start = time.perf_counter()
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
    construction_ms = (time.perf_counter() - construction_start) * 1000

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
    grounded_count = 0
    returned_count = 0
    answer_cases_with_wrong_hit = 0
    wrong_hit_rows = 0
    query_ms = 0.0
    correct_answers = 0

    for case in cases:
        scope = dict(case.get("scope") or {})
        expected = {id_by_key[key] for key in case.get("relevant") or []}
        query_start = time.perf_counter()
        result = client.recall(case["query"], limit=10, scope=scope, strict=True)
        query_ms += (time.perf_counter() - query_start) * 1000
        retrieved = [memory.id for memory in result.memories if memory.id is not None]
        hits = set(retrieved) & expected
        # A grounded row that does not answer the question is a quality
        # failure. Evidence grounding alone must not read as relevance.
        wrong_hits = [memory_id for memory_id in retrieved if memory_id not in expected]
        if expected:
            if hits == expected and not wrong_hits and result.status == "ok":
                correct_answers += 1
            retrieved_relevant.append(recall_at_k(retrieved, expected, 10))
            mrr_values.append(mrr(retrieved, expected))
            precision_values.append(len(hits) / max(1, len(retrieved)))
            if wrong_hits:
                answer_cases_with_wrong_hit += 1
                wrong_hit_rows += len(wrong_hits)
        if case.get("no_answer"):
            abstain_attempts += 1
            if not retrieved and result.status == "abstain":
                abstain_correct += 1
            elif retrieved:
                false_positive_no_answer += 1

        for memory in result.memories:
            returned_count += 1
            if memory.evidence_quote or memory.source or memory.source_id:
                grounded_count += 1
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
                "wrong_hit_ids": wrong_hits,
                "status": result.status,
                "abstained": result.status == "abstain",
                "reason": result.reason,
                "confidence": result.confidence,
                "hit_count": len(hits),
            }
        )

    return {
        "protocol": "independent_gold_v2",
        "cost": {
            "correct_answers": correct_answers,
            "correct_answer_definition": "all relevant rows returned, no wrong rows, status ok",
            "construction_ms": construction_ms,
            "query_ms": query_ms,
            "wall_ms_per_correct_answer": cost_per_correct_answer(
                construction_ms, query_ms, correct_answers
            ),
            "provider_usage": None,
            "construction_usd": None,
            "query_usd": None,
            "usd_per_correct_answer": None,
        },
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
        # Answer-bearing cases where at least one returned row is not relevant,
        # regardless of whether that row carries its own evidence quote.
        "wrong_hit_rate": answer_cases_with_wrong_hit / len(answer_cases)
        if answer_cases else 0.0,
        "wrong_hit_rows": wrong_hit_rows,
        # Share of returned rows carrying stored-source grounding. This is not
        # relevance and must never be reported as accuracy.
        "source_grounded_rate": grounded_count / returned_count
        if returned_count else 1.0,
        "cross_scope_leakage": leakage_count,
        "case_results": case_results,
    }


def _latency_arm(kind: str, directory: Path, n: int) -> dict:
    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings
    from luminary_memory.ingest.llm import NoopEnricher
    from luminary_memory.recall.graph import graph_recall
    from luminary_memory.recall.keyword import keyword_recall
    from luminary_memory.recall.semantic import semantic_recall
    from luminary_memory.recall.temporal import temporal_recall

    start = time.perf_counter()
    engine, engine_name, model_name = _gold_engine(kind)
    settings = Settings(backend="sqlite", db_path=str(directory / f"latency-{kind}.db"),
                        strict_recall=True, evidence_required=True, rule_auto_replace=False)
    client = MemoryClient(settings=settings, engine=engine, enricher=NoopEnricher())
    initialization_ms = (time.perf_counter() - start) * 1000
    try:
        synthetic = generate_memories(n=n, seed=42)
        start = time.perf_counter()
        client.ingest_batch([item["content"] for item in synthetic],
                            tags=[item["tags"] for item in synthetic])
        ingest_ms = (time.perf_counter() - start) * 1000
        scenarios = {}
        for query in ("postgres vector search", "deploy target staging", "sanitize FTS"):
            operations = {
                "semantic": lambda: semantic_recall(client.backend, client.engine, query, limit=10),
                "keyword": lambda: keyword_recall(client.backend, query, limit=10),
                "temporal": lambda: temporal_recall(client.backend, limit=10),
                "graph": lambda: graph_recall(client.backend, query, limit=10),
                "e2e": lambda: client.recall(query, limit=10),
            }
            scenarios[query] = {}
            for name, operation in operations.items():
                start = time.perf_counter()
                operation()
                first_ms = (time.perf_counter() - start) * 1000
                for _ in range(10):
                    operation()
                samples = []
                for _ in range(100):
                    start = time.perf_counter()
                    operation()
                    samples.append((time.perf_counter() - start) * 1000)
                scenarios[query][name] = {
                    "first_ms": first_ms, "warmups": 10, "samples": 100,
                    "warm_ms": percentiles(samples),
                }
        return {
            "engine": {"name": engine_name, "model": model_name,
                       "threads": getattr(engine, "threads", None)},
            "dataset": {"name": "synthetic", "seed": 42, "memories": n},
            "initialization_ms": initialization_ms,
            "cold_ingest_ms": ingest_ms,
            "scenarios": scenarios,
        }
    finally:
        client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run luminary-memory accuracy/latency benchmarks")
    ap.add_argument("--n", type=int, default=500, help="Synthetic memories for latency")
    ap.add_argument("--backend", choices=["sqlite"], default="sqlite")
    ap.add_argument("--engine", choices=["fake", "real"], default="fake",
                    help="Embedding engine for gold evaluation")
    ap.add_argument("--latency-engine", choices=["fake", "real", "both"], default="fake",
                    help="Latency arm; real loads the configured FastEmbed model")
    ap.add_argument("--gold-set", type=Path, default=Path(__file__).with_name("gold_holdout.jsonl"))
    ap.add_argument("--report", type=str, default="/tmp/bench.json")
    args = ap.parse_args()
    if args.n < 1:
        ap.error("--n must be positive")

    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings
    from luminary_memory.ingest.llm import NoopEnricher

    meta, gold_memories, gold_cases = load_gold(args.gold_set)
    with tempfile.TemporaryDirectory(prefix="luminary-bench-") as temp_dir:
        directory = Path(temp_dir)
        arms = ("fake", "real") if args.latency_engine == "both" else (args.latency_engine,)
        latency = {kind: _latency_arm(kind, directory, args.n) for kind in arms}
        gold_settings = Settings(backend="sqlite", db_path=str(directory / "gold.db"),
                                 strict_recall=True, evidence_required=True, rule_auto_replace=False)
        anchor = anchor_time(gold_memories)
        if anchor is not None:
            gold_memories = rebase_timestamps(gold_memories, datetime.now(UTC) - anchor)
        start = time.perf_counter()
        gold_engine, engine_name, model_name = _gold_engine(args.engine)
        gold_client = MemoryClient(settings=gold_settings, engine=gold_engine, enricher=NoopEnricher())
        initialization_ms = (time.perf_counter() - start) * 1000
        try:
            gold_quality = _evaluate_gold(gold_client, gold_memories, gold_cases)
        finally:
            gold_client.close()
        cost = gold_quality["cost"]
        cost["construction_ms"] += initialization_ms
        cost["wall_ms_per_correct_answer"] = cost_per_correct_answer(
            cost["construction_ms"], cost["query_ms"], cost["correct_answers"]
        )
        report = {
            "n": args.n,
            "backend": args.backend,
            "latency": latency,
            "quality": gold_quality,
            "evaluation": {
                "dataset": meta,
                "dataset_path": str(args.gold_set),
                "engine": {"name": engine_name, "model": model_name,
                           "threads": getattr(gold_engine, "threads", None)},
                "evaluation_clock": {"anchor": anchor.isoformat() if anchor else None,
                                     "policy": "rebase newest fixture timestamp to run time"},
                "runtime": {"python": platform.python_version(), "numpy": _module_version("numpy"),
                            "fastembed": _module_version("fastembed")},
                "config": {
                    key: getattr(gold_settings, key)
                    for key in (
                        "embedding_model", "embedding_dim", "rrf_k", "strategy_weights",
                        "dedup_jaccard_threshold", "recall_cliff_threshold", "recall_min_score",
                        "importance_recall_boost", "strict_recall", "scope_include_global",
                        "abstention_min_confidence", "abstention_min_margin", "evidence_required",
                        "rule_auto_replace", "query_planner", "query_planner_keyword_threshold",
                        "ingest_whitelist", "importance_auto", "max_memories",
                    )
                },
                "git_revision": _git_revision(),
                "label_provenance": meta.get("label_provenance", "unknown"),
            },
        }
    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
