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

The cards now include a human-authored `decision_guidance` paragraph. Each
workflow states, in plain English, which source is primary, which sources
corroborate or diagnose it, which source establishes trust, and what should be
ignored, investigated, notified, escalated, or treated as insufficient data.
This is the intended product boundary: onboarding supplies the business rule;
Jev applies it repeatedly over the evidence.

The independent reviewer recomputes exactness, evidence recall, provenance,
unsafe automatic actions, input digests, provider errors, and coverage from the
case fixture. It intentionally fails a run if the Jev path emits an unsafe
automatic action.

## Final policy-bound live run

The final run used those policy-bearing cards and produced:

| Measure | LLM-only control | Jev core | Agent + Jev preflight |
| --- | ---: | ---: | ---: |
| Exact outcomes | 63/120 (52.5%) | 105/120 (87.5%) | 67/120 (55.8%) |
| Unsafe automatic actions | 14 | 0 | 11 |
| Required evidence recall | 90.3% | 100.0% | 92.6% |
| Provider errors | 0 | 0 | 0 |
| Median latency | 3,383 ms | 953 ms | 4,307 ms |
| P95 latency | 5,798 ms | 1,119 ms | 7,627 ms |

Jev was 3.6× faster at the median and 5.2× faster at P95 than the LLM-only
control in this run. More importantly, Jev returned complete required evidence
and made zero unsafe automatic actions on this holdout. The exactness gap was
mostly deliberate safety fallback: Jev returned `investigate` when a `notify`
or `escalate` judgment did not clear the card's 0.70 action-confidence
threshold. It is not a claim that Jev is universally more accurate than an
LLM, or that this synthetic holdout is production proof.

## What changed from the earlier run

The earlier comparison used cards with generic watch items and a missing
decision policy. It mixed two questions: whether Jev could apply a rule and
whether Jev could invent the rule. That was the wrong product test. The
corrected cards make the rule explicit before the benchmark starts.

The remaining Jev misses cluster in `material_action`: 15 of 24 cases were
conservatively held for investigation because the action-confidence threshold
was not reached. Jev was exact on all 24 ambiguous, 24 expected-change, 24
trust-failure, and 24 urgent-risk cases. This is the useful enterprise trade:
the system can fail closed instead of turning uncertainty into a push
notification. Threshold tuning remains card-owner policy, not hidden model
behavior.

The optional mediated arm is intentionally not the product path. It demonstrates
that handing a Jev preflight to a frontier-model agent can still reintroduce
unsafe behavior: it produced 11 unsafe actions and was slower than either
component alone. SignalWeave's core value is the Jev-backed typed decision and
evidence bundle that an external agent may consume, not ownership of that
agent's final behavior.

## Card-context counterfactual

The unsafe-action count must not be interpreted as “Jev alone caused every
failure.” A Jev judgment is only as good as the human meaning encoded in the
card and evidence. The product now blocks a push card during onboarding when
the owner has not supplied decision guidance. The guidance remains free-form;
it is not a new workflow DSL.

The Jev-only card-clarity trial holds the sources and hidden labels constant and
adds only those two explicit human boundaries to the card. Over 48 cases:

| Card version | Exact outcomes | Unsafe automatic actions | Median latency |
| --- | ---: | ---: | ---: |
| Original card with broad default guidance | 29/48 (60.4%) | 0 | 925 ms |
| Clarified human card | 48/48 (100.0%) | 0 | 926 ms |

This is strong evidence that onboarding/context quality is a dominant failure
mode in these two classes. It is not a universal guarantee: the clarification
was a counterfactual human edit constructed from the fixture's owner intent.
The trial lives in
[`evaluations/everything_tracking_card_clarity_trial.py`](../evaluations/everything_tracking_card_clarity_trial.py).

The clarification changes only human-authored watch and question boundaries;
latency remains flat. This is evidence for the onboarding contract: ask for the
decision boundary and the evidence relationship explicitly, then let Jev apply
it at scale. It is not evidence that Jev can recover an absent business rule.

## Where the failures cluster

The Jev path had no unsafe automatic actions in the final policy-bound run.
Its remaining gap is useful calibration around when a defined notification is
strong enough to cross the card's action threshold; the fallback is
`investigate`, not delivery. Trust-failure handling, evidence recall, expected
change suppression, and severe-risk escalation were exact in this fixture.

The adversarial reviewer therefore returns:

```text
protocol_passed: false
promotion_ready: false
verdict: NO-GO FOR AUTONOMOUS DELIVERY
```

The reviewer is intentionally whole-report strict and still returns NO-GO
because the non-product LLM control and mediated agent arm emitted unsafe
actions. The Jev core itself passed the run's safety and provenance checks, but
the right rollout is still Jev-backed shadow evaluation with owner-labeled
holdouts before enabling real notification and escalation.

## What this does and does not prove

It proves that a Jev-backed decision layer can be evaluated against a realistic,
heterogeneous synthetic enterprise fixture with inspectable evidence, stable
input identity, live provider calls, and an independent safety gate. It shows
that Jev can apply explicit English business rules across twelve workflows and
120 messy cases in roughly one second per decision, with complete evidence
recall and no unsafe automatic actions in this run. It also shows that explicit
human context can materially improve Jev outcomes without making the decision
loop slower.

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
  --output artifacts/everything-tracking-llm-benchmark-card-rules.json

PYTHONPATH=src:. \
.venv/bin/python -m evaluations.everything_tracking_llm_adversarial_review \
  --report artifacts/everything-tracking-llm-benchmark-card-rules.json \
  --config evaluations/data/everything-tracking-scenarios.json
```

The reviewer is expected to exit nonzero while any arm in the comparison emits
unsafe automatic actions. Inspect the Jev core row separately: this run had
zero unsafe Jev actions, but the whole-report verdict remains strict because
the control and mediated arms are not safe autonomous delivery paths.
