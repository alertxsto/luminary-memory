# luminary-memory

A lightweight, self-hosted memory layer for AI agents.

## What it does

- **Store** durable facts, preferences, and environment details across sessions.
- **Recall** the right context for the current task — not just the last few messages.
- **Maintain** the store automatically (dedupe, expire, prune).

## Key features

- Four retrieval strategies fused into one ranked recall (semantic, keyword, temporal, graph).
- **First-class Hermes Agent memory provider** — auto-recall every turn, auto-save every session, zero LLM tokens per turn (`memory.provider: luminary`).
- SQLite out of the box, optional pgvector for scale.
- Local CPU embeddings via ONNX — no GPU, no cloud.
- Configurable token budget so memory never overflows the agent's context.
- Clean Python API + CLI.

## Quick links

- [Quickstart](quickstart.md)
- [Architecture](architecture.md)
- [Python API](api.md)
- [CLI](cli.md)
- [Recall](recall.md)
- [Lifecycle](lifecycle.md)
- [Backends](backends.md)
- [Hermes integration](hermes-integration.md)
