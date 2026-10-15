# Internal review record

Date: October 1, 2026. These are independent-agent reviews within this development
session, not external peer review or real-customer validation. No reviewer changed
the frozen run or invoked the trial's model APIs. Reviewer compute is not included
in production-invocation token estimates.

## Process and code review

Reviewer: Hilbert (`01a0f7d0-ca67-7971-95b2-7c24c83fcfda`). Read-only review of
the frozen implementation and a bounded sample of failed onboarding traces.

- Title collisions use adapter/title/domain identity; selecting a resource does
  not provide a usable resolution of the resulting approval blocker. Retail
  preview and simulated owner approval succeeded, but production approval failed.
- `record_insight_card_correction.kind` advertises a string, while implementation
  accepts an enum. Repeated guesses consumed calls. Valid feedback would still
  not clear readiness: corrections are append-only.
- SaaS also attempted approval without the harness's current-card owner receipt.
  That is a distinct procedural failure, not evidence that every failure has the
  same production cause.
- Retail's Jev preview omitted a duplicate distractor ranked 0.05. The evidence
  does not establish a Jev retrieval failure. Scheduled monitoring never executed
  after failed setup, so its judgments and safety remain unassessed.

Suggested remedy: discoverable correction enums and explicit, version-bound,
provenance-bearing ambiguity resolution, without bypassing authorization or
source-health checks. Evaluate a repair under a new protocol version.

## Arm-metadata-blinded narrative review

Reviewer: Russell (`01a0f7d8-02f5-7383-8c70-23878dd99a46`). Read AGENTS.md and
only `blind-review.json`; did not read the mapping, scores, private labels or raw
report. Narrative wording can reveal implementation, so blinding is imperfect.
All 18 completed outputs were inspected; the other 18 had no output and were
unassessed, not safe. Unblinding identifies every completed output as baseline.

“Qualified” means the conclusion is defensible but wording or numeric labels
exceed the evidence. “Unsupported” denotes a substantive unsupported assertion,
not necessarily an incorrect route or an unsafe external action.

| Case | Reviewer assessment | Reason |
| --- | --- | --- |
| 001 | Supported | SLA remains 0.90 despite doubled volume; no within/mix deterioration. |
| 002 | Qualified | Correct refund-timing escalation; mechanical amounts labeled as validated net sales. |
| 007 | Qualified | Correct partial-feed escalation; opening claim calls partial receipts the current total. |
| 010 | Supported | SLA 0.90 → 0.75, all within-queue; authorized notification. |
| 012 | Supported | Collections unchanged; both partitions closed; no invented bank-level change. |
| 013 | Qualified | Net-sales decline and web contribution correct; explicit completeness attestation absent. |
| 014 | Unsupported | Claims $11,000 net sales; source arithmetic gives $10,000. |
| 016 | Supported | Missing current buyer union stays unknown; overlapping audiences not summed. |
| 021 | Supported | Collections decline 25%; both partitions closed; appropriate notification. |
| 022 | Supported | Missing cluster/region coverage blocks assessment despite flat supplied measurements. |
| 026 | Unsupported | Unknown current SLA/delta encoded as zero; invented explicit source annotation. |
| 027 | Supported | Retention within/mix decomposition correct; no causal claim. |
| 028 | Supported | Missing eligibility mapping blocks validated comparison. |
| 029 | Supported | Distinct buyers decline 35%; no audience double counting. |
| 031 | Supported | Latency +40%, lag 8× and three regions warrant investigation; timing is noncausal. |
| 032 | Supported | Distinct buyers unchanged; appropriate ignore. |
| 033 | Supported | Flat latency/lag and zero affected regions; isolated CPU not treated as impact. |
| 036 | Supported | Retention decline entirely explained by mix, not worse plan rates. |

These judgments are 13 supported, three qualified and two unsupported—not an
independent automated accuracy metric. No substantive causal overclaim or
unauthorized recommended action was found in this sample.

### Specific evidence for reservations

- **014:** “net sales are USD 11,000 in both periods.” The commerce rows are web
  8,000 − 1,000 and shop 4,000 − 1,000, totaling 10,000. The zero change is still
  correct. Completeness is also asserted without an explicit attestation.
- **026:** `sla_attainment.current=0` and `sla_attainment.delta=0` contradict the
  missing current denominator. The source does not explicitly mark decomposition
  `insufficient_data`, despite the agent claiming it does. In fact, comparison
  metadata says complete/comparable while denominator fields are missing; the
  handbook confirms missing overdue-open population. Abstention is justified,
  but its asserted source annotation is invented.
- **002:** The narrative correctly says the arithmetic is not validated net sales
  because refund timing is undocumented. Structured net-sales fact labels omit
  that distinction.
- **007:** Exported receipts are 8,000 versus 20,000, but only one of two partitions
  is closed and capture is three days old. Later prose qualifies this correctly;
  the opening current-total claim should say partial/exported amount.
- **013:** Healthy status, current capture time and posting-week mapping do not
  explicitly attest posting completeness. This is an evidential qualification,
  not proof that the source is actually incomplete. The omitted split between
  gross and refund changes is not itself a false claim.

The frozen JSON export's `narrative_review_status` says pending because it was
created before this review. This companion record supplies the later review;
original scores and outputs are unchanged.

## Structured-score audit (not blinded)

Reviewer: Kuhn (`01a0f7d8-8c36-7a80-a2ab-6f28c2de75d1`). Inspected the frozen
report, scorer, protocol and labels; verified scorer/protocol hashes. No scores
were recomputed and no files changed. This audits the evaluator, not just the
agent. It is distinct from the blinded narrative review above.

| Nonexact baseline case | Classification | Finding |
| --- | --- | --- |
| Juniper quiet | Numerical error | $11,000 baseline/current should be $10,000; delta remains correct. |
| Cinder event | Vocabulary contract | Correct +40 ms, three regions and 12 minutes; extra prose in fact keys. |
| Lumen event | Vocabulary contract | Correct 20,000 / 15,000 / −5,000; values appended to fact keys. |
| Lumen quiet | Vocabulary contract | Financial values pass; correct partition counts use undeclared fact names. |
| Cinder quiet | Citation contract | One observation cites a catalog-only, uninspected resource. |
| Juniper quality | Unsupported canonical metrics | Mechanical totals mislabeled as validated net sales despite missing refund timing. |
| Kindred quality | Unknown encoded as zero | Valid baseline passes; current SLA and delta cannot be computed. |
| Cinder quality | Unsupported canonical scope | Flat supplied measurements do not establish the defined customer-population delta. |
| Mosaic quality | Label omission | Available 4,200 baseline rejected merely because current buyers are missing. |
| Lumen quality | Unsupported current metrics; baseline concern | Partial/stale current totals cannot be complete collections; baseline blanket-exclusion also needs review. |

Mutually exclusive case-level taxonomy: one numerical-error case, four
vocabulary/citation-only cases, four quality cases asserting unavailable or
unvalidated canonical quantities, one clear omission-only case. Lumen quality
also has a historical-baseline validity/freshness ambiguity; it is less clean
than Mosaic's clear omission.

Future evaluation work:

1. Complete per-fact availability rules. Mosaic's `if not broken` label branch
   contradicts the available-baseline principle; finance needs an explicit
   historical-baseline freshness policy.
2. Separate wrong values from unknown identifiers, unavailable scope, invalid
   citations and duplicates. `unsupported_numeric_facts` currently conflates
   these, so its precision is not pure arithmetic precision.
3. If partial/exported observations are useful, give them a structured scope and
   validity status rather than relying on prose to qualify canonical quantities.

Original exact score remains **8/18**. No adjusted score or retrospective
comparative win is asserted. Repair these issues only in a declared new version.
