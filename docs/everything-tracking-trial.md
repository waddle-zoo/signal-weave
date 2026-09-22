# Everything-tracking business-value trial

Status: exploratory branch evidence. This is a live Jev replay over synthetic
enterprise scenarios, not a production reliability claim.

The companion LLM comparison is documented in
[`everything-tracking-llm-benchmark.md`](everything-tracking-llm-benchmark.md).
The LLM-only arm there is a control only; SignalWeave's product path requires
Jev.

The trial tests a broader claim than metric alerting:

> Given a human-authored operating concern and a messy bundle of connected
> evidence, can SignalWeave help an agent decide what matters, preserve the
> relevant evidence, and avoid unsupported action?

## Design

The repeated run contains 120 evaluations:

- six fictional enterprises with different operating shapes;
- twelve outcome-level workflows across growth, fulfillment, payments,
  retention, product, platform, logistics, care, finance, manufacturing, and
  supply chain;
- five states per workflow: material action, expected change, ambiguous state,
  trust failure, and urgent operational risk;
- 36 source adapters, including BI, CRM, incidents, support, deployments,
  quality checks, finance, inventory, and operational systems;
- seven or eight sources per case, including two unrelated decoys; and
- two repeats of every case to check repeat stability.

The Jev arm receives the same free-form card and normalized source bundle as the
movement-only baseline. The hidden expected outcome is held by the evaluator
and is not sent to Jev.

The baseline represents a common current state: alert on a large movement,
escalate on a very large movement, and otherwise ignore. It is not a named
general-purpose agent.

## Results

| Measure | Movement-only | SignalWeave + Jev |
| --- | ---: | ---: |
| Exact outcomes | 48/120 (40.0%) | 82/120 (68.3%) |
| Unsafe automatic actions | 48 | 13 |
| Required evidence recall | 0.0% | 100.0% |
| Median latency | 0.01 ms | 940 ms |
| p95 latency | 0.01 ms | 1,079 ms |

Paired comparison:

- Jev improved the exact outcome on 40 cases and was worse on 6.
- Jev removed an unsafe automatic action on 35 cases.
- Jev preserved all labeled required sources in the returned evidence bundle.
- The 13 remaining unsafe Jev actions were six ambiguous cases and seven
  expected-change cases. The adversarial reviewer therefore rejects autonomous
  delivery for this run.

By state, Jev was strongest on material action (**91.7%** exact) and trust
failure (**100%** exact). It was conservative on urgent risk (**75%** exact)
and unreliable at suppressing expected movement (**0%** exact). Ambiguous cases
were **75%** exact, but the remaining wrong notifications are safety failures.

## Adversarial review

The independent reviewer is
[`evaluations/everything_tracking_adversarial_review.py`](../evaluations/everything_tracking_adversarial_review.py).
It independently checks:

- one result per case and reproducible aggregate metrics;
- allowed outcomes and evidence-source scope;
- unsafe automatic actions against the hidden oracle;
- enterprise, domain, adapter, and decoy coverage; and
- that expected labels were not sent to Jev.

The repeated run produced:

```text
scenario_count: 120
reviewer: everything-tracking-adversarial
result: FAIL
errors: 13 unsafe Jev automatic actions
```

The reviewer is intentionally failing the run. A benchmark that only passes
when safety failures are reclassified as “conservative mistakes” is not useful
for an automation product.

The reviewer itself has mutation tests in
[`tests/test_everything_tracking_trial.py`](../tests/test_everything_tracking_trial.py)
for a mutated unsafe result and a consistent safe report.

## What this demonstrates

The useful signal is not Jev latency. The movement-only policy sees a large
number and produces an action even when the movement is expected or
contradictory. Jev uses the owner-defined purpose and the connected evidence to
reduce those unsupported actions while retaining a complete evidence bundle.

That is evidence for the core “everything tracking” direction: a high-level
operating concern can be evaluated across heterogeneous context instead of
being reduced to one dashboard threshold.

## What it does not demonstrate

The evidence recall number is deliberately narrow. Every case supplies the
card's source bundle up front, so it measures evidence preservation during
judgment—not discovery across a real enterprise catalog. Source observations
are generated normalized facts, and no production Superset, Looker, Hex,
Trino, incident, or CRM query executes in this trial.

The expected outcomes are synthetic labels. The trial does not establish that
the labels match a real operator's judgment, that the output is useful enough
to change behavior, or that query cost is reduced.

The next real-business gate is a shadow run from one operating team with real
source snapshots, owner-labeled outcomes, time-split replay, actual query
telemetry, and human feedback on useful versus noisy bundles. The current
result supports read-only shadow evaluation only; it does not support
automatic delivery.

## Reproduce

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.everything_tracking_trial \
  --repeats 2 \
  --concurrency 8 \
  --output artifacts/everything-tracking-trial-repeated.json

PYTHONPATH=src:. \
.venv/bin/python -m evaluations.everything_tracking_adversarial_review \
  --report artifacts/everything-tracking-trial-repeated.json \
  --config evaluations/data/everything-tracking-scenarios.json
```
