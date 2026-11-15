# Benchmarks

The runner separates labelled retrieval quality from synthetic latency. The
default `gold_holdout.jsonl` contains distinct synthetic cases and labels, not
independently human-verified labels. It was not used to choose the configured
thresholds. Freeze those thresholds before evaluating it; once used to tune a
threshold, this fixture is no longer an independent holdout for that decision.
It covers Indonesian, corrected facts, distractors, no-answer and scope.
This small controlled dataset is not evidence of production performance or
superiority to another provider.

`gold_micro.jsonl` and `gold_extended.jsonl` remain usable through `--gold-set`.
They are calibration/regression data: the extended fixture derives from micro,
and both informed the semantic support floor. Extended includes known wrong-hit
and no-answer regressions; do not use it as independent holdout evidence.

```bash
# Dependency-light fake quality and latency
python3 -m benchmarks.run_benchmarks --n 500 --report /tmp/bench-fake.json

# Real FastEmbed quality and separate fake and real latency arms
python3 -m benchmarks.run_benchmarks --n 500 --engine real --latency-engine both --report /tmp/bench-real.json

# Existing calibration fixture, explicitly selected
python3 -m benchmarks.run_benchmarks --gold-set benchmarks/gold_extended.jsonl --report /tmp/bench-calibration.json
```

The real arm requires FastEmbed and its configured model, potentially including
a model download. `--engine fake|real` chooses the gold engine;
`--latency-engine fake|real|both` chooses independent latency stores. Fake is a
deterministic bag-of-words engine and must never be described as model latency.
Each query/strategy scenario records its first call, ten warmups, and 100 warm
measurements. Linear interpolation is used for p50 and p95. Initialization and
first ingest are separately timed: the first ingest includes lazy model load.
The first scenario call is after ingest, not a fresh-process model cold start.
OS and model caches are not cleared, and a `both` run shares the process.

Reports include model, engine, thread count, synthetic seed, fixture metadata
and SHA-256, effective benchmark switches, runtime versions, and git revision.
The revision is HEAD and does not identify uncommitted changes. Fixture dates
are rebased relative to the newest timestamp while preserving intervals; the
original anchor is recorded.

### Quality and resource cost

`quality.cost` accompanies all quality fields. Construction wall time includes
engine/client initialization and fixture ingestion; query wall time sums every
gold recall call. `wall_ms_per_correct_answer` divides their sum by the number
of answer-bearing cases returning all relevant rows, no irrelevant rows, and
status `ok`. No-answer cases contribute query cost but not to that denominator.
This local wall-time resource measurement is not a monetary estimate. A
zero-correct run has `null` cost per answer, and its quality is not quotable as
a cost-associated result. USD cost and provider usage are `null` when not
available, never zero. Quality without the associated cost or an explicit
unknown must not be quoted. Recall, precision, wrong hits and abstention
measure relevance separately from `source_grounded_rate`, which measures only
stored-source grounding.

The current runner uses `NoopEnricher` and does not capture provider usage.
The report reserves `quality.cost.provider_usage`, `construction_usd`,
`query_usd`, and `usd_per_correct_answer` as nullable fields for future
integration. Any integration must aggregate provider-reported construction and
query usage separately and apply explicitly configured prices, without retaining
prompt or memory content. Missing usage or pricing must remain unknown.

Historical artifacts in [`baselines/`](baselines/README.md) predate this cost
protocol; their quality numbers are not quotable without measured associated
cost. See [RESULTS.md](RESULTS.md) for the current reporting status.

The separate `hermes_provider_bench.py` is a resource/latency comparison, not a
matched accuracy comparison with Hindsight or another provider.
