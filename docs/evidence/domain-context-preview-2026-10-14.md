# Domain-context preview evidence

Updated 2026-10-16. Feature branch: `feat/domain-context-memory`; [draft PR #19](https://github.com/waddle-zoo/signal-weave/pull/19). Main and the published download are unchanged.

## Current result

**Raw-source onboarding now completed through a saved, reviewed card, real native approval, live Jev and fresh agent reports. A comparative business advantage is not established.** Both arms produced supported reports in this one known-company observation; SignalWeave used more tokens overall. The separate retained-context courier results below remain mixed and unchanged.

The [public excerpt](../../evaluations/data/retained-context-courier-summary.json) preserves the four unchanged prepared messages, final chat acknowledgements, source facts, actual retrieved definition, native results, usage, review findings and artifact hashes. These are two observations of one known fictional company—not four companies, a precision estimate, customer validation or a repaired onboarding result.

## Completed raw-source workflow: raw-northstar-workflow-v2

The [retained record](../../evaluations/data/raw-northstar-workflow-v2-summary.json)
contains unchanged submissions, actual card policy, source excerpts, per-phase
usage, native judgment and post-run findings. This is a **new formative study**
after the repairs below, not a retry or rescore of either closed v1.

Both fresh authors discovered the running local Superset catalog, inspected
saved queries, wrote a first answer and saved their own reusable context.
Treatment authored its actual two-chart card: monthly Executive sales plus
reporting cutoff. Separate fresh same-model reviewers accessed source evidence
and qualified both proposals. Scripted owner consent applied to that exact card;
native approval then revalidated it. Two fresh reporters used the identical
approved policy and destinations, their own notes and the same companion BI
tools. Treatment additionally evaluated the unchanged card with live Jev.

**Both final reports were useful and numerically supported:** August net sales
were 2,292,267.50 versus July's 2,158,994.74 (**+6.17%**). Online contributed
61,949.94, or **46.48%** of the increase. September ends on the 19th, so neither
treated its raw full-August difference as a comparable sales collapse. Both
proposed `insufficient_data` to Data Trust and a matched-day follow-up. Currency
is undeclared. Completeness of earlier days depends on the fictional owner's
declaration, not a provider guarantee. Contributions are not causal findings.

| Observed work | Company tools + agent | Plus native SignalWeave/skill |
| --- | ---: | ---: |
| Author tools / seconds | 31 / 171.5 | 26 / 208.3 |
| Expert-review tools / seconds | 6 / 60.7 | 7 / 49.6 |
| Fresh-report tools / seconds | 15 / 115.7 | 19 / 85.3 |
| All-phase input / uncached tokens | 451,681 / 134,497 | 948,040 / 205,512 |

These are six agent episodes, not six underlying model HTTP requests. Jev adds
one request with 10,032 input and 152 output tokens, about 1.05s wall time. Its
typed result was `insufficient_data`, Data Trust, with uncalibrated support 0.97.
It supplied no analytical comparisons: frontier agents calculated the supported
closed-month readout from chart rows. The shorter observed treatment reporting
time does **not** establish speed or cost savings; it used more tools and tokens.

What remains unproven or failed:

- The baseline's first answer invented dollar units, and its qualifying reviewer
  missed that error. Its final report removed them. Preserve the original review
  result; this post-run finding is not a rescore or proof that reviewer approval
  alone establishes correctness.
- Neither arm completed the matched-day follow-up. The research companion tools
  expose at most 250 rows per page; 8,937 detail rows need 36 pages, beyond the
  24-call reporting cap. Both attempted an invalid oversized read. This is a
  harness capability gap, not evidence that SignalWeave cannot investigate.
- Treatment fetched a receipt and source contracts already present in its
  roughly 50k-byte evaluation response. Duplicate evidence and handoff size are
  concrete efficiency work, not measured benefits.
- Only proposed role destinations were recorded. No Slack endpoint was resolved,
  message sent or schedule activated. Approval remains delivery-disabled with
  acceptance unassessed; missing metric contracts remain visibly unverified.

The arms had phase-specific tools, fixed order and separate caches; neither had
arbitrary SQL or shell. Source reads were not an atomic snapshot. Native query
telemetry reports zero but does not measure warehouse cost; companion counts
exclude native reads. This one known fixture is neither a holdout nor the
strongest production baseline. No accuracy estimate, amortized cost advantage,
real-human installation result or enterprise-readiness claim follows.

Exact executed method: `39b4f78b70f85241062562f13bd7051839b47229`;
[closed manifest](../../evaluations/data/raw-northstar-workflow-v2.json).
The source/skill SHA-256 is
`5a96678d8a00bdea06086c7539bda2f375fd8dd5ce012647f7aeb89b5bad3479`,
binary SHA-256
`705067faef93c2bcb88aed55ddd9d4b36e6fe71b21fd6ce6b7d514ac37ab699a`.
Report/trace hashes are in the retained record. The cohort is closed: no rerun,
rescore or transfer of its unused allowance. The existing Northstar Superset
installation is a reproduction prerequisite, not a bundled warehouse fixture.

Production-repair checks passed **3,854 tests / 11 skipped**; additional method
checks and scoped independent code/method reviews passed before execution.
[All three native CI builds passed](https://github.com/waddle-zoo/signal-weave/actions/runs/38879568741)
at the exact method commit; publishing was skipped. Those install/MCP checks use
fixture transport and dummy credentials, not analytical judgments or real-human
usability evidence. No new release or main merge is implied.

### Post-study engineering checks (not additional agent trials)

An inference-free replay of the recorded evaluation response removed exact
duplicate report evidence and workflow plans: **48,673 → 38,419 UTF-8 bytes**
using compact JSON serialization, with other top-level fields and canonical
evidence unchanged. Full receipts retain both original structures. This is a
21.1% serialized payload reduction, not a measured token, cost or agent-time
improvement. Agent behavior with the changed packet still needs a forward test.

The research companion now has an **explicitly opt-in** `aggregate_chart_rows`
tool shared equally by future arms. It filters raw saved-query rows and groups
SUM/count without new SQL, date inference or warehouse-completeness claims.
Invalid request definitions fail before source I/O; source-column checks follow
the actual read. Definitions have a 16 KiB pre-I/O limit. Decimal accumulation
uses the parsed values; it cannot recover precision already lost in the
provider's JSON-to-float conversion. The source client can cap a saved query:
retained row counts and declared limits do not certify complete query output.
It does not change the closed v2 tool set or results.

A read-only check against the same running detail chart used a profile and two
aggregations: one saved-chart query, 8,937 returned rows, both aggregates served
from that local helper cache. Each selected 171 rows and four channel groups.
UTC epoch-millisecond predicates were `>= 1785542400000, < 1787184000000`
(August 1–19) and `>= 1788220800000, < 1789862400000` (September 1–19).
An independent direct Decimal loop over the original returned rows agreed:

| Matched-day source result | August 1–19 | September 1–19 |
| --- | ---: | ---: |
| Total net sales | 1,406,132.46 | 1,371,704.27 |
| Online net sales | 512,288.35 | 484,648.16 |

That is **−2.45% total / −5.40% Online**, not the raw −40% full-month difference.
This demonstrates the repaired companion capability, **not** an autonomous
agent investigation, a causal explanation or a SignalWeave advantage. It does
not substitute matched-day policy for the card's approved calendar-month policy.
No model or Jev requests, notifications or source writes occurred. Warehouse
coverage and query cost remain unverified; this is not a new cohort score.

Scoped internal reviews accepted the compact projection and returned-row
aggregation after the request-size fix. Final verification passed **3,914 tests /
11 skipped in 290.03s**, including default-agent compact evaluation, lossless
receipt reconstruction and invalid aggregate requests rejected before I/O.
These are software checks, not more enterprise trial observations.

Fresh local native build `a771be96c85e33a0d138d3789b58bd5615c00ead`
also passed isolated offline setup, bare `serve` outside the checkout, health,
agent configuration and Jev/OpenAI Decisions/ChatGPT-plan configuration checks.
Through the normal agent profile, it recovered the actual approved v2 card and
replayed its saved run: reference reconstruction matched the earlier compact
facts, full stored result and card policy stayed unchanged, delivery stayed
disabled and a zero-budget proxy observed no Jev attempt. Its packaged skill
matched the canonical file. This is compatibility proof, not fresh analysis,
a real-person usability test or a newly published download.

Source/skill SHA-256:
`32c57528b654ab433008b796bf584f95004dbef85652a06c3bec8062c106cef7`;
binary SHA-256:
`ee2115c2e0d25653973a7e372a23d29cefb905b596d5bc37064d62c2cebdbef4`.
Private replay/offline-smoke record SHA-256:
`24af4fe877c60d58ee8b45581d930609370a52b01a7d94fae5e9fdeab5cbfb30` /
`8a8f7aef5eb6247eb205495e73b653cff0640b3d3ee43f68bea20e036c5b9f94`.

## Raw Northstar onboarding attempt: censored, not product evidence

The new `raw-northstar-onboarding-v1` attempted discovery over the running local
Superset catalog (48 dashboards), without prepared cards or normalized scenario
snapshots. Both intended arms had the same saved-query BI tools, calculator,
owner declarations and notes; treatment would add the current native MCP/skill.
This was authoring only, not an installer, recurrence or Jev study.

**The baseline reached the preregistered 24-tool ceiling before saving its
report. The SignalWeave arm never ran.** Its captured source profile contains the
partial September cutoff, and its recorded calculations give the closed-month
total change; neither constitutes a useful delivered report or completed onboarding. The transport
terminated without final usage; observed response counters of zero are not zero
spending. No cost, accuracy or comparative result can be inferred.

The [compact retained record](../../evaluations/data/raw-northstar-onboarding-summary.json)
contains the actual partial message, calls, recorded calculations, daily-source
profile and immutable report/trace hashes. The cohort is closed, with no retry,
rescore or transfer of its unused allowance. The cap/accounting design is the
experimenter's defect, not a SignalWeave or baseline quality result. Independent
preflight review cleared source access and isolation; it did not establish that
24 calls were adequate. A future study must test that question and graceful
accounting before paid execution.

The exact executed method is retained at commit `e8f3a6d`. Current code refuses
live execution of this closed cohort before any source/model work. Subsequent
inference-free repairs make work limits explicit, opt future episodes into the
existing bounded accounting drain, and represent missing/duplicate invocation
receipts as unknown usage rather than zero. They do not raise this cohort's
cap, complete its missing reports or demonstrate improved agent behavior.

At that earlier attempt, native/source identity was `e5ae9ca` as recorded below. Both
zero-model preflights passed; the full suite passed **3,751 / 11 skipped in
287.63s** before the attempt. No approvals, Jev requests, schedules or sends
occurred. Only dummy provider credentials were used; personal settings and
the live Superset dataset were not changed.

After the reviewed accounting/closure repairs and helper cleanup, the final full
suite passed **3,754 / 11 skipped in 280.54s**. The shared helper shrank from
554 to 367 lines; its twenty unchanged tests pass, and an inference-free replay
matched the frozen schemas plus five query/profile/page responses. The raw
trial hashes and executed method remain unchanged. These are software/method
checks, not additional business trials. Reproducing raw source access requires
the existing local Northstar stack; the compact record is not a warehouse export.

## Full raw-source workflow attempt: first answers worked, onboarding unfinished

`raw-northstar-workflow-v1` used the real local Superset catalog and current
native MCP, not prepared cards or normalized scenario exports. Both authors
completed a useful first readout. Separate process review verified the numbers:
August versus July was **+6.2% total sales**, Online **+7.9%**, contributing
**46.5%** of the total increase. September ends on the 19th; its raw −40.2%
overall difference is not a comparable full-month decline. Currency is not
declared; capture time establishes no freshness SLA.

| Observed onboarding work | Company tools + agent | Plus native SignalWeave/skill |
| --- | ---: | ---: |
| Tool calls / seconds | 28 / 92.9 | 55 / 221.2 |
| Input / uncached tokens | 212,614 / 44,934 | 688,837 / 81,349 |
| Output tokens, including reasoning | 9,094 | 29,187 |

Treatment scanned all 8,937 detail rows and saved a v2 draft using that table
as its only required numeric source. The prose policy matched the owner, but
the adapter had no validated recurring comparison for it and its normalized
numeric value was null. Treatment also skipped formal review: the old tool
description incorrectly suggested fixed review required Jev ranking. **No
approved or functioning recurring workflow was established.** This whole-path
comparison also asks treatment to create a card; it is not an isolated Jev
speed/cost ablation or a general performance estimate.

The next research stage failed when its review-packet builder tried to copy
every raw page into a 180k-byte packet. It stopped before expert qualification,
approval, fresh reports or Jev calls. The cohort is closed without retry,
rescore or allowance transfer. [Unchanged readouts, draft, usage and hashes](../../evaluations/data/raw-northstar-workflow-summary.json)
preserve the actual results; exact executed method: `37beb80`. Earlier unknown
cost remains separate, so there is no end-to-end or amortized savings claim.

The diagnosed repairs now preserve bounded source-owned query declarations,
including during existing dashboard metadata fetches, without inferring
business meaning or completeness. Agent-only query provenance remains in the
snapshot but is excluded from recurring judgment input. Fixed-source review
guidance now describes its actual no-ranking path, and the skill favors a
declared aggregate over unnecessary detail scans. These changes still need a
forward usability test; green software checks do not establish that agents
will choose an executable recurring source. The expert-review harness also
needs selective evidence access rather than a larger raw-page prompt.

Source-repair validation at `f017d2f`: **3,821 tests passed, 11 skipped**;
internal adversarial code review accepted the bounded projection after fixes
for recursive parameters and peak-allocation guards. The clean native build
then inspected the real monthly chart (5 observations), coverage chart (1),
and Executive dashboard (44), preserving all ten saved query definitions.
No source errors or provider requests occurred; only dummy decision credentials
were configured. This proves the source plumbing, **not completed onboarding**:
the proposed routed card still failed review with `comparison-window-mismatch`
and `source-contract-required`. Integrated offline tests reproduce that
distinction without erasing destinations or inventing business contracts.

Native source fingerprint:
`a408064158580dad2fcecdc7efb04888a5c8e17eb79349a662c4f20a630e671c`.
Binary SHA-256:
`6d9de48991ffe76b2a8035084af1b92899d26dba7bc48646c309d3f75429c377`.
Private `raw-source-readiness-post-review-v2` report/trace SHA-256:
`022a124a322d2c812c21aa4342cbcf2732058727be5972e416042e0f830b059e` /
`d28d04901edc2c972fac4eefe94ee26a3dd579354ef77609f31e2d46b9ea219f`.
The [plan](../domain-context-plan.md#raw-source-readiness-initial-failure-and-forward-repair)
includes the reproduction command and operator-selected input. This local
artifact is not a published release or a human installation trial.

## Completed readout study: retained-context-courier-v1

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

A subsequent zero-inference audit of those unchanged request records found a
larger treatment input surface: **16 tools / 14,147 bytes** of canonical
tool-definition JSON and a **21,934-byte** opening prompt, versus baseline's
**6 tools / 2,137 bytes** and **3,727-byte** prompt. Both observations used these
same sizes. Treatment received the full installed workflow skill and native
instructions, not just a focused recurring brief. These are serialized UTF-8
sizes, not model tokens, actual internal wire formats or an isolated causal
explanation of the usage difference. A focused recurring-run handoff is a
concrete next efficiency experiment; this audit does not establish savings or
justify removing the agent's company tools.

## Engineering findings

- **Known-reference retrieval:** a 311-note synthetic repro showed an opaque context ID was not a lexical match and could be omitted from a crowded source-anchor packet. History could recover it. The existing retrieval tool now accepts up to twelve exact IDs, with normal current-revision, authorization and response limits; no new tool or context injection into Jev.
- **Visibility race:** three failing repros showed retrieval could return old text after a revision/visibility change during asynchronous source authorization. Final selected-entry rechecks fixed them. A follow-up failing history repro exposed the same current-visibility gap; its final check now covers that endpoint too.
- **Agent guidance:** the monitor guide now starts with the authorized card ID's evaluation, which returns active card guidance and evidence. The guide/skill identify `analyses[].comparison` and `source_contracts` before a repeat query, recommend useful linked diagnostic context, and separate irrelevant operator settings from the business message. These follow-up instructions have not been behaviorally revalidated; the closed study is not rerun or rescored.

At the paid build, `make verify` passed **3,705 tests / 11 skipped in 280.44s**. The subsequent history/guidance corrections passed **179 focused checks in 10.00s**, lint and bundled-skill validation. Software checks are not additional business trials.

Final clean verification after those corrections: **3,706 passed / 11 skipped in 293.42s**. Independent scoped code review found no remaining blocker. A current-native read check recovered the actual reviewed entry, its two history revisions and the saved live-Jev receipt in six MCP operations, preserving the card and the stored outcome, probabilities, analyses, source contracts and observations. Zero model/provider calls or analytical source reads. This verifies compatibility and the shipped guide, not whether an agent follows the new guidance.

That final local build is `e5ae9ca8c1baafb2dfc899f6f97bcb46af7dd8c4`, source/skill fingerprint `1a6bdb32b192ab710f1e4c7453df83ebacf1f7ee903c9a0c239c73bef81ac400`, binary SHA-256 `06664ecd42571c314b796f23226a74a5c3a8c02eddc3484c16ed5f8b9ce5805c`. The paid study's earlier identity below remains unchanged. Local logs: `artifacts/context-history-guidance-clean-verify.log` and `artifacts/context-final-native-replay.log`.

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
