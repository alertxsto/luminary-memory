# Lifecycle

Two maintenance layers keep the store lean: deterministic passes
(`run_lifecycle()`) and LLM-driven curation (`run_maintenance()`).

## `run_lifecycle()`, deterministic passes

### cleanup, TTL expiry

Removes memories whose `ttl_seconds` has elapsed.

### consolidate, merge near-duplicates

Clusters memories by Jaccard similarity (`LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD`, default 0.9) **or embedding-cosine similarity** (`LUMINARY_CONSOLIDATE_SEMANTIC`, default `true`) and merges each cluster into a single memory, keeping the longest content, summing access counts, and unioning tags. Semantic mode (default) merges paraphrases that token overlap would miss; it falls back to Jaccard when embeddings are missing. Disable with `LUMINARY_CONSOLIDATE_SEMANTIC=false` or `luminary-memory lifecycle --no-semantic`.

### importance, auto-estimation

On ingest and before each prune, each memory's importance is estimated from behavior:

```
importance = access_norm × 0.4 + recency_norm × 0.3 + centrality_norm × 0.3
```

- `access_norm`, `log1p(access_count)` normalized to the store's max.
- `recency_norm`, `exp(-age_hours / 24h)` (fresh memories score higher).
- `centrality_norm`, graph relation degree normalized (0 when no graph).

Disable with `LUMINARY_IMPORTANCE_AUTO=false`. Pruning and the health score's
importance dimension both use these live values.

### prune, drop low-value memories

Removes memories below a minimum importance (`LUMINARY_PRUNE_MIN_IMPORTANCE`, default 0.2).

When the store exceeds `max_memories` (default 1000), the oldest and
lowest-importance memories are pruned first, keeping the store under a hard
size cap even if importance-based pruning never fires.

**Rule pinning (v0.2.11+):** memories at importance ≥ 0.9 are pinned and never
pruned — neither by importance threshold nor by the `max_memories` cap. This
protects durable rules (e.g. "always use markdown tables") from being evicted.

### Batched passes (v0.2.12+)

Prune and importance re-estimation are batched at the backend level
(`delete_many`, `update_importances`), so lifecycle runs issue a handful of
statements instead of one write per memory — important on large stores.

## `run_maintenance()`, LLM-driven curation (v0.2.2+)

Sends the store to the configured LLM enricher, which reviews every memory and
decides **keep** / **update** / **delete**:

- **delete**, obsolete, contradicted, or duplicate facts (e.g. the old
  deploy target after it changed).
- **update**, facts that changed, with replacement content.
- **keep**, still-current facts.

Requires an LLM enricher (set `ingest_llm: true` + `llm_*` config); no-ops
otherwise. One LLM call per review run (all memories in a single call).

```python
client = MemoryClient(db_path="memory.db", enricher=enricher)
print(client.run_maintenance())
# {'reviewed': 4, 'deleted': 2, 'updated': 0}
```

### Automatic maintenance in the Hermes provider

With `auto_maintain: true` in `~/.hermes/luminary/config.json` (plus
`ingest_llm: true`), the provider runs `run_maintenance()` automatically at
every session end:

```json
{
  "ingest_llm": true,
  "llm_base_url": "https://api.commandcode.ai/provider/v1",
  "llm_model": "deepseek/deepseek-v4-flash",
  "llm_api_key": "your-key",
  "auto_maintain": true
}
```

Results are recorded in the transparency log
(`~/.hermes/luminary/luminary.log`): `maintenance {'reviewed': N, 'deleted': N, 'updated': N}`.

## `health_score()`, store health report (v0.2.4+)

Returns a 0-100 health score with a per-dimension breakdown, computed from
existing store data (no new schema):

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| `duplicate_rate` | 25% | Share of memories with a near-duplicate (Jaccard > threshold) |
| `staleness` | 25% | Share of memories not accessed in 30 days |
| `importance` | 20% | Share of memories above `prune_min_importance` |
| `density` | 15% | Share of memories with graph relations |
| `size` | 15% | Store volume (scales toward 100 at ~1k memories) |

```python
report = client.health_score()
print(report["score"])            # 87.5
print(report["recommendations"])  # actionable hints
```

CLI:

```bash
luminary-memory health           # human-readable bar
luminary-memory health --json    # raw JSON
```

```
📊 Memory Health: 87.5/100 █████████░
  ✅ duplicate_rate: 98%
  ⚠️ density: 33%
  → 2 stale memories (>30d), run lifecycle prune or LLM maintenance
```

Empty store scores 100 (nothing wrong); low-scoring dimensions produce
recommendations.

## Scheduling

Run via cron for a self-maintaining store:

```cron
0 4 * * *  /usr/local/bin/luminary-memory lifecycle
```

Or programmatically:

```python
client = MemoryClient(db_path="memory.db")
print(client.run_lifecycle())
client.close()
```
