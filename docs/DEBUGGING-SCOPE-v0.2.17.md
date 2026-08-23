# Debugging Scope — Historical v0.2.17 Investigation, Current Status

**Project:** Luminary Memory
**Original cycle:** v0.2.17
**Current interpretation:** the gateway/hook findings are shipped; the
accuracy and provider invariants are maintained in `0.2.18`.

This document is a compact investigation log. It is kept separate from the
current implementation audit so historical release notes do not get mistaken
for the current architecture.

## Investigation matrix

| Scope | Area | Invariant | Current result |
|---|---|---|---|
| 01 | LLM gateway | Direct `choices` and wrapped `data.choices` both parse | Shipped; one transient retry |
| 02 | Context assembly | Core, durable recall, and continuity do not become competing authorities | Shipped; importance-only persistent context removed in v0.2.18 |
| 03 | Telegram hook | `agent:end` activity delivery is truthful and retryable | Shipped; active posts require `ok:true`, inactive-only ranges are acked silently |
| 04 | Session end | Queued writes commit before maintenance reads | Shipped; queue join before `auto_maintain` |
| 05 | Embeddings | Degenerate/missing vectors fail closed | Shipped; lexical/Jaccard fallback |
| 06 | Writer queue | SQLite connections stay thread-affine | Shipped; dedicated writer client and sentinel shutdown |
| 07 | Diagnostics | CLI activity, health, graph, backup, and JSON contracts are inspectable | Shipped and regression-tested |
| 08 | Scope and claims | Ownership, evidence, status, and conflicts survive retrieval/update | Shipped in the accuracy foundation |
| 09 | Session continuity | An abstaining durable recall can use only recent episodes from the exact active session | Shipped; bounded untrusted fallback with active-objective guard |
| 10 | Authority repair | Historical imported authority and uncurated auto-retains can be identified without language heuristics | Shipped; dry-run first, backup before apply |

## Current context model

The previously drafted importance-based three-tier model is obsolete. The live
provider model is:

```text
core tag rows (system prompt, every session)
                    +
scoped query recall (turn context, strict/evidence-aware)
                    +
exact-session episode fallback (only when durable recall has no usable block)
                    -> per-turn scope/authority guard
```

Importance remains useful for ranking, pruning, health, and pinning; it no
longer injects arbitrary top-N memories into every system prompt. Episode rows
are continuity evidence, not durable semantic memories and not a cross-session
fallback.

## Gateway compatibility

The enricher accepts these equivalent shapes:

```json
{"choices": [{"message": {"content": "..."}}]}
```

```json
{"data": {"choices": [{"message": {"content": "..."}}]}}
```

Malformed, empty, or transiently unavailable curation is handled
conservatively. The Hermes provider does not save a raw transcript when an
enabled curation pass produced no durable summary.

## Hook contract

`hermes/hooks/luminary-activity/HOOK.yaml` registers `agent:end`. The handler
reads pending IDs from the shared SQLite store, excludes inactive rows from the
notification, escapes Telegram Markdown, supports Forum Topic IDs, posts at
most three details plus an overflow count, and commits an active notification
cursor only after Telegram reports `ok:true`. A range containing only
inactive rows is acknowledged without a post.

```text
agent:end
  -> read rows after cursor
  -> format factual write activity
  -> sendMessage
  -> active rows? sendMessage : acknowledge inactive range
  -> ok=true ? advance cursor : retry later
```

The matching CLI command is:

```bash
luminary-memory activity --limit 5
luminary-memory activity --limit 5 --json
```

## Runtime verification

```bash
pytest -o addopts='' -q
pytest tests/hermes/test_activity_hook.py -q
ruff check .
python3 -m benchmarks.run_benchmarks --n 40 --report /tmp/luminary-gold.json
```

The current workspace record is `505 passed, 3 skipped`, 83% full-source
coverage, and a controlled 12-case gold suite with zero cross-scope leakage;
`ruff check src tests hermes/hooks` is clean. The current implementation audit
also covers atomic cross-process deduplication, replacement lineage, evidence
fail-closed behavior, scoped JSONL transparency, and real pgvector integration.
