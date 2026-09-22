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

The Jev arm receives the same human-authored free-form card and normalized
source bundle as the movement-only baseline. Push cards now require a
`decision_guidance` paragraph describing the business rule in English; the
fixture names the primary, corroborating, diagnostic, and trust sources for
each workflow. The hidden expected outcome is held by the evaluator and is not
sent to Jev.

The baseline represents a common current state: alert on a large movement,
escalate on a very large movement, and otherwise ignore. It is not a named
general-purpose agent.

## Results

| Measure | Movement-only | SignalWeave + Jev |
| --- | ---: | ---: |
| Exact outcomes | 48/120 (40.0%) | 104/120 (86.7%) |
| Unsafe automatic actions | 48 | 0 |
| Required evidence recall | 0.0% | 100.0% |
| Median latency | 0.01 ms | 962 ms |
| p95 latency | 0.01 ms | 1,182 ms |

Paired comparison:

- Jev improved the exact outcome on 56 cases and was worse on 0.
- Jev removed an unsafe automatic action on all 48 movement-only failures.
- Jev preserved all labeled required sources in the returned evidence bundle.
- The remaining Jev misses were conservative `investigate` fallbacks on
  material-action cases; no Jev notification or escalation was unsafe.

By state, Jev was exact on ambiguous state, expected change, trust failure, and
urgent operational risk (**100%** each). It was conservative on material action
(**33.3%** exact), which is the current calibration gap: the card's action
threshold held uncertain notifications for investigation.

## Adversarial review

The independent reviewer is
[`evaluations/everything_tracking_adversarial_review.py`](../evaluations/everything_tracking_adversarial_review.py).
It independently checks:

- one result per case and reproducible aggregate metrics;
- allowed outcomes and evidence-source scope;
- unsafe automatic actions against the hidden oracle;
- enterprise, domain, adapter, and decoy coverage; and
- that expected labels were not sent to Jev.

The earlier pre-policy repeated run produced:

```text
scenario_count: 120
reviewer: everything-tracking-adversarial
result: FAIL
errors: unsafe Jev automatic actions
```

The reviewer is intentionally strict. The policy-bound Jev-only replay now has
zero unsafe Jev actions, but this should still be treated as shadow-evaluation
evidence until owner-labeled, time-split enterprise data is available.

The independent reviewer passed the policy-bound replay:

```text
scenario_count: 120
reviewer: everything-tracking-adversarial
result: PASS
findings: []
```

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

## Mass-chart retrieval boundary

This trial starts after a bounded source bundle has been selected. It does not
claim that Jev should receive thousands of raw chart observations in one
request. The scalable path is:

1. an adapter-owned catalog or knowledge-graph search finds candidate chart and
   source descriptors using the card's English goal and explicit relationships;
2. Jev ranks that bounded candidate set against the card's decision guidance;
3. adapters materialize only the selected charts, queries, or follow-up sources;
4. Jev evaluates the returned evidence and produces the typed insight bundle.

This keeps retrieval permission-aware and query-cost-aware while reserving Jev
for the semantic extraction and decision work. A raw “100 charts into Jev”
benchmark is a payload-limit test, not evidence for this architecture, and is
not used as SignalWeave product evidence.

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
