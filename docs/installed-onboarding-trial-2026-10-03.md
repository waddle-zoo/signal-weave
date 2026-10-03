# Local binary onboarding: what actually worked

Status: **partial proof, not an enterprise-readiness pass**. These experiments
exercise the actual native executable and stdio MCP with live TypeSafe Jev.
Luna authors cards and a separate Luna invocation reviews the simulated owner's
policy. No expert card is installed. The owner supplies business rules and labeled
historical examples; this is not autonomous discovery of undocumented intent.

## Clean Northstar scale replay

The corrected `installed-workflow-northstar-live-04` run completed setup and all
42 subsequent cases across seven simulated weeks. It reuses Northstar's existing
535,312-row seed and normalized source snapshots, not 42 fresh warehouse queries.

| Check | Observed result |
| --- | --- |
| Outcome, recipient and required-source presence | **41/42** |
| Completed evaluations | 42/42 |
| Identical receipt replay without new source/model calls | 42/42 |
| Recurring Jev requests | 42: one per case |
| Recurring frontier-model invocations | 0 |
| Median recurring evaluation | 0.436 seconds |
| Recurring range | 0.330–0.811 seconds |
| Assisted setup | 251.9 seconds |
| Total Jev attempts, including setup | 102; one failed attempt |

The card and compiled plan remained frozen after approval. Future source IDs were
opaque, correcting the scenario-name hints found in the older 39/42 run. Neither
confidence floors nor expected labels were changed to get a better score.

The remaining mismatch is the previously flagged boundary case: an exactly 10%
decline was labeled `ignore`, while the supplied policy says to ignore movements
*below* 10%. Jev selected ignore with 0.63 support; the unchanged 0.70 floor routed
to Analytics for investigation. We retain **41/42**, not a post-hoc 100% claim.
That label needs owner clarification before another acceptance study.

[Independent raw-output adjudication](evidence/installed-workflow-2026-10-03/installed-workflow-northstar-live-04/adjudication.json)
and its sibling compressed files retain the frozen inputs, native outputs and
request trace. This is evidence for repeated native execution after assisted
onboarding. It does not establish explanation quality, arbitrary data-lake scale,
correct causation, real notification delivery or an advantage over Luna alone.

## Six-business transfer probe

The v5 transfer runs used six business families with 24 assets each, including
duplicate titles, obsolete sources, partial populations and planning data. All
intended cases remain in the denominator.

| Business family | Setup complete | Exact future cases / intended |
| --- | --- | --- |
| Retail | Yes | 3/3 |
| SaaS retention | Yes | 3/3 |
| Support | No | 0/3; not executed |
| Database operations | No | 0/3; not executed |
| Marketplace | No | 0/3; not executed |
| Finance | Yes | 2/3 |

Observed totals: **3/6 setups, 8/18 intended future cases**, with nine executed.
These are not clean cross-business generalization scores: post-run review found a
calibration identity-mapping defect. It paired same-title/type assets by position
in shuffled catalogs. In finance, that could attach settled-receipts history to a
payment-authorizations identity. The agent then saved the wrong required source.
The old artifacts remain intact; failures are not silently removed or attributed
entirely to Jev or the product.

Other concrete failures remain useful: authors invented typed numerical bindings
when sources only advertised a comparison window, and failed required watches
prevented acceptance. Marketplace's source had raw buyer counts but an empty
`analytical_comparisons` list; its numeric binding really was unsupported. Some
agents also passed `limit: 40` to a tool whose maximum is 25. A generic
`no_structured_submission` summary conceals these actionable tool-level failures.

### A substantive analytics result

Harbor's returned typed measurements support a useful distinction:

- Aggregate retention fell from 55% to 37.5%, but within-plan rates stayed at
  90% and 20%. The 17.5-point aggregate decline was entirely mix: **ignore** under
  the owner's policy.
- In the event case, retention fell to 27.5%. Within-plan rates both fell by
  10 points; the decomposition was −10 points within and −17.5 points mix:
  **notify** the authorized owner.
- An incomparable-period case withheld numerical claims and returned
  **insufficient data**.

The arithmetic was independently recomputed from returned source comparisons,
without using the production calculation helper or private expected values.
[Calculation audit](evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-04/harbor-math-review.json).
This is a descriptive decomposition, not proof of causation or a customer result.

## Corrected identity trial: v6

`transfer-live-06` and `transfer-live-07` froze the repaired mapping and rebuilt
binary before inference. They tested the five affected families, not retail again.

| Business family | Setup complete | Exact future cases / intended |
| --- | --- | --- |
| SaaS retention | Yes | 3/3 |
| Support | Yes | 3/3 |
| Database operations | No | 0/3; not executed |
| Marketplace | No | 0/3; not executed |
| Finance | Yes | 3/3 |

**3/5 setups, 9/15 intended future cases; all nine executed cases passed.** The
two runs used 108 Jev attempts including authoring/calibration, with no provider
errors or exhausted budget. This is a separate result, not a replacement for v5.
[SaaS/support/operations adjudication](evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-06/adjudication.json)
and [marketplace/finance adjudication](evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-07/adjudication.json).

Operations initially required an unavailable typed comparison. After repair, its
quiet historical example still became `investigate` because ignore support was
0.62, below the unchanged floor. Later author revisions did not finish accepted
setup; one owner review rejected omitted data-gap instructions. No future
operations case was executed. A policy-faithful owner review alone is not a
passing workflow evaluation.

Marketplace exposed a second fixture problem. Its original private evidence
labels require the deduplicated union source, not the audience-tags source.
However, the calibration builder required both first-listed assets for retrieval
recall. The union-only card got all three historical outcomes and required
evidence right, but failed that unjustified extra retrieval requirement. Its
attempted repair selected an obsolete Archive asset instead of Audience, and
then failed a quiet outcome too. That navigation mistake is real; treating the
first card as a failed business analysis would also be misleading. It remains a
failed setup under the original frozen protocol, not a retroactive pass.

For v7, minimum retrieval scope comes from the original historical required
evidence labels. Both legitimate snapshots remain available. Missing a required
source still fails; optional availability does not itself make retrieval
mandatory. No future outcomes, routes, snapshots or required evidence labels
change. This independently reviewed test repair is evaluated in a separately
versioned, single-company marketplace probe; it is not a new six-company score.

### Prospective marketplace check: v7

`transfer-live-08` completed onboarding and **3/3 future cases**, with exact
outcomes, recipients, required evidence and no-call receipt replay. Setup took
142.0 seconds. Recurring evaluation had a 0.249-second median with cached
synthetic sources, one Jev request and no frontier-model call per case. The run
used **17 total Jev attempts**, against a cap of 25, without errors or censoring.
The card kept the 0.70 confidence floor. Future business labels were unchanged.
[Independent adjudication](evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-08/adjudication.json).
The quiet/event reports are explicitly `partial`, the data-quality report is
`blocked`, and numeric claims are empty. This pass certifies native routing and
source presence on these cases, not a finished analytical narrative or validated
quantitative report.

The corrected five-family probe plus this final check used 125 Jev attempts in
total, including onboarding, calibration and failures. The failed v6 marketplace
setup remains failed. Do not substitute the v7 result into the old denominator.

Across separately versioned trials, retail, SaaS, support, finance and marketplace
each now have an agent-authored, accepted card followed by three correct future
cases. **Operations does not.** This is a regression inventory, not a pooled
accuracy estimate or a fully successful six-company prospective cohort. The next
meaningful improvement must address that remaining onboarding failure and then
validate a single frozen, cross-business protocol.

## Repairs and review discipline

Production changes preserve omitted acceptance labels at the MCP boundary and
support explicit, isolated historical replay clocks. Old evidence is evaluated
at its declared historical time without relaxing freshness or fetching current
context. The bundled guide now stresses original policy order, exact endpoints,
optional-source coverage and the difference between a comparison window and an
executable analytical comparison.

Research repairs cover native response scoring, legal card-local route aliases,
opaque future IDs and semantic identity matching for calibration assets. They do
not install scenario logic in production. Internal Luna reviewers examine code
and raw traces, but their conclusions are checked too: a claimed finance runtime
expansion bug was rejected because the actual card was `fixed/none` and explicitly
contained the third source. No retrieval-mode contract was changed on that basis.

All traces are synthetic and delivery-disabled. Secrets were checked before
export, and the offline adjudicator produced identical results from compressed
and original artifacts. Internal model review is **not external peer review**.

Frozen v5 harness content hashes match commit `4113c27` (some v5 protocols record
the preceding HEAD because the new harness had not yet been committed). v6 hashes
match `3be22c5`; v7 hashes match `d324b8f`. Use the recorded content hashes, not the
older HEAD alone, to identify the experiment implementation. The v6/v7 binary
hash is verified against the executable used in the trials.

Final verification: **2,287 offline tests passed, five opt-in tests skipped**;
**18 native binary/MCP packaging tests passed** with no paid inference. The native
checks require loopback sockets and macOS semaphores unavailable in the sandbox;
they passed when run with the necessary permission. Ruff and `git diff --check`
passed. No release was published and nothing was merged into main.

## What is still unproven

1. Reliable end-to-end onboarding across all six families. Operations still did
   not pass, and the separately versioned successes are not a single frozen
   cross-business acceptance result.
2. Calibration that represents the full recurring evidence set, including optional
   sources, and a reviewed live preview before unattended use.
3. Faithful final reports and comparative benefit against Luna with the same
   cards, context, calculations and evidence. This trial has no such control arm.
4. Real connector extraction, expensive query behavior, managed-device install,
   actual human usability and real delivery reliability.

The next trial must keep the frozen failures, budgets and unchanged future labels;
it must not rerun until lucky and report only the successes.
