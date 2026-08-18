---
name: luminary-memory
description: "Use luminary-memory for agent memory: auto-recall context, auto-save turns, explicit recall/ingest/list tools, config tweaks."
version: 2.0.0
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
explicit tools for on-demand memory access — all local, zero LLM tokens.

**What your agent remembers is what it becomes.**

## When to Use

- **Recall context** — when the current task depends on things said or done in
  earlier sessions (preferences, decisions, environment details, past fixes).
- **Store durable facts** — after learning something that will matter later
  (a user preference, a project convention, a config decision).
- **Inspect the store** — list what luminary currently remembers, or check
  whether a fact is already known before storing it again.
- **Troubleshoot** — when memory seems stale or missing, check the store and
  the transparency log.

## How It Works (3 ways to interact)

| Path | When | Trigger |
|------|------|---------|
| **Auto-recall** | Every turn | `memory.provider: luminary` — background recall injected into context (🌙 indicator) |
| **Auto-retain** | After each turn | provider saves `User: ... / Assistant: ...` to the store |
| **Explicit tools** | On demand | `luminary_recall` / `luminary_ingest` / `luminary_list` |

## Agent Usage — Explicit Tools

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

Use this before re-ingesting — if a fact is already stored, update instead of
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
`run_maintenance()` automatically at every session end — no manual trigger
needed. Results are logged to `~/.hermes/luminary/luminary.log`. CLI:
`luminary-memory health` (human bar) or `--json`.

## Configuration — Tweaks

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
| `ingest_llm` | `false` | **LLM memory curation** — drops chit-chat, stores factual summary instead of raw transcript |
| `llm_base_url` / `llm_model` / `llm_api_key` | `""` | OpenAI-compatible enricher endpoint/model/key |
| `auto_maintain` | `false` | **LLM store review at session end** — keeps/updates/deletes stale or duplicate facts (needs `ingest_llm`) |
| `recall_indicator` | `true` | Show `🌙 Luminary — recalled N memories` |
| `retain_indicator` | `true` | Show `🌙 Luminary — memory saved` |
| `backend` | `sqlite` | `sqlite` (zero config) or `pgvector` (scale) |

**LLM memory curation:** with `ingest_llm: true`, the enricher evaluates each
turn and keeps only durable facts — greetings, chit-chat, and trivial
acknowledgements are dropped, and kept turns are stored as concise factual
summaries (e.g. `"Deploy target is the staging cluster."`) instead of raw
`User: ... / Assistant: ...` transcripts. Without it (default), turns are
stored verbatim with zero LLM cost.

Example — save less often, no indicators:

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

## Transparency Log

`~/.hermes/luminary/luminary.log` records every recall, retain, and error:

```
2026-08-18 04:26:37 INFO initialize session=... platform=telegram agent=default
2026-08-18 04:26:40 INFO recall query='deploy target' limit=10 -> 5 memories (142ms)
2026-08-18 04:26:45 INFO retain stored len=312 tags=['session:...', 'platform:telegram']
```

Check this first when memory seems wrong or missing.

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| No 🌙 indicator | `recall_indicator` off, or store empty, or provider not active (`hermes memory status`) |
| Recall returns nothing | Store empty; or `auto_recall` / mode `tools` disables auto-injection (use the tool) |
| Turns not saved | `auto_retain` off, or `retain_every_n_turns` batching — wait N turns |
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
pip install "luminary-memory[hermes]>=0.2.10"
# config.yaml → memory: provider: luminary
mkdir -p ~/.hermes/hooks/luminary-activity
cp hermes/hooks/luminary-activity/*.py hermes/hooks/luminary-activity/HOOK.yaml ~/.hermes/hooks/luminary-activity/
mkdir -p ~/.hermes/skills/luminary-memory && cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/
```

## Notes

- Default backend SQLite (zero config); pgvector via `LUMINARY_BACKEND=pgvector`.
- Recall runs four strategies (semantic, keyword, temporal, graph) fused by RRF.
- The store is local; no data leaves the machine. Zero LLM tokens per turn.
