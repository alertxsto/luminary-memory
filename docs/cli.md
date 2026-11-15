# CLI

## Global options

Every command accepts:

- `--db-path PATH`, override the SQLite path.
- `--backend sqlite|pgvector`, select the backend.

The CLI recall path uses strict abstention, evidence-required results, and
non-destructive rule handling. Set scope without placing identity values in
shell history:

```bash
export LUMINARY_USER_ID=u1
export LUMINARY_WORKSPACE_ID=luminary
export LUMINARY_AGENT_ID=coding-agent
export LUMINARY_SESSION_ID=session-42
```

Supply all three owner fields for a scoped read; a partial identity is not a
wildcard. Without a scope the CLI reads only the fully unowned local namespace.
See [ownership migration](api.md#ownership-and-legacy-migration) before
assigning legacy records.

## Commands

### activity

Show recent persisted memory activity in the same compact style used by the
Telegram activity hook. This command is read-only and does not bump recall
access counters.

```bash
luminary-memory activity --db-path ~/.hermes/luminary/memory.db
luminary-memory activity --limit 5 --json
```

Human output:

```text
🌙 Luminary — 2 recent memories stored
  📌 #12 ALWAYS verify tests before release
    tags: core, rule · source: hermes
  • #11 Deploy target is staging
    tags: deploy · source: cli
```

JSON output is stable and automation-friendly:

```json
{
  "status": "active",
  "event": "memory_activity",
  "count": 1,
  "memories": [
    {
      "id": 11,
      "content": "Deploy target is staging",
      "tags": ["deploy"],
      "source": "cli",
      "importance": 0.5,
      "created_at": "2026-08-23T10:00:00+00:00"
    }
  ]
}
```

An empty store is explicit rather than silently producing a blank screen:

```text
🌙 Luminary — no stored memory activity
```

`activity` reads persisted active durable-memory rows for operator visibility.
It does not report raw Hermes session episodes, recall hits, or LLM review
decisions that did not create a durable row.

### add

```bash
luminary-memory add "The deploy target is the staging cluster" --tags deploy,infra --source hermes
```

Stores a memory. Prints the new id, or `rejected by whitelist` if filtered.

### recall

```bash
luminary-memory recall "where do we deploy?" --limit 5
luminary-memory recall "where do we deploy?" --json
```

Runs the full four-strategy pipeline. Default output is a rich table; `--json` emits a machine-readable object.
The JSON form includes `status` (`ok`, `fallback`, or `abstain`), `reason`,
confidence, evidence quote, source, and provenance. An unrelated query returns
an explicit abstention with zero memories instead of a guessed top result.

### search

```bash
luminary-memory search "postgresql" --limit 10
```

Keyword (FTS) search only.

### list

```bash
luminary-memory list --limit 50 --offset 0
```

Most recent first.

### lifecycle

Core memory is the DB-backed equivalent of `MEMORY.md`: those rows are
loaded into the system prompt every session. Promote or demote one record
without touching its content or history:

```bash
luminary-memory core 12            # auto-loaded in every session
luminary-memory core 12 --off      # back to ordinary query recall
luminary-memory core 12 --json     # id, core, importance, tags
```

Only an active memory can change designation. The same rule (core tag plus the
pinned importance floor) runs for the owner-confirmed inspector action, so the
two surfaces cannot disagree, and a scoped client can only change its own
records.

```bash
luminary-memory lifecycle
luminary-memory lifecycle --no-semantic   # Jaccard-only consolidation
```

Runs cleanup + consolidate + prune (plus importance re-estimation), prints
counts. `--semantic/--no-semantic` toggles embedding-cosine consolidation
(default: semantic on).

### export

```bash
luminary-memory export --path backup.json
luminary-memory export --path backup.json --no-embeddings
```

Exports memories visible to the current scope to a JSON file.
`--no-embeddings` skips embedding vectors to keep the file small.

### import

```bash
luminary-memory import --path backup.json
```

Imports memories from a JSON export (recomputes embeddings when absent). Every
record must match the target ownership; import rejects a mismatched batch rather
than assigning missing ownership. Use the trusted owner-confirmed migration
flow described in the [Python API guide](api.md#ownership-and-legacy-migration).

### reindex

```bash
luminary-memory reindex
```

Re-embeds every stored memory with the currently configured
`LUMINARY_EMBEDDING_MODEL` and prints a JSON summary
(`total`, `reindexed`, `unchanged`, `failed`, `confidence_repaired`, `dim`,
`model`).

Run this after changing the embedding model. Recall skips any row whose vector
width does not match the query vector, so without a reindex a model change
silently de-indexes the whole store: the rows are still there, they just never
match again. Recall logs a one-time warning when it detects this state.

`reindex` also repairs rows whose grounding confidence was stored as `0.0` even
though their evidence was verified. Those rows sit below the abstention gate and
can never be returned; the repair restores the confidence implied by the
evidence origin (`operator` `1.0`, `user` `0.9`, `curated_user` `0.8`).

### stats

```bash
luminary-memory stats
```

Prints store statistics as JSON.

### health

```bash
luminary-memory health
luminary-memory health --json
```

Prints a 0-100 store health score with a per-dimension breakdown (duplicate
rate, staleness, importance, graph density, size) and actionable
recommendations. `--json` emits the raw report.

### graph

```bash
luminary-memory graph                  # top entities as a table
luminary-memory graph --relations      # also print co-occurrence edges
luminary-memory graph --json           # raw JSON (entities + relations)
luminary-memory graph --limit 50       # more entities
```

Shows the knowledge graph: entities ranked by degree (connections) and the
co-occurrence relations between them.

### version

```bash
luminary-memory version
```

Prints the installed version and Python runtime.

## Authority repair (SQLite migration utility)

The repair utility is intentionally a script rather than a normal write command
so an operator must choose the database and explicitly opt into mutation:

```bash
# Read-only JSON plan
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db

# Create a backup and archive the selected rows
python scripts/repair_memory_authority.py \
  --db-path ~/.hermes/luminary/memory.db --apply
```

It identifies imported authority snapshots and structurally uncurated Hermes
turn batches using provenance/scope metadata. `--apply` archives rows and
records audit events; it never hard-deletes them. Review the dry-run output and
backup path before resuming automatic writes.

## Exit codes

- `0`, success.
- `1`, error (e.g. invalid backend, rejected ingest).
