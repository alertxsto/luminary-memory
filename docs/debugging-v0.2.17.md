# Gateway, Hermes, and Telegram Debugging Guide

This guide preserves the v0.2.17 gateway investigation and records the
post-v0.2.18 runtime behavior. The regression suite and CI workflow are the
verification source for the current implementation; the provider log is the
runtime source for a deployed Hermes installation.

## 1. Gateway envelope failure and fix

With `ingest_llm=true`, `OpenAICompatibleEnricher` accepts standard
OpenAI-compatible responses and gateways that wrap them in `data`:

```json
{
  "data": {
    "choices": [
      {"message": {"content": "{\"worth_saving\": true, \"summary\": \"Deploy target is staging.\"}"}}
    ]
  }
}
```

Before v0.2.17 the enricher looked only at the root `choices` field. A wrapped
response therefore became an empty string, which looked like a valid request
but caused curation to produce no summary. The v0.2.17 fix unwraps a
dictionary-valued `data` field before reading `choices`, while preserving the
direct response path. The request has one defensive retry for transient
failures.

When Hermes curation is enabled, an empty/failed curation is intentionally
dropped rather than stored as a raw transcript. This is conservative write
behavior; it prevents gateway failure from polluting recall.

## 2. Current Hermes context flow

The old “core + persistent importance context + recall” description is no
longer current. Since v0.2.18, the provider has three separate context
surfaces:

| Source | Selection | Destination |
|---|---|---|
| Core memory | Active DB rows tagged `core`, selected in stable insertion/id order and bounded by `core_top_n`/`core_budget` | System prompt every session |
| Query recall | Scope/status/validity/evidence-aware fused candidates, bounded by `recall_limit`/`token_budget` | Turn context or explicit tool result |
| Session continuity | Recent immutable episodes from the exact current `session_id`, only when durable recall has no usable block | Bounded untrusted reference block |

Importance boosts query ranking and lifecycle decisions; it does not silently
pin arbitrary rows into the prompt. Core is curated default context; query
recall and session continuity are reference data. The current user request
always wins. Durable recall and core are deduped by ID plus content hash, while
session continuity is a separate episode surface and is never promoted merely
because it was injected.

### Context-loss checks

When Hermes appears to “forget” the active task, inspect the boundaries in this
order:

1. Confirm the provider received the same `session_id`, user, workspace, and
   agent identity on the current turn and on the prefetch operation.
2. Check for `session_episode.recorded` and `session_context.completed` in the
   per-home JSONL log. Missing episode events mean the issue is admission or
   backend support, not ranking.
3. Check `recall.completed` for `status`, `reason`, `confidence`, and scope. An
   intentional abstention should fall through to the exact-session block;
   unrelated historical rows must not be used as a substitute.
4. Confirm the system block's active-objective instruction is present and that
   the current request was not explicitly history-wide.

## 3. Telegram activity hook flow

```mermaid
sequenceDiagram
    participant Hermes as Hermes agent
    participant Provider as Luminary provider
    participant Writer as Writer queue
    participant DB as memory.db
    participant Hook as agent:end hook
    participant Telegram as Telegram Bot API

    Hermes->>Provider: completed turn
    Provider->>Writer: enqueue scoped retain
    Writer->>DB: commit accepted memory
    Hermes->>Hook: agent:end
    Hook->>DB: read IDs greater than state.json cursor
    Hook->>Telegram: sendMessage (escaped Markdown + optional topic)
    Telegram-->>Hook: {"ok": true} or failure
    Hook->>Hook: active post? advance only on ok=true; inactive-only range acked
```

The hook reports persisted writes only. It does not claim that a memory was
recalled or used by the model. It shows a maximum of three detailed rows and a
`... (+N more)` overflow line. Rules/core rows are marked with `📌`; ordinary
facts use `•`.

### Required runtime checks

1. `hermes/hooks/luminary-activity/HOOK.yaml` contains `agent:end`.
2. `TELEGRAM_BOT_TOKEN` and either `LUMINARY_HOOK_CHAT_ID` or
   `TELEGRAM_HOME_CHANNEL` resolve from the environment or `~/.hermes/.env`.
3. `LUMINARY_DB_PATH` points to the same store used by the provider.
4. Forum topics use `LUMINARY_HOOK_THREAD_ID` or
   `TELEGRAM_HOME_CHANNEL_THREAD_ID`.
5. `state.json` is writable.
6. Telegram returns `{"ok": true}`; `ok:false`, malformed bodies, HTTP
   errors, and network errors leave active rows pending for retry. Inactive-only
   ranges are acknowledged without a message.

### Expected output

```text
🌙 Luminary — 2 recent memories stored
  📌 #12 ALWAYS verify tests before release
    tags: core, rule · source: hermes
  • #11 Deploy target is staging
    tags: deploy · source: cli
```

Equivalent local verification:

```bash
luminary-memory activity --db-path ~/.hermes/luminary/memory.db --limit 5
luminary-memory activity --db-path ~/.hermes/luminary/memory.db --json
```

## 4. Provider concurrency checks

- Retains execute on a dedicated writer thread with a thread-owned SQLite
  client.
- `on_session_end()` joins queued writes before running `auto_maintain`.
- `on_session_switch()` flushes the old session and increments the prefetch
  generation.
- Prefetch cache entries are accepted only when session ID, query, generation,
  and scope still match.
- `shutdown()` sends a sentinel, joins the writer, then closes the caller's
  client.

If a memory appears from an earlier session, inspect the `trace_id`, scope, and
status/reason fields in the provider log before changing ranking weights.

### Provider transparency events

`$HERMES_HOME/luminary/luminary.log` is JSONL. A normal operation has a
`*.started` event followed by `*.completed`, `*.discarded`, or `*.failed` with
the same `trace_id`. Every event includes `scope.user_id`,
`scope.workspace_id`, `scope.agent_id`, and `scope.session_id` (null when the
runtime did not provide one), plus backend/mode/platform context.

```bash
tail -f ~/.hermes/luminary/luminary.log | jq
rg '"trace_id": "<trace-id>"' ~/.hermes/luminary/luminary.log
```

Recall events expose `query_hash`, not the query. Retain events expose content
length and memory ID, not content. The provider deliberately omits memory
text, prompts, Telegram credentials, and LLM API keys. Scope IDs are still
present, so use normal local file permissions and retention.

Pre-compress and core-tool events use the same scope/trace contract. A
`provider.shutdown.completed` event with `status: "partial"` means a writer or
prefetch worker remained alive after the bounded join and needs investigation;
it is not a clean shutdown. Accepted retain work is drained before a clean
close. If the writer remains alive, Luminary keeps the lifecycle fenced and
will not initialize a new session on that provider instance until the worker
has stopped.

## 5. Accuracy/debugging checklist

```bash
# Provider and CLI use strict behavior; scope is explicit and reproducible.
export LUMINARY_USER_ID=u1
export LUMINARY_WORKSPACE_ID=luminary
export LUMINARY_AGENT_ID=coding-agent
export LUMINARY_SESSION_ID=session-42

luminary-memory recall "where do we deploy?" --json
luminary-memory activity --json
```

For a weak/unrelated query, verify:

```json
{"status": "abstain", "reason": "no_supported_candidate", "memories": []}
```

For a supported result, verify `evidence_quote`, `source_id`, validity fields,
scope fields, and `provenance` are present. For conflicting claims, use the
diagnostic `include_conflicted` path and resolve through explicit
supersession—do not solve a provenance problem by raising semantic
auto-replacement.

For a store that predates the single-authority provider path, first run the
read-only authority audit and inspect its JSON before applying anything:

```bash
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db
```

Applying the plan requires an explicit `--apply`; it creates a consistent
SQLite backup and archives identified rows with audit events rather than
deleting them.

## 6. Verification commands

```bash
pytest -o addopts='' -q
pytest tests/hermes/test_activity_hook.py -q
ruff check .
python3 -m benchmarks.run_benchmarks --n 40 --report /tmp/luminary-gold.json
```

The current repository verification record is `505 passed, 3 skipped`, 83%
full-source coverage, and clean Ruff. The controlled gold run reports
recall@10 `0.95`, MRR `1.00`, abstention accuracy `1.00`, evidence support
precision `1.00`, and zero cross-scope leakage. These are regression numbers,
not a matched Mem0/Hindsight claim.
