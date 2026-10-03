# Narrative review

Scope: completed retail packet only. This is the style-can-leak arm, uses synthetic cases, and is an internal narrative review—not external peer review. I read the repository instructions and only `artifacts/enterprise-onboarding-repair-v6-probe-01-review/blind-review.json` for trial evidence. No live calls or runtime files were used.

## Recomputed packet arithmetic

For the complete `posting_week` packet:

- Web baseline: `18,400 - 2,300 = 16,100 USD`; current: `14,950 - 5,750 = 9,200 USD`; contribution: `-6,900 USD`.
- Shop baseline and current: `9,200 - 2,300 = 6,900 USD`; contribution: `0 USD`.
- Total baseline: `23,000 USD`; current: `16,100 USD`; delta: `-6,900 USD`; relative change: `-6,900 / 23,000 = -30.0%`.

For the second complete `posting_week` packet, both channels are unchanged, so total baseline and current are `23,000 USD`, delta `0 USD`, and web contribution `0 USD`. For the two undocumented-timing packets, the displayed rows can be arithmetically subtracted, but the packet does not support canonical net-sales values.

## Per-case audit

### review-001 — supported

Candidate: “Notify the business owner: current-period net sales are down 30.0% week over week, driven by web net sales; shop is unchanged. Refund postings match the transaction feed and are not double-counted.”

The arithmetic, USD units, previous-complete-week comparison, and `>=10%` notification threshold all pass. “Driven by” is supported only as an accounting contribution, not as a causal explanation; the detailed claim correctly limits the source to an association. The proposed business route is authorized: `team-1ad71a8723aa9325e8c1`.

Exact evidence: the Commerce weekly row gives `"baseline_gross": 18400, "baseline_refunds": 2300, "current_gross": 14950, "current_refunds": 5750` for web and `"baseline_gross": 9200, "baseline_refunds": 2300, "current_gross": 9200, "current_refunds": 2300` for shop; the Returns operations source says, “Posting week matches transaction feed; refunds already included in its rows.”

### review-002 — qualified

Candidate: “Company-wide weekly net sales were USD 23,000 in the previous complete UTC reporting week and USD 16,100 in the current complete week … the applicable source population is complete for the selected company-wide weekly feed.”

The USD arithmetic, `30%` decline, web contribution, and business-owner routing are correct. However, the cited Commerce weekly evidence supplies channel rows and USD fields but does not state “company-wide” or “complete”; its contract also leaves `population` empty. Those population/completeness claims are therefore unsupported and should be removed or explicitly qualified. “Delivery is disabled and no notification was sent” is a process-state assertion, not established by the cited source evidence; retain it only if separately backed by packet execution metadata.

Exact evidence: the source says “Completed transaction amounts by sales channel; refunds are positive deductions, amounts in USD,” and its row values are `18,400/2,300 -> 14,950/5,750` for web and `9,200/2,300 -> 9,200/2,300` for shop. The owner policy says, “Notify the business destination for a net-sales decline of at least 10% against the prior complete week.”

### review-003 — supported

Candidate: “Insufficient data for the weekly net_sales decision: current-period refund timing and versioned posting mapping are unavailable … proposed recipient is Data Operations only.”

This correctly declines to manufacture canonical numbers. The source rows are unchanged, but the packet marks timing as undocumented and the refund source lacks a versioned timing mapping. The owner policy explicitly sends missing definitions/incomplete postings to the data destination, not the business route. The proposed recipient `team-66fa81ad827deebeb98f` is authorized.

Exact evidence: the Commerce weekly values contain `"refund_timing": "undocumented"`; Returns operations says, “New refund feed has no versioned timing mapping.” The owner policy says, “Missing definitions or incomplete postings require insufficient_data to the data destination, not a business alert.”

### review-004 — supported

Candidate: “Net sales are unchanged at USD 23,000 versus the previous complete reporting week. The web channel contributed USD 0 to the change, so the configured 10% decline threshold is not met; ignore.”

The numbers recompute exactly: web is `16,100 USD` in both periods, shop is `6,900 USD` in both, total is `23,000 USD` in both, and web contribution is `0 USD`. Ignore/no recipient is consistent with the owner policy.

Exact evidence: the Commerce weekly rows are `"baseline_gross": 18400, "baseline_refunds": 2300, "current_gross": 18400, "current_refunds": 2300` for web and `"baseline_gross": 9200, "baseline_refunds": 2300, "current_gross": 9200, "current_refunds": 2300` for shop; timing is `"posting_week"`. Returns operations says, “refunds already included in its rows.”

### review-005 — supported

Candidate: “Insufficient data for the net_sales decline test … Provisional arithmetic from the displayed rows would show no change … but these values are not submitted as canonical business facts.”

The distinction between provisional arithmetic and a policy-valid metric is correct. The case routes only to Data Operations (`team-66fa81ad827deebeb98f`), does not assert a business decline, and does not infer causation. As with review-002, “no external notification was sent” is not a source claim; it is acceptable only as a separately verified execution-state note.

Exact evidence: the Commerce weekly rows are unchanged and explicitly mark `"refund_timing": "undocumented"`; Returns operations says, “New refund feed has no versioned timing mapping.”

### review-006 — supported

Candidate: “Ignore for the current shadow observation: net sales are unchanged at 23000 USD versus the previous complete UTC reporting week (delta 0 USD; relative change 0%). Web contribution to the change is 0 USD and shop is unchanged. This is an accounting observation, not a causal explanation.”

The arithmetic, units, comparison window, non-causal framing, and no-delivery outcome all match the packet. No recipient is proposed, which is correct for an unchanged metric below the notification threshold.

Exact evidence: the source rows show `18,400/2,300 -> 18,400/2,300` for web and `9,200/2,300 -> 9,200/2,300` for shop, with `"refund_timing": "posting_week"`; Returns operations says, “Posting week matches transaction feed; refunds already included in its rows.”

## Overall finding

Five cases are supported as written at their core decision level. Review-002 is qualified because it overstates source population/completeness and includes an execution-state claim not evidenced by the cited sources. Reviews 003 and 005 correctly prioritize `insufficient_data` over invented numbers when refund timing cannot be validated. No candidate makes a supported causal claim; the review should preserve the accounting-versus-causation distinction in any final copy.

## Shared execution-context addendum

The packet-wide process context supports execution-state language for all six cases, without relying on trial-arm knowledge: every episode is caller-managed, delivery-disabled shadow analysis; `real_external_notifications=false`; and the exposed tools include only `submit_analysis`, with no delivery tool. Therefore, statements such as “delivery is disabled,” “no notification was sent,” or “no external notification was sent” are supported execution-state claims across the packet, including where they were not repeated in the case summary.

This does not resolve review-002's population/completeness qualification. Severity: material to alert trust, not merely wording. Calling an unverified or unscoped feed “company-wide” and “complete” can make a reader treat the alert as representative of the full business and change whether they trust or escalate it. That claim still needs removal or explicit evidence/qualification.
