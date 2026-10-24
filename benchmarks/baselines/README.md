# Recorded baselines

Reproducible gold-set runs. Each file is one `--engine real` evaluation, kept so
a later release can be compared against a matched environment instead of a
historical number quoted out of context.

| File | Fixture | Engine | recall@10 | abstention | wrong-hit | leakage |
|---|---|---|---:|---:|---:|---:|
| `gold-real-v1.json` | `gold_micro.jsonl` (`3646de58…`) | `BAAI/bge-small-en-v1.5` | 0.90 | 1.00 | 0.10 | 0 |

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
- `gold-real-v1.json` still contains one wrong hit: `paraphrase_deploy` returns
  the off-topic docs URL as its third row. That is the graph-expansion defect
  tracked separately; the calibration change did not introduce it, it stopped
  masking it by zeroing the row's semantic score.

## Historical numbers

`benchmarks/RESULTS.md` holds older pipeline-smoke measurements. They were
produced on a different fixture, engine and date and must stay labelled
historical. Never present them as a current release baseline.
