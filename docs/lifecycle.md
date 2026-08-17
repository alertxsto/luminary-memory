# Lifecycle

`run_lifecycle()` runs three maintenance passes:

## cleanup — TTL expiry

Removes memories whose `ttl_seconds` has elapsed.

## consolidate — merge near-duplicates

Clusters memories by Jaccard similarity (`LUMINARY_CONSOLIDATE_JACCARD_THRESHOLD`, default 0.9) and merges each cluster into a single memory — keeping the longest content, summing access counts, and unioning tags.

## prune — drop low-value memories

Removes memories below a minimum importance (`LUMINARY_PRUNE_MIN_IMPORTANCE`, default 0.2).

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
