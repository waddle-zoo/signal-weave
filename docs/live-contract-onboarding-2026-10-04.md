# Live local onboarding probe

Date: 2026-10-04

This probe tests the path a local agent actually uses: MCP onboarding, Jev
resource ranking, Jev plan compilation, typed source-contract visibility in the
review packet, then delivery-disabled simulation with live Jev judgment.

## Result

| Adapter identity | Cases | Exact onboarding + handoff | Jev calls | Delivery |
| --- | ---: | ---: | ---: | --- |
| Looker-style explore | complete + partial | **2/2** | 8 | disabled |
| Trino-style query | complete | **1/1** | 4 | disabled |

The Looker complete case produced:

`ready_for_approval → investigate → retrieve_evidence / pending`

The matching partial-contract case produced:

`ready_for_approval → insufficient_data → repair_source / blocked`

The Trino-style complete case produced the same investigation handoff. Every
case showed the exact contract in the review packet, bound its exact key onto
the card, used `jev-1.13.0`, and performed no real delivery. This proves the
local onboarding path is not tied to Superset naming or a hardcoded chart
metric.

## What the first attempt caught

The first three-adapter probe was stopped after six calls because its budget was
incorrectly set to six total requests. One card requires four Jev requests in
the current onboarding path, not one: bounded ranking, anchor/ranking work,
plan compilation, and judgment. The run produced no report and no delivery.
That failed trace is retained under
[`evidence/live-contract-onboarding-2026-10-04/failed-budget-probe/`](evidence/live-contract-onboarding-2026-10-04/failed-budget-probe/).
The runner now calculates the cap from cards × quality arms × four requests per
card, and the corrected runs completed without budget censorship.

The first completed Looker preview also exposed a real policy boundary: Jev's
initial confidence was 0.69 against the default 0.70 automatic-action floor.
SignalWeave correctly held the case for review instead of inventing a push. The
corrected onboarding card explicitly asked for an investigation handoff, so the
successful run verified the safe behavior rather than lowering the threshold to
make a notification look successful.

## Limits

This is local adapter simulation, not a hosted Looker or Trino integration
claim. It proves onboarding and contract handling across two adapter identities
and one negative quality arm, not universal connector correctness, report prose
quality, or enterprise adoption. The next meaningful proof is a full
agent-authored multi-source onboarding cohort with a held-out final report and
replay checks.

Raw protocol, reports, traces, and hash manifest are retained in
[`evidence/live-contract-onboarding-2026-10-04/`](evidence/live-contract-onboarding-2026-10-04/).
