# Blind internal narrative review — v4-01

Reviewer: fresh subagent Mill (`01a0f99a-3d2e-7c00-a716-a2041b403a04`).
Read AGENTS.md and only `blind-review.json`; did not see arms, scorer, previous
reports or this mapping before reporting. No edits or paid calls. Main agent
mapped arms after the verdicts. This is synthetic internal review, not external
peer review or an inter-rater reliability study.

All 12 outputs were present and complete. Verdicts: **8 supported, 3 qualified,
1 unsupported**. Final outcome and recipient keys agree with public policy in
11/12 cases. Qualified means supported decision with a scope limitation or
missing requested next step; unsupported denotes material policy conflict.

| Case | Verdict | Findings |
| --- | --- | --- |
| review-001 | supported | SLA .90→.75, delta −.15, mix 0, within −.15; notify business. |
| review-002 | supported | Missing eligible denominator; abstains and requests corrected export; insufficient_data to data. |
| review-003 | qualified | Export subtraction is 0 ms but canonical population-scoped delta lacks population; missing corrected-export request. Correct data route. |
| review-004 | supported | Latency and lag unchanged, regions 0, CPU isolated; ignore. |
| review-005 | supported | +40 ms/+40%, lag 8×, three regions, 12-minute rollout lead; investigate business, no causal proof asserted. |
| review-006 | qualified | Same population qualification on 0 ms; correctly asks for corrected evidence and routes to data. Simple subtraction is not explanatory decomposition. |
| review-007 | supported | Unchanged latency/lag, regions 0; populated list supports comparison within this packet; ignore. |
| review-008 | supported | SLA .90 both weeks despite volume doubling; mix/within 0; ignore. |
| review-009 | qualified | Correct missing-denominator abstention/data route, but omits owner's request for corrected export or versioned definition. |
| review-010 | unsupported | Supplied population and all three trigger signals support investigate/business. Adds an explicit-completeness prerequisite and instead chooses insufficient_data/data. Arithmetic is correct; recipient is allowlisted but wrong for this decision. |
| review-011 | supported | Stable SLA .90 and zero effects; ignore, no causal inference. |
| review-012 | supported | SLA −.15 due to within-segment effects, mix 0; notify business. |

All 32 structured numeric claims reproduce supplied arithmetic with declared
units. That does not validate the two canonical zero-latency claims' population
scope. SLA −.15 ratio units means −15 percentage points, not −15% relative.
Every cited source exists in the case snapshots and was inspected. No distractor
population was substituted. No unsupported causal conclusion or destructive
action appears. Review-005's same-population association should cite both the
service export and event calendar; both were inspected and cited elsewhere.

After unblinding: baseline 5 supported/1 qualified; treatment 3 supported/2
qualified/1 unsupported. Reviewer examined final narratives, **not** actual card
endpoint strings or native admission behavior; main's endpoint audit is separate.

Limitations: aggregate snapshots, sparse source contracts, no raw-row validation
or delivery receipts. Healthy/complete labels are assertions, and missing SLA
denominators contradict blanket completeness. Repeated evidence settings are
not 12 independent demonstrations. Actual delivery, causal validity and general
comparative performance remain unverified.
