# CLI

## Global options

Every command accepts:

- `--db-path PATH` — override the SQLite path.
- `--backend sqlite|pgvector` — select the backend.

## Commands

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

```bash
luminary-memory lifecycle
```

Runs cleanup + consolidate + prune, prints counts.

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

## Exit codes

- `0` — success.
- `1` — error (e.g. invalid backend, rejected ingest).
