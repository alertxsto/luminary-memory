# Benchmark Results — luminary-memory

No results have been recorded under the current holdout, latency, and
cost-per-correct-answer protocol. Run the commands in [README.md](README.md) to
produce a report; do not substitute fabricated or historical measurements.

Historical artifacts in [`baselines/`](baselines/README.md) used calibration
fixtures and did not record the required cost per correct answer. Their
quality figures are therefore withheld from this results summary and are not
quotable as holdout or cost-associated quality. The older fake-engine latency
measurements used too few samples for a meaningful p95 and do not represent
real-model latency.

For a new result, record the report artifact, revision and any working-tree
changes, dataset hash, configuration, model and cache conditions. Include the
measured construction and query resource cost per correct answer alongside
quality; if unavailable or no answer is correct, explicitly withhold the
quality claim. Report provider usage and monetary cost as unknown unless
measured usage and configured pricing are both available. Keep relevance
separate from grounding and fake latency separate from real-model latency.
