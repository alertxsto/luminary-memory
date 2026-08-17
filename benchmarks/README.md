# Benchmarks

Reproducible harness for recall quality (recall@k, MRR) and latency (p50/p95) per strategy and end-to-end.

```bash
python -m benchmarks.run_benchmarks --n 2000 --backend sqlite --report /tmp/bench.json
```

- Deterministic seed, SQLite by default.
- `--backend sqlite` only for now; pgvector path is validated via existing mocked tests.
- Emits JSON report + stdout Markdown summary.
- Uses a fake deterministic embedding engine for pure-latency runs; swap `--real-embed` (future) for quality runs.

Report shape:
```json
{"n": 2000, "backend": "sqlite", "ingest_ms": 123, "latency_ms": {"semantic": {"p50": ...}}, "quality": {"postgres vector search": {"recall@5": ...}}}
```
