# Domain-context preview evidence

Updated 2026-10-16. Feature branch: `feat/domain-context-memory`; [draft PR #19](https://github.com/waddle-zoo/signal-weave/pull/19). Main and the published download are unchanged.

## Current result

**Actual shared-context retrieval and live card decisions worked in two retained courier readouts. A comparative business advantage is not established.** Both equal-information arms produced supported outcomes and proposed recipients. The independent reader preferred the baseline's data-repair explanation; treatment added a useful numerical breakdown to the decline but was denser and used more tokens.

The [public excerpt](../../evaluations/data/retained-context-courier-summary.json) preserves the four unchanged prepared messages, final chat acknowledgements, source facts, actual retrieved definition, native results, usage, review findings and artifact hashes. These are two observations of one known fictional company—not four companies, a precision estimate, customer validation or a repaired onboarding result.

## Latest study: retained-context-courier-v1

The study reused the **actual** agent-authored notes, saved approved card and separately reviewed definition from v7. Nothing was imported, reconstructed, manually completed or reapproved. The definition remained unbound; this tests standalone retrieval, not automatic card dependency use. Both original onboarding reviews remain rejected and unattended readiness remains unqualified.

Four fresh Luna-medium reporting invocations, two live Jev requests, no retry. Each arm recovered its own stored brief through tools rather than receiving pasted notes. Both retained the same company-source, glossary and calculator tools. Treatment added the current native MCP and bundled workflow skill, and received its actual saved context ID—not the note body. Both treatment reporters fetched that exact reviewed revision and evaluated the saved card delivery-disabled.

Sources were normalized synthetic company-MCP exports, not live vendor dashboards or warehouse queries. Shared primary observations, evidence and comparisons matched across arms. The source's declared measurement windows were separate from the actual capture clock. Current approved policy was replayed retrospectively; no historical approval is asserted.

| Observation | Equal-information agent | Agent + SignalWeave/live Jev |
| --- | --- | --- |
| Missing current eligible-parcel denominator | `insufficient_data` → Data Operations; no business alert | Same final route and native outcome |
| Overall SLA decline | 90% → 75%; proposed Business owner notification | Same route; native outcome `notify`; correct tier decomposition |

For the missing-data observation, the previous total was 5,220/5,800; the current numerator was 10,440 but its denominator was absent. An export's “complete/comparable” label did not establish the missing rate. The baseline also read the current handbook note identifying a missing open-overdue-population export; treatment omitted this useful diagnostic context.

For the decline, 5,220/5,800 → 8,700/11,600 is a 15-percentage-point drop, exceeding the owner's 5-point trigger. Each tier declined 90% → 75%; equal tier weights yield −7.5 points each and zero mix. These are accounting explanations, not causes. Neither source established a causal mechanism.

A separate Luna-xhigh reader saw full source facts and policy, without the arm map, costs or a requested winner; message content could reveal tooling. It verified the calculations/routes but flagged treatment's omitted repair context, potentially misleading contribution caveat on the incomplete case, and excess operator jargon. Treatment's decline breakdown was supported but denser than baseline. This is one independent internal review, not external peer review.

The research sink recorded proposed reports; final chat replies acknowledged them. No Slack/email notification or schedule was exercised. A correct prepared message is not evidence of actual human delivery or installer usability.

## Observed work, not claimed savings

| Report-only measure | Equal-information agent | Agent + SignalWeave |
| --- | ---: | ---: |
| Agent tools by observation | 6, 7 | 3, 5 |
| Analytical source reads | 2, 2 | 1, 2 |
| Agent seconds | 13.47, 22.01 | 10.85, 34.70 |
| Total agent input / uncached | 170,246 / 47,494 | 283,749 / 55,013 |
| Additional Jev input / output | — | 12,317 / 262 |

All four invocations completed within the fixed cap: 453,995 input / 351,488 cached / 102,507 uncached / 3,267 output. Usage includes each saved-login invocation's internal model/tool turns; “four invocations” does not mean four underlying OpenAI HTTP requests. Original onboarding usage remains separate in the excerpt, not erased or amortized into a claimed win. Provider billing is unknown.

Treatment's second decline source read was redundant. Its native packet already included original totals, tier counts, windows and the declared freshness contract. The agent nevertheless reread the same source “for additional freshness or tier detail.” Fewer tools did not prevent this duplicate, establish a cost advantage, or measure avoided Trino queries. The baseline's extra handbook read improved the repair explanation. Timing samples and synthetic fast sources do not establish general speed.

## Engineering findings

- **Known-reference retrieval:** a 311-note synthetic repro showed an opaque context ID was not a lexical match and could be omitted from a crowded source-anchor packet. History could recover it. The existing retrieval tool now accepts up to twelve exact IDs, with normal current-revision, authorization and response limits; no new tool or context injection into Jev.
- **Visibility race:** three failing repros showed retrieval could return old text after a revision/visibility change during asynchronous source authorization. Final selected-entry rechecks fixed them. A follow-up failing history repro exposed the same current-visibility gap; its final check now covers that endpoint too.
- **Agent guidance:** the monitor guide now starts with the authorized card ID's evaluation, which returns active card guidance and evidence. The guide/skill identify `analyses[].comparison` and `source_contracts` before a repeat query, recommend useful linked diagnostic context, and separate irrelevant operator settings from the business message. These follow-up instructions have not been behaviorally revalidated; the closed study is not rerun or rescored.

At the paid build, `make verify` passed **3,705 tests / 11 skipped in 280.44s**. The subsequent history/guidance corrections passed **179 focused checks in 10.00s**, lint and bundled-skill validation. Software checks are not additional business trials.

## Identity and reproduction

The paid study and its successful zero-inference preflight used clean native build `1c5623561c6f2cdd187768d22c0ac0e365fd7cda`:

- Source/skill fingerprint: `cc1530aa2d132b9175e77dcc6f724137e5fa2f47dd1e74c37db8dd39c8086faf`.
- Binary SHA-256: `34a65a4819afcc95f04017f2ab97bfca1558099b7e3086137273b04d823e8a64`.
- Report / trace SHA-256: `181b0bd995af3f6c7f7e915b9163f2c76eb50791f0ccefa04900c3db12d59a83` / `7811301744d1e50be27a6c264e99a676c32d9502401768fe9b05e41c3f0bbd85`.

These identify a local build and ignored raw artifacts, not a new published release or public replay from Git alone. The runner pins Codex CLI 0.162.0-alpha.2 and current native/skill fingerprints. The retained original home is required; missing/changed artifacts are rejected rather than reconstructed.

The [manifest](../../evaluations/data/retained-context-courier-v1.json) fixes observation indices 1/2 and alternating arm order. Caps: four Luna invocations, twelve tools/180 seconds each, at most two Jev requests; 600k input/150k uncached between-invocation stops, unknown usage or transport/frozen-input failure. These thresholds are not hard in-flight billing caps. No retry or budget increase.

For a **new, separately authorized study**, build current source and run the zero-inference preflight first:

```sh
uv run python scripts/build_binary.py
uv run python -m evaluations.retained_owner_periods --context-readout \
  --binary dist/signalweave --prior /path/to/original-v7-artifacts \
  --codex-executable /path/to/pinned/codex --output artifacts/new-preflight
```

Live inference requires a matching successful `--preflight /path/to/report.json`, a new output directory, `--run --key-file /path/to/private/jev.key`, and its own authorized budget. This completed cohort is closed. Preflight verified both source observations, current reviewed context and unchanged card. Both runs restored the original research connection files' bytes/modes and removed their private backup copies. The runtime credential was independently verified to be the original synthetic dummy, not the live key. The personal key and agent configuration were untouched; new research receipts persisted.

## Earlier evidence retained, not pooled

[The preceding full evidence report and archive chain](https://github.com/waddle-zoo/signal-weave/blob/3b8c99b/docs/evidence/domain-context-preview-2026-10-14.md) preserve previous messages, negatives, identities, usage and review disagreements.

| Earlier series | Finding retained |
| --- | --- |
| Fresh retail v5 | Actual discovery, authored card, scripted approval and useful live-Jev report; both arms correct, reader slightly preferred baseline, treatment cost more. Reviewed context was not retrieved. |
| Retained retail observations | Missing-data and quiet routes matched in both arms; reader preferences split. Same source reads and more treatment uncached tokens. [Excerpt](../../evaluations/data/retained-owner-periods-summary.json). |
| Courier v6/v7 setup | V6 stopped before treatment; v7 both authored setups but reviews rejected, including a false treatment comparison-key objection. No later reports or Jev requests; not repaired by this study. [V7 excerpt](../../evaluations/data/courier-owner-v7-summary.json). |
| Permission/native checks | Prepared-card handoffs, exact approval fingerprint, context lifecycle/restart and signed HTTP contracts worked; synthetic auth is not customer SSO or human usability. |
| Other earlier negatives | Incomplete onboarding, false numeric review, parcel-volume omissions, unknown usage, transport and message-quality findings remain in the archive—not discarded or counted as current passes. |

## Remaining acceptance gates

Fresh real-human onboarding; multiple businesses and raw connector shapes; scaled noise/recall; context updates improving investigation; multi-step evidence gathering and causal restraint; realistic query costs; amortized benefits; customer SSO; and actual authorized scheduling/delivery remain unproven. Alert-only screening and routine reporting also need separate comparisons: a study that always launches a frontier reporter cannot establish savings from suppressing quiet alerts. No enterprise-readiness or overall superiority claim is made.
