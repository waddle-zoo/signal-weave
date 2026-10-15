# Release outcome review — 2026-10-12

## Human-journey audit update — 2026-10-13

**Needs revision; partial evidence.** The intended experience is install →
connect existing read-only BI → ask Codex a business question → clarify material
ambiguities → review a reusable card → run it on later periods → receive a short,
evidence-linked report or an authorized agent-delivered alert. Runtime smoke and
provider decisions alone do not establish that experience.

The recent company trials did not measure business quality: both planned pairs
in `pilot-20261012-certified-03-05-2pair-attempt-02` were not run, with **zero
agent calls**. The transport constructed a single `company_mcp` connection with
descriptors declaring other adapter names; that violates the reviewed MCP
manifest contract. The transport now groups descriptors by adapter and retains
redacted setup diagnostics. These are evaluation repairs, not evidence that
SignalWeave's business analysis failed or improved. A fresh run is required.

Northstar's `pilot-20261012-4-hil-4dbc21d4` made two agent calls, returned a
scope-qualified factual report, but completed no onboarding or recurring pairs.
The simulated owner never resolved the routing-changing severe-incident rule.
Its four future periods are unobserved, not incorrect decisions. A real human
could supply the missing incident definition or explicitly revise the rule;
the trial must model that conversation rather than silently fill the gap or
keep asking a static owner answer forever. Preserve report-only value while
automation is pending. This does not justify inventing a threshold or routing
to an unapproved recipient.

The warm paired protocol gives both arms the same reviewed card, notes, source
tools, snapshots, model and effort. It measures the added runtime bundle, not
the benefit of onboarding or remembered context. Its parent-triggered bundle is
not natural agent tool selection. Calling the frontier model in both arms on
every period also cannot demonstrate a benefit from skipping unnecessary
reasoning on quiet runs. Those are distinct experiments; retain equal access
and count all preparation/provider/query work in each comparison. Do not deny
the baseline cards, notes, caching, parallel reads or authorized calculation
tools to manufacture a benefit.

The Superset-shaped native HTTP trial demonstrates a real response-size defect:
the compact evaluation packet was **595,094 serialized bytes**. Its initial
`ok=false` and `source_count=0` fields were harness parser errors: health uses
`healthy`, and source count belongs in result telemetry. A diagnostic run
observed one source, 400 observations, 402 evidence items and no fetch error.
An unexpected typed outcome still needs explanation, but a raw current-value
table with no substantive alert rule is not a business-all-clear benchmark.
Do not credit or blame Jev for the incorrectly parsed health/count fields.

The product repair keeps the complete judgment and evidence in its durable
receipt. The default agent handoff now uses compact mode; large packets expose
explicit omitted-section coverage and a bounded directory instead of flooding
the next model turn. The existing `get_decision_receipt` tool supports lossless,
byte-bounded pages by field path, offset and limit. Tests recover all 400 items,
including the last item, preserve stored evidence, reject cross-tenant access,
and prevent inference during paging. An adversarial directory-overflow probe
was found and repaired before final certification. Oversized single scalar
values still require an explicit full-audit read; this is a disclosed limit,
not silently truncated evidence. This repair changes the agent handoff, not
Jev's input, judgment, thresholds or routing policy.

The rebuilt candidate has source fingerprint
`9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2`
and binary fingerprint
`6abe5f0e292a688a30c139f917e98cd6635bb4b6bb974597f23e3edfcda9d7b5`.
Its native installer/terminal test and fresh-home live-Jev/restart-replay smoke
passed. Neither proves a useful delivered business alert. The candidate is
local, not a newly published GitHub download.

### What would establish the user benefit

- Separate cold setup, first useful report, clarification/card completion, and
  warm recurring performance. Record human interventions and confusing steps.
- Let the treatment agent decide when to use SignalWeave alongside its existing
  BI tools. Give the baseline the same owner context, source access, model,
  caching and calculation capabilities, with its own reusable notes.
- Replay quiet, material, missing, conflicting and changed-definition periods;
  retain every planned slot. Judge the concise final report, evidence accuracy,
  relevant recipients and missed or useless alerts, not only a native outcome.
- Exercise the caller's scheduler and a local simulated delivery sink, including
  retries and deduplication. A shadow receipt or proposed recipient is not a
  delivered alert. Real Slack/email delivery needs separate user authorization.
- Review outputs with arm identity hidden. Report end-to-end time, source/query
  work and measured usage; do not present estimated API pricing as actual Codex
  subscription billing or claim a cost win before both arms complete.

No completed comparative cohort in this update establishes that SignalWeave
is more accurate, cheaper or faster than Codex with the same BI MCP. A smaller
handoff is a verified implementation benefit only after its native measurement;
it must not be promoted into an unmeasured business-quality claim.

**Status: partial. One synthetic Northstar onboarding artifact reviewed; no completed first report or A/B result.** This review covers the RC2 install/smoke evidence, the shared installed-workflow comparison, and the new Northstar/company fixtures. The Docker/Superset service is unavailable while the Mac is locked, so synthetic MCP or fixture-backed snapshots do not count as a hosted BI-provider run.

## What the evidence establishes

The [installer evidence](evidence/release-rc2-2026-10-12-installer.json) records 59 offline installer-journey checks passed, with two native opt-ins excluded from that count; both native opt-ins also passed (one PTY onboarding and one package/MCP smoke). These use fake release transport, temporary homes and dummy credentials; there are no live provider requests or real user agent-configuration changes. This supports process/package behavior, not a first useful report from a person connecting their BI source.

The [native smoke](evidence/release-rc2-2026-10-12-native-smoke.json) records a default-profile handshake, one approved synthetic card evaluated through live Jev, and a receipt replay after process restart. Its `notify` and `-20` are provider/runtime smoke outputs. The artifact contains no final agent report, hosted Superset read, human card review, or external delivery.

The [installed workflow trial](../evaluations/installed_workflow_trial.py) is a useful paired *post-onboarding* comparison: both monitoring arms get the same treatment-authored card, notes, source tools, recurring model and effort; treatment additionally gets SignalWeave's evaluation bundle. It explicitly excludes onboarding quality from that comparison. Do not use it to claim setup or card-authoring benefit.

The [release-company protocol](../evaluations/release_company_journeys.py) specifies six first-report stories and 24 later episode pairs. Its plan holds `gpt-6-luna`/`xhigh`, source tools, owner answers, snapshots and signed-card copy constant across arms; native provider judgment is secondary to the final Luna report. It also specifies delivery-disabled runs and keeps labels outside `public_episode()`. These are design properties, not evidence that a live run completed.

The current bounded shared-runner pilot is narrower: journeys 01/02 only, with synthetic second-step policy confirmations and two or four later pairs. The protocol explicitly says report-before-automation is not measured in that run. Those synthetic answers can make its shadow episode labels internally coherent for those two stories; they are not actual customer policy approval and do not resolve the other four stories' policy gaps. Do not use this pilot as evidence for first-report value.

Northstar and OrbitWorks are authored synthetic profiles, and the [Northstar seed note](../evaluations/data/northstar-multistep-seed/README.md) describes small local snapshots used with counterfactual movements. They help exercise source-selection and failure cases; they do not establish hosted-provider behavior or customer realism at enterprise scale.

## Northstar pilot 4: first-value assessment

The [pilot report](../artifacts/northstar-release-2026-10-12/pilot-20261012-4/shared-trial/report.json), [trace](../artifacts/northstar-release-2026-10-12/pilot-20261012-4/shared-trial/trace.jsonl) and [frozen scenario](../artifacts/northstar-release-2026-10-12/pilot-20261012-4/shared-trial/frozen-scenarios.json) describe one live-model, synthetic-source onboarding attempt. It used `gpt-6-luna`/`xhigh`; the default `agent` profile was present. The run made 19 tool calls over about 228 seconds and saved a draft card. Setup did not complete; the agent's own data-foundation signoff was `not_ready`, and a *synthetic* owner review rejected the card. Neither is a human or business-owner decision. Jev calls were zero. All four intended follow-up periods were not run, and there are no baseline/treatment final reports to compare.

The snapshots do support a useful, tightly qualified report about this replay. The primary source reports settled net sales of 400 source-currency units in both January and February 2026 (0%); all four channels are 100 in each month. Web conversion is 0.10 (10%) with 1,000 sessions in both months, finance booked revenue is 4,000 source-currency units in both months, and average open-ticket backlog is 100 in both months. These are separate metrics and populations, not a shared denominator. The currency code is not supplied. The evidence is a historical local-seed replay, not a fresh warehouse read or a statement about Northstar's current business.

An appropriately bounded first report could say: “In this Northstar local-seed replay, settled net sales across completed order lines were 400 source-currency units in both January and February 2026 (0%); each of the four channels was 100 in both months. Web conversion (10% on 1,000 sessions), finance booked revenue (4,000 source-currency units), and average open-ticket backlog (100) were also unchanged within their own source populations. The snapshots are historical, and backlog does not establish whether a severe incident occurred, so this is a factual update rather than an alert decision.”

The policy questions are real for recurring decisions: the owner has not defined what source or threshold establishes a “severe operational incident,” and the written rules do not explicitly settle positive net-sales movement or every 10% to under-15% case. The last “otherwise ambiguous material movement” clause may imply investigation, but an unattended card should not have to infer that. These gaps justify withholding approval for automatic routing; they do not prevent a descriptive report. The support source is an average backlog measure, so it cannot establish either the presence or absence of a severe incident.

The sign-off request to reconfirm a common Northstar population across *all* selected sources is overstrict for this descriptive card. The source contracts state distinct populations and grains: completed settled order lines by month/channel for net sales, web sessions and attributed orders for the funnel, booked finance-ledger revenue, and open tickets summarized as an average. The card uses the latter sources as separate corroboration/context and does not combine them into one rate. Keep those source-specific scopes visible and never imply a common cohort. If a later claim depends on entities joining across sources, verify that join then. The empty free-text `scope` fields are a metadata gap worth documenting, but the explicit per-source `population`, `grain`, metric and comparison fields are sufficient to describe this replay without inventing a shared-population requirement.

**Policy-vs-scope judgment:** the missing severe-incident evidence/threshold and the disposition of net-sales increases and 10%-to-under-15% moves are genuine English policy gaps for unattended action. “Otherwise ambiguous material movement” is not precise enough to silently authorize a particular notify outcome or recipient. By contrast, requiring all corroborating sources to share one population is not justified for this card's separate, source-qualified factual comparisons; ask for source-specific scope confirmation only if a contract is actually unclear or a claim relies on cross-source joins. The missing population field in an optional free-text `scope` slot does not erase the explicit population and grain elsewhere in the contracts. The card can remain unapproved while the report is still delivered to the requesting user.

**Generalized repair:** make first value and recurring readiness separate outcomes. The default guide/MCP instructions should say, briefly: after inspecting complete evidence, give the requester a scope-qualified factual report now; label historical/replay data and source-specific populations/units; state material gaps and avoid a policy disposition when an incident signal is unknown. Then leave recurring automation draft/not-ready and ask only the owner questions needed for unattended decisions. Do not turn this into a provider or state-machine change, imply an active monitor, or send a notification. In this pilot the agent's explicit instruction to stop on material ambiguity, plus the harness's `no_structured_submission` result, made a policy pause suppress the one-off report too; that is a fixable instruction/flow issue, not evidence that the source data was unusable.

## Bounded acceptance criteria

Judge the human workflow against these outcomes, with the actual live artifacts and transcripts:

1. **Cold setup and first use.** A new user can install the candidate, connect an authorized BI source and default agent, and ask a plain-language question without undocumented recovery. Record cold setup and first-report completion, elapsed time, manual interventions, and all attempted users. A process smoke or dummy-credential setup is not a pass for this outcome.
2. **Useful report before alert policy exists.** The first report states the observed metric, population/grain, comparison window and direction; cites inspected evidence; gives a small number of plausible drivers as associations or hypotheses; calls out material gaps; and offers a concrete next step. An unknown threshold must not block this report, imply causation, or authorize unattended notification. Ask only for missing owner decisions.
3. **Reviewable card.** The agent presents the source scope, metric definition, eligible population, grain, cadence/window, freshness and failure behavior, and any decision/recipient policy in language a data expert can check against the sources. A data-expert review (agent or human) records its source-linked findings and is identified as such. If policy requires human owner approval, show that as a distinct step; never label a model review or synthetic owner response as human approval or metric certification.
4. **Warm recurrence and routing.** On later periods, the approved card yields a concise, evidence-linked report; quiet, changed, stale, conflicting and unavailable-source cases are handled distinctly. Notify recommendations must follow an owner-approved threshold and recipient. A shadow recommendation is not a delivered alert: a claim of reliable notification also needs evidence from the caller's scheduler/sink that the right authorized recipients received one message, with retry/deduplication behavior accounted for.
5. **Fair report comparison.** Keep the planned 24 later episode pairs and both arms' final reports, inspected refs, provider judgment, failures and status. Review reports blinded by arm. Report the six first-use stories separately from those 24 pairs; the latter cannot establish onboarding advantage. Preserve cold setup/first report separately from warm recurrence, and provider output separately from final-report quality. Count every planned slot, including setup, model, tool, source, timeout, budget, scorer and not-run failures; disclose both completion counts and denominators.

For the blinded report review, mark each report pair on: factual/numeric correctness; useful scope and comparison; evidence traceability; calibrated driver language; honest handling of missing/conflicting inputs; next action and recipient policy; readability for the intended role. Treat a provider decision as supporting evidence, not a substitute for the user-facing report. No ratings are assigned here because the live report pairs are not available.

## Concrete defects and limits to resolve

1. **P1 — the final-report scope/window rubric is not measuring the stated fields.** [`score_report`](../evaluations/release_company_journeys.py#L903) awards its 10-point `scope_window` dimension only if the user-facing `scope` contains `public["family"]` (an internal token such as `saas_customer_health`). For episodes without a known gap, it then accepts any nonempty `window` rather than checking the expected period; for gap cases it checks only for “unknown” or “conflict.” Correct natural-language scope can therefore lose credit while an incorrect window can pass. Replace this with checks against the expected scope/window (or blind human assessment) before using the deterministic total comparatively.
2. **P1 — the Northstar first report was lost at the policy gate.** The agent inspected complete January/February comparisons and recorded the values in notes, but its final response only reports that setup stopped; the structured result is `no_structured_submission`. This misses the requested immediate user value even though the current snapshot supports a factual report. Preserve the draft/not-ready state for recurring automation while emitting the report first; count this run as a missed first-report outcome, not as proof that the policy gate should be removed.
3. **P1 for the full six-story extension, not the bounded 01/02 pilot — policy labels need explicit authorization context.** Journeys 01, 02, 04 and 06 originally state that materiality is unknown; journeys 02 and 06 also leave routing unresolved, while later episodes carry `notify` labels. The current bounded pilot adds synthetic second-step threshold confirmations for 01/02 (and a shadow-only route confirmation for 02), so that specific pair plan is internally coherent if those answers are surfaced to the agent. It is still synthetic and delivery-disabled, not customer approval. Before extending the labels to the other journeys, require explicit policy/route answers or score unresolved cases as report-only / human-signoff; keep report quality separate from notification authorization.
4. **Fixture-date defect reported by the independent review is corrected in current source, but not runtime-verified here.** `_public_company` now constructs episode dates with `datetime` plus `timedelta` ([current source](../evaluations/release_company_journeys.py#L421)). This removes the observed September 35/42 string-construction defect at source level. Regenerate/freeze and validate the fixture before treating any planned denominator as runnable; do not count the correction as a successful pilot run.
5. **The evidence is not yet an end-to-end utility, human-signoff, or delivery result.** The installer checks are isolated and use dummy credentials; the native smoke has one synthetic card and no final report; the Northstar MCP uses historical local-seed snapshots; and the company sources are normalized mocks, including fixture-only Superset-shaped snapshots. Northstar's owner rejection is explicitly synthetic, so no real human owner/card signoff was exercised. The current product documentation also assigns scheduling and delivery to the caller's agent/workflow runner. Keep setup usability, first-report quality, data-expert review, human owner signoff, recurring report quality, and actual notification delivery as separate claims until each has its own evidence.

The current source corrects the fixture date construction, but I did not run or validate a rebuilt fixture. The scorer and first-report gap remain material. The bounded 01/02 shared-runner run may test post-onboarding shadow recurrence after its synthetic owner answers; it cannot establish report-before-automation value. No A/B scores are available. These artifacts do not establish that a human can complete the full workflow or reliably receive the right recurring report.
