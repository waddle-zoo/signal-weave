# Redwood: completed-delivery reviews with accessible evidence

Status: source controls implemented; native preflight and expert method review
are in progress. No analyst outcome or improvement is claimed yet.

The first zero-inference native preflight found a transport compatibility gap:
the company MCP's bare `dict` return annotation produced JSON text without
`structuredContent`. The source rows were readable through the agent's MCP
client, but SignalWeave's bridge rejected them. The fixture keeps that format;
the [bridge compatibility fix](../mcp-source-bridge.md) accepts one JSON text
snapshot under the same source schema, identity, tenant and byte-budget checks.
It does not infer an arbitrary vendor API's field mapping. The failed preflight
is retained separately; it is not an onboarding or Jev result.

This is a **known-company development workflow**, not an unseen enterprise.
Earlier Redwood tests used late-shipment counts and a late-order-promises
alternative. This case adds raw dated shipments, unequal warehouse volumes,
planned-operation exceptions, carrier context, coverage uncertainty and the
follow-up of previously affected records. It does not replace or rescore those
earlier findings or the [Harbor result](harbor-onboarding-2026-10-17.md).

## The person's job

A fulfillment lead wants a short weekly delivery assessment, an explanation of
which warehouses or carriers account for movement, and the next justified review.
The agreed KPI is paid, noncancelled **completed shipments by promised date**,
not every customer commitment. Both compared seven-day cohorts have at least
seven days of maturity. In-transit and unpaid/cancelled records remain available
but are outside this KPI; claims must preserve that scope.

Prior owner context defines a two-percentage-point deterioration threshold with
at least 100 eligible shipments in each whole-company cohort. Recorded approved
warehouse maintenance can explain a policy exception only for its dated scope.
Missing coverage calls for data-owner review, not an all-clear. Carrier notes can
corroborate timing without proving a cause. A later lower overall rate does not
establish that earlier delivery-followup cases are closed.

## Matched journey

Two fresh Luna 6 xhigh analysts first discover sources, calculate a useful
readout and retain their own working notes. Both keep identical company SQL,
saved reporting definitions, prior owner references and local evidence-file
tools. Treatment additionally uses the current native/default-profile MCP and
installed SignalWeave skill to author and review its own card. It does not
receive an expert-written card or numerical answers.

An attributed simulated expert reviews the actual saved policy, source scopes,
notes, messages and file manifests before local shadow approval. The first
reviewed native check reuses the initial source without another frontier call.
At each of two later cutoffs, each arm starts a fresh analyst with its own latest
notes, previous brief and file manifest—not an inherited conversation containing
several future weeks. Baseline authors first; treatment runs the first later
check first, baseline the follow-up first. This is not randomized or powered.

The shared `export_query_csv` capability copies exact query results into a real
local file with query, cutoff and source provenance; it returns only a small
sample to the agent. `read_evidence_file` permits audience-labeled readback, and
files survive a fresh analyst session. This is a caller-file-tool **substitute**
in the restricted trial workspace—not a SignalWeave feature, production access
control, actual recipient delivery or proof of ordinary workspace compatibility.
Neither arm gets shell access, hidden fixture code or future source files.

## Prospective checks and limits

Review the useful final work, not just the internal enum: correct pooled counts
and denominators; scope-matched maintenance handling; material unexpected issues
and intended reviewers; supported findings despite uncertainty; accessible
supporting detail instead of an unnecessary row dump; and an evidence-backed
follow-up rather than an invented recovery or cause. Valid alternative query
and presentation paths are allowed. Recipients are proposed, never messaged.

Maximum six primary analyst invocations and six live Jev requests, 60 admitted
tools and 420 response seconds per actor; no actor retries. Between-actor stops
include **all onboarding and recurrence**: 3,000,000 aggregate CLI input tokens
or 400,000 uncached input tokens. These are not in-flight caps or a dollar limit.
Before any inference, the draft's four long conversations were revised to six
fresh analyst sessions under the same aggregate token stops. This avoids giving
later weeks the hidden benefit of an inherited conversation. The earlier native
preflight failure spent no analyst or Jev allowance; it remains separately logged.

Source-bridge authoring and internal expert-review effort are unmeasured and must
not be counted as free in any net-saving claim. SQLite query timings do not
represent expensive Superset/Trino production queries.

Method: `evaluations/redwood_workflow_journey.py`; source:
`evaluations/redwood_company.py`; caller files:
`evaluations/caller_evidence_files.py`. Large snapshots, transcripts and CSVs stay
in ignored `artifacts/`, not Git. Real-human setup, actual message delivery,
customer-hosted connectors and general enterprise performance remain separate
acceptance gates.
