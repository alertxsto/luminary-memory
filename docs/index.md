# luminary-memory

A lightweight, self-hosted memory layer for AI agents.

## What it does

- **Store** durable facts, preferences, and environment details across sessions.
- **Recall** the right context for the current task — not just the last few messages.
- **Maintain** the store automatically (dedupe, expire, prune).

## Key features

- Four retrieval strategies fused into one ranked recall (semantic, keyword, temporal, graph).
- **First-class Hermes Agent memory provider** — auto-recall every turn, auto-save every session, zero LLM tokens per turn (`memory.provider: luminary`).
- **LLM memory curation** — optional `ingest_llm` drops chit-chat and stores factual summaries; `auto_maintain` prunes stale/duplicate facts at session end.
- **Health score** — `health_score()` / `luminary-memory health` reports store quality (0-100) with recommendations.
- **Knowledge graph** — `graph()` / `luminary-memory graph` surfaces entities and co-occurrence relations, ranked by degree.
- SQLite out of the box, optional pgvector for scale (integration-tested in CI).
- Local CPU embeddings via ONNX — no GPU, no cloud.
- Configurable token budget so memory never overflows the agent's context.
- Clean Python API + CLI.
- **Automated contribution tooling** — CI (3.11/3.12 + pgvector), triage auto-labeling, stale bot, contributor account check.

## Quick links

- [Quickstart](quickstart.md)
- [Architecture](architecture.md)
- [Python API](api.md)
- [CLI](cli.md)
- [Recall](recall.md)
- [Lifecycle](lifecycle.md)
- [Backends](backends.md)
- [Hermes integration](hermes-integration.md)
