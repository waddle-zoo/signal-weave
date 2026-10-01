# Targeted bootstrap regression v3-03

The repaired workflow completes, but comparative benefit is still unproven.
Final routing is correct in all six treatment cases; native SignalWeave routing
is jointly correct in only three. The agent is still doing important repairs.

This follows the pre-run declaration in [the repair ledger](bootstrap-repair-ledger.md).
Known-failure companies Kindred Helpdesk and Cinder Database Cloud were selected
before dispatch, with all periods and both arms. This is retrospective
development, not a fresh holdout or a representative success estimate.

Frozen revision `7f2d73b174b4d8f77e7ae997d5dc6ed57c23ac4b`, production repair
`3387916154e8fb98f4dd981249d816e598b4a7b3`. Seed 20261002, unchanged v3 raw
contracts. Dataset digest
`bb559f8f482911af51d8649ea096fae08bc4244d9088f92f183751be917969b2`.
Both arms used Codex Luna low effort with saved login; treatment used live Jev,
observed `jev-1.13.0`. All 16 episodes completed; 29 of 60 permitted Jev attempts,
no provider failures, missing usage or budget censoring. No external delivery.

## Results

| Endpoint | Luna + BI | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Setup complete | 2/2 | 2/2 |
| Monitoring complete | 6/6 | 6/6 |
| Frozen exact structured score | 5/6 | 4/6 |
| Final outcome AND recipients correct | 6/6 | 6/6 |
| Native outcome AND recipients correct | — | 3/6 |
| Setup seconds, total | 56.26 | 175.53 |
| Monitoring seconds, total | 163.16 | 150.19 |
| Monitoring median seconds | 27.53 | 25.66 |
| Source reads | 21 | 31 |
| Tool calls | 47 | 64 |
| Agent input + output tokens, including setup | 476,999 | 1,470,835 |
| Agent input + output tokens, monitoring only | 331,419 | 523,974 |
| Illustrative API-equivalent USD | 0.03651 | 0.08984 |

Cached inputs are counted once within input totals. Dollar estimates are not
Codex subscription bills. Treatment's 7.9% lower monitoring wall time is offset
by more setup time, reads and tokens. Two known companies do not support a
population-level speed claim. The 29 Jev calls consumed 123,650 input and 5,084
output tokens. There is no isolated causal attribution to a particular repair.

## Remaining product defects

- **Helpdesk event:** correct analytical window and comparison key now produce
  the complete .90→.75 calculation. Jev outcome support is .99 notify, but two
  required watch items are unknown, so the code correctly requests investigation.
  The agent repairs the final notification. Quiet and missing-denominator native
  routes are correct. The card made explanatory mix analysis and a missingness
  condition mandatory; item ambiguity still prevents unattended operation.
- **Cloud event:** policy text requests investigate→business, while stored routes
  contain notify→business and insufficient_data→data, with no investigation route.
  Jev returns investigate, but the native recipient set is empty. The agent fixes
  recipients without changing outcome. Onboarding completion is not semantic
  agreement between prose and executable delivery configuration.
- **Cloud quiet:** native insufficient_data→data is incorrect on the supplied
  complete quiet evidence. The card retains setup questions about thresholds and
  destinations as recurring analytical questions, plus ambiguous topic-only
  watch items. The agent repairs the result to ignore. These are plausible
  contributors visible in traces, not isolated causal proof.
- The Cloud card still uses a prose comparison-window label and only the service
  source. Its snapshot contains prose values, not an analytical comparison, so
  this run does not prove the window mismatch is fixed. The fixtures intentionally
  lack the new source-declared window capability.

Native outcome correctness is 4/6 and recipient correctness 3/6; their intersection
is 3/6. Two outcome changes plus one recipient-only repair must not be presented
as six autonomous successes.

## Evaluation defects remain visible

[Independent blind review](evidence/bootstrap-codex-regression-v3-03/review.md)
found 11 supported narratives, one qualified, none unsupported. All final routes
follow public policy. The qualification is a baseline omitted recovery request.
The review disagrees with both arms' strict missing-population zero-delta penalty
when stated as qualified reported arithmetic; it also disagrees with treatment's
mandatory rollout-detail penalty, absent a clear public requirement.

Keep the frozen scores, not a retrospective rescore. Before a new confirmatory
trial, explicitly define required explanations, per-fact scope and correction
requests in instructions shared by both arms. Use a coherent time-series ledger
or call these independent conditions. Neither critique removes the observed
native routing defects or establishes lower cost.

[Results](evidence/bootstrap-codex-regression-v3-03/results.json),
[blind packet](evidence/bootstrap-codex-regression-v3-03/blind-review.json), and
[sealed mapping](evidence/bootstrap-codex-regression-v3-03/review-key.json)
retain configuration, hashes, costs and all outputs. The results file's pending
review marker is historical; the separate completed review supplies that result.
