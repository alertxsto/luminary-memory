# Recorded baselines

Reproducible gold-set runs. Each file is one `--engine real` evaluation, kept so
a later release can be compared against a matched environment instead of a
historical number quoted out of context.

| File | Fixture | Engine | floor | recall@10 | abstention | wrong-hit | leakage |
|---|---|---|---:|---:|---:|---:|---:|
| `gold-real-v1.json` | `gold_micro.jsonl` (`3646de58…`) | `BAAI/bge-small-en-v1.5` | 0.70 | 0.90 | 1.00 | 0.10 | 0 |
| `gold-real-v2.json` | `gold_micro.jsonl` (`3646de58…`) | `BAAI/bge-small-en-v1.5` | 0.74 | 0.70 | 1.00 | 0.00 | 0 |
| `gold-real-v3.json` | `gold_micro.jsonl` (`3646de58…`) | `BAAI/bge-small-en-v1.5` | **0.635** | **0.85** | 1.00 | **0.00** | 0 |

`v1` and `v2` are kept for comparison only: `v1` used a 0.70 floor that returned
a grounded but off-topic documentation URL on two answer-bearing cases, and
`v2` used 0.74 while expansion could still raise a candidate's score. `v3` is
the shipped configuration:
it scores every candidate against the question as asked, so expansion only
selects candidates, and the floor is the measured midpoint between the highest
confident wrong answer and the lowest correct answer.

## Reproduce

```bash
python -m benchmarks.run_benchmarks --n 50 --engine real --report /tmp/gold.json
```

## How to read these numbers

- Fixture timestamps are rebased at load time so the newest `observed_at` equals
  run time. Relative ages and validity windows are preserved, so the same commit
  scores the same on any date. `evaluation.evaluation_clock.anchor` records the
  original anchor.
- `wrong_hit_rate` counts answer-bearing cases that returned at least one
  irrelevant row, even when that row carries its own evidence quote.
  `source_grounded_rate` is only the share of returned rows with stored-source
  grounding; it is not accuracy.
- The latency block in a full report always comes from the deterministic fake
  engine so those figures stay comparable across releases. It is not a
  measurement of the real model.
- The derivation of the `v3` floor is in `benchmarks/README.md` and
  `docs/recall.md`.
- The floor sweep that chose `v2` is in `benchmarks/README.md`. 0.74 was the
  lowest value that stops the off-topic docs row from being returned on the
  exact and paraphrased deploy cases; 0.70 admitted it (cosine 0.7098) while
  still excluding the no-answer cases.

## Historical numbers

`benchmarks/RESULTS.md` holds older pipeline-smoke measurements. They were
produced on a different fixture, engine and date and must stay labelled
historical. Never present them as a current release baseline.
