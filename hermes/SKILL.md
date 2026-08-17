---
name: luminary-memory
description: "Use luminary-memory for agent memory: ingest, recall, lifecycle."
version: 1.0.0
author: Dwiky Candra
license: Apache-2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, recall, self-hosted, sqlite, pgvector]
---

# luminary-memory (Hermes integration)

**luminary-memory** is a self-hosted memory layer. This skill wires it into Hermes so an agent can store durable facts across sessions, recall the right context on demand, and keep the store clean.

> **Note (v0.2.1+):** the preferred integration is the **pip entry-point provider**
> (`hermes memory setup luminary` → `memory.provider: luminary`), which gives
> auto-recall every turn, auto-save every session, explicit `luminary_recall` /
> `luminary_ingest` / `luminary_list` tools, and a deterministic recall indicator.
> See `docs/hermes-integration.md`. The standalone-skill flow below remains
> supported for manual/managed setups.

## When to Use

- When an agent needs durable cross-session memory beyond the built-in MEMORY.md/USER.md files.
- When recall should surface context relevant to the current task (not just the last few messages).
- When the store needs periodic maintenance (deduplication, expiry, pruning).

## Install

```bash
pip install luminary-memory
# or from source: pip install -e ".[dev]"
```

## Agent usage

### Ingest a durable fact

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="~/.luminary/memory.db")

# after learning something durable (a preference, an environment detail):
client.ingest("user prefers concise responses", tags=["preference"], source="hermes")
client.close()
```

### Recall into the system prompt

Before answering, recall relevant context for the current query:

```python
from luminary_memory import MemoryClient

client = MemoryClient(db_path="~/.luminary/memory.db")
result = client.recall("what does the user prefer about response style?", limit=5)
for memory, score in zip(result.memories, result.scores):
    print(f"[{score:.2f}] {memory.content}")
client.close()
```

Inject the recalled memories into the conversation as context.

### Lifecycle via cron

Schedule periodic maintenance (TTL cleanup, near-duplicate consolidation, low-value pruning):

```bash
# cron: run daily
luminary-memory lifecycle
```

Or programmatically:

```python
client = MemoryClient(db_path="~/.luminary/memory.db")
print(client.run_lifecycle())   # {"cleanup": N, "consolidate": N, "prune": N}
client.close()
```

## Configuration

Set `LUMINARY_*` env vars or pass a `Settings` object. See the project README for the full table.

## Notes

- Default backend is SQLite (zero config). Switch to pgvector with `LUMINARY_BACKEND=pgvector`.
- Recall runs four strategies (semantic, keyword, temporal, graph) and fuses them — no single query style dominates.
- The store is local; no data leaves the machine.
