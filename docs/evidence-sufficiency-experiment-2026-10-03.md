# Evidence sufficiency: experiment, not a victory lap

Status: completed; **neither primary arm passed**. No inference treatment promoted.

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

## Observed results

Frozen code: `2f86814`. All **36/36** requests returned from `jev-1.13.0`, with
zero retries, errors or omitted attempts. No notifications were sent. The full
[protocol](evidence/evidence-sufficiency-2026-10-03/protocol.json),
[inputs](evidence/evidence-sufficiency-2026-10-03/inputs.json.gz),
[results](evidence/evidence-sufficiency-2026-10-03/report.json.gz), and
[raw requests/responses](evidence/evidence-sufficiency-2026-10-03/trace.jsonl.gz)
are retained with a [hash manifest](evidence/evidence-sufficiency-2026-10-03/manifest.json).

| Primary case | Documented | Documented + normalized |
| --- | ---: | ---: |
| Quiet | 2/2 | 2/2 |
| Incident | 2/2 | 2/2 |
| Membership absent | 2/2 | 2/2 |
| Partial membership | 0/2 | 0/2 |
| Different baseline/current memberships | 1/2 | 0/2 |
| Missing latency baseline | 1/2 | 2/2 |
| **Exact outcome, recipient and handoff** | **8/12** | **8/12** |

Both original-evidence arms achieved 4/6 against the legacy labels. Neither
passed quiet history: raw evidence produced two investigation handoffs; normalized
evidence produced two data-repair handoffs. Thus removing business investigation
alone would misleadingly suggest a fix. The quiet case needs suppression, not a
different unnecessary task.

The new provider specification changed quiet judgments to `ignore` with support
0.93/0.95, or 0.79/0.79 with normalization. This supports a narrow conclusion:
**supplying explicit source definitions can resolve this quiet-case ambiguity**.
It does not isolate which definition helped, establish a generic completeness
test, or demonstrate autonomous collection of those definitions.

The missingness controls prevent calling that an overall success. Across the two
primary arms, eight expected data-repair handoffs instead became investigations:

- Six raw model answers selected `insufficient_data`, but with support below
  the unchanged 0.70 floor. Code routed these to `investigate`.
- Two selected `investigate` themselves (normalized partial membership,
  support 0.51/0.52). A fallback-only change cannot fix these two cases.
- All 36 final handoffs were consistent with their final routed outcomes.
  That is implementation consistency, **not** business-policy correctness.
- No incident or data gap was suppressed. This small, related fixture set
  cannot establish a production false-negative rate.

Normalization had no net gain on this endpoint. It stabilized the missing-baseline
case while worsening membership comparability. The two repetitions of the raw
different-membership case straddled the confidence floor (0.69/0.71); the missing
baseline also differed (0.72/0.68). Therefore repeated inputs are not evidence of
deterministic model outputs or stable final routing.

Provider-call median latency was 0.245 seconds; reported usage totaled 256,794
input and 5,921 output tokens. These are **component measurements**, not end-to-end
agent latency, billed dollars, saved human time, or an advantage over Luna. There
is no matched Luna arm in this diagnostic.

## Engineering, data science and product decision

**Engineering:** Do not lower confidence thresholds, add company-specific branches,
or silently reinterpret the failed cases. The evidence shows both a model judgment
gap and a code-owned uncertainty-routing tradeoff. A source being present and a
watch condition being present do not establish comparable population coverage.

**Data science:** Retain the failed primary gate. The information intervention
improved one reused case, not generalized accuracy. Two repetitions are a stability
probe, not twelve independent enterprise trials. Any next treatment needs a fresh
protocol and must retain these negative controls. Known failures are development
cases thereafter, not held-out proof.

**Product:** The next onboarding acceptance check must include a plausible but
incomplete export, not just a healthy example, an incident and a wholly missing
source. Users care whether work reaches the correct team. An agent that replaces
a dashboard check with unnecessary data-repair tasks has not removed that toil.

The next bounded hypothesis is an explicit, source-bound evidence-validity check
separate from event significance. It must use the source's real population/window
contract, not a default assumption of completeness. Before a production change:

1. Establish whether existing source-health/comparison contracts can express this
   check without a new abstraction. Test partial, mismatched, missing and legitimately
   scoped populations; a regional card must not require the entire company.
2. Predeclare the treatment, routing policy and costs of unnecessary investigation
   versus missed repair. Do not treat a lower confidence threshold as a repair.
3. Require exact outcome, evidence and recipient handoffs across the known failures
   plus independently constructed business families and paraphrased policies.
4. Then run actual binary/MCP onboarding with an agent collecting the contract,
   followed by a matched Luna baseline with the same evidence and final-report
   requirements. Measure setup effort and recurring usefulness separately.

No enterprise-readiness, onboarding-success, full-investigation or comparative
value claim follows from this experiment. The local-adoption goal remains open.

## Reproduction and regression checks

Two internal Luna reviewers independently assessed experimental validity and
engineering/product behavior. Both confirmed the failed primary gate and rejected
readiness claims. The engineering reviewer recomputed all 36 rows against raw
responses; the data-science reviewer also checked request-level label absence and
qualified the synthetic oracle and normalization confound. These are internal
adversarial reviews, not external peer review or a customer validation.

The review found a separate instruction-content defect: `repair_source` reused
analytical follow-up prose without requiring repair first. A subsequent small
engine patch now prefixes source/evidence validation and re-evaluation, includes
existing missing-slot instructions, and retains owner guidance explicitly after
repair. Reachable sources no longer imply sufficient evidence in the completion
instructions. This changes neither model inference, probabilities, thresholds,
recipients nor the failed experimental scores. Tests cover source failure and
semantic insufficiency, with and without owner follow-up. Whether an external
agent follows the improved instructions better is **not measured** here.

The follow-up reviewer caught a composition boundary: valid 8,000-character owner
guidance plus repair/slot text can exceed the handoff limit. The repair path now
references the full attached plan and, when necessary, the exact card version's
guidance instead of silently truncating policy. Tests include maximum-length
guidance and a 12,000-character three-slot plan. The structured plan is retained
unchanged. After this repair, **56 focused tests** plus Ruff and diff checks pass.

Offline evidence audit (no credentials or model calls):

```sh
python -m pytest -q tests/test_evidence_sufficiency_trial.py \
  tests/test_installed_policy_placement_probe.py
```

The archived-evidence test checks file hashes, the frozen input digest, all 36
request/response pairs, evaluator-label absence, raw probabilities, threshold
routing and reported scores. It preserves the failed gate rather than making
tests pass by relabeling failures.

The initial full offline suite passed **2,334 tests with five opt-in skips**.
After the archive audit and initial handoff repair, a second full run passed
**2,337 tests with five skips**. The final length-boundary fix was subsequently
covered by the **56-test focused run** and the reviewer's separate 20-test run;
the full suite was not rerun a third time. Ruff and `git diff --check` passed.
`make verify` could not launch because `uv` is absent
from this shell; the existing virtualenv's pytest and Ruff were run directly.

To reproduce the paid experiment, check out the frozen code revision `2f86814`,
freeze from the retained `transfer-live-11/trace.jsonl.gz` using
`python -m evaluations.evidence_sufficiency_trial --trace PATH --output NEW_PLAN`,
then run the same module with `--live --plan NEW_PLAN --output NEW_RUN
--key-file PRIVATE_KEY_PATH`. Directories must be new. Later code changes require
a new protocol; `jev-latest` may resolve differently and is not an immutable
model version guarantee.
