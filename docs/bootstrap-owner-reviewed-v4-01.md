# Independent-owner bootstrap trial v4-01

**The correction path failed its preregistered goal.** Independent review caught
one unnecessary evidence requirement, but native outcome and recipient-key
correctness remained 4/6. Final agent routing was 5/6 versus baseline 6/6.
This does not establish a comparative benefit or enterprise readiness.

The [frozen protocol](bootstrap-owner-reviewed-v4.md) ran once at
`b2210e5272cccb896d4b98fc9b20e9fc86573b7e`, seed 20261002, on the same two
known-failure development companies as v3-04. This is not a fresh holdout even
though the retained fixture split is named `holdout`. Fixtures and scoring were
unchanged; no edits or intermediate score inspection occurred during execution.

All 16 author/monitor episodes and six independent owner-review invocations
completed without retries, transport failures, budget censoring or missing usage.
Author/monitor: saved-login Codex Luna, low effort. Owner reviewer: independent
Luna, high effort, in both arms. Live Jev resolved to `jev-1.13.0`: 46 requests,
209,156 input and 8,895 output tokens. No real human approval or external delivery
occurred. Model approval is not policy proof.

## Measured results

| Endpoint | Luna + BI | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Setup complete | 2/2 | 2/2 |
| Monitoring complete | 6/6 | 6/6 |
| Frozen exact structured score | 5/6 | 4/6 |
| Final outcome AND recipient keys correct | 6/6 | 5/6 |
| Native outcome AND recipient keys correct | — | 4/6 |
| Owner-review attempts | 2 | 4 |
| Setup seconds, total | 116.48 | 375.00 |
| Monitoring seconds, total | 165.91 | 144.44 |
| Monitoring median seconds | 23.71 | 23.23 |
| Source reads | 21 | 35 |
| Tool calls, including owner reviews | 51 | 85 |
| Agent input + output tokens, including setup/review | 615,462 | 2,757,628 |
| Agent input + output tokens, monitoring only | 388,378 | 507,687 |
| Illustrative API-equivalent USD, all work | 0.05855 | 0.15748 |

Cached input is counted once in input totals. Prices are illustrative token-price
estimates, not measured Codex subscription charges. Every monitoring episode still
wakes Luna. Lower measured monitoring wall time does not establish a repeatable
speed advantage and does not offset the observed correctness/cost regression.

## What improved, and what did not

The helpdesk reviewer rejected making mix/within-segment analysis a prerequisite
for the owner's SLA alert. The author explicitly revised it to advisory and
obtained acceptance. Database authoring now preserves `investigate` rather than
rewriting it to `notify`, and includes an investigation route. Those are useful
observations, not isolated causal effects of review versus stochastic authoring.

The runtime still failed:

- **Helpdesk event:** Jev's outcome favors notify at .97, but the required question
  “Are there data gaps that make the result insufficient for action?” has .65
  answerability. The pending slot downgrades the result to investigate with no
  investigation recipient. The agent repairs it to notify. A correct final agent
  output is not a successful native route.
- **Database quiet:** Jev favors insufficient_data at .69, below the unchanged .70
  action threshold; code routes to investigate. The agent repairs this to ignore.
  The card's complete-coverage question/watch remains uncertain despite the
  populated cluster list. A list alone is not a universal completeness contract;
  the retained fixture does not define this distinction rigorously enough.
- **Database event:** Native investigate and recipient key match the frozen label.
  The agent changes this to insufficient_data/data operations because explicit
  complete-coverage confirmation is absent. The blind reviewer finds this adds
  a prerequisite not demanded by the public policy. Retain the failure and the
  source-contract ambiguity; do not assume it away or lower a threshold.

Three agent outcome changes comprise two repairs and one degradation. Both
missing-data conditions and the helpdesk quiet route were natively correct.
Approval reviews policy fidelity, not the empirical adequacy of selected sources.
That gap remains material even when the prose and outcome names are right.

## Additional audit limitation: keys are not delivery endpoints

The accepted database card stores bare team keys as `destination`, whereas the
public destination directory supplies `slack://` addresses. The frozen native
scorer checks recipient keys, not equality of actual destination strings.
Consequently its 4/6 result must **not** be advertised as four verified deliveries.
The model owner reviewer also missed this mismatch. The trace is preserved, not
retrospectively relabeled. This exact lookup belongs in a code-owned onboarding
check against the supplied directory, not another semantic model judgment.

The separate [post-run endpoint audit](evidence/bootstrap-owner-reviewed-v4-01/endpoint-audit.json)
finds only **2/6** native runs jointly match outcome, recipient keys and exact
configured endpoints. It is an additional diagnostic, not a substituted primary
endpoint or proof of actual delivery. The original 4/6 score remains unchanged.

## Blind narrative review

A fresh internal reviewer saw only public business evidence and anonymized final
outputs: [review](evidence/bootstrap-owner-reviewed-v4-01/review.md).
Baseline: 5 supported, 1 qualified. Treatment: 3 supported, 2 qualified,
1 unsupported. All 32 structured numeric claims reproduce the supplied arithmetic;
the two population-scoped zero-latency claims still lack population validation.
One treatment output also omits the owner's requested corrected-export next step.
No unsupported causal conclusion was found. This is one internal agent reviewer,
not external peer review or customer validation.

The frozen exact score retains earlier ambiguities about mandatory rollout
details and population-scoped arithmetic. They do not excuse the agent's added
coverage requirement, missing native route or incorrect endpoint strings.

## Retained evidence and next experiment

[Compact results](evidence/bootstrap-owner-reviewed-v4-01/results.json),
[blind packet](evidence/bootstrap-owner-reviewed-v4-01/blind-review.json),
[mapping](evidence/bootstrap-owner-reviewed-v4-01/review-key.json), and
[owner requests, decisions, cards and native results](evidence/bootstrap-owner-reviewed-v4-01/owner-review-and-native.json)
preserve the failure. Full local report SHA-256:
`738421956b6d4e7577bb8998c9d4dc743302d69922908a2d3788d754d35198bb`.
The results' pending-review field records export time; the separate review is complete.

Next: isolate the question-answerability predicate on a small paired live probe,
including explicitly negative answers, missing/conflicting evidence and scope
mismatches. The current Noul instruction asks whether an answer exists, but its
true criterion is the owner question itself. Test clearer aligned wording before
changing production. Keep original v4 cards, fixtures, scores and raw outputs.
Do not spend another full bootstrap trial merely to seek a favorable outcome.
