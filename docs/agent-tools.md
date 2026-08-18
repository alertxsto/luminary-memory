# Agent tools

When `mode` is `tools` or `hybrid`, the Luminary provider registers six tools
that the model can call explicitly, in addition to the automatic recall/retain
that runs every turn.

## luminary_recall

```json
{"name": "luminary_recall", "description": "Search long-term memory for context relevant to the current turn.", "parameters": {"query": "string (required) — the search query", "limit": "integer (optional, default 10)"}}
```

Runs the full four-strategy fused recall (semantic + keyword + temporal + graph)
and returns the top-N memories as context.

## luminary_ingest

```json
{"name": "luminary_ingest", "description": "Store a durable fact in long-term memory.", "parameters": {"content": "string (required)", "tags": "string (optional, comma-separated)", "source": "string (optional)", "importance": "float (optional, 0.0–1.0)"}}
```

Stores a memory. With `ingest_llm` enabled the fact is curated by the enricher
first (drops chit-chat, stores a factual summary).

## luminary_list

```json
{"name": "luminary_list", "description": "List stored memories (most recent first).", "parameters": {"limit": "integer (optional, default 20)", "offset": "integer (optional)"}}
```

Paginates over the store. Useful for the agent to review what it has saved.

## luminary_core_add

```json
{"name": "luminary_core_add", "description": "Pin a durable rule into core memory (auto-loaded every session).", "parameters": {"content": "string (required)"}}
```

Pins a memory as `core` + `importance 0.9`. Core memories are loaded into the
system prompt at the start of every session — the DB-backed equivalent of
`MEMORY.md`. Rule auto-replace is applied: a semantically similar existing rule
is replaced instead of stacking a contradiction.

## luminary_core_remove

```json
{"name": "luminary_core_remove", "description": "Unpin a rule from core memory.", "parameters": {"id": "integer (required) — the memory id returned by luminary_core_list"}}
```

Removes the `core` tag from a memory (keeps it in the store, just stops
auto-loading it every session).

## luminary_core_list

```json
{"name": "luminary_core_list", "description": "List all pinned core memories.", "parameters": {}}
```

Returns every memory tagged `core`, sorted by importance. Use this to inspect
what the agent will see at the start of the next session.

---

## Tool availability by mode

| Mode | Auto-recall | Auto-retain | Tools registered |
|------|-------------|-------------|------------------|
| `context` | ✅ | ✅ | ❌ (no tools) |
| `tools` | ❌ | ✅ | ✅ (all 6) |
| `hybrid` | ✅ | ✅ | ✅ (all 6) |
