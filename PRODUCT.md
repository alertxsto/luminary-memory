# Product brief: Luminary Memory

## Product

Luminary Memory is a self-hosted memory layer for AI agents. It stores
evidence-backed facts locally, retrieves scoped context conservatively, and
keeps durable core memories separate from ordinary query recall.

## Audience

- Agent builders who need durable memory without a hosted memory vendor.
- Operators running Hermes through CLI, Telegram, gateways, or scheduled jobs.
- OpenCode users and operators who need scoped local recall with an npm plugin
  and Python sidecar.
- Contributors who need a small, inspectable Python codebase and explicit
  lifecycle behavior.

## Product thesis

Memory should be useful because it is grounded, scoped, and reviewable—not
because it always returns something. A good recall can abstain, an update can
remain a conflict until explicitly superseded, and every provider operation can
be diagnosed without logging private memory text.

## Current product surface

- SQLite by default, with an optional pgvector backend.
- Semantic, keyword, temporal, and graph candidates fused through weighted RRF.
- Scope filtering, evidence validation, conflict lineage, abstention, and
  token-bounded serialization.
- DB-backed `core` memories that behave like an agent's durable native memory.
- Python API, CLI, provider tools, lifecycle maintenance, health reporting, and
  a redacted JSONL transparency log.
- Hermes integration through the public provider entry point. The installer
  selects Luminary and disables Hermes' two native persistent surfaces through
  existing config keys; it does not patch Hermes source or pin a Hermes version.
- OpenCode integration through an npm plugin and local Python JSONL sidecar:
  strict latest-query automatic recall, `luminary_recall` and
  `luminary_ingest`, scoped local identity, and graceful local failure.

## Design boundaries

- Retrieval does not require an LLM. Optional LLM calls are limited to write-time
  curation and maintenance.
- Automatic turn retention is conservative for Hermes: without curation, raw
  transcript batches are not promoted as durable facts. OpenCode has no
  automatic turn retention; only explicit ingest writes.
- The runtime must not hardcode a natural language, person, or provider-specific
  identity. Identity comes from scope and the stored evidence.
- Compatibility is based on the public Hermes provider capability contract for
  Hermes. OpenCode compatibility is its plugin API/configuration, skill
  discovery, scope mapping, and Python sidecar protocol. If a host cannot
  expose the relevant contract, the integration should fail visibly rather
  than silently create competing authorities.

## Website direction

The public site should feel like a moonlit technical editorial: quiet, precise,
archival, and inspectable. It should teach the memory lifecycle through an
evidence ledger and expose the tracked documentation without inventing benchmark
claims or hiding integration boundaries.
