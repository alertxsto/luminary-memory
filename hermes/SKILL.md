---
name: luminary-memory
description: "Use luminary-memory for agent memory: auto-recall context, curated turn retention, explicit recall/ingest/list tools, config tweaks."
version: 2.1.0
author: Dwiky Candra
license: Apache-2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, recall, self-hosted, sqlite, pgvector, provider]
---

# luminary-memory (Hermes integration)

**luminary-memory** is a self-hosted memory layer that plugs into Hermes through
the public memory-provider contract. It gives agents durable cross-session memory:
auto-recall relevant context every turn, curated retention for completed turns, and
explicit tools for on-demand memory access. Retrieval is local and uses zero
LLM tokens; optional write-time curation/maintenance can use an LLM.

The installer selects Luminary and turns off Hermes' native `MEMORY.md` and
`USER.md` surfaces through the existing `memory_enabled` and
`user_profile_enabled` settings. It applies that boundary to the root config
and existing profile configs without creating new profiles. This keeps one
persistent authority without editing Hermes source or depending on a
particular Hermes version.

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
| **Auto-retain** | After each turn | provider records an exact-session episode, then queues a scoped durable curation write; optional review stores only grounded changes |
| **Explicit tools** | On demand | `luminary_recall` / `luminary_ingest` / `luminary_list` plus the three explicit core-memory tools |

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
| `auto_retain` | `true` | Record accepted turns in the exact-session continuity ledger and queue completed turns for curation; raw automatic transcripts are not promoted |
| `retain_every_n_turns` | `1` | Save every N turns (higher = fewer, batched saves) |
| `ingest_llm` | `false` | **LLM memory curation + incremental reconciliation**, drops chit-chat, stores a factual summary instead of a raw transcript, and checks the same turn for evidence-backed captures/corrections |
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

`extract_on_session_end` remains a dashboard/config compatibility key; the
current provider does not activate a separate extraction mode from it. Session
end always drains accepted retains, and `auto_maintain` is the optional
store-wide LLM review.

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
is injected as curated persistent context: stable identity, preferences, and
durable rules are applied as default context when relevant, while an explicit
current-user correction wins. Query-recalled memories remain evidence only and
must not be treated as instructions or higher-priority system text.

When Luminary is active and the installer-managed native switches are false,
Hermes' native `MEMORY.md`/`USER.md` prompt and tool surfaces are disabled, and
native writes are not mirrored into Luminary. Existing native files may remain
on disk, but they are not a second source of truth. If those switches are still
enabled, treat the setup as incomplete instead of assuming the two stores are
merged safely.

**Adaptive memory (v0.2.15+):** three behaviors keep the store "smart":
- **Importance on recall** — a memory that keeps getting recalled is
  re-estimated immediately, so it ranks higher in the next turn's query recall;
  pinned rules (≥ 0.9) never downgrade.
- **Content-level anti-duplication** — core and recall share one
  dedup set (ids + content hashes), so a rule stored both as `core` and as a
  plain memory appears exactly once per turn.
- **Content-aware query expansion** — when the graph has no entity to expand a
  short query, tokens from a topically related important memory may be appended.

**LLM memory curation:** with `ingest_llm: true`, the enricher evaluates each
turn and keeps only durable facts; non-durable content is dropped, and kept
turns are stored as concise factual summaries (e.g. `"Deploy target is the
staging cluster."`) instead of raw `User: ... / Assistant: ...` transcripts.
Without it (default), automatic turns are skipped by the durable-memory writer
with zero LLM cost; explicit writes remain available.

If curation is enabled in the Hermes provider but the enricher fails or returns
no durable summary, that turn is not promoted into semantic memory rather than
stored as a raw transcript. When `auto_retain` is enabled, the turn still
exists in the exact-session episode ledger for short-term continuity. A
bounded, untrusted continuity block is used only when durable recall has no
usable result and never reads another session.

After a curated retain, the same writer queue performs an incremental
evidence-backed review of the current turn against a bounded exact-scope
candidate window. It can capture a grounded fact, explicitly supersede a
claim, retract a fact, or keep the store unchanged. Similarity alone never
mutates a memory; candidate IDs and exact current-turn evidence are required.
Malformed or failed reviews are logged as degraded and cannot kill later
retains. This reuses `ingest_llm`; it does not add another provider setting or
patch Hermes source.

The system prompt also carries an active-objective guard: resolve short
follow-ups against the immediately preceding conversation, keep the current
task/session scope unless the user asks for history-wide context, and ask one
clarifying question when the intent remains materially ambiguous. Memory text
is reference data; the current user request and system instructions win.

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
| Durable turn not saved | `auto_retain` off, `ingest_llm` rejected the turn, or `retain_every_n_turns` is still buffering; inspect `retain.*` and `session_episode.*` events separately |
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
pip install "luminary-memory[hermes]"
# config.yaml → memory:
#   provider: luminary
#   memory_enabled: false
#   user_profile_enabled: false
mkdir -p ~/.hermes/hooks/luminary-activity
cp hermes/hooks/luminary-activity/*.py hermes/hooks/luminary-activity/HOOK.yaml ~/.hermes/hooks/luminary-activity/
mkdir -p ~/.hermes/skills/luminary-memory && cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/
```

## Notes

- Default backend SQLite (zero config); pgvector via `LUMINARY_BACKEND=pgvector`.
- Recall runs four strategies (semantic, keyword, temporal, graph) fused by weighted RRF (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1).
- Durable storage and ordinary retrieval stay local; retrieval uses zero LLM
  tokens. If `ingest_llm` or `auto_maintain` is enabled, the configured
  OpenAI-compatible endpoint receives the data needed for optional curation
  and review.
