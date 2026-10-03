# Local adoption: implementation and proof gate

Status: implementation advanced; proof gate **not complete**. This updates the
working acceptance criteria for the existing local-first adoption goal; it does
not declare the earlier failed trials passed.

Latest [six-company v6 cohort](enterprise-onboarding-repair-v6-cohort.md): both
arms completed 6/6 setups and 18/18 later reports. Treatment achieved 16/18 native
outcomes/routes and 17/18 strict final reports, versus 18/18 strict reports for
Luna alone. Luna corrected two treatment outcomes. A blinded internal retail
review found a material population-completeness overclaim. The gate remains
**not complete**, with no demonstrated comparative advantage.
Post-run review qualified the finance native comparison: its decisive reporting
cutoff reached Luna/the oracle but not Jev. Retain the failed handoff and original
counts; fix explicit source-context parity before another model comparison.

The [63-call component investigation](jev-v6-state-diagnostics.md) retained both
unchanged requests and explicit missing-evidence controls. A candidate semantics
clarification improved quiet outcomes but weakened missing-evidence judgments and
left required checks unresolved; it is not being promoted to production.
Reporting now exposes literal source boundaries, and onboarding guidance calls
for explicit preview-behavior and recurring-source-coverage review. Those changes
pass offline contracts; their end-to-end benefit still requires a new frozen run.

Earlier [agent-onboarding regression](enterprise-onboarding-journeys-2026-10-02.md):
six synthetic businesses, messy 24-asset catalogs and 48 planned setup/monitoring
episodes. Treatment completed **1/6 setups and 3/18 later reports**, versus Luna's
6/6 and 18/18. All six treatment agents read the guide and obtained a preview;
approval/tool-contract failures prevented five from becoming usable workflows.
That run used 99 live Jev attempts with one provider error, without exhausting its
budget. A native review/approval fingerprint defect reproduced offline at that
revision. Its simulated owner evaluator also conflated source checks with
business-policy changes, limiting attribution of those historical failures.
Subsequent repairs and current qualifications are recorded in the v6 cohort.

Earlier [recurring evidence](recurring-runtime-trial.md): three transfer cards approved;
12/12 structured results and reviewer-usable reports in both arms after completing
five interrupted treatment runs. All 12 treatment receipts replay without new
calls. The original prospective trial remains failed. Arm-masked reviewers
preferred the baseline artifact six times and tied six times, with unequal final
artifact detail confounding a prose comparison. No comparative benefit is proven.
The local rc2 binary is verified on this Mac, not yet published or cross-platform
certified. Remaining proof work is a frozen, equal-output prospective comparison
and actual onboarding/release validation, not more retrospective success claims.

## Deliverable

A locally installable, agent-connected SignalWeave that helps draft and review a
reusable investigation, evaluates fresh evidence with live Jev, and supplies a
faithful evidence bundle to a caller-owned report writer. People supply business
policy and approve definitions and routes. We do not infer undocumented policy,
own the agent/scheduler/delivery system, or promise universal enterprise accuracy.

## Local binary first-use check — October 2, 2026

The rc2 development binary now supplies a read-only `get_signalweave_guide` for
query, report and monitor paths, plus opt-in Codex CLI registration. The existing
GitHub Actions release workflow builds native archives; no new release was
published for this iteration. The local Apple Silicon archive was built from
`2a7939a`, with binary SHA-256
`e6563b79bbc8948d81e93b777a4148a0df4dd97e2854b8f890497217e7b8f96e`.
It passed real installer/private setup checks outside the checkout and all four
MCP guide paths. Claude registration remains manual. Signing/notarization and
managed-device acceptance are not established by these checks.

A fresh private home per synthetic company exercised source inspection, native
card drafting and delivery-disabled report preview with live Jev. Source
contracts and English owner policies were supplied by the scripted driver;
discovery, human usability, autonomous authoring and recurring delivery were not
tested. Six paid tool attempts were used, with no retries or frontier-model calls.
The frozen code was `082e8a1`; period p03 was selected in advance for each of the
three existing fixtures. These are reused cases, not new held-out enterprises.

| Company | Measurements and provenance | Decision and recipient |
| --- | --- | --- |
| Canyon Freight | Correct | Correct: Fleet Operations |
| Helio Support | Correct | **Missed notification** to Support Quality |
| Lattice Energy | Correct | Correct: Commercial Operations |

**This is 2/3 fully correct, not an onboarding success gate.** Helio's weighted
current recontact rate was 11.8056%, above the owner's 9% threshold, yet Jev
selected `ignore`. No code or expected label was changed to excuse that result.
The result shows a policy application failure despite available evidence; it
does not justify blaming missing company context. These cards did not include
source-bound numeric conditions. Whether agent-authored checks improve this flow
must be tested, not assumed from earlier expertly configured runs.

The initial run failed before inference because the harness used a symlinked
macOS temporary path. Correcting the harness preserved the private-path security
check. A second harness defect affected scoring: recurring fixtures express
contributions as records, whereas the first-report scorer expects a mapping.
Offline projection corrected the scorer without changing outputs or making any
new model calls. Both original reports remain unmodified:

- [Zero-call failed run](evidence/installed-first-report-2026-10-02/report.json)
- [Frozen live protocol](evidence/installed-first-report-2026-10-02-corrected/frozen_protocol.json)
- [Raw live outputs and original scoring](evidence/installed-first-report-2026-10-02-corrected/report.json)
- [Corrected scores, hashes and separate Luna review](evidence/installed-first-report-2026-10-02-corrected/adjudication.json)

Reproduce the native preflight without paid inference:

```sh
SIGNALWEAVE_TEST_BINARY=dist/signalweave uv run pytest tests/test_installed_first_report_trial.py
```

The focused native suite passed eight tests. The full offline suite passed 2,007
tests with four opt-in skips before the final scorer-format regression was added;
that focused suite then passed eight tests with one native-only skip. Ruff and
`git diff --check` passed. `make verify` could not launch because `uv` was absent
from this shell; the existing virtualenv's Ruff and pytest were run directly.

That next proof step was run in the
[six-company onboarding regression](enterprise-onboarding-journeys-2026-10-02.md)
and failed. It let the user's agent read the guide, discover supported assets,
and draft from public owner policy without private labels or expert card edits.
Those failures motivated the subsequent source-selection/approval handoff,
evaluation-contract and research owner-review repairs; current proof gaps are
described in the v6 qualification below.
Require first-report review and owner-labeled threshold-crossing, quiet and
missing-evidence acceptance cases before unattended-use certification. Explicit
shadow approval can remain unassessed. Preserve numeric units and
source bindings, inspect actual numeric-condition results, and verify the final
outcome as well as the math. A numeric check alone is not proof of correct routing.
Compare the resulting recurring reports against the same agent without
SignalWeave before claiming better quality, lower cost or less human work.

The v6 work repaired those setup handoffs sufficiently for six fresh agent-authored
cards to reach shadow monitoring, not to satisfy the behavioral gate. The next
acceptance work must make the authoring agent consume actual preview/evaluation
failures, preserve supporting sources needed for explanations, and verify source
meaning is equally available to native Jev and the reporting agent. Independent
current or historical examples must be explicitly supplied or reviewed, not
invented from a model's output or taken from future test labels. Keep all previous
failures and account for extra onboarding review costs. Do not merely rerun the
same study hoping for higher confidence scores.

## Acceptance criteria

1. Audit the existing release/install/setup path and close demonstrated defects.
   Distinguish local/CI evidence from signing, managed-device or customer proof.
2. Keep one coherent bounded Jev outcome decision. Add only approved,
   source-bound numerical checks computed in code, not a Boolean workflow DSL.
   No company fixtures in production and no heuristic substitute for Jev.
3. Preserve source, freshness, authorization, confidence and required-evidence
   gates. Explain model uncertainty separately from observed source failures to
   the final writer. Advisory checks cannot silently become new policy.
4. Exercise fresh agent-assisted onboarding, preview, explicit synthetic-owner
   approval, repeated production MCP evaluations, final reports and exact receipt
   replay across independently authored company fixtures. Freeze holdouts before
   inference. Both comparison arms get the same approved context, source evidence
   and deterministic calculations, including the new numerical checks.
5. Count all intended cases and all attempts. Compare persistent Luna alone with
   live Jev + SignalWeave + the same Luna writer. Review final prose independently;
   correct routes alone do not establish faithful explanation. Measure setup and
   recurring latency/tokens/source reads separately. No dollar or labor savings
   inferred from token counts or synthetic data.
6. Keep single-step/multi-step and safety regression tests passing. Obtain
   adversarial implementation and methodology review, resolve concrete findings,
   retain raw evidence and document supported limits.

For the prospective bounded trial, success requires all frozen intended outcomes,
routes and arithmetic/provenance checks, no unsupported delivered numeric or causal
claims, and exact replay with no additional calls. A comparative benefit requires
no correctness loss plus either at least 20% lower whole-report recurring latency
or at least three masked quality wins with no losses. Otherwise report parity or
failure, not a product advantage. Passing a small synthetic trial is not proof of
universal accuracy or real customer adoption. Failed experiments are never replaced
by reruns. Additional tests require a new frozen protocol and retained denominator.

The research motivating this work is [retained here](policy-composition-investigation.md).
The experimental composition layer remains evaluation-only and rejected for
production. Direct Jev's earlier 12/12 decision score is not a completed end-to-end
reporting result.
