# Product brief: Luminary Memory

## Product

Luminary Memory is a self-hosted memory layer for AI agents. It stores
evidence-backed facts locally, retrieves scoped context conservatively, and
keeps durable core memories separate from ordinary query recall.

## Audience

- Agent builders who need durable memory without a hosted memory vendor.
- Operators running Hermes through CLI, Telegram, gateways, or scheduled jobs.
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

## Design boundaries

- Retrieval does not require an LLM. Optional LLM calls are limited to write-time
  curation and maintenance.
- Automatic turn retention is conservative: without curation, raw transcript
  batches are not promoted as durable facts.
- The runtime must not hardcode a natural language, person, or provider-specific
  identity. Identity comes from scope and the stored evidence.
- Compatibility is based on the public Hermes provider capability contract. If a
  host cannot expose that contract, the integration should fail visibly rather
  than start two competing memory authorities.

## Website direction

The public site should feel like a moonlit technical editorial: quiet, precise,
archival, and inspectable. It should teach the memory lifecycle through an
evidence ledger and expose the tracked documentation without inventing benchmark
claims or hiding integration boundaries.
