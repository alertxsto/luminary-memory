# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-08-17

### Added

- SQLite backend with FTS5 keyword search and in-process vector search.
- Optional pgvector backend (HNSW-ready).
- Four-strategy recall: semantic, keyword, temporal, graph.
- Reciprocal Rank Fusion (RRF) + Jaccard dedup + token budget.
- Ingest pipeline with whitelist filter and optional LLM enrichment.
- Lifecycle: TTL cleanup, near-duplicate consolidation, low-value pruning.
- Python API (`MemoryClient`) and CLI (`luminary-memory`).
- Environment-variable configuration (`LUMINARY_*`).
