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

Once a card is approved:

```sh
signalweave run growth-health --run-key 2026-W40 --output ./investigations
```

Use a stable run key for a retry; change it for a genuinely new evaluation. A replay
returns the saved decision without refetching or reevaluating it. The local home
holds the cards and receipts across agent/process restarts. `result.json` is the
machine-readable record; `brief.md` is a readable, numerical evidence brief, not
an LLM-authored causal explanation. An existing agent or scheduler provides wakeups.

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

Exact arithmetic over the supplied binary floats avoids cancellation/overflow
inside the decomposition; returned values are finite floats with a reconciliation
residual. This is not decimal-currency precision or evidence of source accuracy.

## What Jev contributes

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
