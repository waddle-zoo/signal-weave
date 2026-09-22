# Northstar real-row shadow trial

This is the closest current proof to a company-shaped deployment. It replays
real Northstar seed-row distributions from the local Superset warehouse through
the same six monitoring cases and compares three arms:

- SignalWeave + Jev;
- a deliberately explicit fixed-threshold comparator; and
- an embeddings-plus-reasoning control.

Every arm receives the same normalized observations and free-form card. The
expected outcomes are a reviewable human rubric over counterfactual monitoring
days; they are not independent production operator labels.

## Recorded result

The replay used six cases: no change, modest movement, an isolated channel
movement, a corroborated decline, conflicting sources, and an unavailable
source.

| Arm | Correct | Accuracy | False notify | Missed notify | Median latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| SignalWeave + Jev | 4 / 6 | 66.7% | 0 | 0 | 496 ms |
| Fixed threshold | 6 / 6 | 100.0% | 0 | 0 | 0.34 ms |
| Embeddings + reasoning | 1 / 6 | 16.7% | 0 | 1 | unavailable |

Jev used six requests, 95,325 input tokens, and 1,020 output tokens. The source
validation path reached the local Superset instance, confirmed the executive
dashboard metadata, and observed the expected dashboard data.

## What this proves

- The Jev path can process messy, cross-source monitoring evidence over real
  local row distributions.
- It did not produce a false notification or missed notification in this
  replay.
- It handled the unavailable-source case as `insufficient_data`.
- The embeddings control was not a useful replacement for the typed decision
  path in this fixture.

## What it does not prove

The fixed comparator winning 6/6 is important: SignalWeave should not replace a
simple, well-calibrated rule when the business rule is genuinely simple. Jev's
two false `investigate` routes on no-change and modest-movement cases show a
calibration gap, not a reason to hide the baseline.

This is therefore shadow evidence, not an autonomous-delivery recommendation.
The next promotion gate needs time-split snapshots and independent labels from
the operating team, plus query latency/bytes/cache telemetry and human feedback
on whether an evidence bundle was useful, noisy, late, or incomplete.

Reproduce with the evaluation-only harness:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_shadow_trial \
  --seed-dir /path/to/northstar/warehouse/init \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --skip-openai \
  --output artifacts/northstar-shadow-trial.json
```

The generated JSON and Markdown remain ignored artifacts so credentials and
local warehouse paths cannot enter Git.
