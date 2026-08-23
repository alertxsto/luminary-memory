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

## Public method contracts

The most important signatures are intentionally explicit here; the generated
pdoc pages remain the detailed reference.

```python
client.ingest(
    text,
    tags=None,
    source=None,
    metadata=None,
    enrich=True,
    importance=None,
    user_id=None,
    session_id=None,
    workspace_id=None,
    agent_id=None,
    observed_at=None,
    valid_from=None,
    valid_to=None,
    status="active",
    confidence=None,
    evidence_quote=None,
    source_id=None,
    claim_key=None,
    supersedes_id=None,
    source_text=None,
) -> int | None

client.recall(
    query,
    limit=10,
    token_budget=None,
    tags=None,
    tag_mode="any",
    scope=None,
    strict=None,
    include_conflicted=False,
) -> RecallResult
```

`ingest()` returns the canonical ID for an inserted or exact duplicate row and
returns `None` for empty or whitelist-rejected input. `source_text` is the
original evidence context for a distilled memory; it is not stored as the
memory's searchable content. `claim_key` plus `supersedes_id` is the explicit
versioning path. A different value with the same claim key but no explicit
supersession remains a visible conflict instead of silently replacing the old
fact.

`ingest_batch()` mirrors these write rules and returns one ID/`None` per input;
its `tags` and `metadata` arguments are parallel lists. `list(limit=0)` means
unlimited, and `count()` is the active, scope-visible public count. `search()`
is keyword-only; `recall()` is the scoped fused pipeline.

Mutation and inspection methods are:

```python
client.get(id, scope=None)
client.update(memory)
client.delete(id)
client.retract(id, reason=None)                 # soft-delete + audit
client.supersede(id, content, ..., source_text=None)
client.resolve_conflict(id, status="active", ...)
client.list(limit=100, offset=0, scope=None)
client.search(query, limit=10, scope=None)
client.run_lifecycle(semantic=None)
client.run_maintenance(review_all=True)
client.health_score()
client.graph(limit=20)
client.export(path, include_embeddings=True)
client.import_memories(path)
```

Bound clients cannot use a per-call scope to switch user, workspace, agent, or
session ownership. Global compatibility rows may be visible for reads when
configured, but a scoped client cannot mutate them. Normal recall hides
`conflicted`, `superseded`, deleted, and expired rows; `include_conflicted`
exists for diagnostics.

## Result and provenance shape

`RecallResult` contains `memories`, parallel `scores`, `strategies_hit`,
`status`, `reason`, `confidence`, and `provenance`. A strict caller should
handle `status="abstain"` as a correct no-answer outcome rather than forcing
the first candidate. Each returned `Memory` can carry ownership, validity,
status, confidence, `evidence_quote`, `source_id`, `claim_key`,
`supersedes_id`, `content_hash`, and `needs_reindex` in addition to its content,
tags, and metadata.

The Hermes episode ledger is a backend/provider boundary, not a new
`MemoryClient.recall()` source. Its `record_episode()` and
`recent_episodes()` helpers preserve exact-session continuity without turning
raw turns into durable semantic memories.

## Consistency contracts

- `MemoryClient.count()` is the active, scope-visible count and agrees with
  `list(limit=0)`. Use `client.backend.count()` only when inspecting raw rows
  retained for lifecycle/audit history.
- Exact active duplicates are resolved by the database for the complete
  `user_id`/`workspace_id`/`agent_id`/`session_id` scope. A concurrent duplicate
  write returns the canonical ID and does not create a second episode,
  evidence row, or graph lineage.
- Export/import deduplication follows the same active-row rule: deleted or
  superseded history does not block restoring an active copy.
- With `evidence_required=True`, recall only returns quotes grounded in the
  stored content, including permissive and fallback paths.

Regenerate whenever public docstrings change; CI optionally checks freshness with `pdoc --output-dir /tmp/pdoc_check && diff`.
