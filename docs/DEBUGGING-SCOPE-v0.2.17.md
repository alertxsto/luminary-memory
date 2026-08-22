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
| 02 | Context assembly | Core and recall do not duplicate IDs/content | Shipped; importance-only persistent context removed in v0.2.18 |
| 03 | Telegram hook | `agent:end` activity delivery is truthful and retryable | Shipped; cursor advances only after `ok:true` |
| 04 | Session end | Queued writes commit before maintenance reads | Shipped; queue join before `auto_maintain` |
| 05 | Embeddings | Degenerate/missing vectors fail closed | Shipped; lexical/Jaccard fallback |
| 06 | Writer queue | SQLite connections stay thread-affine | Shipped; dedicated writer client and sentinel shutdown |
| 07 | Diagnostics | CLI activity, health, graph, backup, and JSON contracts are inspectable | Shipped and regression-tested |
| 08 | Scope and claims | Ownership, evidence, status, and conflicts survive retrieval/update | Shipped in the accuracy foundation |

## Current context model

The previously drafted three-tier model is obsolete. The live provider model
is:

```text
core tag rows (system prompt, every session)
                    +
scoped query recall (turn context, strict/evidence-aware)
                    -> per-turn ID/content dedup
```

Importance remains useful for ranking, pruning, health, and pinned/core rules;
it no longer injects arbitrary top-N memories into every system prompt.

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
reads pending IDs from the shared SQLite store, escapes Telegram Markdown,
supports Forum Topic IDs, posts at most three details plus an overflow count,
and commits its delivery cursor only after Telegram reports success.

```text
agent:end
  -> read rows after cursor
  -> format factual write activity
  -> sendMessage
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

The current workspace record is `406 passed, 3 skipped`, clean Ruff, and a
controlled 12-case gold suite with zero cross-scope leakage. See
[`IMPLEMENTATION-AUDIT.md`](IMPLEMENTATION-AUDIT.md) for the full evidence,
output examples, and open validation work.
