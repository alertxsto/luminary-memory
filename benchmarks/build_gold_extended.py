"""Generate the extended controlled-gold fixture.

The 12-case micro fixture cannot calibrate a query-expansion admission rule:
every candidate token appears in exactly one memory, so any "shared vocabulary"
threshold that drops an off-topic token also drops the vocabulary a legitimate
paraphrase needs.

This fixture keeps the micro cases intact and adds enough in-scope background
memories that token document frequency becomes a real signal: shared project
vocabulary appears across many memories, while a single memory's private
wording appears once.

Run:
    python benchmarks/build_gold_extended.py
"""

from __future__ import annotations

import json
from pathlib import Path

MICRO = Path(__file__).with_name("gold_micro.jsonl")
OUTPUT = Path(__file__).with_name("gold_extended.jsonl")

SCOPE = {"user_id": "u1", "workspace_id": "luminary"}

# Background memories. The vocabulary here is deliberate: "deploy", "target",
# "production", "release" and "project" recur, so they are shared topic words;
# "canonical", "adalah" and "fingerprint" appear once and are private wording.
BACKGROUND = [
    ("The release checklist requires two reviewers before a deploy.",
     "release", "gold:bg-release-review"),
    ("A deploy to production is announced in the operations channel.",
     "deploy", "gold:bg-deploy-announce"),
    ("The target environment for load tests is a dedicated staging cluster.",
     "deploy", "gold:bg-loadtest-env"),
    ("Project documentation lives in the shared knowledge base.",
     "docs", "gold:bg-docs-home"),
    ("Every production incident gets a written follow-up within two days.",
     "operations", "gold:bg-incident-followup"),
    ("The release train leaves every second Thursday.",
     "release", "gold:bg-release-train"),
    ("Target response time for the public API is two hundred milliseconds.",
     "operations", "gold:bg-latency-target"),
    ("Feature work is merged into the integration branch, not the release branch.",
     "release", "gold:bg-branch-model"),
    ("The project uses trunk-based development with short-lived branches.",
     "project", "gold:bg-trunk"),
    ("Production access requires hardware-backed second factor authentication.",
     "operations", "gold:bg-prod-access"),
    ("Target coverage for the test suite is set by the coverage gate.",
     "tests", "gold:bg-coverage"),
    ("The release notes are generated from merged pull requests.",
     "release", "gold:bg-release-notes"),
    ("Project onboarding lives in the first-week checklist.",
     "project", "gold:bg-onboarding"),
    ("A failed deploy rolls back automatically to the previous revision.",
     "deploy", "gold:bg-rollback"),
    ("Production logs are retained for thirty days before archival.",
     "operations", "gold:bg-log-retention"),
    ("Target audience for the beta is internal engineering teams.",
     "project", "gold:bg-beta-audience"),
]

# Extra cases that exercise the same behaviours as the micro set but with a
# store where shared vocabulary actually exists.
EXTRA_CASES = [
    {
        "type": "case",
        "key": "rule",
        "query": "What must happen before release?",
        "scope": SCOPE,
        # The micro fixture labels only `shared_rule` because nothing else in
        # that 12-memory store answers this. In this larger store,
        # `bg_release-review` ("The release checklist requires two reviewers
        # before a deploy") is also a correct answer to the same question, so
        # the label must include it. Leaving it out would make a correct
        # retrieval look like a failure and would push future work toward
        # "fixing" behaviour that is right.
        "relevant": ["shared_rule", "bg_release-review"],
        "no_answer": False,
    },
    {
        "type": "case",
        "key": "release_paraphrase",
        "query": "Where does a deploy go after review?",
        "scope": SCOPE,
        "relevant": ["deploy_production_u1", "indonesian_fact"],
        "no_answer": False,
    },
    {
        "type": "case",
        "key": "private_wording",
        "query": "What is the canonical API reference?",
        "scope": SCOPE,
        "relevant": ["docs_url"],
        "no_answer": False,
    },
    {
        "type": "case",
        "key": "no_answer_fingerprint",
        "query": "What is the cluster fingerprint?",
        "scope": SCOPE,
        "relevant": [],
        "no_answer": True,
    },
]

META = {
    "type": "meta",
    "format": "luminary-memory-gold",
    "version": 1,
    "name": "controlled-extended-v1",
    "language": ["en", "id"],
    "derived_from": "controlled-micro-v1",
    "note": (
        "Micro cases are preserved unchanged so results stay comparable. "
        "Background memories exist so expansion-token document frequency is a "
        "real signal instead of always 1."
    ),
}


def main() -> None:
    records = [json.loads(line) for line in MICRO.read_text().splitlines() if line.strip()]
    memories = [record for record in records if record.get("type") == "memory"]
    cases = [record for record in records if record.get("type") == "case"]

    existing = {memory["key"] for memory in memories}
    added = 0
    for content, tag, source in BACKGROUND:
        key = source.replace("gold:bg-", "bg_")
        if key in existing:
            continue
        memories.append(
            {
                "type": "memory",
                "key": key,
                "content": content,
                "scope": dict(SCOPE),
                "tags": [tag],
                "source": source,
                "evidence_quote": content,
                "observed_at": "2026-08-06T10:00:00+00:00",
            }
        )
        added += 1

    # Extra cases replace same-key micro cases (the label is completed here,
    # not duplicated), and add new keys.
    overrides = {case["key"]: case for case in EXTRA_CASES}
    cases = [overrides.pop(case["key"], case) for case in cases]
    cases.extend(overrides.values())

    lines = [json.dumps(META, ensure_ascii=False)]
    lines += [json.dumps(memory, ensure_ascii=False) for memory in memories]
    lines += [json.dumps(case, ensure_ascii=False) for case in cases]
    OUTPUT.write_text("\n".join(lines) + "\n")

    print(
        f"wrote {OUTPUT.name}: {len(memories)} memories ({added} background), "
        f"{len(cases)} cases"
    )


if __name__ == "__main__":
    main()
