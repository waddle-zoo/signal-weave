# Card-guided retrieval trial — 2026-09-29

This is the current live Jev evidence for the 1,000-chart dashboard-scale
slice. It is intentionally separate from the generalized readiness trial: the
purpose here is to test whether SignalWeave can retrieve the right chart set
and turn a human-authored card into a safe outcome plus an inspectable evidence
bundle.

The first run below intentionally failed the evidence-role gate because the
cards left several role distinctions implicit. After the cards explicitly named
their focal, corroborating, diagnostic, quality, and contradictory evidence,
the rerun passed at 95.8% promoted role accuracy and 100% driver recall. The
separate owner-labeled holdout in
[`card-guided-owner-holdout-trial-2026-09-30.md`](card-guided-owner-holdout-trial-2026-09-30.md)
passes the same gate on six new cases.

Run it with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  .venv/bin/python evaluations/card_guided_retrieval_benchmark.py \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --limit 6 --output /tmp/card-guided-retrieval.json

.venv/bin/python evaluations/card_guided_retrieval_adversarial_review.py \
  /tmp/card-guided-retrieval.json
```

## Result

The live run used Jev for retrieval and final judgments, with lexical-selection
and gold-selection controls using the same Jev decision stage. Each case had
1,000 synthetic chart entries, a bounded 40-candidate pool, and six different
operating situations: growth, fulfillment, rollout noise, payment data trust,
platform incident response, and normal dashboard noise.

| Measure | Jev card-guided | Lexical selection + Jev | Gold selection + Jev |
| --- | ---: | ---: | ---: |
| Retrieval precision | 100% | 45.8% | 100% |
| Retrieval recall | 100% | 100% | 100% |
| Outcome accuracy | 100% | 100% | 100% |
| Promoted evidence-role accuracy | 54.2% | 37.5% | 37.5% |
| Suggested evidence-role accuracy | 62.5% | 62.5% | 58.3% |
| Promoted role coverage | 87.5% | 68.8% | 62.5% |
| Promoted driver recall | 83.3% | 50.0% | 33.3% |
| Suggested driver recall | 83.3% | 66.7% | 50.0% |
| Median end-to-end latency | 1,957 ms | 1,119 ms | 999 ms |
| Jev requests | 30 | 18 | 18 |
| Estimated TypeSafe cost | $0.0236 | $0.0156 | $0.0113 |

The result is strong evidence for the bounded retrieval and policy-execution
path. It is not proof that SignalWeave can state the causal reason for every
business movement. The advisory evidence-role threshold is 0.50, while action
and watch/question thresholds remain 0.70. Jev therefore exposes more useful
weighted leads without making those leads safe automatic actions.

The no-alert case was fixed to include normal observations. It now evaluates
normal evidence and returns `ignore`; it no longer passes by sending an empty
source set and testing `insufficient_data` instead.

## Adversarial decision

The reviewer passes the following:

- live Jev path, not a local heuristic or fixture;
- six cases at 1,000 chart entries each;
- bounded retrieval precision and recall;
- exact outcome routing, including `ignore`, `notify`, `investigate`, and
  `escalate`; and
- per-observation findings present in the report.

It deliberately fails the current run on:

- promoted evidence-role accuracy below 80%; and

That is the correct current status. The core route and primary-driver recall are
strong on this synthetic slice, but full causal/explanatory role quality still
needs independent owner labels or a shadow trial. `suggested_role` is useful
evidence for an agent or human to review; it is not a causal claim and should
not be marketed as one.

The scenario cards now state explicit owner policy—thresholds, expected rollout
effects, stale-source handling, and which signals are diagnostic. The four-case
policy experiment reached 100% outcome accuracy in all three arms. This is
evidence that onboarding quality matters: Jev executes clear human context well,
but should not be expected to invent a missing decision boundary.

## Code and process review

The adversarial code review found one real regression in the evidence-plan
change: a partial-source safety return had become unreachable below an earlier
evidence-plan return. The dead branch and unused plumbing were removed, and a
regression test now proves that blocking partial quality takes precedence over
an incomplete follow-up plan. The full suite is **559 passed, 2 skipped**;
Ruff and `git diff --check` also pass.

The process reviewer now independently reloads the checked-in scenario catalog,
verifies every reported expected outcome and gold label against it, and
recomputes reported aggregate metrics from per-case rows. On the current report,
those integrity checks pass. This still does not make the synthetic scenario
labels equivalent to an operator-labeled production replay.

## Next proof gate

Replay this contract with a real team's labeled historical runs. For each
observation, have an owner label the accepted role (`driver`, `corroborates`,
`diagnostic`, `contradicts`, `quality`, or `unknown`) and whether the evidence
bundle was useful, incomplete, late, noisy, or unsafe. Keep the labels outside
the Jev payload and split them by time. Do not promote the explanatory claim
until that review clears the same role-accuracy and driver-recall thresholds.
