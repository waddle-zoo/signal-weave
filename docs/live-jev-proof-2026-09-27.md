# Live Jev proof — 2026-09-27

This is the first current-branch proof that SignalWeave is using the real
TypeSafe Jev service rather than a synthetic transport. It is bounded shadow
evidence, not a claim of universal business correctness or autonomous
production delivery.

## Results

| Trial | Live scope | Result |
| --- | --- | --- |
| Onboarding retrieval | 8 deliberately different enterprise cases across SaaS, retail, fintech, marketplace, logistics, and sparse catalogs | 8/8 required-candidate recall; 8/8 safe review-preserving outcomes; 6/8 exact recommended sets; 0 tenant leaks; 0 governed-role disagreements |
| Everything tracking | 6 company shapes, 12 workflows, 60 cases, 36 source adapters, 7–8 sources per case, two unrelated decoys | 53/60 exact outcomes (88.3%); 100% required-evidence recall; 0 unsafe automatic actions; 24 unsafe baseline actions; median Jev latency 532 ms; p95 662 ms |
| Northstar local Superset runtime | Production `build_runtime()` and `live_card_check.py` against dashboard 1 | 10 charts; 25 normalized observations; 36 evidence items; 2 live Jev requests; 2.51 s end-to-end; typed result probabilities `ignore=0.01`, `investigate=0.54`, `notify=0.45`; delivery disabled |
| Northstar production MCP lifecycle | Live discovery → free-form onboarding → persisted review → approval → evaluation → idempotent replay through the registered MCP tools | 1 approved card; `ready_for_approval` review; 1 live Jev request; 25 observations; 36 evidence items; 25,765 Jev input tokens; `notify` at 0.72; 1 receipt after replay; 0 duplicate provider or Jev calls on replay; delivery disabled |
| Northstar real-row replay, original card | Six counterfactual cases built from local Northstar row distributions and validated against the live local Superset dashboard | 5/6 correct; 1 false notify on a modest -6% movement; 0 missed notify; source-unavailable case failed safe |
| Northstar real-row replay, clarified card | Same six cases and evidence; added an explicit owner policy: ignore below 10%, notify only after material corroboration, otherwise investigate | 6/6 correct; 0 false notify; 0 missed notify |

The 60-case run was independently recomputed by
`evaluations/everything_tracking_adversarial_review.py`; it passed with no
findings. Expected labels were held outside the Jev request.

## What this proves

- The production Jev adapter is making real TypeSafe requests and returning
  typed probabilities, not merely returning a Jev-shaped fixture response.
- SignalWeave can pass a real local Superset dashboard through the production
  source adapter, normalize heterogeneous chart evidence, and use live Jev to
  produce a bounded decision.
- Across varied operating contexts, Jev preserved the required evidence and
  avoided automatic action when the evidence was ambiguous, expected, or
  untrusted.
- Human-authored context materially changes the result. The first Northstar
  card did not define a numeric boundary for ordinary movement; the live run
  exposed a false notify. Adding the explicit owner policy corrected that case
  without changing the runtime or source data.
- The production lifecycle now keeps onboarding and audit state out of the
  Jev execution payload. Before this fix, an approved card carrying its
  persisted candidate catalog and review history could exceed the TypeSafe
  request budget. The runtime now sends only execution-relevant card context;
  the live MCP lifecycle completed without that failure, while the review and
  approval records remain persisted for governance.

This is the intended division of responsibility: humans define what matters
and what outcomes mean; SignalWeave retrieves and packages the evidence; Jev
provides the typed semantic judgment; code owns authorization, data-quality
gates, thresholds, and delivery safety.

## What remains unproven

- These are local fixtures and a local Northstar Superset instance, not a
  customer-authorized hosted Preset, Hex, or Looker tenant.
- The expected Northstar outcomes are a reviewable rubric over counterfactual
  periods, not independent operating-team labels.
- The 60-case corpus is broad coverage evidence, not a production load test or
  a statistically sufficient accuracy estimate.
- No Slack, email, incident, or other external destination was contacted.
- Live Jev billing, rate limits, and customer-specific semantic correctness
  still require an authorized pilot with operator labels.
- The live MCP lifecycle used a local Northstar Superset and shadow delivery;
  it proves the integration contract and bounded decision path, not that every
  customer-authored card will be semantically correct without operator review.

## Reproduction

Keep the TypeSafe key outside the repository and run the bounded live trials:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  .venv/bin/python -m evaluations.onboarding_contract_trial \
  --evaluator live --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --limit 8 --format markdown

TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  .venv/bin/python -m evaluations.everything_tracking_trial \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --max-cases 60 --repeats 1 --concurrency 8 \
  --output /tmp/signalweave-live-everything-tracking.json

.venv/bin/python evaluations/everything_tracking_adversarial_review.py \
  --report /tmp/signalweave-live-everything-tracking.json
```

The local Superset runtime proof additionally requires the Northstar fixture
and its running Superset service. The delivery-disabled result is the required
promotion boundary until a real operator labels the output.
