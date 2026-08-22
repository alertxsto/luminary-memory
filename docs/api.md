# Python API

Generated from docstrings via **pdoc** (zero-config, no mkdocs dependency).

**HTML reference:** [`api/`](./api/), open `docs/api/index.html` after running the generator.

## Build the reference

```bash
pip install -e ".[dev]"        # includes pdoc
pdoc --output-dir docs/api --docformat markdown src/luminary_memory
# open docs/api/luminary_memory.html , MemoryClient, Settings, backends, etc.
```

## Quick surface

- `MemoryClient`, `ingest`, `ingest_batch`, `recall` (tags + snippets + planner + strict abstention), `search`, `get`/`update`/`delete`, `supersede`, `resolve_conflict`, `retract`, `list`, `export`/`import_memories`, `run_lifecycle`, `run_maintenance` (LLM curation), `health_score` (store health report), `graph` (entities + relations), `stats`, `close`.
- `Settings`, `LUMINARY_*` env vars, `as_dict()`.
- `Memory`, `RecallResult`, `types.py` — including scope, status, validity,
  confidence, evidence, claim, supersession, and reindex fields.
- Subpackages `backends/`, `embeddings/`, `ingest/`, `recall/`, `lifecycle/`, `export`.

Regenerate whenever public docstrings change; CI optionally checks freshness with `pdoc --output-dir /tmp/pdoc_check && diff`.
