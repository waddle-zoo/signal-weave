# Live enterprise comparison — 2026-10-04

Status: the current Jev core passes the synthetic enterprise acceptance gate on
this branch. This is strong product evidence, not production or universal
accuracy proof.

## Question

Does a human-authored SignalWeave card plus live Jev produce a better recurring
analysis decision than sending the same card, source bundle, and task to a
plain GPT Luna agent?

The product claim tested here is narrow: SignalWeave should apply an explicit
business rule across heterogeneous evidence, preserve the evidence needed to
explain the result, fail closed when an automatic action is not supported, and
do so faster than a general-purpose agent. It is not a claim that Jev invents
missing business context.

## Fair cross-enterprise trial

The live comparison used 60 held-out cases:

- six fictional enterprises with different operating shapes;
- twelve workflows spanning growth, fulfillment, payments, retention, product,
  platform, logistics, care, finance, manufacturing, and supply chain;
- five states per workflow: material action, expected change, ambiguous state,
  trust failure, and urgent operational risk;
- 36 source adapters and seven or eight normalized sources per case, including
  unrelated decoys;
- the same human-authored card and source bundle for Jev and Luna;
- hidden expected labels kept outside every provider prompt; and
- live `jev-latest` and live `gpt-5.6-luna` calls, with delivery disabled.

The three measured arms were:

1. `jev`: SignalWeave's core typed Jev decision and evidence bundle;
2. `llm-raw`: direct Luna using the same card and sources; and
3. `llm-signalweave`: optional diagnostic composition where Luna receives the
   Jev bundle and makes a second decision.

Only the first arm is the product promotion gate. The third arm is retained to
show that a downstream agent can reintroduce unsafe behavior; SignalWeave does
not own or authorize that agent's final action.

### Result

| Measure | Jev core | Direct Luna | Luna + Jev bundle |
| --- | ---: | ---: | ---: |
| Exact outcomes | **60/60 (100.0%)** | 46/60 (76.7%) | 51/60 (85.0%) |
| Evidence recall | **100.0%** | 92.8% | 95.9% |
| Unsafe automatic actions | **0** | 4 | 4 |
| Provider errors | 0 | 0 | 0 |
| Median latency | **656.5 ms** | 2,978.2 ms | 3,703.2 ms |
| P95 latency | **959.8 ms** | 4,554.9 ms | 4,892.5 ms |
| Estimated provider cost | **$0.0811** | $0.0823 | $0.1755 |

Jev was approximately 4.5× faster at the median and 4.7× faster at P95 than
direct Luna in this run. The Jev cost estimate was roughly 1.5% lower than
direct Luna. These are provider-usage estimates, not invoices; the meaningful
result is the combination of exactness, complete evidence, and zero unsafe
core actions.

The independent reviewer returned `PROMOTE`: protocol checks passed and Jev
core unsafe actions were zero. It emitted warnings for the two diagnostic Luna
arms, as intended.

## Dashboard-scale retrieval trial

The retrieval trial used six noisy Superset-shaped dashboards, 1,000 chart
descriptors per dashboard, two repeats (12 cases total), a bounded candidate
pool of 40, and a selection cap of eight charts. Jev selected candidates from
catalog metadata, then SignalWeave evaluated only the selected snapshots.

| Measure | Jev card-guided | Lexical selection + Jev | Gold selection + Jev |
| --- | ---: | ---: | ---: |
| Retrieval precision | **100.0%** | 45.8% | 100.0% |
| Retrieval recall | **100.0%** | 100.0% | 100.0% |
| Decision F1 | **100.0%** | 84.9% | 100.0% |
| Role accuracy | 95.8% | 95.8% | 95.8% |
| Driver recall | **100.0%** | 100.0% | 100.0% |
| Outcome accuracy | **100.0%** | 100.0% | 100.0% |

The gold arm is important: it isolates final decision quality from retrieval.
The first run failed that arm at 50% because the old fixture cards implicitly
treated explanatory watch items as mandatory delivery prerequisites. That was
a benchmark/card-contract defect, not a retrieval win. After making advisory
slots explicit and publishing fresh/stale/comparable metadata, the repeat-aware
review passed with no findings.

## What the repair taught us

Two failures were investigated rather than hidden:

- A growth case had perfect selected evidence but was downgraded because
  “name the strongest related signals” was implicitly required. The corrected
  card marks narrative questions and report-quality checks advisory; policy and
  source-quality gates remain enforced.
- A product-adoption case oscillated around the 0.70 action floor because its
  owner plan said “no planned change” only in prose. The adapter now exposes
  `owner_change_status=unplanned` and `planned_change=false`; Jev's prompt treats
  those as typed source-owned context. Five live repeats then produced `notify`
  at 0.79–0.88 support. The urgent logistics case produced `escalate` in eight
  of eight repeats after source-quality checks were separated from narrative
  watch classification.

This is the core onboarding lesson: cards remain free-form, but the connected
systems must publish the small semantic facts that the owner's rule depends on
—especially risk direction, materiality, quality, and planned-change state.
Jev applies those facts; it does not invent them.

## What this proves

On these live-provider, held-out simulations, SignalWeave provides a measurable
layer of value beyond raw Luna prompting:

- semantic candidate selection over a noisy chart catalog rather than sending
  every chart to an agent;
- typed evidence roles and complete source recall for the final bundle;
- consistent application of owner-defined ignore, investigate, notify,
  escalate, and trust-failure policy;
- fail-closed behavior when support is below the card's action threshold; and
- materially lower decision latency with slightly lower estimated Jev usage
  cost in the core comparison.

## What this does not prove

The fixtures are synthetic and the source snapshots are normalized. The trial
does not execute real Superset, Looker, Hex, Trino, warehouse, incident, or
ownership queries, and it does not measure warehouse bytes or billing. The
retrieval trial tests a 1,000-entry catalog adapter, not arbitrary enterprise
catalog recall or raw chart pixels. The Luna baseline is one model and one
prompt, not every possible agent architecture. Expected outcomes are evaluator
labels, not real operator labels.

Therefore this is not authorization for unattended production delivery. The
next proof gate is one real operating team in shadow mode: historical,
time-split source snapshots; owner-labeled outcomes and recipients; connector
query telemetry; useful/noisy/incomplete feedback; and a held-out period that
is never used to tune the card.

## Reproduction

The raw reports used for this result were retained in `/private/tmp` during the
run. Their SHA-256 hashes are:

```text
d136dfb6613e4874f2eeb980588b0d7829d80ffb12bce1c148addfb13da6a6e6  everything-final-20261004-v3.json
0c962b3a06cee5838cafa52328841e89efae9f490cfcdd0190e180f179ae6fdb  everything-final-20261004-v3-review.json
997c4599f707d8dd8227ddeb6cac6d246e38b34755d6fdb4e1b4a230f3dce7ba  card-guided-current-20261004-v3-repeat2.json
255807e78499d09ed3e5cdfaccb0361a00f37658ac0db2a1d02554fc0e3b8c21  card-guided-current-20261004-v3-repeat2-review.json
```

From the repository root, with real local secrets supplied out of band:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. .venv/bin/python evaluations/everything_tracking_llm_benchmark.py \
  --dotenv /absolute/path/to/hyperset/.env \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --model gpt-5.6-luna --repeats 1 --concurrency 4 \
  --output /tmp/everything-final.json

PYTHONPATH=src:. .venv/bin/python \
  evaluations/everything_tracking_llm_adversarial_review.py \
  --report /tmp/everything-final.json \
  --config evaluations/data/everything-tracking-scenarios.json

TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. .venv/bin/python evaluations/card_guided_retrieval_benchmark.py \
  --typesafe-key-file /absolute/path/to/apikey_typesafe --repeats 2 \
  --output /tmp/card-guided.json

PYTHONPATH=src:. .venv/bin/python \
  evaluations/card_guided_retrieval_adversarial_review.py \
  /tmp/card-guided.json
```
