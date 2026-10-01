# Blind narrative review: cloud, marketplace, finance

## Scope and standard

Evidence source: [blind-review.json](blind-review.json), restricted to Cinder Database Cloud, Mosaic Exchange, and Lumen Freight Finance. Read repository `AGENTS.md`. Reviewed all 18 selected outputs: two anonymous submissions for each company's three dated conditions. Each pair has identical public business inputs. All 18 have nonempty analyses and `execution_complete: true`; none is unassessed. Empty or missing outputs would remain unassessed, not failures.

Used the public brief, glossary, owner answers, catalog descriptions, snapshots, `numeric_vocabulary`, and `submission_contract.numeric_definitions`. Did not read results, mappings, traces, hidden source labels, code, or other reports; did not infer arm identities. Dates below are packet dates. Each comparison uses that case's supplied baseline; this review does not establish a reconciled longitudinal history across episodes.

**Supported** means the substantive narrative, quantities, evidence, and proposed decision are supported within the packet. **Qualified** means the decision remains useful and policy-consistent but a specific measurement, citation, or narrative defect needs correction. **Unsupported** means the proposed operational decision conflicts materially with owner policy, even if its underlying arithmetic is right. These are whole-output judgments, not claims that every sentence shares the same status. Vocabulary or claim-type awkwardness alone is not an arithmetic failure.

Result: **12 supported, 5 qualified, 1 unsupported, 0 unassessed**. The counts describe only these selected submissions, not arm performance or trial-wide accuracy.

## Independently checked evidence and policy

References below are public snapshot keys in each selected case's `business.period.snapshots`; evidence values are under `evidence[0].values` unless otherwise specified.

| Short reference | Public source key | Role |
| --- | --- | --- |
| C-service | `company_mcp\|resource-ee271f169093125e61d0` | Customer-cluster latency, lag, and coverage |
| C-calendar | `company_mcp\|resource-e92083b287448edc785c` | Rollout and latency-change timestamps |
| C-capacity | `company_mcp\|resource-3e8f64ae0ebe74580f18` | Single-node capacity, not customer impact |
| M-union | `company_mcp\|resource-2a72f4a07f7f213d5574` | Distinct completed-purchase customer IDs |
| M-audience | `company_mcp\|resource-34394f79b765f093ff6f` | Overlapping buyer tags |
| M-sessions | `company_mcp\|resource-0e2cc7b12f617d0698a6` | Sessions, not distinct buyers |
| F-receipts | `company_mcp\|resource-4320ff3ae64c05222c66` | Settled USD receipts and current bank rows |
| F-ingest | `company_mcp\|resource-b1dbfd93ab7ae2ea6ea6` | Bank closure and watermark |

| Company / date (2026) | Independent calculation and validity | Required decision |
| --- | --- | --- |
| Cinder / Oct 08 | Printed p95: 100 − 100 = 0 ms; lag: 10 / 10 = 1×. `affected_regions` and `cluster_population` are null. The arithmetic is available, but the defined population is not validated. Calendar has no latency-change timestamp. | `insufficient_data` → Data operations |
| Cinder / Oct 15 | P95: 140 − 100 = +40 ms, +40%; lag: 80 / 10 = 8×; 3 affected regions, population eu-1/us-1/ap-1. Calendar: 13:38:17.935840 − 13:26:17.935840 = 12 minutes, with the same targets. Meets ≥20% latency, ≥2× lag, ≥2 regions. | `investigate` → Business owner |
| Cinder / Oct 22 | P95: 100 − 100 = 0 ms; lag unchanged at 10 ms; 0 affected regions; population present. CPU 95% does not establish customer impact. | `ignore`, no recipients |
| Mosaic / Oct 08 | Union baseline 1,600; current null, `missing_union_export`. Tags are 1,200 + 1,200 with unknown intersection, so their sum is not a buyer count. Sessions cannot substitute. | `insufficient_data` → Data operations |
| Mosaic / Oct 15 | Complete marketplace union: 1,040 − 1,600 = −560 people; −560 / 1,600 = −35%, exceeding the 15% decline threshold. | `notify` → Business owner |
| Mosaic / Oct 22 | Complete union: 1,600 − 1,600 = 0 people, 0%. | `ignore`, no recipients |
| Lumen / Oct 08 | 2/2 partitions closed; watermark equals cutoff. 7,875 + 7,875 = 15,750 USD; 15,750 − 21,000 = −5,250 USD, −25%, exceeding the 10% decline threshold. | `notify` → Business owner |
| Lumen / Oct 15 | 1/2 partitions closed; watermark and receipts `source_captured_at` are Oct 12, exactly 72 hours before Oct 15 cutoff. Printed rows sum to 8,400 USD, but closure fails. **Neither baseline, current, nor delta is canonical.** | `insufficient_data` → Data operations |
| Lumen / Oct 22 | 2/2 partitions closed; watermark equals cutoff. 10,500 + 10,500 = 21,000 USD; 21,000 − 21,000 = 0 USD, 0%. No baseline bank rows. | `ignore`, no recipients |

Finance closure is stronger than mere subtraction or a plausible historical amount: all three `collections.*` definitions expressly reject baseline validation from a partial/stale export because there is no independent historical closure attestation. The Oct 15 printed difference of −12,600 USD (−60%) is therefore **not a valid collections result**. Both submissions correctly omit it and the printed baseline. Equal row sums cannot repair closure. Generic `source_status: healthy` and a fresh wrapper `captured_at` cannot override the actual watermark and source age.

Authorized routes checked exactly against `owner_answers.routing`: Cinder business `team-b38c29bd3701bb1cdceb`, data `team-d9b0b08268525cabb39c`; Mosaic business `team-cd9a62a127bfd002519e`, data `team-94a83c73f01991486e76`; Lumen business `team-3906f513bb89f0227942`, data `team-965b86f144b7c8a738b7`. These are proposed routing decisions; the packet does not independently demonstrate delivery.

## Per-ID findings

### Cinder Database Cloud

| Review ID / date | Judgment | Evidence, precise defect, and business usefulness |
| --- | --- | --- |
| review-031 / Oct 08 | Qualified | Correct `insufficient_data` to data; C-service and C-calendar were inspected and support the missing coverage and unavailable lead time. Explicitly avoids causal inference and requests a corrected export. However, `numeric_claims[0]` emits canonical `latency.delta = 0` although its public definition requires the defined customer population, which is null. Retain 100 − 100 as explicitly provisional arithmetic or omit the canonical fact. Useful data-repair escalation; not evidence of validated fleet stability. |
| review-035 / Oct 08 | Qualified | Correct `insufficient_data` to data, supported by inspected C-service; correctly rejects CPU as an impact trigger. Same narrow scope defect as review-031: an unqualified structured `latency.delta = 0` accompanies acknowledged missing population. Arithmetic is right; population validity is unresolved. Useful coverage warning, with a less explicit repair request. |
| review-020 / Oct 15 | Unsupported | C-service supports every reported quantity: +40 ms/+40%, 8× lag, 3 regions, CPU 95%. But `analysis.outcome` is `notify`, and recipients contain both business and data. Owner policy requires `investigate` to business for this complete, material condition. The summary's “investigate with data operations” does not repair the structured decision. Both IDs are generally allowed destinations, but the extra data route is not prescribed here. Useful detection, materially incorrect operational handoff. The “accounting_decomposition” wording merely combines threshold evidence; no arithmetic penalty for that label. |
| review-033 / Oct 15 | Supported | Correct `investigate` to business. Inspected/cited C-service and C-calendar support +40 ms, 3 regions, and 12 minutes; +40% and 8× also recalculate correctly. Matching targets justify investigating the rollout, while the text expressly limits timing to association. Useful, bounded incident triage. Its statement that no external notification was sent is not independently verifiable from this packet; assessment covers the proposed decision. |
| review-022 / Oct 22 | Supported | Correct `ignore` with no recipients. Inspected C-service supports zero delta, unchanged lag, and zero affected regions; inspected C-calendar supports withholding lead time because the change timestamp is null. Useful suppression of CPU-only noise; no material defect. |
| review-025 / Oct 22 | Qualified | Correct `ignore`, correct quantities, and the substantive CPU statement is supported by inspected C-service. However, `claims[1].evidence_refs` additionally cites C-capacity, which is absent from both `inspected_refs` and top-level `analysis.evidence_refs`. That source's values do not contain the cited 95% reading. Remove the redundant citation; this is a provenance defect, not fabricated arithmetic. Still useful noise suppression. |

The missing-population qualifications above are a scope reading of the public `latency.delta` definition, not an invented claim that 100 − 100 is mathematically wrong. Both outputs correctly withhold an impact conclusion. C-calendar's target list cannot reconstruct missing observed cluster coverage.

### Mosaic Exchange

| Review ID / date | Judgment | Evidence and business usefulness |
| --- | --- | --- |
| review-015 / Oct 08 | Supported | Correct `insufficient_data` to data; only the available baseline 1,600 is emitted. Inspected/cited M-union, M-audience, and M-sessions support rejecting overlap and session substitution. Requests a corrected/versioned union. Useful prevention of double counting; no material defect. |
| review-016 / Oct 08 | Supported | Same correct data route and baseline-only quantity, grounded in inspected M-union. Does not invent a current count or delta. Owner policy itself supports the warning against overlapping tags; inspecting all unrelated sources is unnecessary. Useful, concise export-repair request. |
| review-003 / Oct 15 | Supported | Correct `notify` to business; inspected/cited M-union supports 1,600 → 1,040, −560 people, −35%. Explicitly acknowledges that no driver/mix decomposition is available. Useful growth alert without a fabricated explanation. |
| review-029 / Oct 15 | Supported | Correct business notification and identical verified arithmetic/population from M-union. Subtraction is described as reconciliation; it does not claim a causal driver. Useful threshold alert; no material defect. |
| review-004 / Oct 22 | Supported | Correct `ignore`, no recipients, 1,600 → 1,600, delta 0. M-union is inspected/cited; M-audience is inspected and the public owner definition corroborates the summary's overlap warning. Useful suppression of an unwarranted growth alert. |
| review-032 / Oct 22 | Supported | Correct `ignore`, no recipients, and all three canonical quantities supported by inspected/cited M-union. “Decomposes” describes simple subtraction and adds no driver insight, but is not an arithmetic or causal failure. Useful quiet monitoring result. |

Mosaic's public definitions do not impose finance's special historical-closure invalidation on its available baseline. The missing current union prevents the comparison; it does not by itself invalidate the separately printed baseline under this packet's policy.

### Lumen Freight Finance

| Review ID / date | Judgment | Evidence, precise defect, and business usefulness |
| --- | --- | --- |
| review-005 / Oct 08 | Supported | Correct `notify` to business; inspected/cited F-receipts and F-ingest establish totals, −5,250 USD/−25%, full closure, and cutoff watermark. Correctly limits bank discussion to current 7,875/7,875 and says absent baseline bank rows prevent attribution. Useful controller alert; no cash-shortfall cause is established. |
| review-012 / Oct 08 | Supported | Same correct decision, quantities, and closure evidence. The current-bank split reconciles; explicitly refuses bank-specific attribution without baseline rows. Useful actionable collections warning; no material defect. |
| review-006 / Oct 15 | Qualified | Correct `insufficient_data` to data, empty numeric claims, and both required sources inspected/cited. The 72-hour source age and 1/2 closure are supported. But `claims[1]` asserts a “24-hour maximum” absent from public policy; catalog and snapshot `freshness_sla_hours` are null. Remove that unsupported limit and rely on failed closure/cutoff. Useful repair request that properly withholds even the baseline. |
| review-007 / Oct 15 | Supported | Correct `insufficient_data` to data and no canonical numeric claims. F-ingest/F-receipts support the incomplete partitions, earlier watermark, and provisional status of both amounts. Correctly avoids asserting missing cash or reconstructing a bank decomposition. Useful prevention of a false cash alarm; no material defect. |
| review-008 / Oct 22 | Supported | Correct `ignore`, no recipients; F-receipts/F-ingest support 21,000 → 21,000, delta 0, closure, and cutoff watermark. Restricts the equal-bank observation to the current period. Useful quiet controller monitoring; no material defect. |
| review-021 / Oct 22 | Qualified | Correct `ignore`, no recipients, totals, zero delta, and closure. However, `claims[1]` says “neither bank contributes a change versus the baseline total.” Only current east/west amounts of 10,500 each exist; baseline bank amounts are absent. Aggregate flatness cannot rule out offsetting bank changes. Remove that attribution and retain the current split. Useful aggregate monitoring, misleading bank-level reassurance. |

The complete finance submissions cite F-ingest at analysis/claim level while their individual numeric facts cite F-receipts. That provides the necessary validity context in the complete output; the public contract does not explicitly require every numeric fact to repeat the closure citation. Keeping that dependency attached when extracting facts would improve downstream reliability.

## Overall usefulness and limits

The strongest demonstrated usefulness is selecting the intended population, applying owner thresholds, escalating missing evidence, and suppressing CPU, audience-overlap, and late-bank false alarms. All numeric fact names use the public vocabulary; emitted arithmetic and units match the printed inputs. The defects concern routing, population validation, provenance, an unsupported policy limit, and unsupported bank attribution—not spelling errors or subtraction mistakes.

No selected output asserts that rollout timing proves deployment causation. Review-033 supplies a useful association and investigation hypothesis. The finance bank-attribution defect in review-021 is unsupported explanatory reassurance, not evidence of a causal mechanism. Simple subtraction and current-period splits do not explain why a metric moved.

This is an independent blind review of a bounded public packet. It is not external peer review, empirical enterprise proof, demonstrated cash-shortfall prediction, verified incident resolution, or evidence of realized business benefit. No arm identities, broader trial results, or unseen execution behavior were inferred. Only this review file was written; no paid or external calls were made.
