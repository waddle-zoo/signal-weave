# Enterprise onboarding repair v3: aborted run

Status: **aborted / incomplete**. This is an archival audit, not a result report
and not a narrative success claim.

The run was deliberately interrupted with SIGINT. A subsequent check confirmed
that the reported PID 71159 was absent and the runtime session was gone. The
frozen revision recorded by the run was
`3860519877bb47b14b9d80312e7b807f57735c1d` (`3860519`). No runtime edits were
made during the run.

The immediate abort reason was a protocol defect exposed during Juniper
treatment onboarding. The first synthetic owner review correctly rejected an
arithmetic error. The second review then demanded that the owner rule be copied
into `numeric_conditions`, even though the inspected source had no analytical
comparisons and declared no required comparison keys. After the draft added a
`previous_period` numeric binding, the third review accepted it. The trace shows
that this was an invented comparison binding: both inspected source snapshots
have `analytical_comparisons: []`, and their contracts have
`required_comparison_keys: []`. The later preview itself reported the required
comparison as missing and returned `insufficient_data`. That acceptance was not
valid evidence of a working comparison contract, so the run was intentionally
stopped rather than allowed to continue as a passing trial.

## Denominator and export status

The protocol intended 48 episode records: six companies, two arms, one onboarding
episode, and three monitoring episodes per arm/company. The archive contains nine
episode JSON records. There is one additional Harbor treatment onboarding attempt
visible only in the raw trace; it was interrupted before an episode JSON record was
written. The remaining 39 intended records have no observed result. They are not
treated as successes, failures, or estimates.

The complete exporter was not produced. This partial audit must not be substituted
for the required complete export.

## Exact observed provider attempts

- `gpt-5.6-luna`: 12 OpenAI request records, IDs `-1` through `-12`; 11 response
  records and one request without a response (`-12`, the trace-only Harbor
  treatment attempt). These include agent invocations and synthetic owner-review
  invocations; they are not a claim about hidden SDK retry counts.
- `jev-latest`: 15 Jev request records, IDs `1` through `15`; all 15 have response
  records and none is recorded as a failed request. IDs `1–12` belong to the
  Juniper treatment onboarding episode; IDs `13–15` belong to the trace-only
  Harbor treatment onboarding attempt.

## Partial outcomes

The nine retained episode records are summarized in
[`partial-audit.json`](evidence/enterprise-onboarding-repair-v3-full-01/partial-audit.json).

Juniper Trail Retail has one completed baseline onboarding, one failed treatment
onboarding (`no_structured_submission`), and three completed baseline monitoring
records. Its three treatment monitoring records are blocked before agent/Jev
execution because treatment onboarding did not complete; they have zero tool,
OpenAI, and Jev calls. The failed treatment onboarding did execute work: it used
12 Jev attempts, three owner-review attempts, and retained two rejected owner
reviews before the final no-structured-submission termination.

Harbor Workspace has one completed baseline onboarding with an approved synthetic
owner review. Its treatment onboarding is trace-only: one model request (`-12`),
three Jev responses (`13–15`), ten observed tool results, and a final
`onboard_insight_card` result were retained before SIGINT. It did not complete
onboarding and has no score.

Kindred Helpdesk, Cinder Database Cloud, Mosaic Exchange, and Lumen Freight
Finance have no observed records in this aborted run. No outcomes are assigned.

## Archive

Raw trace data is preserved compressed at
[`trace.jsonl.gz`](evidence/enterprise-onboarding-repair-v3-full-01/trace.jsonl.gz).
The nine raw episode records are preserved individually under
[`episodes/`](evidence/enterprise-onboarding-repair-v3-full-01/episodes/), with
the run configuration and protocol sidecar retained alongside them. The archive
manifest and recorded hashes are in
[`partial-audit.json`](evidence/enterprise-onboarding-repair-v3-full-01/partial-audit.json).

No scoring, completion inference, comparative claim, reliability claim, or
narrative success claim is made from this aborted run.
