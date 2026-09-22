# Everything-tracking: Jev versus an LLM control

This is the comparative evidence report for the broader “everything tracking”
trial. It tests whether the required Jev decision layer adds value when an
agent must interpret a human-authored operating concern across messy,
heterogeneous evidence.

The product path is Jev-first. The LLM-only arm exists only as a control group
to answer “what does Jev add?” It is not a supported SignalWeave deployment
mode. The optional `llm-signalweave` arm tests an agent consuming a typed Jev
preflight and then making a final response; it still depends on Jev and is not
the core deterministic path.

## Protocol

Each run used the same 120 cases:

- six fictional enterprises and twelve outcome-level workflows;
- five states per workflow: material action, expected change, ambiguous state,
  trust failure, and urgent operational risk;
- 36 source adapters and seven or eight normalized sources per case;
- two repeats of every case;
- live Jev calls and live OpenAI Responses calls using `gpt-5.6-luna`;
- the same card and source bundle for all arms; and
- hidden expected labels kept outside provider input.

The independent reviewer recomputes exactness, evidence recall, provenance,
unsafe automatic actions, input digests, provider errors, and coverage from the
case fixture. It intentionally fails a run if the Jev path emits an unsafe
automatic action.

## Final live run

The final corrected run produced:

| Measure | LLM-only control | Jev core | Agent + Jev preflight |
| --- | ---: | ---: | ---: |
| Exact outcomes | 82/120 (68.3%) | 83/120 (69.2%) | 77/120 (64.2%) |
| Unsafe automatic actions | 16 | 13 | 11 |
| Required evidence recall | 98.7% | 100.0% | 98.2% |
| Provider errors | 0 | 0 | 2 |
| Median latency | 4,992 ms | 927 ms | 6,394 ms |
| P95 latency | 8,403 ms | 1,093 ms | 10,497 ms |

The Jev core was about 4.8× faster at the median than the LLM-only control in
this run and returned complete required evidence. That is a meaningful
decision-loop latency result. It is not a claim that Jev is universally more
accurate than an LLM.

## Stability across three live runs

The same protocol was run three times to expose provider stochasticity. These
are repeated evaluations of the same fixture, not three independent enterprise
datasets.

| Arm | Exact outcomes | Unsafe automatic actions |
| --- | ---: | ---: |
| LLM-only control | 238/360 (66.1%) | 56 |
| Jev core | 247/360 (68.6%) | 38 |
| Agent + Jev preflight | 230/360 (63.9%) | 38 |

The safety reduction versus the LLM-only control reproduced across the three
runs: Jev produced 18 fewer unsafe actions and the agent-with-Jev arm produced
18 fewer. The exactness improvement did not establish a durable advantage:
Jev was only 2.5 percentage points higher than the control in aggregate, while
the optional agent-with-Jev arm was lower. The correct conclusion is that Jev
shows a promising safety and latency effect, not a proven accuracy win.

## Card-context counterfactual

The unsafe-action count must not be interpreted as “Jev alone caused every
failure.” A Jev judgment is only as good as the human meaning encoded in the
card and evidence. In the fixture, the ambiguous cards asked whether a change
was meaningful but did not say “missing corroboration is investigate-only.” The
expected-change cards included a planning source, but did not say “planned
movement must suppress delivery.”

The Jev-only card-clarity trial holds the sources and hidden labels constant and
adds only those two explicit human boundaries to the card. Over 48 cases:

| Card version | Exact outcomes | Unsafe automatic actions | Median latency |
| --- | ---: | ---: | ---: |
| Original free-form card | 19/48 (39.6%) | 12 | 912 ms |
| Clarified human card | 48/48 (100.0%) | 0 | 917 ms |

This is strong evidence that onboarding/context quality is a dominant failure
mode in these two classes. It is not a universal guarantee: the clarification
was a counterfactual human edit constructed from the fixture's owner intent.
The trial lives in
[`evaluations/everything_tracking_card_clarity_trial.py`](../evaluations/everything_tracking_card_clarity_trial.py).

It also reveals a runtime safety gap. One original ambiguous card produced a
`notify` result at 0.72 confidence while a question was `not_supported` at
0.17. The wrapper currently gates automatic action on aggregate confidence and
configured delivery, not on whether every action-critical question is
supported. That should be treated as a product hardening item, not hidden by
relabeling the card.

## Where the failures cluster

The Jev failures are not evenly distributed. In the final run, the remaining
unsafe Jev actions were concentrated in ambiguous and expected-change states.
That means the current gap is calibration around “material but not actionable”
and “large but expected,” not source preservation. Trust-failure handling and
evidence recall were strong in this fixture, but that is not enough to authorize
delivery.

The adversarial reviewer therefore returns:

```text
protocol_passed: false
promotion_ready: false
verdict: NO-GO FOR AUTONOMOUS DELIVERY
```

The right current operating mode is Jev-backed read-only or shadow evaluation,
with human approval for notification and escalation. The next improvement
should target outcome calibration and owner-labeled holdouts, not adding more
LLM prompt text.

## What this does and does not prove

It proves that a Jev-backed decision layer can be evaluated against a realistic,
heterogeneous synthetic enterprise fixture with inspectable evidence, stable
input identity, live provider calls, and an independent safety gate. It shows
that Jev is substantially faster than the LLM control in this decision loop and
that unsafe-action reduction is a plausible value path. It also shows that
explicit human context can materially improve Jev outcomes without making the
decision loop slower.

It does not prove universal semantic correctness, catalog-scale retrieval
recall, lower query cost, or safe autonomous delivery. All arms receive a
prepared source bundle; discovery from a 100,000-resource enterprise catalog is
a separate retrieval evaluation. The labels are synthetic and must be replaced
with owner-labeled historical or shadow-run outcomes before production rollout.

## Reproduce

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.everything_tracking_llm_benchmark \
  --dotenv /absolute/path/to/hyperset/.env \
  --repeats 2 \
  --concurrency 6 \
  --output artifacts/everything-tracking-llm-benchmark-final.json

PYTHONPATH=src:. \
.venv/bin/python -m evaluations.everything_tracking_llm_adversarial_review \
  --report artifacts/everything-tracking-llm-benchmark-final.json \
  --config evaluations/data/everything-tracking-scenarios.json
```

The reviewer is expected to exit nonzero until the Jev path has zero unsafe
automatic actions on the labeled holdout.
