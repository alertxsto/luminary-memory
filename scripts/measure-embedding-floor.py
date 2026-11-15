#!/usr/bin/env python3
"""Measure the semantic support floor for an embedding model.

``MEASURED_SEMANTIC_SUPPORT_FLOORS`` in ``luminary_memory/config.py`` is a
table of cosine scores that separate "this memory answers the question" from
"this memory is merely topically adjacent".  Those numbers are a property of
the embedding model, so shipping a different model without re-measuring its
floor silently drops every query: an unmeasured model falls back to the
conservative 0.78 and lpmost correct answers land below it.

This script reproduces the measurement from the versioned gold fixtures.

    python scripts/measure-embedding-floor.py --model BAAI/bge-small-en-v1.5
    python scripts/measure-embedding-floor.py \\
        --model sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \\
        --fixture benchmarks/gold_micro.jsonl benchmarks/gold_extended.jsonl

It reports three things per model:

* the score band of memories that a case actually needs (answer-bearing),
* the score band of the best in-scope memory for cases with no answer,
* the floor that keeps the highest confident wrong answer out while keeping
  the lowest correct answer in, with the margin on each side.

Nothing is written; the numbers printed are what belongs in the config table.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT / "benchmarks"))

from gold import load_gold  # noqa: E402
from luminary_memory.config import semantic_support_floor  # noqa: E402
from luminary_memory.embeddings.fastembed import FastembedEngine  # noqa: E402
from luminary_memory.scope import memory_matches_scope, normalize_scope  # noqa: E402


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def measure(model: str, fixtures: list[Path]) -> int:
    engine = FastembedEngine(model)
    answer_scores: list[float] = []
    no_answer_scores: list[float] = []
    misses: list[str] = []

    for fixture in fixtures:
        meta, memories, cases = load_gold(fixture)
        vectors = {
            item["key"]: engine.embed(str(item["content"]))
            for item in memories
        }
        content = {item["key"]: str(item["content"]) for item in memories}
        tag_map = {item["key"]: set(item.get("tags") or []) for item in memories}
        scope_map = {item["key"]: item.get("scope") or {} for item in memories}
        for case in cases:
            case_scope = normalize_scope(case.get("scope") or {})
            in_scope = [
                key
                for key in vectors
                if memory_matches_scope(
                    _Probe(scope_map[key], tag_map[key]),
                    case_scope,
                    include_global=False,
                )
            ]
            if not in_scope:
                continue
            query_vector = engine.embed(str(case["query"]))
            scores = {key: _cosine(query_vector, vectors[key]) for key in in_scope}
            relevant = [key for key in case.get("relevant") or [] if key in scores]
            label = f"{fixture.name}:{case['key']}"
            if relevant:
                best = max(scores[key] for key in relevant)
                answer_scores.append(best)
                if max(scores, key=scores.get) not in relevant:
                    misses.append(label)
            else:
                no_answer_scores.append(max(scores.values()))
        print(
            f"  {fixture.name}: {len(cases)} cases, {len(memories)} memories "
            f"({meta.get('name')})",
            file=sys.stderr,
        )

    highest_wrong = max(no_answer_scores, default=0.0)
    lowest_right = min(answer_scores, default=0.0)
    feasible = lowest_right > highest_wrong
    floor = (lowest_right + highest_wrong) / 2 if feasible else lowest_right

    print(f"model            {model}")
    print(f"cases            {len(answer_scores)} answer-bearing, {len(no_answer_scores)} no-answer")
    if answer_scores:
        print(
            f"answer-bearing   min {min(answer_scores):.4f}  "
            f"p10 {_percentile(answer_scores, 0.10):.4f}  "
            f"median {_percentile(answer_scores, 0.50):.4f}  "
            f"max {max(answer_scores):.4f}"
        )
    if no_answer_scores:
        print(
            f"no-answer best   min {min(no_answer_scores):.4f}  "
            f"p90 {_percentile(no_answer_scores, 0.90):.4f}  "
            f"median {_percentile(no_answer_scores, 0.50):.4f}  "
            f"max {max(no_answer_scores):.4f}"
        )
    if not feasible:
        print("bands overlap: no single floor separates them for this fixture set")
    print(f"suggested floor  {floor:.4f}")
    if answer_scores and no_answer_scores:
        print(
            f"margins          {lowest_right - floor:+.4f} above highest wrong, "
            f"{floor - highest_wrong:+.4f} below lowest right"
        )
    print(f"configured now   {semantic_support_floor(model):.4f}")
    if misses:
        print(f"top-1 misses     {len(misses)}: {', '.join(misses[:8])}")
    return 0


class _Probe:
    """Minimal row shape for :func:`memory_matches_scope`."""

    status = "active"

    def __init__(self, scope: dict, tags: set[str]):
        self.user_id = scope.get("user_id")
        self.workspace_id = scope.get("workspace_id")
        self.agent_id = scope.get("agent_id")
        self.session_id = scope.get("session_id")
        self.tags = tags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="fastembed model name")
    parser.add_argument(
        "--fixture",
        nargs="+",
        default=None,
        help="gold fixture paths (default: micro + extended + holdout)",
    )
    args = parser.parse_args(argv)
    fixtures = (
        [Path(item) for item in args.fixture]
        if args.fixture
        else [
            ROOT / "benchmarks" / "gold_micro.jsonl",
            ROOT / "benchmarks" / "gold_extended.jsonl",
            ROOT / "benchmarks" / "gold_holdout.jsonl",
        ]
    )
    missing = [str(path) for path in fixtures if not path.exists()]
    if missing:
        print(f"missing fixture: {', '.join(missing)}", file=sys.stderr)
        return 2
    return measure(args.model, fixtures)


if __name__ == "__main__":
    raise SystemExit(main())
