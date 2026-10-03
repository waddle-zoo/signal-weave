# Evidence sufficiency: experiment, not a victory lap

Status: protocol written before paid calls; results will be appended below.

## Decision this experiment can inform

Should the next onboarding improvement focus on collecting precise source
definitions, deterministic measurement normalization, or neither? The failing
operations card repeatedly escalated a nominally quiet example. That is not
enough to blame Jev, declare the context wrong, or weaken a confidence threshold.

The prior [63-call sensitivity study](jev-v6-state-diagnostics.md) already tested
generic semantic reminders, blank metadata removal and clock hints. Some raw
judgments improved but missing-data controls worsened. The newer
[six-call placement probe](native-onboarding-handoff-2026-10-03.md) did not repair
quiet acceptance. Those failed hypotheses are retained, not repeated here.

The original source lists measured values and a cluster list, but does not
explicitly declare the expected fleet or both measurement intervals. Its
historical `ignore` label may assume more than the model can establish. Original
labels are retained for comparison, **not treated as unqualified ground truth**.

## Three perspectives

- **Engineering:** Keep one retained agent-created card, version, plan, confidence
  floor and production engine unchanged. Test source exports, not a hidden custom
  classifier. Save full requests, responses and workflow handoffs. No production
  behavior changes or delivered notifications.
- **Data science:** Separate added information from equivalent derivations. Use
  predeclared missing-data controls, a frozen request order, two repetitions and
  zero retries. Retain every attempt. A failed or missing row does not disappear
  from the denominator. These are six related constructed cases, not twelve
  independent customers or a statistically established population accuracy.
- **Product:** A quiet success must suppress unnecessary follow-up work. An event
  must request investigation, and missing necessary evidence must request repair.
  Count those handoffs separately from selected outcomes and recipients. There is
  no measured human time saving, notification click-through or customer adoption.

## Frozen comparison

Use the final card and three historical inputs from native `transfer-live-11`.
Do not change its policy, sources, thresholds, versions, questions or stored plan.

| Arm | Intervention | Cases × repeats | Role |
| --- | --- | ---: | --- |
| Original | Retained snapshots unchanged | 3 × 2 | Diagnostic legacy-label agreement |
| Original + typed | Derive two normalized observations and percent changes from the same latency/lag values | 3 × 2 | Representation/pipeline diagnostic |
| Documented | Add an explicit synthetic provider specification | 6 × 2 | Primary information intervention |
| Documented + typed | Same provider specification plus the same normalization | 6 × 2 | Primary normalization intervention |

**36 attempts maximum**, seeded interleaved order, no retries or cherry-picked
reruns. The primary arms get identical factual evidence. Typed normalization
also activates the production observation-role questions; it is not a strictly
formatting-only intervention. Raw provider values remain intact, missing values
remain missing and there is no conversion of absence into zero.

The provider specification declares field meanings, units, an expected three-
cluster fleet and the two closed UTC reporting windows. It distinguishes expected
population from observed membership. These are **new synthetic source assertions**,
not facts recovered from the earlier run, not an independent completeness audit,
and not instructions about which outcome to select. Its definition text is
invariant across cases. The original evidence archive is not edited.

Three added controls use an otherwise actionable event:

1. Only one cluster appears in the export although the expected fleet has three.
2. Baseline and current cluster memberships differ.
3. Baseline latency is missing while the other incident conditions are present.

Starting from an actionable case matters: a missing value in a conjunction may be
irrelevant if another required condition is already conclusively false. These
controls make the omitted evidence decision-relevant. The original missing-
coverage case also remains. No missing case inherits a quiet label by accident.

A small deterministic fixture oracle checks memberships, field presence and the
declared numeric trigger. **This simple numeric policy can be implemented without
Jev.** The experiment tests SignalWeave's semantic evidence handoff and uncertainty
handling; it cannot establish a moat or superiority over SQL rules or Luna.

## Acceptance and stop rule

Each primary arm must pass **all six cases in both repetitions**: exact outcome,
exact configured recipients, required evidence/retrieval, and the expected
workflow handoff. Quiet maps to `suppress`, event to `retrieve_evidence`, and
necessary-data gaps to `repair_source`. Record model probabilities and final
routing separately; selected-answer support is not the probability that the
whole workflow is correct. No thresholds or required-watch gates are lowered.

Internal engineer/PM review tightened the endpoints before freezing: report
outcome agreement, exact routes, handoff agreement with the owner, and handoff
consistency with the actual routed outcome separately. Also check handoff status
(`complete`, `pending`, `blocked`) and its delivery keys. A low-confidence gap
can correctly follow the implementation's investigation fallback while still
failing the owner's desired data-repair route. Count that as misdirected repair,
not as an implementation inconsistency or a delivered false alert. Actual sent
alerts are **not measured**; no sink is invoked.

Call this a useful candidate for further onboarding work only if a primary arm
passes that gate without false suppression of an incident or gap. Do not promote
the synthetic provider assertions into generic production defaults. A successful
component result still needs independent source contracts, a new business family,
actual binary/MCP onboarding and matched agent/report baselines before wider claims.

The runner freezes source trace, inputs and implementation hashes. Execution
rejects changed inputs, code or schedule. Each attempt is saved separately, so an
interruption is visible. The default command only freezes a plan; paid inference
requires a separate `--live --plan ... --key-file ...` invocation.

## Sources shaping the design

The TypeSafe skill directed explicit state and narrow typed judgments with code
owning arithmetic and control. The live docs warn about literal interpretation,
numeric precision and irrelevant state; these are hypotheses to test, not proof
of the cause in our run. See [state](https://docs.typesafe.ai/concepts/state),
[choice](https://docs.typesafe.ai/primitives/choice), and
[documented Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
