# Fresh bootstrap holdout v3-01: completed, failed acceptance

SignalWeave plus live Jev did not win this fresh-seed trial. Both arms completed all six setups, but treatment produced fewer exact monitoring results, two incorrect operational routes, more source reads, and substantially more agent tokens. Slightly faster monitoring did not offset those failures. This result stays failed; neither citation reinterpretation nor agent corrections turn it into evidence of autonomous system reliability.

The comparison follows the [bootstrap protocol](bootstrap-benchmark-protocol.md) and [frozen v3 rules and endpoints](bootstrap-benchmark-v3.md). Counts and resource totals below were recomputed from the 48 episode records in [results.json](evidence/bootstrap-codex-holdout-v3-01/results.json), then reconciled with its summary. Narrative findings come from the sealed [Retail/Workspace/Helpdesk review](evidence/bootstrap-codex-holdout-v3-01/review-retail-workspace-helpdesk.md) and [Cloud/Marketplace/Finance review](evidence/bootstrap-codex-holdout-v3-01/review-cloud-marketplace-finance.md), unblinded afterward with the [review key](evidence/bootstrap-codex-holdout-v3-01/review-key.json).

## What was frozen and measured

Frozen implementation: **`8dde234432ca914aa60763e102b645dba9e877f2`**. Seed **`20261002`**, holdout split, six synthetic company families, one setup and three chronological monitoring conditions per company and arm: 12 setup episodes plus 36 monitoring episodes. Fresh identifiers, ordering, and quantities do not create independent enterprises or new analytical families. The prior seed and two development regressions had already informed repairs; their failures and costs remain in the [repair ledger](bootstrap-repair-ledger.md), separate from this run.

Baseline is `luna_bi`: Luna with source tools, calculators, and persistent notes. Treatment is `luna_signalweave_jev`: the same agent plus production SignalWeave authoring/evaluation, persisted cards, and live Jev. Both requested `gpt-5.6-luna`, low reasoning, through Codex CLI `0.153.4`; observed Jev resolution was `jev-1.13.0`. This compares the integrated workflow, not an isolated Jev effect or every possible agent baseline.

Limits were 45 MCP calls and 360 seconds per Codex episode, plus a global 210-attempt Jev ceiling. Pre-agent evaluation and transport startup count in full time. The run completed without budget censoring: 48 Codex invocations, 89 Jev attempts, no failed provider attempts, missing terminal usage, runtime failures, invalid monitoring submissions, or recorded foreign-tool events. Codex's internal inference requests/retries are not observable; 48 invocations does not mean 48 API requests. All four owner-policy topics were consulted in every setup, through a scripted owner. Approval was simulated and external delivery disabled.

The [local configuration](../artifacts/bootstrap-codex-holdout-v3-01/config.json) and checked-in results retain content fingerprints as well as the revision. Dataset digest: `78b1fa45e4a7b7f8b4f71bc0cae19755b71c941fae17159c14dff5cc590c114e`; public-context digest: `5f63d6f24334af2a3efc88db5bedf5c158276c718269defb78d36bc8211cc4da`. The scenario clock was rebased to `2026-10-01T15:26:17.935840+00:00`, preserving source lag. These are fixture reporting dates, not evidence of three weeks of production operation.

## Final decisions and strict scores

| Endpoint | Baseline | Treatment |
| --- | ---: | ---: |
| Setup complete | 6/6 | 6/6 |
| Monitoring complete and schema-valid | 18/18 | 18/18 |
| Exact structured result | 15/18 (83.3%) | 11/18 (61.1%) |
| Correct final outcome and exact recipient set | 18/18 | 16/18 |
| Correct event outcome/recipients | 6/6 | 4/6 |
| Correct quality-condition outcome/recipients | 6/6 | 6/6 |
| Correct quiet-condition outcome/recipients | 6/6 | 6/6 |
| Wrong recipient sets / scorer unsafe-route flags | 0 / 0 | 2 / 2 |
| Missed events | 0 | 1 |
| Quiet false alerts / unsafe suppression of missing data | 0 / 0 | 0 / 0 |
| Complete inspected-source provenance | 18/18 | 17/18 |
| Unsupported typed causal claims | 0 | 0 |

Neither arm reached 17/18 exact. Treatment also failed the all-event and zero-wrong-recipient gates. Zero quiet false alerts does not excuse treatment's Cinder event notification where investigation was required. The structured scorer checks fields and citation dependencies; its exact flag does not certify prose or business usefulness.

Each cell below gives `review-ID: final outcome; exact pass/fail`. Dates are 2026 packet dates. All recipient sets are correct except treatment 019 and 020, detailed below.

| Company | Condition / date | Baseline | Treatment |
| --- | --- | --- | --- |
| Juniper Trail Retail | Quiet / Oct 08 | 002: ignore; pass | 024: ignore; fail |
| Juniper Trail Retail | Quality / Oct 15 | 014: insufficient_data; pass | 018: insufficient_data; pass |
| Juniper Trail Retail | Event / Oct 22 | 013: notify; pass | 017: notify; pass |
| Harbor Workspace | Event / Oct 08 | 030: notify; pass | 036: notify; pass |
| Harbor Workspace | Quiet / Oct 15 | 023: ignore; pass | 027: ignore; pass |
| Harbor Workspace | Quality / Oct 22 | 009: insufficient_data; pass | 028: insufficient_data; pass |
| Kindred Helpdesk | Event / Oct 08 | 001: notify; pass | 019: insufficient_data; fail |
| Kindred Helpdesk | Quality / Oct 15 | 010: insufficient_data; pass | 034: insufficient_data; pass |
| Kindred Helpdesk | Quiet / Oct 22 | 026: ignore; pass | 011: ignore; pass |
| Cinder Database Cloud | Quality / Oct 08 | 031: insufficient_data; fail | 035: insufficient_data; fail |
| Cinder Database Cloud | Event / Oct 15 | 033: investigate; pass | 020: notify; fail |
| Cinder Database Cloud | Quiet / Oct 22 | 022: ignore; pass | 025: ignore; fail |
| Mosaic Exchange | Quality / Oct 08 | 015: insufficient_data; pass | 016: insufficient_data; pass |
| Mosaic Exchange | Event / Oct 15 | 003: notify; pass | 029: notify; pass |
| Mosaic Exchange | Quiet / Oct 22 | 004: ignore; pass | 032: ignore; pass |
| Lumen Freight Finance | Event / Oct 08 | 012: notify; fail | 005: notify; fail |
| Lumen Freight Finance | Quality / Oct 15 | 007: insufficient_data; pass | 006: insufficient_data; pass |
| Lumen Freight Finance | Quiet / Oct 22 | 021: ignore; fail | 008: ignore; fail |

The paired exact results are 11 both-pass, three both-fail, four baseline-only passes, and zero treatment-only passes. Conditions within a company are correlated; these are not 18 independent enterprise trials.

## What failed, and where

The baseline's three exact failures are one unavailable population and two finance citation failures. Treatment shares those three and adds a wrong total, a missed service event, an incorrect incident handoff, and an uninspected citation. Those distinctions matter:

- **Wrong numbers:** treatment review-024 reports USD 25,200 as both Retail totals instead of USD 36,000. It omits USD 10,800 of shop proceeds. The zero change and ignore decision remain correct. These are the run's two `wrong_value` numeric diagnostics, within one output.
- **Unavailable scope:** reviews 031 and 035 correctly escalate missing customer-cluster coverage, yet emit canonical `latency.delta = 0`. The subtraction 100 − 100 is right; the population needed to validate that metric is absent. One `unavailable_scope` diagnostic per arm, not a subtraction error.
- **Strict numerical citation failure:** finance reviews 012/021 and 005/008 have correct amounts and valid closure evidence in the overall submission, but each numerical fact cites receipts without its required bank-control dependency. Each arm has six `invalid_citations` numeric diagnostics across two outputs. These do not mean six wrong numbers. Frozen scoring gives those facts no credit and marks the required delta missing; scores are retained unchanged.
- **Operational failures:** treatment review-019 routes to Data rather than notifying the business owner about SLA attainment falling 0.90→0.75. Review-020 notifies both business and Data instead of investigating with business, and omits the rollout-calendar evidence and required 12-minute lead-time fact. A generally authorized destination can still be wrong for the condition.
- **Narrative provenance:** treatment review-025 adds an uninspected, unlisted capacity-source citation to a CPU statement already supported by the inspected service source. Remove the extra citation; this is not fabricated arithmetic.

The [retained full report](../artifacts/bootstrap-codex-holdout-v3-01/report.json) supplies narrower mechanism evidence. Helpdesk's card uses `Previous complete reporting week`, while its source uses `previous_period`; the computed analysis explicitly rejects the window despite contiguous complete weekly intervals. Harbor's card puts `previous_period` in `required_comparison_keys`, while the actual key is `retention`; complete analyses coexist with a required-source failure. These are authoring/contract integration defects. Cinder's persisted delivery mapping assigns business to notify and Data to investigate, contrary to owner policy, has no insufficient-data delivery method, and includes only the service source rather than the rollout calendar. Setup completion therefore did not establish policy-correct cards.

Native system outcome correctness was **11/18**; recipient correctness was separately **11/18**. Only **9/18 had both correct**. The agent changed seven native outcomes: six corrections and one degradation, Cinder's investigate→notify event response. A recipient-only correction, Cinder quality, is not counted as an outcome override. Final treatment routing improved to 16/18, but that must not be reported as native automation accuracy. Retail quality and Finance quiet also show low-support distributions followed by investigation; the persisted results expose confidence-policy interactions, not proof that Jev alone caused the failures. The experiment has no Jev-only or retrieval-only ablation.

## What the blind reviews add

The sealed internal reviews cover all 36 nonempty final narratives, with no unassessed outputs. Their recorded judgments aggregate after unblinding to baseline **14 supported / 4 qualified / 0 unsupported**, treatment **11 / 4 / 3**. Each output received one review; this is not overlapping inter-rater agreement or external peer review. Classification criteria vary slightly between the two reports, so these counts remain descriptive.

The three treatment outputs judged unsupported are the Retail total, missed Helpdesk alert, and Cinder handoff above. Review also catches defects beyond the structured score: baseline Finance 021 claims neither bank contributed a change despite missing baseline bank rows; treatment Finance 006 asserts a 24-hour maximum absent from the public owner policy. Unblinding finds `max_source_age_hours = 24` in the authored card, explaining the runtime reference without establishing it as an owner-specified rule. Neither issue is a numerical subtraction failure. No reviewed narrative establishes a causal mechanism from rollout timing or accounting contributions.

Review/scorer disagreements remain visible. The Finance reviewer accepts closure citations attached at whole-output level, whereas frozen v3 scoring requires them on each canonical numerical assertion. The reviewer notes that the public submission contract does not explicitly state that per-fact repetition requirement. We preserve both the strict failure and the less severe narrative assessment. Retail reviews 002, 013, and 017 are qualified because their packet lacks affirmative posting-closure evidence; no extra mandatory Retail closure field was specified. That qualification is not a retrospective outcome rescore or an extension of Finance's special rule to Retail.

The [blind packet](evidence/bootstrap-codex-holdout-v3-01/blind-review.json) now includes the full existing public `numeric_vocabulary` and `submission_contract`, including `numeric_definitions`. The review exporter fix added those omitted fields; it changed neither the benchmark, inputs given to the running agents, results, nor scorer. In Finance, the public rule explicitly requires all bank partitions closed and the watermark at cutoff, and invalidates even the baseline on a stale/partial export without historical closure attestation. Both arms correctly withhold all canonical collections quantities in that condition. A plausible printed historical amount is insufficient. The original results file's “pending” narrative-review status is retained as a historical artifact; the sealed reviews linked here supply the subsequent assessment.

## Time, calls, tokens, and illustrative dollars

These totals include setup, review/approval/simulation work, repeated calls, and all monitoring. Source reads include internal SignalWeave reads. Timings are sums of recorded full episode wall time, not isolated model latency or warehouse benchmarks. The run alternates arms across chronological episodes under the seeded schedule; the small monitoring timing difference does not establish a stable latency advantage.

| Resource | Baseline | Treatment |
| --- | ---: | ---: |
| Setup / monitoring seconds | 165.04 / 475.21 | 449.06 / 449.23 |
| Total episode seconds | 640.25 | 898.29 |
| Monitoring median seconds | 25.04 | 24.27 |
| MCP calls, setup / monitoring | 60 / 83 | 106 / 83 |
| MCP calls, total | 143 | 189 |
| Source reads, setup / monitoring | 15 / 44 | 19 / 62 |
| Source reads, total | 59 | 81 |
| Scripted owner question calls | 24 | 26 |
| Codex invocations, setup / monitoring | 6 / 18 | 6 / 18 |
| Agent input tokens | 1,488,520 | 4,203,856 |
| Cached input tokens, subset of input | 1,184,512 | 3,479,040 |
| Agent output tokens | 20,359 | 30,112 |
| Agent input + output, setup / monitoring | 450,466 / 1,058,413 | 2,769,160 / 1,464,808 |
| Agent input + output, total | 1,508,879 | 4,233,968 |
| Jev attempts, setup / monitoring | 0 / 0 | 71 / 18 |
| Jev input / output tokens | 0 / 0 | 327,693 / 14,211 |

Treatment used **180.6% more agent tokens** and **40.3% more total episode time**. Monitoring time alone was 5.5% lower. The preregistered resource endpoint required at least 20% fewer total agent tokens, no fewer exact cases, no additional safety failures, and all quality gates met. It failed on every one of those requirements. Both arms woke Luna for every period; there are no measured wakeup savings.

All 89 Jev attempts have recorded usage, with no failed or unknown-usage attempts. Setup accounts for 219,882 input / 12,303 output tokens; monitoring for 107,811 / 1,908. Combined Codex usage is 5,692,376 input tokens, including 4,663,552 cached, plus 50,471 output. Cached input is included once, not added to total input or treated as zero work. Recorded setup tool activity includes eight treatment drafts, ten reviews, nine simulations, and eight approval calls; one completed setup is not one semantic call.

Using the run's dated September 30 price assumptions per million tokens—Luna input $0.20, cached input $0.02, output $1.20; Jev input $0.042, output $0—the estimates recompute as follows. These are illustrative token-price calculations, **not Codex subscription bills or provider invoices**; rates were not refreshed for this report.

| Illustrative USD | Baseline | Treatment |
| --- | ---: | ---: |
| Setup, including Jev | $0.027831160 | $0.141952364 |
| Monitoring, including Jev | $0.081091480 | $0.122489142 |
| Codex component, total | $0.108922640 | $0.250678400 |
| Jev component, total | $0 | $0.013763106 |
| Observed setup + three periods, total | $0.108922640 | $0.264441506 |
| Total divided by 18 scheduled monitoring runs | $0.006051258 | $0.014691195 |

The last row amortizes only the observed setup across the three measured periods per company. It assumes no future savings. Synthetic source billing, real warehouse latency, and real-human effort remain unmeasured. The [two retained regressions](bootstrap-repair-ledger.md) separately consumed 16 Codex invocations and 26 Jev attempts; they are development effort, not extra holdout observations.

## Remaining gaps and targeted retest

The useful behavior is bounded: selecting the intended population, suppressing mix/volume/CPU noise, and escalating missing exports. It does not establish realized customer benefit, incident resolution, cash prediction, enterprise reliability, or causal diagnosis. The six families have tiny catalogs and normalized in-process sources. Agent-authored approvals were scripted. Cross-period baseline values also do not consistently reconcile to the previous packet's current values, with no revision history; this is not a validated longitudinal ledger.

The next useful work is a targeted regression, followed only if justified by a newly frozen prospective test:

1. Replay the comparison-window aliases, required comparison-key selection, and Cinder outcome/destination mappings against public policy. Check the persisted card and native route before crediting agent rescue; retain unknown-window and missing-evidence failures.
2. Regress Retail all-channel summation, Cloud missing-population abstention, and Finance closure/citation dependencies. Test correct and incorrect values separately from missing provenance. Clarify the public per-fact citation requirement prospectively, without changing these scores.
3. Recheck narrative bank attribution, card-derived versus owner-derived freshness rules, and rollout association. Explicit historical closure or posting-completeness evidence would need a versioned dataset change, not a silent assumption.
4. Freeze any repairs, prompts, public contract, scorer, and resource endpoint before another measured run. A fresh seed in these families can test regression generalization; new families, messy connectors, real owners, and a shadow pilot are separate evidence gaps. No paid retest was run or promised here.

The full [local report](../artifacts/bootstrap-codex-holdout-v3-01/report.json), [trace](../artifacts/bootstrap-codex-holdout-v3-01/trace.jsonl), and [configuration](../artifacts/bootstrap-codex-holdout-v3-01/config.json) retain execution evidence; local artifacts may not accompany a repository checkout. The full report SHA-256 was independently checked against `results.json`: `82c49fb4ef55f6cad3a09327203cc9c6f6da7f81cc67fbf5bc7e265a025bc2c0`. This reporting pass writes only this document and makes no result, scorer, production, or paid-call changes.
