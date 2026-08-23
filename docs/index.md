# luminary-memory

A lightweight, self-hosted memory layer for AI agents.

> Current implementation: `0.2.18`. The strict CLI/Hermes accuracy path now
> includes scope isolation, evidence/provenance, conflict history, abstention,
> delivery-safe Telegram activity reporting, and scoped JSONL transparency
> events, and exact-session continuity fallback. Current verification: `505 passed, 3 skipped`, 83% coverage.

## What it does

- **Store** durable facts, preferences, and environment details across sessions.
- **Recall** the right context for the current task, not just the last few messages.
- **Maintain** the store automatically (dedupe, expire, prune).

## Key features

- Four retrieval strategies fused into one ranked recall via weighted RRF (semantic 0.4, keyword 0.3, graph 0.2, temporal 0.1) + query expansion.
- **First-class Hermes Agent memory provider**, auto-recall every turn and evaluate automatic turn batches for durable storage (`memory.provider: luminary`); zero LLM tokens for retrieval. The installer disables Hermes' native memory surfaces so Luminary is the only persistent authority. Explicit writes remain available without curation.
- **Core memory**, DB-backed equivalent of `MEMORY.md` (tag `core`), auto-loaded into the system prompt every session — durable rules never need a query match.
- **Adaptive importance (v0.2.15)**, memories that keep getting recalled are re-estimated immediately, so frequently-used facts rank higher in the next turn's query recall; pinned rules never downgrade.
- **Content-aware query expansion (v0.2.15)**, when the graph has no entity to expand a short query, tokens from a topically related important memory may be appended without a static alias table.
- **Content-level anti-duplication (v0.2.15)**, core and recall share one dedup set (ids + content hashes) so identical text appears exactly once per turn.
- **LLM memory curation and reconciliation**, optional `ingest_llm` drops chit-chat, stores factual summaries, and checks each turn for evidence-backed captures/corrections; `auto_maintain` still prunes stale/duplicate facts at session end.
- **Health score**, `health_score()` / `luminary-memory health` reports store quality (0-100) with recommendations.
- **Knowledge graph**, `graph()` / `luminary-memory graph` surfaces entities and co-occurrence relations, ranked by degree.
- SQLite out of the box, optional pgvector for scale (integration-tested in CI).
- Local CPU embeddings via ONNX, no GPU, no cloud.
- Configurable token budget so memory never overflows the agent's context.
- Database-enforced exact deduplication across concurrent writers, with
  legacy duplicate migration and replacement lineage.
- Redacted Hermes JSONL logs with trace IDs, scope, status/reason, counts,
  confidence, and latency for long-running troubleshooting.
- Clean Python API + CLI.
- **Automated contribution tooling**, CI (3.11/3.12 + pgvector), triage auto-labeling, stale bot, contributor account check.

## Quick links
- [CLI reference](cli.md)
- [Agent tools](agent-tools.md)

- [Quickstart](quickstart.md)
- [Architecture](architecture.md)
- [Configuration reference](config-reference.md)
- [Python API](api.md)
- [Recall](recall.md)
- [Lifecycle](lifecycle.md)
- [Backends](backends.md)
- [Hermes integration](hermes-integration.md)
- [Benchmark protocol and results](../benchmarks/README.md)
- [v0.2.17 Debugging & Integration Guide](debugging-v0.2.17.md)
- [v0.2.17 Debugging Scope & Investigation Log](DEBUGGING-SCOPE-v0.2.17.md)
