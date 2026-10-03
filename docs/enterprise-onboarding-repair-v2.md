# Agent onboarding repair: prospective regression

Status: implementation under review; live acceptance not yet demonstrated.

The first messy-catalog trial completed only one of six treatment onboardings.
Its failures and raw evidence remain in
[the original report](enterprise-onboarding-journeys-2026-10-02.md).
This repair does not reinterpret that run as a success.

## Goal and stopping rule

Starting with an ordinary brief, catalog and simulated owner answers, the agent
must create its own card without a seeded expert policy or manual card repair.
All six treatment onboardings must complete. All 18 later native SignalWeave and
final agent outcomes and recipient mappings must match the frozen owner labels.
Required numeric facts and their provenance must pass; material narrative claims
must be supported by the current evidence. Independent adversarial reviewers
must check both the implementation and the resulting reports, including quiet
and missing-data periods. Missing reports count as failures.

This is a known-family regression, not evidence of perfect enterprise reliability.
Do not describe the goal as achieved while any part of this gate remains unmet.

## Repairs under test

- Source confirmation binds material policy, source definitions and authorization,
  rather than semantic ranking scores or the order of a bounded result list.
- Explicit selections remain valid when present in the authorized catalog but
  omitted by a later ranking. Selected-source inputs expose their actual schema.
- Workflow evaluation accepts typed snapshots or one explicit current-source
  capture. The server retains source identities and authorization. A single current
  example does not establish full behavioral coverage or enable delivery.
- Authoring guidance separates action policy from unconditional evidence
  prerequisites. Missing historical examples must remain unassessed, not invented.
- Both synthetic owner reviewers receive bounded current catalog and inspected
  source contracts, separately from authoritative owner policy. Source metadata
  cannot invent thresholds, recipients or missing-data rules.
- Both agent arms receive identical mechanical citation validation and instructions
  about qualified measurements. This checks inspected identities and inclusion,
  not truth or expected outcomes; its benefit cannot be attributed to Jev.

## Execution

Keep the original dataset, seed, private labels, scenario families and later
periods unchanged. A focused repair probe uses Harbor Workspace and Cinder Database
Cloud, retaining all their quiet, event and missing-data periods and both arms.
Cap that probe at 64 Jev attempts. It cannot satisfy the six-company goal.

After review and the probe, freeze a separate full run with at most 144 Jev
attempts. Every attempt, error, missing report and reviewer correction is retained.
No runtime or prompt edits, hidden retries, manual card changes, private feedback,
or future-period access are permitted during a run. Any subsequent repair requires
a separately named run and an explanation of what changed.

```sh
python -m evaluations.enterprise_onboarding_journeys --live \
  --company-index 1 --company-index 3 --jev-budget 64 \
  --jev-key-file /secure/path/to/key \
  --output artifacts/enterprise-onboarding-repair-v2-probe-01
```

Omit the company indices and budget override for the full six-company run; use a
new output directory. The wrapper writes its protocol before dispatch, and the
runner records source hashes and the Git revision. SDK retries remain disabled.

Report setup separately from later monitoring. Compare outcome/routing correctness,
numeric/provenance support, unnecessary and missed alerts, source reads, tool
errors, wall time and observed usage. Do not claim dollar savings from saved-login
token estimates or speed advantages from missing/blocked treatment work.

## What this cannot establish

The sources are normalized synthetic MCP assets. The six familiar business families
have scope distractors, not 144 independent real enterprise datasets. Owner review
uses a model, not a real person. There is no real connector installation, live
delivery, scheduler, query bill, months-long operation or causal ground truth.
Passing this regression supports these simulated workflows, not universal adoption.
