#!/usr/bin/env python
"""Release gate: exercise public strict recall with the real default model.

This is not a unit test and not a semantic-ordering smoke. It drives
``MemoryClient.recall`` end to end on a bounded, isolated SQLite store and
asserts *which facts come back*: the current scoped deploy fact must be
retrieved, an off-topic but graph-linked documentation row must not be, expired
and cross-scope rows must stay out, and unanswerable queries must abstain.

It intentionally fails while a known recall defect is open. A release gate that
passes on a confident wrong answer is worse than no gate.

Usage:
    python scripts/smoke-real-model.py [--report PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ANSWER = "Project Luminary deploy target is production."
INDONESIAN = "Target deploy saat ini adalah production untuk project Luminary."
DOCS = "The canonical API reference is https://docs.example.test/luminary/api."
STAGING = "Project Luminary deploy target is staging."
OLD = "Project Luminary deploy target is development."
OTHER_USER = "Project Luminary deploy target is a private cluster for tenant two."
COFFEE = "The office has a coffee machine on the second floor."
DARK_MODE = "User prefers dark mode for the dashboard."


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


MEMORIES = [
    # key, content, scope, valid_from, valid_to, observed_at
    ("answer", ANSWER, {"user_id": "u1", "workspace_id": "luminary"}, None, None, _iso(1)),
    ("indonesian", INDONESIAN, {"user_id": "u1", "workspace_id": "luminary"}, None, None, _iso(0)),
    ("docs", DOCS, {"user_id": "u1", "workspace_id": "luminary"}, None, None, _iso(5)),
    ("staging_expired", STAGING, {"user_id": "u1", "workspace_id": "luminary"}, None, _iso(9), _iso(20)),
    ("dev_expired", OLD, {"user_id": "u1", "workspace_id": "luminary"}, None, _iso(40), _iso(50)),
    ("other_user", OTHER_USER, {"user_id": "u2", "workspace_id": "luminary"}, None, None, _iso(1)),
    ("coffee", COFFEE, {"user_id": "u1", "workspace_id": "luminary"}, None, None, _iso(3)),
    ("dark_mode", DARK_MODE, {"user_id": "u1", "workspace_id": "luminary"}, None, None, _iso(2)),
]

# key, query, scope, must_include, must_exclude, expect_abstain
CASES = [
    (
        "exact",
        "What is the project Luminary deploy target?",
        {"user_id": "u1", "workspace_id": "luminary"},
        {"answer"},
        {"docs"},
        False,
    ),
    (
        "paraphrase",
        "Where will Luminary go live now?",
        {"user_id": "u1", "workspace_id": "luminary"},
        {"answer"},
        {"docs"},
        False,
    ),
    (
        "scope_isolation",
        "What is the deploy target?",
        {"user_id": "u2", "workspace_id": "luminary"},
        {"other_user"},
        {"answer", "indonesian", "docs"},
        False,
    ),
    (
        "no_answer_password",
        "What is the office WiFi password?",
        {"user_id": "u1", "workspace_id": "luminary"},
        set(),
        {"answer", "coffee", "docs"},
        True,
    ),
    (
        "no_answer_token",
        "What is the private cluster access token?",
        {"user_id": "u1", "workspace_id": "luminary"},
        set(),
        {"answer", "other_user", "docs"},
        True,
    ),
]


def _run() -> tuple[bool, list[dict]]:
    from luminary_memory.api import MemoryClient
    from luminary_memory.config import Settings
    from luminary_memory.ingest.llm import NoopEnricher

    settings = Settings(
        strict_recall=True,
        evidence_required=True,
        rule_auto_replace=False,
    )
    if settings.embedding_model != "BAAI/bge-small-en-v1.5":
        raise SystemExit(
            f"unexpected embedding model {settings.embedding_model!r}; "
            "this gate must run the real default model"
        )

    results: list[dict] = []
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="luminary-release-gate-") as root:
        settings.db_path = str(Path(root) / "gate.db")
        client = MemoryClient(settings=settings, enricher=NoopEnricher())
        try:
            ids: dict[str, int] = {}
            for key, content, scope, valid_from, valid_to, observed_at in MEMORIES:
                memory_id = client.ingest(
                    content,
                    source=f"gate:{key}",
                    evidence_quote=content,
                    observed_at=observed_at,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    **{k: v for k, v in scope.items() if v is not None},
                )
                if memory_id is None:
                    raise SystemExit(f"gate fixture was rejected: {key}")
                ids[key] = memory_id
            key_by_id = {value: key for key, value in ids.items()}

            for case_key, query, scope, must_include, must_exclude, expect_abstain in CASES:
                result = client.recall(query, limit=10, scope=scope, strict=True)
                returned = {key_by_id[mid] for mid in (m.id for m in result.memories) if mid in key_by_id}
                entry = {
                    "case": case_key,
                    "query": query,
                    "status": result.status,
                    "confidence": round(float(result.confidence), 4),
                    "returned": sorted(returned),
                    "must_include": sorted(must_include),
                    "must_exclude": sorted(must_exclude),
                    "expect_abstain": expect_abstain,
                }
                if expect_abstain:
                    if result.status != "abstain" or returned:
                        failures.append(
                            f"{case_key}: expected abstention, got status={result.status} "
                            f"returned={sorted(returned)}"
                        )
                else:
                    missing = must_include - returned
                    leaked = must_exclude & returned
                    if missing:
                        failures.append(f"{case_key}: missing required fact(s) {sorted(missing)}")
                    if leaked:
                        failures.append(f"{case_key}: returned excluded fact(s) {sorted(leaked)}")
                results.append(entry)
        finally:
            client.close()
    return not failures, results, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None, help="Write a JSON report here")
    args = parser.parse_args()

    ok, results, failures = _run()

    print(f"{'case':22} {'status':8} {'conf':>6}  returned")
    for entry in results:
        print(
            f"{entry['case']:22} {entry['status']:8} {entry['confidence']:6.4f}  "
            f"{', '.join(entry['returned']) or '-'}"
        )

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps({"passed": ok, "failures": failures, "cases": results}, indent=2) + "\n"
        )

    if failures:
        print("\nRELEASE GATE FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("\nRELEASE GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
