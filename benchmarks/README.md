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

## Hindsight-parity benchmark (provider)

`benchmarks/hermes_provider_bench.py` measures the resource + latency profile of the
Hermes memory provider against Hindsight's local_embedded mode:

```bash
python benchmarks/hermes_provider_bench.py --n 5000 --backend sqlite --report /tmp/lum_vs_hindsight.json
```

Measured for luminary (CI-safe, deterministic fake embedding):

- **recall p50/p95** — end-to-end `client.recall()` latency (incl. embedding), fixed query set
- **peak RSS** — max resident set size observed during the run
- **lifecycle duration** — `run_lifecycle()` (TTL cleanup + consolidate + prune) on the same store

Report shape:

```json
{"n": 5000, "backend": "sqlite", "ingest_ms": ..., "recall_latency_ms": {"p50": ..., "p95": ..., "mean": ...}, "lifecycle_ms": ..., "peak_rss_mb": ..., "queries": [...]}
```

### Hindsight reference arm (optional, manual)

Hindsight's local_embedded mode downloads ~200MB of model weights and runs a daemon,
so it is intentionally **not** a CI gate. To record the reference numbers manually:

1. Install Hindsight with local_embedded per its docs.
2. Ingest the same synthetic dataset (`benchmarks/synthetic.py`, `--n 5000`).
3. Run the same fixed query set; record p50/p95 latency and peak RSS.
4. Paste the numbers into the `reference.hindsight_local_embedded` field of the report.

The claim the benchmark supports: luminary matches/exceeds Hindsight's recall
experience at a fraction of the resource cost (no daemon, no ~200MB download,
no GPU-sized embedding model).
