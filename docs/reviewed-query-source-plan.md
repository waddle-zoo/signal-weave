# From an analyst's answer to a repeatable check

Status: source implementation and native packaging were tested, but the first
full onboarding attempt failed at native inspection. Interface repairs and
expert migration are being evaluated. **Not a published release, successful
onboarding trial or demonstrated comparative benefit.** See the
[actual journey and retained failure](evidence/query-source-onboarding-2026-10-18.md).

The implementation uses the existing connection and a private reviewed artifact;
see [query-source usage](query-sources.md). Offline tests cover schema/SQL shape,
clock continuity, source identity, dynamic result columns, bounded transport,
token refresh, Preset consent/limits and the human CLI. A real local Superset
4.1.3 query returned the retained analyst's 12-row observation without a reader
process or new credentials. Its exact-equality assertion against the community
MCP capture failed on decimal representation/rounding, not business totals;
a separate no-request review confirmed that distinction. Original evidence is
retained. None of these checks completes the business acceptance gates below.

## The user experience to deliver

The person asks a business question. Their agent answers with existing BI tools,
clarifies only material ambiguities, and offers to repeat that useful check.
They review the meaning, source, attention rules and proposed message—not write
a Python integration, decode API envelopes, or deploy a second MCP service.

After that review, an ordinary run gets fresh measurements, applies the saved
card policy, and gives the caller useful evidence and next steps. The agent can
investigate further and write the final human explanation. Scheduling and sending
remain caller-owned. No claim that SQL alone explains a cause.

## Why this is next

[Northstar's retained-analysis journeys](evidence/northstar-workspace-first-use-2026-10-18.md)
produced useful answers but no overall treatment advantage. A publication source
still required frontier analysis before policy evaluation. The subsequent source-
authoring attempt exposed substantial custom integration work even for baseline.
Neither is the easy recurring workflow we want to offer.

The existing native Superset path executes saved chart definitions. The generic
MCP bridge expects a normalized `ResourceSnapshot`. Keep both; add a first-class
route for an agent's reviewed analytical query without requiring another reader.

## Small implementation boundary

1. **Preserve the analyst's executable work.** Save a fixed query, its existing
   connection, input/date semantics, bounded result shape and ordinary-language
   definition. Keep SQL and company-specific aliases outside production code.
   Reuse existing card/source storage and review where practical; do not add a
   new workflow engine or another mandatory approval bureaucracy.
2. **Own the connector plumbing.** Reuse native credentials, authentication and
   source identity. Handle synchronous/asynchronous results, bounded polling,
   row/byte limits and query/result references. No second credential store,
   custom subprocess, or user-installed SDK for the shipped native path.
3. **Preserve measurements, not guesses.** Carry named result columns, nulls,
   units/definitions supplied by the analyst, explicit comparison windows and
   actual query provenance. Do not infer aggregation, complete ingestion or a
   policy outcome from a column name. SQL or existing diagnostics performs math;
   Jev sees compact facts and the saved plain-English policy.
4. **Review the actual runnable check.** Show source/query scope and a real
   delivery-disabled readout, not just catalog health or a ready label. Keep
   draft inspection and execution authority explicit. Changes to SQL/scope must
   be visible; a mutable saved-query ID alone must not conceal replacement SQL.
5. **Make recurrence ordinary.** Declare business timezone, relative-date meaning
   and historical cutoff behavior. Refresh at the next cutoff without editing
   SQL or republishing an analyst file. Never quietly substitute host date or
   `MAX(date)` for the requested business window. Errors stay errors, not stale
   last-good measurements or zero-valued all-clears.

Start with the actual Superset connection, then verify the Preset authentication
path separately. This is a connector capability, not a Superset-only product
direction. Do not claim Hex, Looker or arbitrary company MCP support from it.

Superset documents [SQL execution](https://superset.apache.org/developer-docs/api/execute-a-sql-query/)
and [result retrieval](https://superset.apache.org/developer-docs/api/sql-lab/).
Those pages describe Next; the local trial is **4.1.3**. Verify behavior against
the installed server before choosing request/auth/polling contracts. SQL Lab
POST/session behavior must not be assumed equivalent to chart reads. Parser
checks are not a sandbox: preserve the source's actual read permissions and
warehouse credential boundary; do not advertise that a `SELECT` prefix proves
absence of side effects.

## Evidence required before calling it useful

- Reuse the actual expert queries and owner intent. No researcher-made analysis
  or scenario-specific production shortcuts.
- Onboard through the current native executable and normal MCP profile; record
  every additional user/agent step and dependency. No unpublished developer
  runtime disguised as a one-line human installation.
- Match the expert's requested first answer, then refresh changed cutoffs and
  preserve company/segment reconciliation. Test attention, quiet and meaningful
  data gaps before claiming unattended reliability.
- Inspect the human message: what changed, why it merits attention, supported
  explanation versus hypothesis, evidence and next actor. A correct enum alone
  is not a business outcome.
- Compare with the capable agent's real retained notes/scripts and full BI tools.
  Baseline may automate deterministically. Count setup, corrections, source work,
  inference and human intervention, including censored attempts. If both paths
  provide equal utility more simply without SignalWeave, report that result.

Admit the smallest complete journey first, independently review actual outputs,
then transfer to different schemas and business policies. Do not replace this
with another large count of component cases or claim generalized enterprise
value from one company's quiet checkpoints.
