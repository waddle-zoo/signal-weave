# Separate narrative review: development regression v3-02

Evidence source: this run's [blind-review.json](blind-review.json) only. The reviewer read its six outputs, public company policy, catalog, and source evidence, then recalculated each case from this file's rows. No mapping, results file, private scoring labels, prior review document, or other run's artifacts were inspected for this review. Prior verdicts and quantities were not used as inputs to the calculations or judgments. No arms are identified or inferred. No paid or live calls were made.

Blinding is imperfect. The reviewer has prior conversational context about the semantic `insufficient_data` change, compact responses, regression work, and a previous narrative review. This review cannot be described as an independent, previously unexposed reviewer. The findings below are based on the current supplied evidence, not an attribution of outputs to execution paths.

This is a development regression review, not proof of product accuracy, generalization, or comparative benefit. Arithmetic and narrative support were independently checked against the supplied exports; upstream company data, actual delivery, runtime behavior, and private benchmark scoring were not independently verified. `execution_complete: true` is not proof of narrative correctness or message delivery.

Verdicts use the same substantive standard: **supported** means the narrative and intended decision match the supplied evidence; **qualified** means the decision is supported but particular claims need qualification or citation repair; **unsupported** means a central factual claim contradicts the evidence even if the decision is correct. Minor wording or claim-type notes are distinguished from material defects.

| Review ID | Narrative verdict | Policy and intended recipient | Material finding |
| --- | --- | --- | --- |
| review-001 | supported | Supported | Correct totals, 30% decline, channel contribution, and accounting explanation. |
| review-002 | supported | Supported | Correct decline and routing; unavailable regional detail is scoped appropriately. |
| review-003 | supported | Supported | Correct USD 10,000 totals, zero movement, and channel contributions. |
| review-004 | supported | Supported | Missing timing mapping correctly blocks validated metric claims and routes to data operations. |
| review-005 | supported | Supported | Correct total and channel arithmetic; no notification warranted. |
| review-006 | supported | Supported | The inspected export's undocumented timing is sufficient to withhold metric claims and request correction. |

## Policy, references, and calculation method

The public policy in all six current cases defines net sales as gross completed-order revenue less refunds **posted during the reporting week**, excluding tax and shipping. Compare against the previous complete reporting week in UTC. A decline of at least 10% calls for business notification; otherwise ignore. Missing definitions or incomplete postings call for `insufficient_data` to the data destination. The policy does not require refunded orders to have originally been purchased in that same week.

Authorized business recipient: `team-f88d053536cba66bc88e`, destination `slack://team-f88d053536cba66bc88e`. Authorized data recipient: `team-b5fcff88e8691a8a9289`, destination `slack://team-b5fcff88e8691a8a9289`. These identifiers were checked against this file's destination list and owner routing answer.

References abbreviated below:

- **Commerce**: `company_mcp|resource-949a4c0c44fb188d1658`, the completed-transaction saved query with gross/refund amounts by channel in USD.
- **Returns**: `company_mcp|resource-00dc1bfdfad5f5f05554`, refund posting metadata, explicitly not an additional refund ledger.

The Orders weekly source includes cancellations, tax, and shipping. The other identically titled Commerce weekly entry is an archived test-store chart. Neither matches the approved measurement population. None of the six outputs uses those populations in its arithmetic or explanation.

For each case, I calculated channel net = gross minus positive refund deductions; total net = sum of channel nets; signed delta = current total minus baseline total; percentage change = signed delta / baseline total × 100. Channel contribution is that channel's signed net change, not a causal estimate. Refunds are subtracted once. All cited references exist in the supplied source map and in the respective output's `inspected_refs`; statement-level support was also checked, rather than assuming reference existence proves a claim.

## review-001 — supported

**Fresh numerical verification:** baseline total = `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD`. Current total = `(6,500 - 2,500) + (4,000 - 1,000) = 7,000 USD`. The signed change is USD -3,000 and the percentage change is `-3,000 / 10,000 × 100 = -30%`. Web moves from USD 7,000 to USD 4,000, contributing USD -3,000; shop remains USD 3,000, contributing zero. All four numeric claims, the gross/refund quantities embedded in the second prose claim, and the 30% summary agree with the rows.

**Meaning and source support:** Commerce declares `refund_timing: posting_week`. Returns says the posting week matches the transaction feed and refunds are already included in the rows. The third claim correctly cites Returns for the no-additional-ledger statement. No refund is deducted twice.

**Decision, recipient, and explanation:** `notify` to the business recipient alone is supported by the 30% decline exceeding the 10% threshold. The explanation identifies both accounting components: web gross falls USD 1,500 and web refunds rise USD 1,500, each reducing net sales by USD 1,500; shop is unchanged. “Accounting drivers, not causality” accurately limits the conclusion. It does not assert an operational reason for either change.

**Exact defects:** none material found. “Same-week refunds” is acceptable in its explicit posting-week context; it should not be read as refunds on purchases necessarily made that week.

## review-002 — supported

**Fresh numerical verification:** this case's Commerce rows give baseline `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD` and current `(6,500 - 2,500) + (4,000 - 1,000) = 7,000 USD`. Delta is USD -3,000, or -30%. Web changes from USD 7,000 to USD 4,000 and shop remains USD 3,000. All four numeric claims and both numerical prose claims are correct. The summary's lower gross sales and higher refunds are directly supported by web's gross moving 8,000 to 6,500 and refunds moving 1,000 to 2,500.

**Meaning, inspected evidence, and limitations:** this output reports inspecting and citing only Commerce. That source itself provides positive refund deductions, completed-transaction scope, USD units, and `refund_timing: posting_week`; the owner supplies the metric definition. The output does not claim to have inspected Returns or quote information exclusive to it. Returns' presence elsewhere in the review packet is not needed to repair a missing citation here. “No incomplete posting or definition gap is indicated” is supported as a bounded statement about the supplied evidence, not as an upstream audit guarantee.

**Regional scope and decision:** the rows have `channel` but no region field. “No regional breakdown is available in the inspected source” is supported. The public brief does not make a regional breakdown a prerequisite for its net-sales decision, so the output appropriately retains `notify` to the authorized business recipient. It neither fabricates a region nor turns optional detail into insufficient data.

**Explanation and causal limits:** the summary identifies the affected channel, gross/refund direction, and unchanged shop, and explicitly calls the result accounting rather than causality. No unsupported causal mechanism appears.

**Exact defects:** none material found. The regional caveat is extra context rather than an owner-requested requirement; its inclusion does not change the supported decision.

## review-003 — supported

**Fresh numerical verification:** web net is `8,000 - 1,000 = 7,000 USD` in both columns. Shop net is `4,000 - 1,000 = 3,000 USD` in both columns. Each total is USD 10,000; signed delta is USD 0; percentage change is 0%. Web and shop each contribute USD 0. All four numeric claims, both prose claims, and every numerical statement in the summary reconcile with this case's rows.

**Meaning and evidence scope:** the inspected Commerce export explicitly has posting-week timing. The output cites only that source and does not claim additional inspection. It uses both channels for total sales and does not confuse a subtotal with the company total. No regional fields are present in the supplied rows, so the summary's regional limitation is supported within this source's scope.

**Decision, recipient, and usefulness:** `ignore` with an empty recipient list matches an unchanged validated metric and the owner's 10% decline rule. The regional limitation does not require a data-operations route under the supplied policy. The explanation gives the total, comparison, signed movement, and channel reconciliation without inventing a causal story.

**Exact defects:** none material found. The regional sentence could explicitly say “in this export” for standalone clarity, but its source-scoped reading is supported and creates no material qualification.

## review-004 — supported

**Evidence and semantic scope:** Commerce says `refund_timing: undocumented`; Returns says the new refund feed has no versioned timing mapping. The first two prose claims cite their respective supporting sources. Their combined implication is that these refund amounts cannot yet be validated against the owner-defined posting-week metric, even though the snapshots' generic contracts say `healthy`.

**Fresh arithmetic check, distinguished from metric validity:** subtracting the raw columns gives web USD 7,000 and shop USD 3,000 in each column, totaling USD 10,000 per column and a zero raw difference. That is an arithmetic property of the export. Without the timing mapping, it does not establish the approved weekly net-sales levels or movement. This output appropriately leaves `numeric_claims` empty and withholds levels, delta, and contribution rather than using apparent flatness to justify `ignore`.

**Decision, recipient, and usefulness:** `insufficient_data` goes only to the authorized data recipient. Requesting a corrected export or versioned refund-timing definition follows the owner's remediation instruction. The output describes a validation gap; it does not invent missing rows, claim that actual postings are definitely incomplete, or issue a business alert. No causal inference is made.

**Exact defects:** none material found. Minor classification note: `analysis.claims[2].claim_type` is `hypothesis`, but its statement is more precisely a measurement limitation derived from policy and the two cited sources. The text remains supported.

## review-005 — supported

**Fresh numerical verification:** baseline total = `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD`. Current total is independently the same sum, USD 10,000. Delta is USD 0. Web is USD 7,000 in each week; shop is USD 3,000 in each week; both contributions are zero. All four numeric claims, the gross/refund amounts in the accounting claim, and the summary are correct.

**Meaning and source support:** Commerce documents posting-week timing and Returns confirms the feed mapping and that its metadata is not another refund ledger. Both sources are reported inspected and included in the overall evidence references. The calculation uses both channels, subtracts refunds once, and stays within the approved sales population.

**Decision, recipient, and explanation:** unchanged net sales do not meet the decline threshold. `ignore` and no recipients are supported. The narrative supplies the total, prior-week comparator, and zero channel contributions. It makes no causal claim and does not invent a data-quality blocker.

**Exact defects:** none material found. The summary does not literally say “ignore,” but “the decline threshold was not met,” together with the explicit `outcome`, communicates the intended decision without contradiction.

## review-006 — supported

**Evidence and inspected-source scope:** the output reports inspecting and citing only Commerce. Its `refund_timing: undocumented` directly supports the first claim and is enough to trigger the owner's missing-definition rule. The output does not claim to have inspected Returns or to know the separate metadata's precise wording. Its conclusion therefore does not depend on crediting an uninspected source.

**Fresh arithmetic check, distinguished from metric validity:** the supplied columns yield `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD` in each column, raw delta USD 0, and raw web contribution USD 0. Those calculations cannot establish reporting-week net sales until the refund timing is confirmed. The output correctly has no numeric claims and does not publish those raw quantities as validated metrics. “Cannot be safely reported” is scoped to the required net-sales comparison; the output explicitly acknowledges that gross/refund amounts exist.

**Decision, recipient, and usefulness:** `insufficient_data` to the authorized data recipient is correct. The requested corrected export or versioned definition addresses the stated gap. The narrative does not infer causation, actual missing transactions, or a business decline. It does not silently adopt an order-booking or test-store population to fill the gap.

**Exact defects:** none material found. Minor classification note: `analysis.claims[1].claim_type` is `accounting_decomposition`, although the text states why a decomposition is unavailable rather than supplying one. That is a taxonomy imprecision, not a fabricated result. “Required same-week refund definition” is supported when read as posting-week assignment, as the next claim explicitly states; “refund posting-week definition” would be clearer on its own.

## What this review establishes

All six current narratives are supported by the provided policy and source evidence under the stated review standard. The four outputs with numeric claims have been recalculated, and the two that lack validated timing appropriately abstain from numeric metric claims. No material arithmetic, metric-scope, recipient, citation, or causal-overclaim defect was found. The small claim-type and wording notes above do not change those judgments.

These are independently checked narrative findings relative to this evidence packet, not a structured benchmark score. They do not prove upstream completeness, actual notifications, runtime enforcement, performance on other cases, an improvement over another run, or a causal advantage of an unidentified execution path.
