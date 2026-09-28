# Agent tools

When `mode` is `tools` or `hybrid`, the Luminary provider registers six tools
that the model can call explicitly, in addition to the automatic recall/retain
that runs every turn.

## luminary_recall

```json
{"name": "luminary_recall", "description": "Recall relevant memories from the Luminary store for a query.", "parameters": {"query": "string (required)", "limit": "integer (optional; provider default 10)"}}
```

Runs the full scoped four-strategy recall (semantic + keyword + temporal +
graph). The JSON result contains `status`, `reason`, `confidence`, `memories`,
`scores`, and `provenance`; unsupported queries may return an empty `abstain`.
An operational strategy failure reports `degraded` with surviving hits or
`error` without usable hits. Core matches already present in the system prompt
are omitted from the tool payload and reported through
`deduplicated_core_ids`.

## luminary_ingest

```json
{"name": "luminary_ingest", "description": "Store a new memory in the Luminary store.", "parameters": {"content": "string (required)", "tags": "array of strings (optional)"}}
```

The provider supplies the source (`hermes-tool`) and current ownership scope;
the tool does not accept arbitrary `source` or `importance` arguments. Exact
duplicates are suppressed, whitelist rejection is reported, and the write
records evidence/provenance through the normal client path. This explicit tool
remains writable even when automatic turn curation is disabled.

## luminary_list

```json
{"name": "luminary_list", "description": "List recent memories from the Luminary store (read-only).", "parameters": {"limit": "integer (optional, default 20)"}}
```

Returns only `id`, `content`, and `tags`, most recent first. It is an
inspection view, not a recall query and not an episode-ledger reader.

## luminary_core_add

```json
{"name": "luminary_core_add", "description": "Pin a durable rule into core memory (auto-loaded every session).", "parameters": {"content": "string (required)"}}
```

Pins a memory as `core` and raises it to the configured pin threshold (default
`0.9`). Core memories are loaded into the system prompt at the start of every
session — the DB-backed equivalent of `MEMORY.md`. A same-key, different-value
claim remains auditable until a caller explicitly supersedes an eligible
predecessor; similar text alone does not replace it.

## luminary_core_remove

```json
{"name": "luminary_core_remove", "description": "Unpin a rule from core memory.", "parameters": {"id": "integer (required) — the memory id returned by luminary_core_list"}}
```

Removes the `core` tag from a memory (keeps it in the store, just stops
auto-loading it every session).

## luminary_core_list

```json
{"name": "luminary_core_list", "description": "List current core memories.", "parameters": {"limit": "integer (optional, default 50)"}}
```

Returns `id`, `content`, and `importance` for active memories carrying the
configured core tag, in stable ascending store-id/insertion order. The result
is bounded by the supplied limit; the prompt itself is additionally bounded by
`core_top_n` and `core_budget`.

---

## Tool availability by mode

| Mode | Auto-recall | Auto-retain | Tools registered |
|------|-------------|-------------|------------------|
| `context` | ✅ | ✅ | ❌ (no tools) |
| `tools` | ❌ | ✅ | ✅ (all 6) |
| `hybrid` | ✅ | ✅ | ✅ (all 6) |

## Accuracy behavior

Provider tool calls inherit the provider's current scope and strict recall
policy. `luminary_recall` returns status, confidence, and provenance; an
unrelated or weakly supported query may return `abstain` with no memories.
`luminary_ingest` records evidence and ownership metadata, and exact duplicate
writes are suppressed within the same scope.
