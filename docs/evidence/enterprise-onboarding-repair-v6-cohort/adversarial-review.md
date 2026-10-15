# Adversarial review: v6 cohort and Jev diagnostics

Status: recorded review of the pre-worker exporter/replay implementation. No
live calls were made. No production `src/` change is proposed. Exporter fixes
for the two scoped consistency findings below are in progress and require a
follow-up review after the worker completes them.

## Cohort result and finance qualification

The recorded cohort remains incomplete as an overall acceptance result:

- Luna BI baseline: 18/18 strict structured cases.
- Luna + SignalWeave/Jev: 17/18 strict structured cases.
- Native Jev routing: 16/18; two final Luna reports changed the native outcome.
- Narrative qualification remains unresolved; the narrative gate is not passed.

The 17/18 structured count is not an overall treatment pass. Native routing,
missing-evidence safety, narrative review, and the stated acceptance gate remain
separate requirements. Archived scores should be qualified in documentation;
they should not be rewritten.

The finance native comparison has an additional fairness qualification. The
private fixture oracle requires `control.watermark == public period.as_of` in
`evaluations/bootstrap_scenarios.py`, but frozen Jev request 74 does not expose
`period.as_of`, an authoritative `reporting_cutoff`, or an
`expected_reporting_cutoff`. The public control description says that it
contains the expected reporting cutoff, while the export contains only the
watermark and partition counts. The public `submission_contract` also has no
cutoff field.

Luna receives the simulated period clock. Native Jev receives source capture
timestamps, but capture time is not inherently a reporting cutoff. The added
evaluation-clock probe therefore cannot close this gap: an evaluation clock is
not an authoritative business cutoff unless the fixture explicitly says so.

The finance native failure is consequently underdetermined relative to the
baseline and should not be interpreted as a clean Jev semantic failure. A new
versioned fixture is required before a paid native comparison. It should
publish the agreed cutoff in the control source or trusted context, with
explicit semantics distinguishing it from source capture time and evaluation
clock. The generating oracle need not change, and no metadata should be
invented retroactively.

## Scoped exporter blocks

These are consistency defects in the exporter contract, not claims that the
archived artifacts were tampered with.

1. Before the worker fix, cohort score fields were not bound to the raw
   successful submission or system-evaluation events. The exporter recomputed
   from report-row fields while trace validation checked episode and API usage
   accounting. A report row could be internally consistent with its cached
   score without being demonstrably the value recorded in the raw event.

2. The standalone `export()` path trusted cached scores and native decisions,
   while staged `export_cohort()` performed additional recomputation. The
   exporter worker is binding raw successful submissions/system evaluations and
   adding single-export recomputation; that fix needs review before these
   outputs are treated as scoped consistency-checked evidence.

3. Trace validation proves balanced API attempts, not complete retention of
   every agent/tool event. Omitted tool events or episode-level failure detail
   are not independently rejected by the current validation contract.

4. Component source hashes and context digests are recorded provenance. They
   are not proof of historical source state or tamper-proof authenticity when
   checked against files available later. The exporter should not describe
   current-file hash agreement as historical attestation.

   A separate historical consistency check did verify all 18
   `source_fingerprint.sha256` entries in the remaining-v6 config against the
   committed revision `7703b0d` using `git show <revision>:<path>` followed by
   SHA-256 calculation; every entry matched. The retail and remaining source
   maps are also identical, as previously checked in the cohort verification.
   This establishes scoped recorded-revision consistency without requiring the
   historical files to remain in the current working tree. It still does not
   attest that the recorded execution used only those files or that the run
   itself is tamper-proof.

5. The cohort ledger reports counts and an unassessed narrative gate but does
   not itself emit an executable overall `passed`/`not_passed` acceptance
   decision. Consumers must not promote 17/18 structured exact cases to an
   overall pass.

The exporter also does not enforce every possible arm-level methodological
constraint, such as a zero-Jev baseline, although the recorded run reports no
baseline Jev calls. That is a wider verifier limitation, not evidence of a
problem in the archived run.

## Replay scope and limits

Dynamic state edits in `jev_request_replay.py` are intentional diagnostic
operators. They are not presented as a security boundary, and no general
production repair claim is made from them. The replay documentation correctly
limits the work to component sensitivity and says that answer flips do not
establish repaired evidence completion.

The remaining operational safeguards are:

- restrict the replay output directory to mode 700;
- redact the plan/config/results artifacts, not only the audit trace;
- retain bounded provider error status/code without recording sensitive bodies;
- use controlled synthetic inputs only unless a separate data-handling review
  authorizes otherwise.

The replay retains canonical logical request payloads, not byte-identical SDK
or HTTP requests. It also retains only compact failure classifications unless
bounded error telemetry is added. These are explicit sensitivity-diagnostic
limitations, not strict transport-reproduction evidence.

## Wider methodological limits

The cohort is a staged, known-family synthetic regression with separate
rebased clocks, simulated owner review, and an unassessed full-cohort narrative
gate. It does not establish real-user onboarding, real connector behavior,
unattended delivery safety, commercial savings, or generalized reliability.

No further paid comparison should proceed until the corrected fixture version
publishes the finance reporting cutoff and the exporter worker's scoped
consistency fixes have been reviewed.

## Replay safeguard disposition

Reviewed the current replay runner and the added mocked success/failure tests.
The previously identified operational replay safeguards are now satisfied for
the controlled synthetic-input scope:

- live replay requires explicit `--synthetic-input` confirmation;
- the output directory is created with mode 700;
- `config.json`, `results.json`, and printed progress are passed through the
  audit redactor;
- successful responses and plan values are covered by the redaction test;
- failures retain `status`, exception type, and a bounded HTTP status when
  available, without retaining raw exception messages or headers; and
- the success and failure paths are mocked and do not make provider calls.

The two archived diagnostic configs still record the prepatch runner hash
`339352e18c7ab9d529f8c2b71f8e45b1da1105ec3825990e411842eb1371a05e`. The current
runner has a different hash, so the original diagnostic artifacts remain
attributed to their original runner and are not silently reclassified under the
patched safeguards.

Disposition: the replay output-permission, artifact-redaction, bounded-error,
and explicit synthetic-input findings are closed for this scoped runner path.
This is not a general data-security certification: the operator must still
ensure that the input trace and mutation plan are synthetic, and the runner
still records canonical logical payloads rather than byte-identical SDK/HTTP
requests. Exporter-worker changes remain pending separate review.

## Exporter disposition (current worker revision)

Reviewed the current exporter implementation and its related tests after the
worker revision. The two scoped exporter blocks are cleared:

- Monitoring rows are checked against exactly one successful, author-role
  `submit_analysis` receipt for completed episodes. The receipt arguments are
  normalized through `_Submission` before comparison and score recomputation;
  rejected calls do not count as submissions.
- Treatment native output is checked against exactly one `system.evaluation`
  response for completed treatment monitoring episodes. The retained native
  routing input and derived native decision must agree with that trace-bound
  response.
- Both `export()` and `export_cohort()` recompute structured scores and native
  routing decisions before writing their artifacts. The related tests cover
  cache falsification even when the cached values are recomputed, missing or
  duplicate receipts, rejected/malformed/wrong-actor receipts, and missing or
  invalid native evaluations.
- The explicit machine status is limited to `not_passed` and `unassessed`.
  Structured/native failures produce `not_passed`; otherwise the result stays
  `unassessed`, and the narrative gate remains `unassessed`. No overall pass
  claim is introduced.

The worker reports 225 related tests passed with a clean Ruff diff. I did not
run the full suite or make production-code changes. The reported current v6
remaining/cohort trace-reaudit exports also succeeded with 48 retained records
and the unchanged native 16/18 and final 17/18 outcomes; the archived raw
diagnostic artifacts remain unchanged.

Disposition: scoped findings 1/2 and the explicit-status ambiguity are closed
for this exporter revision. This is scoped recorded-artifact consistency, not
cryptographic execution attestation or proof that every historical log event
was retained. The source-fingerprint qualification above still applies: the
18 remaining-v6 entries were independently matched to committed revision
`7703b0d`, which establishes recorded-revision consistency without claiming
historical execution authenticity. The finance result remains qualified and
is not cleared for a new paid comparison until a new fixture explicitly
publishes the agreed reporting cutoff; an evaluation clock or inferred
metadata is not an authoritative cutoff.

This current section supersedes the earlier pending-review note for the
exporter worker; the replay limitations and finance qualification remain in
force.
