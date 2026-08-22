---
name: luminary-memory
description: "Use luminary-memory for agent memory: auto-recall context, auto-save turns, explicit recall/ingest/list tools, config tweaks."
version: 2.1.0
author: Dwiky Candra
license: Apache-2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, recall, self-hosted, sqlite, pgvector, provider]
---

# luminary-memory (Hermes integration)

**luminary-memory** is a self-hosted memory layer that plugs into Hermes as a
first-class memory provider. It gives agents durable cross-session memory:
auto-recall relevant context every turn, auto-save completed turns, and
explicit tools for on-demand memory access. Retrieval is local and uses zero
LLM tokens; optional write-time curation/maintenance can use an LLM.

**What your agent remembers is what it becomes.**

## When to Use

- **Recall context**, when the current task depends on things said or done in
  earlier sessions (preferences, decisions, environment details, past fixes).
- **Store durable facts**, after learning something that will matter later
  (a user preference, a project convention, a config decision).
- **Inspect the store**, list what luminary currently remembers, or check
  whether a fact is already known before storing it again.
- **Troubleshoot**, when memory seems stale or missing, check the store and
  the transparency log.

## How It Works (3 ways to interact)

| Path | When | Trigger |
|------|------|---------|
| **Auto-recall** | Every turn | `memory.provider: luminary`, background recall injected into context (🌙 indicator) |
| **Auto-retain** | After each turn | provider queues a scoped write; optional curation stores a concise summary |
| **Explicit tools** | On demand | `luminary_recall` / `luminary_ingest` / `luminary_list` |

## Agent Usage, Explicit Tools

### Recall relevant memories

```python
# when the task needs earlier context
result = client.recall("what deploy target do we use?", limit=5)
for memory, score in zip(result.memories, result.scores):
    print(f"[{score:.2f}] {memory.content}")
```

Prefer the injected auto-recall context when present; use the tool when you
need a targeted query the auto-recall didn't cover.

### Store a durable fact

```python
# after learning something that will matter across sessions
client.ingest(
    "The deploy target is the staging cluster",
    tags=["deploy", "infra"],
    source="hermes",
)
```

Good candidates: user preferences, project conventions, environment details,
decisions with reasons. Skip: one-off trivia, content already in context that
will not matter later.

### List what's stored

```python
client.list(limit=20)   # most recent first
```

Use this before re-ingesting, if a fact is already stored, update instead of
duplicating.

### Store maintenance

The store keeps itself clean two ways:

```python
# deterministic passes (TTL, consolidate, prune)
client.run_lifecycle()

# LLM review: keep current facts, update changed ones, delete stale/duplicates
client.run_maintenance()   # requires an LLM enricher (ingest_llm)

# health check: 0-100 score with per-dimension breakdown + recommendations
report = client.health_score()
```

In the Hermes provider, `auto_maintain: true` (plus `ingest_llm: true`) runs
`run_maintenance()` automatically at every session end, no manual trigger
needed. Results are logged to `~/.hermes/luminary/luminary.log`. CLI:
`luminary-memory health` (human bar) or `--json`.

## Configuration, Tweaks

Provider config lives in `~/.hermes/luminary/config.json` (auto-created,
0600 perms). Defaults work out of the box; tweak only what you need.

| Key | Default | What it does |
|-----|---------|--------------|
| `mode` | `hybrid` | `context` (auto-inject only) · `tools` (tools only) · `hybrid` (both) |
| `auto_recall` | `true` | Auto-recall every turn (background) |
| `recall_sync` | `false` | `true` = recall synchronously against the current message (higher relevance, adds latency) |
| `recall_limit` | `10` | Max memories injected per recall |
| `token_budget` | `2048` | Max tokens of injected memory |
| `auto_retain` | `true` | Auto-save turns to the store |
| `retain_every_n_turns` | `1` | Save every N turns (higher = fewer, batched saves) |
| `ingest_llm` | `false` | **LLM memory curation**, drops chit-chat, stores factual summary instead of raw transcript |
| `llm_base_url` / `llm_model` / `llm_api_key` | `""` | OpenAI-compatible enricher endpoint/model/key |
| `auto_maintain` | `false` | **LLM store review at session end**, keeps/updates/deletes stale or duplicate facts (needs `ingest_llm`) |
| `consolidate_semantic` | `true` | **Semantic consolidation**, merge near-duplicates via embedding cosine (fallback Jaccard) during lifecycle |
| `importance_auto` | `true` | **Auto importance estimation**, score memories by recency + access + graph centrality; drives prune & health score |
| `max_memories` | `1000` | **Hard store cap**, oldest/lowest-importance memories pruned when the store exceeds this |
| `recall_indicator` | `true` | Show `🌙 Luminary, recalled N memories` |
| `retain_indicator` | `true` | Show `🌙 Luminary, memory saved` |
| `backend` | `sqlite` | `sqlite` (zero config) or `pgvector` (scale) |
| `core_tag` | `core` | **Core memory**, tag marking rules auto-loaded into the system prompt every session (DB-backed MEMORY.md) |
| `core_top_n` | `12` | Max core memories in the system prompt |
| `core_budget` | `8000` | Max chars of core memory in the system prompt |

**Persistent context (removed in v0.2.18):** the importance-based
persistent-context family (`context_top_n`, `context_budget`,
`context_min_importance`) was removed. Importance now drives query
retrieval/recall and pruning only; it no longer pins memory into the prompt as
rules that could override a live user instruction. Durable rules that must
always be present belong in **core memory** (below).

**Core memory (v0.2.13+):** memories tagged `core` are auto-loaded into the
system prompt every session (the DB-backed equivalent of Hermes' native
`MEMORY.md`). Rules the user wants always present (e.g. "always use markdown tables")
should be stored with the `core` tag (or via `luminary_core_add`). Capped by
`core_top_n` / `core_budget` (characters). Use `luminary_core_remove` to unpin.
Core content comes **only** from the DB (`by_tag_top`), never from recall. Core
is injected as a reference that is subordinate to the user's current explicit
instruction.

**Adaptive memory (v0.2.15+):** three behaviors keep the store "smart":
- **Importance on recall** — a memory that keeps getting recalled is
  re-estimated immediately, so it ranks higher in the next turn's query recall;
  pinned rules (≥ 0.9) never downgrade.
- **Content-level anti-duplication** — core and recall share one
  dedup set (ids + content hashes), so a rule stored both as `core` and as a
  plain memory appears exactly once per turn.
- **Rule-aware query expansion** — when the graph has no entity to expand a
  short query, keywords from a durable rule on the same topic are appended.

**LLM memory curation:** with `ingest_llm: true`, the enricher evaluates each
turn and keeps only durable facts, greetings, chit-chat, and trivial
acknowledgements are dropped, and kept turns are stored as concise factual
summaries (e.g. `"Deploy target is the staging cluster."`) instead of raw
`User: ... / Assistant: ...` transcripts. Without it (default), turns are
stored verbatim with zero LLM cost.

If curation is enabled in the Hermes provider but the enricher fails or returns
no durable summary, that turn is dropped rather than stored as a raw transcript.
This keeps the provider's write path conservative.

Example, save less often, no indicators:

```json
{
  "retain_every_n_turns": 5,
  "recall_indicator": false,
  "retain_indicator": false
}
```

### Env vars

| Var | Purpose |
|-----|---------|
| `LUMINARY_BACKEND` | `sqlite` / `pgvector` |
| `LUMINARY_EMBEDDING_MODEL` | ONNX model (default `BAAI/bge-small-en-v1.5`) |
| `LUMINARY_HOOK_CHAT_ID` | Chat for the activity hook (defaults to home channel) |
| `LUMINARY_DB_PATH` | Override store location (hook) |

## Scope and accuracy behavior

Hermes binds provider writes/reads to the available user, workspace, agent, and
session identity. Scope is applied before candidate generation and fallback.
Provider recall is strict and evidence-required: weak or ambiguous queries may
return an abstention instead of an unrelated memory. Results expose status,
confidence, evidence quote, source, and provenance.

The `luminary-activity` Telegram hook is write-only activity telemetry: it
reports committed rows after `agent:end`, escapes Markdown, supports topic
threads, and retries pending IDs when Telegram delivery fails.

## Transparency Log

`~/.hermes/luminary/luminary.log` is JSONL and records initialization, recall,
retain, pre-compress, core, maintenance, discard, shutdown, and error events
with a correlated `trace_id`:

```
{"event":"recall.completed","trace_id":"8f2c1e0a7b91d4c2","scope":{"user_id":"u_42","workspace_id":"main","agent_id":"luminary","session_id":"s_17"},"status":"abstain","reason":"low_confidence_or_ambiguous","memory_count":0,"confidence":0.22,"latency_ms":3.4}
```

Scope, backend, mode, status/reason, counts, confidence, and latency are
included for troubleshooting. Query text, memory content, Telegram tokens, and
LLM API keys are intentionally omitted; recall uses a short `query_hash`.
Correlate a `*.started` line with its `*.completed`, `*.discarded`, or
`*.failed` event:

```bash
tail -f ~/.hermes/luminary/luminary.log | jq
rg '"trace_id": "8f2c1e0a7b91d4c2"' ~/.hermes/luminary/luminary.log
```

Check this first when memory seems wrong or missing. Keep the file under
normal local permission and retention controls because scope identifiers are
present.

## Verification

Run the full suite plus a live Hermes runtime smoke test in one command:

```bash
bash hermes/test.sh            # pytest + ruff + hermes runtime smoke
bash hermes/test.sh --quick    # pytest + ruff only
bash hermes/test.sh --hermes   # hermes runtime smoke only
```

Run this before every push (see AGENTS-workflow: laporan + tes + verifikasi
hermes wajib sebelum push).

Latest repository verification is recorded in `docs/IMPLEMENTATION-AUDIT.md`.
The long-term suite includes cross-process SQLite deduplication, replacement
lineage, evidence fail-closed behavior, scoped JSONL telemetry, and real
pgvector integration when `LUMINARY_PG_DSN` is supplied. A live Telegram
delivery still requires a real bot/channel and is covered locally by mocked
contract tests.

## Dashboard settings

All provider settings (including `max_memories`, `consolidate_semantic`,
`importance_auto`) are editable from the **Hermes dashboard**: open
**Config → Memory → Luminary** (or `/api/memory/providers/luminary/config`).
The dashboard renders the provider's `get_config_schema()`, if a new setting
is missing there, the installed package is stale: reinstall
(`pip install -e ".[hermes]"`) and restart the dashboard service.

Saving writes to `~/.hermes/luminary/config.json` via `save_config()`.
Unknown keys are dropped with a warning (never silently), check the dashboard
or gateway logs if a value does not persist.

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| No 🌙 indicator | `recall_indicator` off, or store empty, or provider not active (`hermes memory status`) |
| Recall returns nothing | Store empty; or `auto_recall` / mode `tools` disables auto-injection (use the tool) |
| Turns not saved | `auto_retain` off, or `retain_every_n_turns` batching, wait N turns |
| Slow first recall | ONNX model loads on first use (one-time cost) |
| Errors | Check `~/.hermes/luminary/luminary.log` |

## Install

### One-shot (recommended)

```bash
git clone https://github.com/alertxsto/luminary-memory.git
cd luminary-memory && bash hermes/install.sh
bash ~/.hermes/scripts/restart-bots.sh
```

### Manual

```bash
pip install "luminary-memory[hermes]>=0.2.18"
# config.yaml → memory: provider: luminary
mkdir -p ~/.hermes/hooks/luminary-activity
cp hermes/hooks/luminary-activity/*.py hermes/hooks/luminary-activity/HOOK.yaml ~/.hermes/hooks/luminary-activity/
mkdir -p ~/.hermes/skills/luminary-memory && cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/
```

## Notes

- Default backend SQLite (zero config); pgvector via `LUMINARY_BACKEND=pgvector`.
- Recall runs four strategies (semantic, keyword, temporal, graph) fused by weighted RRF (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1).
- The store is local; no data leaves the machine. Zero LLM tokens per turn.
