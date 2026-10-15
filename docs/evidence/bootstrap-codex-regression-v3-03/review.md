# Internal blind narrative review

Reviewer: Curie (independent subagent), 2026-10-01. Read AGENTS.md and only
`blind-review.json`; no results, arm mapping, scorer, previous reports or paid
calls. This record summarizes the returned review, then records unblinding.
It is one review per output, not external peer review or inter-rater agreement.

**11 supported, 1 qualified, 0 unsupported.** All twelve final proposed outcomes
and recipient sets follow public owner rules. No external delivery was tested.

| Case | Judgment | Concrete assessment |
| --- | --- | --- |
| 001 | Supported | Eligible SLA .90→.75, unchanged cohort weights, within −.15 and mix 0; notify business. |
| 002 | Qualified | Correct insufficient-data routing and withheld current attainment for null denominators, but omits the owner's requested corrected-export/versioned-definition ask. |
| 003 | Supported | Reported latency 100→100 and lag 10→10 coexist with missing population/regions; data routing and caveats correct. Zero subtraction describes reported values, not verified population comparability. Missing event timestamp prevents rollout lead time. |
| 004 | Supported | Unchanged latency/lag, zero affected regions and known population; ignore isolated 95% CPU. Null change timestamp is not converted to zero lead time. |
| 005 | Supported | +40% latency, 8× lag, three regions satisfy investigate. Calendar supports 12-minute temporal association, explicitly not causation. Minor wording caveat: the no-controlled-test note concerns a prior rollout, not proof of current testing history. |
| 006 | Supported | Missing population/regions requires data routing; corrected export requested. Same reported-arithmetic versus verified-scope distinction as 003. Calendar unnecessary to establish coverage failure. |
| 007 | Supported | Complete population, stable latency/lag, zero affected regions; ignore. No mandatory calendar inspection for this decision. |
| 008 | Supported | .90→.90 with complete eligible denominators, unchanged cohort rates/weights; volume growth alone does not trigger. |
| 009 | Supported | Null total/priority denominators and missing overdue-open export; valid .90 baseline retained, current withheld, explicit recovery request. |
| 010 | Supported | The service source alone contains +40% latency, 8× lag and three regions: correct business investigation. Public rules do not require calendar inspection or a rollout hypothesis. |
| 011 | Supported | Same complete stable SLA decomposition as 008; ignore, no recipients. |
| 012 | Supported | .90→.75 with within −.15 and mix 0; notify. Accounting explanation is not represented as causal inference. |

The supporting resources are the eligible Queue service
`company_mcp|resource-cd2e0e36f156148773cf`, Support handbook
`company_mcp|resource-30652812e13cefb915b1`, customer-cluster Database service
`company_mcp|resource-ee271f169093125e61d0`, and Change calendar
`company_mcp|resource-e92083b287448edc785c`. Every cited reference is in the
respective inspected set and catalog. No closed-ticket-only or synthetic-cluster
source substitutes for the owner-defined population.

## Reviewer/scorer disagreements and limitations

- Public vocabulary lists allowed quantities but does not clearly require all of
  them. In 010, the frozen scorer demands a rollout source, lead-time fact and
  explanatory claim that the reviewer finds optional under the public task.
- In 003/006, the frozen scorer rejects canonical latency.delta with unavailable
  scope. The reviewer accepts the narrative's qualified arithmetic on reported
  values. Public instructions should distinguish those two claims explicitly.
- In 002, clarify whether routing itself constitutes the recovery request. The
  qualification applies the instruction literally to the returned message.
- Queue snapshots mark coverage complete despite null denominators; actual
  missing fields and handbook statements take precedence.
- Database evidence lacks separate baseline/current memberships and interval
  boundaries. One population list does not independently prove comparability.
- Kindred's overlapping intervals contain inconsistent values between scenarios.
  Treat them as independent cases, not a longitudinal company ledger.
- `accounting_decomposition` is broadly used for subtraction, ratios and missing
  calculations; clarify this taxonomy before penalizing it.

After the review was sealed, the existing review key identifies baseline as
5 supported/1 qualified, treatment as 6 supported/0 qualified. No scores were
changed. These are assessments of final agent output, not the native system's
decision or evidence that SignalWeave reduced agent work.
