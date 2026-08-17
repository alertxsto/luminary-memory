# Lifecycle

Two maintenance layers keep the store lean: deterministic passes
(`run_lifecycle()`) and LLM-driven curation (`run_maintenance()`).

## `run_lifecycle()` — deterministic passes

### cleanup — TTL expiry

Removes memories whose `ttl_seconds` has elapsed.

### consolidate — merge near-duplicates

Clusters memories by Jaccard similarity (`LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD`, default 0.9) and merges each cluster into a single memory — keeping the longest content, summing access counts, and unioning tags.

### prune — drop low-value memories

Removes memories below a minimum importance (`LUMINARY_PRUNE_MIN_IMPORTANCE`, default 0.2).

## `run_maintenance()` — LLM-driven curation (v0.2.2+)

Sends the store to the configured LLM enricher, which reviews every memory and
decides **keep** / **update** / **delete**:

- **delete** — obsolete, contradicted, or duplicate facts (e.g. the old
  deploy target after it changed).
- **update** — facts that changed, with replacement content.
- **keep** — still-current facts.

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
