# Narrative review of six development-regression outputs

Evidence source: [blind-review.json](blind-review.json) only. No mapping, results file, private scoring labels, prior summary, or other run's artifacts were inspected for this review. No arms are identified or inferred. No paid or live calls were made.

Blinding is imperfect: the reviewer previously worked on tests for semantic `insufficient_data`, routing, and compact responses, and had conversational context about the regression's purpose and an earlier retail failure. That context is disclosed, not used as evidence for the judgments below. This is a development regression review, not proof of product accuracy or comparative benefit.

The review independently recomputed arithmetic from the supplied source rows and checked the output's prose and structured claims against the supplied owner policy. It did not independently fetch or audit the upstream company data. `execution_complete: true` and the submitted `outcome` are not evidence that a narrative is correct or that a recipient actually received a message. No structured-score result was consulted or reproduced.

Verdicts: **supported** means the substantive narrative and decision match this evidence; **qualified** means the decision is supported but particular claims need explicit qualification or citation repair; **unsupported** means a central factual claim is contradicted by the evidence, even if the selected decision remains correct.

| Review ID | Narrative verdict | Decision and intended recipient | Principal finding |
| --- | --- | --- | --- |
| review-001 | supported | Supported | Correct 30% decline and channel contribution. |
| review-002 | supported | Supported | Correct arithmetic, accounting explanation, and causal limits. |
| review-003 | unsupported | Supported | Both total net-sales levels are understated by USD 3,000. |
| review-004 | supported | Supported | Correctly withholds validated net-sales claims when timing is undocumented. |
| review-005 | supported | Supported | Correct flat total and channel calculations. |
| review-006 | qualified | Supported | Correct data routing, but unvalidated arithmetic is presented as approved net-sales facts; one claim omits its supporting source reference. |

## Public policy and evidence used

The owner defines net sales as completed-order gross revenue minus refunds **posted during the reporting week**, excluding tax and shipping. This does not require a refund to concern a purchase made in that same week. Notify the business destination for a decline of at least 10% versus the previous complete UTC reporting week; otherwise ignore. Missing definitions or incomplete postings require `insufficient_data` to the data destination.

Authorized business recipient: `team-f88d053536cba66bc88e` (`slack://team-f88d053536cba66bc88e`). Authorized data recipient: `team-b5fcff88e8691a8a9289` (`slack://team-b5fcff88e8691a8a9289`).

Source references below are abbreviated only for readability:

- **Commerce**: `company_mcp|resource-949a4c0c44fb188d1658`, the completed-transaction saved query, with channel rows and positive refund deductions.
- **Returns**: `company_mcp|resource-00dc1bfdfad5f5f05554`, refund timing metadata, explicitly not another refund ledger.

The Orders weekly source includes cancellations, tax, and shipping; the other Commerce weekly catalog entry is an archived test-store chart. Neither is a valid substitute for the owner-defined population. All six outputs cite and report inspecting Commerce and Returns, and none uses those other populations in its explanation. All source contracts say `healthy`, but the explicit undocumented timing in reviews 004 and 006 still blocks semantic validation. Snapshot receipt health does not resolve that gap.

## review-001 — supported

**Independent numerical check:** baseline net sales = `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD`. Current net sales = `(6,500 - 2,500) + (4,000 - 1,000) = 7,000 USD`. Delta = `-3,000 USD`; percentage change = `-3,000 / 10,000 × 100 = -30%`. Web changes from USD 7,000 to USD 4,000; shop remains USD 3,000. All four `numeric_claims` and all prose quantities agree.

**Meaning, scope, and routing:** Commerce declares `refund_timing: posting_week`; Returns confirms the timing and that refunds are already in the channel rows. Refunds are deducted once. `notify` to the business recipient alone follows the 10% threshold. There is no evidenced missing-definition reason to route this case to Data Operations.

**Explanation and causal limits:** “Web drove the full USD -3,000 decline” is supported as accounting attribution in the context of the explicitly labeled decomposition. It does not establish why sales or refunds changed. No operational cause is invented. The explanation usefully identifies the affected channel and unchanged comparator. It could additionally state that web gross fell USD 1,500 and web refunds increased USD 1,500, each contributing USD -1,500 to net movement; that is a useful omission, not a false claim.

**Exact defects:** none material found. “Accounted for” would be clearer than “drove” if the summary were displayed without its accounting context.

## review-002 — supported

**Independent numerical check:** the supplied rows yield baseline USD 10,000, current USD 7,000, delta USD -3,000, and a 30% decline. Web is `8,000 - 1,000 = 7,000` initially and `6,500 - 2,500 = 4,000` currently; shop is USD 3,000 in both periods. All four numeric claims and all quantities embedded in prose are correct. A positive “USD 3,000 decrease” and a signed delta of USD -3,000 express the same movement.

**Meaning, scope, and routing:** the posting-week evidence validates the stated calculation within the supplied export. The business recipient is authorized and the decline exceeds the notification threshold. Returns is used as metadata, without adding a second refund subtraction.

**Explanation and causal limits:** the gross/refund figures explain the channel contribution more concretely than an alert about a chart alone. “Attributable to web net sales” is an accounting statement here, supported by the arithmetic and the explicit “No causal inference is made.” The statement that these amount rows do not support rate mix/within effects is appropriate: no rates or denominator populations are supplied. No causal mechanism or rate decomposition is fabricated.

**Exact defects:** none material found.

## review-003 — unsupported

**Independent numerical check:** both periods total `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD`. Web is USD 7,000 and shop USD 3,000 in each period. Total delta and both channel contributions are zero.

**Exact defects:** `analysis.numeric_claims[0]` (`net_sales.baseline`) and `[1]` (`net_sales.current`) each report **USD 7,000 instead of USD 10,000**. `analysis.claims[0].statement` repeats “Net sales were USD 7,000 in both…” as the total. Each reported level is USD 3,000 too low, or 30% below the source-derived total. The USD 7,000 figure equals the web subtotal; the output does not establish how the error occurred. Its next claim explicitly gives web USD 7,000 plus shop USD 3,000, so the narrative is internally inconsistent as well as contradicted by the rows.

**Decision, scope, and routing:** `ignore` with no recipients is nevertheless supported: the correct total is unchanged, the posting-week mapping is present, and the 10% decline threshold is not met. The zero delta and zero web contribution are correct. These correct fields do not validate the erroneous levels.

**Explanation and causal limits:** the channel explanation and summary correctly describe no movement, with no causal overclaim. “No data gap was reported” is supported by the supplied timing metadata; it is not a certification of all upstream data quality. The central total-level error makes this output unsuitable as a reliable numerical narrative without correction. Replace both numeric levels and the first prose claim with USD 10,000.

## review-004 — supported

**Independent evidence check:** Commerce explicitly says `refund_timing: undocumented`; Returns states “New refund feed has no versioned timing mapping.” Each observation cites the source that contains it. The missing information concerns whether these refund amounts implement the required reporting-week definition, not whether a source can be contacted.

**Numerical meaning and insufficient-data scope:** raw subtraction of the supplied rows would yield USD 10,000 in each column and a zero difference. That arithmetic cannot certify owner-defined weekly net sales while timing is unresolved. The output appropriately leaves `numeric_claims` empty and says these metrics cannot be reported **reliably**. It does not deny that the export contains numbers, invent missing rows, assume actual postings are incomplete, or treat apparent flatness as a validated business result.

**Decision, recipient, and usefulness:** `insufficient_data` goes only to the authorized data recipient. Asking for a corrected export or versioned refund-timing definition is exactly within the owner's stated remediation policy. No business alert or causal claim is proposed.

**Exact defects:** none material found. `analysis.claims[2]` is labeled `hypothesis`, although its content is more precisely an evidence-based measurement limitation and policy conclusion. That label does not invalidate the statement.

## review-005 — supported

**Independent numerical check:** baseline and current net sales are each `(8,000 - 1,000) + (4,000 - 1,000) = 10,000 USD`. Total delta = USD 0; percentage change = 0%. Web stays USD 7,000 and shop USD 3,000, so each contributes USD 0. All four numeric claims and all prose quantities are correct.

**Meaning, scope, and routing:** the posting-week timing is documented in Commerce and confirmed in Returns. The decomposition deducts the refunds once and includes both channels. `ignore` with no recipients follows the public policy. The mismatched booking and test-store populations do not enter the calculation.

**Explanation and causal limits:** the narrative usefully reports the total, the comparator, each channel's unchanged contribution, and why the threshold is not met. It makes no causal claim and invents no data gap.

**Exact defects:** none material found.

## review-006 — qualified

**Decision and recipient:** `insufficient_data` to the data recipient alone is supported. Commerce has undocumented refund timing and Returns has no versioned timing mapping. The summary identifies this limitation and requests appropriate remediation. It does not issue a business alert.

**Independent arithmetic versus metric meaning:** subtracting the supplied export columns produces baseline USD 10,000, current USD 10,000, delta USD 0, and web contribution USD 0. Those quantities are arithmetically correct for the export. They do not establish that the refunds were assigned by posting week, so they cannot yet be asserted as validated owner-defined net-sales quantities.

**Exact defects:**

1. All four `analysis.numeric_claims` are unqualified `net_sales.*` facts despite the unresolved timing. `analysis.claims[1]` strengthens the unsupported interpretation with “Under the approved definition, baseline net sales are USD 10,000…”; the summary similarly calls the figures “observed baseline and current net sales.” An approved definition alone does not prove that this export implements it. Retain these values only as explicitly unvalidated export arithmetic, conditional on confirming the timing, or omit them from validated metric claims. The correct `insufficient_data` decision does not erase the unsupported metric meaning.
2. `analysis.claims[2].statement` says Returns reports the missing versioned mapping, but that claim's `evidence_refs` lists only Commerce. Add `company_mcp|resource-00dc1bfdfad5f5f05554` to that claim. The statement itself is supported by the supplied Returns evidence and the overall analysis does include that reference; the defect is claim-level citation completeness.
3. The same claim's “same-week refund matching” is imprecise. The policy concerns refunds posted during the reporting week, not matching refunds to original purchases made in that week. Use “refund posting-week classification cannot be validated” to avoid implying an additional business rule.

**Explanation and causal limits:** the remediation and data-gap explanation are useful, and no causal mechanism is invented. The first claim's statement that the raw gross/refund rows are unchanged is supported. Its appended “computed net-sales change” needs the same export-only qualification as the other quantities. The qualification applies to what the numbers mean; it is not an arithmetic error or a routing error.

## Boundary of the findings

The per-ID judgments above come from checking narrative claims, references, policy, and arithmetic directly. They are separate from any structured benchmark score. In particular, correct outcome/recipient fields coexist with false total levels in review-003 and unvalidated metric assertions in review-006. This review does not establish which execution path produced either defect, whether a service delivered any message, how the ongoing regression performs, or whether one arm is better.
