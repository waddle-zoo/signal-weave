# Local, repeatable investigations

The target: describe a business problem once, review how it will be investigated,
then let your existing agent repeat the work and deliver the evidence. SignalWeave
owns the saved analytical contract and execution checks. It does not replace the
agent, BI tools, or scheduler.

This branch implements the first quantitative slice of that target, not a general
data scientist. Install the [local executable or CLI](local-install.md), connect
approved sources, and expose SignalWeave as an MCP to your agent.

## What runs locally

1. Your agent helps turn the business brief into a free-form insight card and
   identifies approved sources. People still review definitions and expected outcomes.
2. A source supplies bounded comparison tables, controlling totals, population,
   time windows, provenance, and declared coverage. Existing adapters keep working;
   new company MCPs use the [configured bridge](mcp-source-bridge.md).
3. Code validates the measurement contract and computes contributions. Jev uses
   those calculations and the card to make typed semantic judgments.
4. A receipt persists the result, method, inputs, provenance, limitations and next
   steps. The agent explains it or continues the investigation. Delivery remains
   caller-owned.

The new numerical methods require that comparison-table contract. Existing
Superset/Preset chart observations do **not** automatically become complete segment
partitions; a reviewed source export must supply the needed tables first. The local
MCP example demonstrates that export boundary rather than claiming every connector
already performs these deeper analyses.

For recurring scalar observations that are not decomposable tables—p95 latency,
queue depth, a cached chart value—adapters can instead return a typed
`ResourceContract.comparison_contracts` entry. It carries the metric definition,
population, unit, exact comparison window, and provider-owned coverage and
comparability assertions. A card binds the entry through
`SourceRef.required_comparison_keys`. Required incomplete or non-comparable
contracts are a deterministic `insufficient_data` gate; Jev is retained for the
semantic explanation, not asked to infer source completeness from prose. This is
the generic bridge between arbitrary BI/operational assets and the stricter
analysis path.

Once a card is approved:

```sh
signalweave run growth-health --run-key 2026-W40 --output ./investigations
```

Use a stable run key for a retry; change it for a genuinely new evaluation. A replay
returns the saved decision without refetching or reevaluating it. The local home
holds the cards and receipts across agent/process restarts. `result.json` is the
machine-readable record; `brief.md` is a readable, numerical evidence brief, not
an LLM-authored causal explanation. An existing agent or scheduler provides wakeups.

## Start with the first report

An agent should inspect existing definitions and source comparisons, draft the
investigation, then call `preview_investigation_report(card_id)`. This invokes
the same real adapters and Jev as `simulate_insight_card`; it does not approve
the card or send a notification. Both tools now return `report` and
`report_markdown` alongside the underlying evidence.

The report includes reproducible numeric claims, source/query/period provenance,
coverage, unresolved questions and intended routes. `complete` means the bounded
analytical checks passed, not that the business policy is independently proven.
`partial` and `blocked` are not synonyms for "nothing changed." Contributions
account for a measured difference; they do not establish its causal mechanism.

Show this first report to the owner. Ask only about unresolved definitions,
materiality or delivery policy. Repair missing context and test other periods
with independent expected results before requesting `approve_insight_card`.
One successful preview is not workflow certification. The existing
`evaluate_card_workflow` acceptance path remains available for policy replay.

An approved `evaluate_insight_card` run returns the same report format and saves
the generated report in its receipt. Reusing an idempotency key replays it without
new source or Jev calls. `signalweave run ... --output ...` also writes
`report.json` and `report.md`. An external agent may use this evidence to write
a richer narrative, investigate gaps, or send a digest. SignalWeave does not
verify that additional prose or deliver it automatically.

Receipts created before report archiving return their original decision and an
explicit report-unavailable reason. They never synthesize a historical report
from today's card or renderer; use a new run key for a new evaluation.

The opt-in feasibility experiment is `python -m evaluations.first_report_trial`.
Without `--live` it creates only a frozen manifest. Live mode uses four small
synthetic companies, a maximum of 48 Jev attempts without retries, at most two
author drafts per company, and saved-login Luna for authorship and comparison.
Both recurring arms receive the same authored context and deterministic analysis
tool. This tests runtime after shared onboarding, not independent onboarding
superiority. Initial setup periods are development examples; later periods are
unseen by the author. Narrative usefulness still requires separate review. No
real source connections, human usability study, or enterprise-readiness claim
follows from this fixture trial.

### Recorded first-report results

For the newer comparison including a persistent LLM and final owner-facing prose,
see the [business-outcome trial](business-outcome-trial.md). It found 10/12 strict
passes for SignalWeave versus 12/12 for the baseline and **no end-to-end speed or
cost advantage** in that small sample. The earlier timings below measure a
different boundary and must not be used as a final-report efficiency claim.

The [initial attempt](evidence/first-report-live-01/report.json) and
[paired rerun](evidence/first-report-live-02/report.json) retain every attempt,
frozen inputs, authored cards, raw model journals and token usage. The rerun used
commit `cee8d0d`; the initial attempt records working-file hashes rather than a
complete committed source snapshot. These are small development experiments,
not an enterprise benchmark or an independently peer-reviewed study.

Four synthetic businesses cover net sales, weighted support SLA rates, shipment
lateness and signed subscription movements. Luna authored the cards using existing
definitions and inspected comparisons. The operator supplied the business rules
and routing directory; this was not onboarding from an undocumented data lake.
The initial harness omitted the operator identity, so approval correctly failed.
One shipping policy was also ambiguous and was clarified before the rerun. The
other three authored drafts were reused, not regenerated until they passed.

All four workflows reached approval in the rerun. Eight paired, author-unseen
periods produced these **original strict scores**, which remain unchanged:

| Check | SignalWeave + Jev | Luna + the same card and analysis tools |
| --- | ---: | ---: |
| Status, outcome, route and numerical/provenance checks | 7/8 | 5/8 |
| Exact archived report replay without new model calls | 8/8 | Not tested |
| Median recurring elapsed time, cached synthetic inputs | 0.278 s | 29.146 s |

The apparent correctness gap is not a defensible model-quality win. A support
case's expected recipient contradicted the owner policy; both systems correctly
chose the Data Steward. Correcting that oracle alone gives 8/8 versus 6/8.
Luna's `no_action` instead of `ignore` accounts for another strict failure.
The remaining subscription case depends on an underdefined distinction between
a current movement's magnitude and its contribution to a between-period change.
The reviewers disagreed about that interpretation. We do not count it as proof
of superior judgment. Future trials expose exact outcome enums and let the
baseline select analysis references instead of copying full tables.

Timing compares a saved workflow with a fresh CLI agent episode, including tool
discovery, prose and JSON output. It excludes warehouse-query time, uses cached
synthetic inputs, and does not compare an optimized persistent agent or scripted
baseline. It demonstrates a shorter repeatable execution path in this fixture, **not** a measured
dollar saving or a claim that Jev is 100 times better at analysis. Setup cost is
retained separately: the two attempts used 46 Jev calls and 13 Luna episodes in
total, including approval and failed setup work. No notifications were delivered.

Two separate Luna reviewers examined methodology and owner-facing report quality:
[method review](evidence/first-report-live-02/adversarial-method-review.json) and
[quality review](evidence/first-report-live-02/independent-quality-review.json).
They found stronger auditability in the native reports but clearer prose in the
baseline. Those findings prompted a concise report lead, explicit gaps, labeled
Jev judgments and a collapsible audit appendix. Revised presentation is an
offline re-render, not a new successful model trial. Internal AI review is not
external peer review, a human usability test, or customer adoption evidence.

The bounded result: agent-authored, owner-context-backed investigations can be
approved, run repeatedly through live Jev, and return checked measurements with
durable evidence. Automatic recovery of trustworthy definitions from arbitrary
BI assets, broad method coverage, report usefulness to actual owners, and a fair
end-to-end cost advantage remain unproven.

### Earlier first-report development counterexamples

This historical subsection covers only the first-report experiment series. Its
counts and reviews exclude the later [business-outcome trial and six-case repair
probe](business-outcome-trial.md), which include the unresolved failures.

That series' final [two live probes](evidence/first-report-probes-live-01/report.json)
froze inputs and independent expected results at commit `d9c5945`, reused the
approved cards without re-authoring or approval calls, and used the compact
baseline interface. Neither model received the expected labels. These are
targeted development counterexamples, separate from the original denominator:

| Probe | Expected action | SignalWeave + Jev | Compact Luna baseline |
| --- | --- | --- | --- |
| SLA miss rate stays at 13%; current-rate threshold is 12% | Notify Support Operations | Correct; 0.380 s | Correct; 17.988 s |
| Net sales stay at $1,000; all channel changes are zero | Ignore; no recipient | Correct; 0.269 s | Correct; 14.798 s |

Both reports passed the numerical, provenance, outcome and recipient checks.
Both SignalWeave replays were exact with no new model calls. This distinguishes
a level-based rule from a change-based rule without changing the approved
workflows. It does not establish an accuracy advantage, population-level error
rate, warehouse-query savings, or performance against an optimized persistent
Luna executor. Two successful cases are not enterprise certification.

The probes used exactly 2 Jev calls (15,660 input / 465 output tokens) and 2 Luna
episodes (141,262 input / 785 output tokens, provider-reported episode accounting).
Across those three retained first-report runs: **48 Jev calls, 15 Luna episodes, no Jev retries**.
No real notifications were sent. The code review repairs bind claims to actual
source comparisons, enforce required evidence and configured routes, and prevent
replays from inventing reports that were never archived. The original eight
reports preserve their decisions and measured values under these stricter checks.

The [code-review close-out](evidence/first-report-live-02/code-review.json)
records five resolved findings. The [separate probe review](evidence/first-report-probes-live-01/review.json)
rechecked calculations and policy outcomes, found no expected-label leakage, and
still preferred Luna's owner-facing prose. Passing the code review does not
close the broader onboarding and adoption gaps listed below.

## Quantitative methods available now

| Method | What it answers | What it does not establish |
| --- | --- | --- |
| Additive contribution | Which disjoint segments account for the change in a total? | Why those segments changed |
| Symmetric rate decomposition | How much of a rate change is within-segment performance versus population mix? | Causal effects or statistical significance |

For example, an aggregate conversion rate can fall from 82% to 28% while every
segment improves. The implemented decomposition separates **+10 percentage points
of within-segment improvement** from **−64 points of population-mix change**.
That rules out an explanation that attributes the whole decline to worsening
within-segment conversion. It does not prove what caused the mix shift.

For each segment, with rate `r` and population weight `w`:

```
within = (r_current - r_baseline) × average(w_current, w_baseline)
mix    = (w_current - w_baseline) × average(r_current, r_baseline)
```

The components sum to the aggregate-rate change. This is a symmetric accounting
decomposition, consistent with the standardization approach in [Das Gupta's
methodology manual](https://www2.census.gov/library/publications/1993/demographics/p23-186.pdf).
Interactions are split symmetrically, not assigned to a causal mechanism.

## Measurement contract

`ResourceSnapshot.analytical_comparisons` accepts `AnalyticalComparison` objects.
Each identifies a metric, definition, unit, population, dimension, two explicit
periods, controlling totals and segment values. A rate requires numerator and
denominator counts/exposures, not a pre-averaged percentage.

The source asserts completeness, disjointness and comparability. Code cannot
prove those claims from aggregates; onboarding must establish them. Totals must
come from a controlling query, not be manufactured by summing whatever segments
were returned. The example runs separate total and segment aggregations, but both
query the same synthetic table: it does not independently certify upstream completeness.

Add `required_comparison_keys` to a required `SourceRef` when the investigation
depends on specific comparisons. Missing keys block evaluation, even if narrative
evidence remains. Required comparisons are validated even if semantic selection
omits that source. Optional-source failures do not become mandatory blockers;
the report's `required` field reflects that effective requirement.

Other admission rules:

- Missing values are not zero. Partial/unknown coverage and non-disjoint segments
  cannot produce a complete decomposition.
- Controlling totals and components must reconcile within representation error,
  not an arbitrary percentage tolerance. Arbitrary source rounding is not supported.
- Duplicate comparison/segment identities, invalid windows and nonfinite values
  are rejected. Finite inputs whose outputs cannot be represented return unavailable.
- Unequal calendar periods require declared comparability and retain a qualification;
  `require_equal_duration` optionally enforces equal elapsed time. No implicit exposure normalization.
- Rate denominators must be positive in every segment and period. Structural
  entrants/exits and zero-exposure strata need a different method. Numerators are
  nonnegative; this is not yet a signed-ratio or bounded-proportion validation system.
- Source freshness/health and payload limits still apply to analytical-only sources.
  Observation baseline requirements can be satisfied by a complete comparison only
  when source, comparison/subject ID and metric match.

### Comparison-window onboarding

Adapters can publish `ResourceDescriptor.contract.available_comparison_windows`,
for example `["previous_period"]`. These are exact, opaque identifiers compatible
with the configured resource's required comparisons, not human labels or a union
that hides incompatible required comparisons. Custom identifiers, including spaces
and Unicode, are supported without translation, case folding, or aliases. An empty
or omitted declaration means compatibility is unknown; review warns but does not
block legacy sources. Context-only resources need not declare windows.

`SourceRef.required_comparison_keys` identifies analytical tables by their exact
`analytical_comparisons[].key` or reviewed catalog requirements. It does not contain
`comparison_window` identifiers or time-window labels. Inspect the source rather
than inventing keys. Schema guidance makes this distinction explicit; it does not
prove that callers will always author the correct keys.

Discovery exposes the contract and onboarding review exposes each candidate's
`available_comparison_windows`. The configured MCP bridge's reviewed descriptor
owns this field; caller source-selection fields and snapshot metadata cannot replace
it. This capability must actually be supplied by the adapter/operator. Adding the
field alone does not repair existing cards or establish that a trial now succeeds.

When `comparison_windows` is omitted from draft/propose/onboard, defaults are the
intersection of nonempty declarations from required selected sources. If those
declarations have no common window, drafting fails with `comparison-window-mismatch`.
If none is declared, legacy defaults remain and review marks compatibility unverified.
An explicit empty list is rejected. Explicit identifiers are retained for review;
every allowed card window must be supported by each required source that declares
windows, since compilation may choose any of them. Optional sources do not narrow
the intersection; their mismatches produce warnings.

Review blocks incompatible cards and cached plans whose windows are empty or outside
the card's allowlist. Approval rechecks the catalog and cannot waive this blocker
through source-selection confirmation. Changed declarations invalidate the review
fingerprint. Execution still requires an exact match to
`AnalyticalComparison.comparison_window` and validates the actual coverage, periods,
totals, and denominators. A declared capability is not proof of valid run evidence.

Exact arithmetic over the supplied binary floats avoids cancellation/overflow
inside the decomposition; returned values are finite floats with a reconciliation
residual. This is not decimal-currency precision or evidence of source accuracy.

## What Jev contributes

### Exact policy numbers

When a policy contains an exact numerical boundary, the onboarding agent can add
`numeric_conditions` to the draft. The owner still reviews the English policy,
measurement binding and first result. For example:

```json
{
  "text": "Any channel accounts for at least 80 units of movement",
  "source_key": "sales",
  "comparison_key": "net-sales-by-channel",
  "measurement": "contribution",
  "segment": null,
  "unit": "USD",
  "absolute": true,
  "comparator": ">=",
  "threshold": 80
}
```

Code computes the check from a complete, reproducible analytical comparison.
The source and comparison must be explicitly bound to the card. Units must match;
rate results use fractions, so 12% is `0.12`, not `12`. Supported measurements
are aggregate `baseline`, `current`, `delta`, and segment `contribution`.
For contributions, null means any segment; a string selects that exact segment,
including a segment literally named `any`. Absolute magnitude is opt-in.

These are **facts for Jev, not action rules**. Keep alternatives, conjunctions,
exceptions and the outcome policy in `decision_guidance`. There is no new workflow
language. Missing, ambiguous or unhealthy inputs produce `unknown`, never false.
Optional context does not waive required-source gates. Editing the checks changes
the reviewed card contract and requires a new approval.
Checks bound to a required source must be computable: a missing exact segment,
unit mismatch, or invalid comparison forces `insufficient_data` even if Jev
suggests a confident notification or suppression. An optional source's unknown
check remains advisory. This is a measurement-admission gate, not a demand that
every speculative semantic question be answered.

Do not add a required watch item for every possible explanation. Required watch
and question slots are unconditional evidence prerequisites; speculative/advisory
detail should be omitted or explicitly marked advisory by the owner. Jev still
decides the outcome from the whole policy; numerical checks do not certify the
policy's completeness or the source's truth.

Reports and the optional writer projection retain both the computed checks and
separately labeled model judgments. An unresolved semantic assessment can reflect
model uncertainty; it is not proof that a source is missing or that records
conflict. Actual source failures remain independently visible and blocking.

Jev evaluates the English business rules, relevance and evidence against a bounded
typed contract. It does not invent arithmetic, SQL authority, p-values, or causal
conclusions. The production path has no alternate offline semantic engine. Unit
tests use doubles solely to isolate code contracts; live trials use Jev.

Local installation does **not** mean private/offline inference: selected evidence
is sent to TypeSafe. Company connectors need their own credentials and data-sharing
approval. Connecting an MCP gives tool access, not automatic understanding of its
definitions or permission to run all tools.

## Next gates before the full product claim

1. **Onboarding without bespoke mapping code.** Have an agent discover source
   schemas, propose a measurement mapping, ask only unresolved business questions,
   then validate the proposal against actual source results before approval.
2. **More methods with explicit assumptions.** Time-series seasonality and change
   detection, funnel/cohort analysis, and experiment/causal methods need separate
   validated contracts. A regression coefficient alone is not proof of causality.
3. **Investigation efficiency.** Learn approved source relationships, reuse queries,
   measure cached versus new-query cost, and stop when the question is answered.
   Do not infer this benefit from subsecond Jev requests.
4. **Revalidation.** Detect semantic/schema drift and require targeted reapproval;
   test against historical decisions before permitting a changed investigation.
5. **Distribution policy and user validation.** The v0.2.0rc1 preview is published
   with macOS ARM64/Intel and Linux x64 builds, installed-binary CI checks, and a
   live check of the published ARM Mac download. Developer-ID signing,
   notarization, managed-device acceptance, and real Codex/Claude user onboarding
   remain open; a working MCP handshake is not evidence that users succeed.

The defensible product opportunity is the reviewed, reusable investigation and
its accumulated evidence—not merely a faster classification API. These gates are
still open; [the bounded proof](local-investigation-proof.md) says exactly what ran.
