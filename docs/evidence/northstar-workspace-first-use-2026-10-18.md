# Northstar: useful first answer before recurring automation

Status: useful first readouts completed; saved recurring draft needs source repair.
This is a synthetic business on real local Superset, not customer validation.
Separate internal reviewer agents checked the method and actual handoffs;
this is not external peer review or a panel of human participants.

## What the owner actually received

Both agents produced useful historical sales readouts. They identified the
misleading partial-month dashboard drop, separated executive net sales from
non-reconciling funnel revenue, and proposed concrete Analytics/Data Trust
checks rather than inventing a campaign or technical cause.

The baseline supplied a weekday-aligned prior-year comparison, raw-fact/mart
reconciliation, reusable SQL and two material owner questions. Its report omitted
an explicit company-wide sales bridge and falsely implied that Analytics and
Data Trust had already reviewed the work. They were intended reviewers, not
participants. Those original claims remain recorded and need correction before use.

SignalWeave's agent made the company-wide net-sales impact explicit, supplied
an arithmetic orders/value decomposition, and saved/reviewed one card. Its
equal-length August/September comparison was repeatedly called “like-for-like”
without establishing weekday/seasonal comparability. The measured figures can
still be reported, but equal duration alone does not establish that stronger claim.

This is evidence of useful first answers and a saved workflow draft—not a
completed onboarding or an incremental whole-journey advantage. The card still
needs owner choices about scope, comparison, significance and freshness. Its
saved `Last week` parameter differs from the unfiltered inspection. A later
native probe established that it was silently ignored (repair below). The next test must resolve the
owner choices and exercise that exact saved workflow, not count approval readiness
as success or blame historical fixture dates on the product.

## Executed first-use pair

| Recorded component | Luna + company MCP | Luna + company MCP + SignalWeave |
| --- | ---: | ---: |
| Response time | 401.15 s | 491.88 s |
| Admitted research MCP calls | 70 | 44 |
| CLI input tokens, including cached prefixes | 2,957,506 | 3,934,074 |
| Cached input tokens | 2,809,600 | 3,751,168 |
| Uncached input tokens | 147,906 | 182,906 |
| Output tokens | 46,959 | 54,927 |
| Live Jev requests | 0 | 0 |

Both had a final message, known terminal usage, retained briefs/notes, no process
errors and unchanged business-data fingerprints. Treatment includes extra card
authoring/review work. Fewer tool calls did not mean faster or cheaper onboarding;
native internal HTTP reads are not included in a total warehouse-work counter.
No dollar cost, general quality ranking or Jev advantage follows from this pair.
The prior incomplete actor below remains an additional unknown-cost attempt.

The actual binary was the unpublished `aac8efd` candidate, production fingerprint
`95b0bc319748c0f0c8ecb4029ecff8a97a5fd8d8bd121bf4baa9bd0a3fb3d7d1`,
SHA-256 `09f7a1fe41ffa8e3b68eee8d140e79f0572f2c03e40c50a791bb29ef73e4dcb6`.
It was current when the closed pair ran. Later guidance fixes do not rescore it.

## What matters to the user

The owner sees an unexpected online-sales decline and wants its contribution to
net sales explained. Analytics and Data Trust investigate first; leadership gets
a concise update after investigation. The owner also wants to repeat the check
daily. A useful answer comes before card approval, not after a setup questionnaire.

We assess the whole handoff, not whether an outcome enum matches a label:

1. Does the readout answer the sales question with reproducible arithmetic,
   correctly scoped sources and actual measurement dates?
2. Does the investigation narrow the next useful check without asserting an
   unproved cause, complete coverage or completed delivery?
3. Is the message short and relevant to its intended reader, with evidence the
   next analyst can inspect rather than a verbose inventory of tool calls?
4. Does onboarding preserve useful definitions and source choices, identify only
   material owner questions, and avoid inventing approval or business rules?
5. Is there a credible reusable workflow? In the treatment, inspect the saved
   draft and actual review. In the baseline, inspect its actual notes/runbook.

Independent review should classify each item as supported, partial, unsupported,
or not exercised, with examples from the actual work. Successful setup or model
completion does not establish any of these outcomes.

## Arms and execution

Both fresh Luna agents receive the same owner request, analytical guidance,
independent community Superset MCP, private ordinary workspace, shell and files.
They can discover databases, inspect dashboards/charts/datasets and run SQL or
export results. Source mutations are excluded at discovery and dispatch. The
fixture database disables DML; this is not proof of enterprise access isolation.
Shared execution-history listing/detail tools are excluded so a later analyst
cannot browse earlier agents' investigative SQL. Execution results and CSV export
remain available from query identifiers returned to that analyst.

The treatment additionally has the current native SignalWeave default `agent`
profile and its actual native-installed workflow skill. It should return the
first useful readout, then draft and review one reusable card if possible. It
must not approve or evaluate the card without owner review. The baseline keeps
its own notes and gets no instructions referring to unavailable SignalWeave tools.

The native executable is copied to a fresh private installation and the real
PTY setup wizard registers it with isolated Codex configuration. This tests a
source-built candidate, not downloading a published release or a human panel.
The community MCP is
[bintocher/mcp-superset](https://github.com/bintocher/mcp-superset), revision
`4e0a856a1d45b8f2799e6926dac41fbc64307191`, in a separate environment.
The analyst launch uses an isolated audited MCP bridge to those actual source
and native processes, not the user's personal registered MCP inventory. Original
source replies are also saved into both workspaces; this is an experimental
convenience, not an advertised native SignalWeave export feature.

The declared order is baseline then treatment. Each has one attempt, at most
600 response seconds, 90 MCP calls and 40 workspace calls. Admission stops
between actors at 4 million cumulative CLI input tokens or 350,000 uncached
input tokens. In-flight usage may cross an admission threshold. Missing usage
or an incomplete attempt stops further admission; neither is counted as zero.
No Jev requests are admitted in this first-use phase because approval has not
occurred. Later policy evaluations require a separately reviewed continuation.
Both agents see remaining tool budget, are asked to begin with targeted named
assets, and save a supported provisional brief before optional wider exploration.

This pair is diagnostic, not a statistically powered superiority comparison.
Treatment card setup is extra work: raw first-use times cannot establish the
ROI of recurrence. Baseline source access must remain available in later runs.

## Reproduction and audit

Method: `evaluations/northstar_workspace_journey.py` (`prepare`, then `actor`).
Revised evidence stays in ignored `artifacts/northstar-workspace-first-use-v5`;
the original attempt remains in `artifacts/northstar-workspace-first-use-v4`.
The frozen study records native/Codex identities, source revision, prompts,
tool scope, workspace inventories, sandbox checks and before/after warehouse
data fingerprints. The source environment's installed code and dependencies are
fingerprinted too, not just its entrypoint. Source replies are retained as original JSON/content with
hashes in each analyst's workspace for code-derived supporting evidence.

Preparation completed without paid inference: fresh wizard and registration,
native skill installation, actual company SQL probe and sandbox checks passed.
An earlier zero-inference preparation failed because the study supplied the
wrong canary text to an existing sandbox-check helper. Its log is preserved;
it is a method defect, not a product failure or an analytical trial.
The second preparation passed without inference, but independent review blocked
analyst admission because shared SQL history remained visible. The final method
closes that access before admitting either analyst; no analytical run was retried.
The third preparation passed, but admission caught an inventory-order defect:
the sandbox probe's own file was created after the starting inventory. No model
invocation occurred. The corrected method inventories after that probe; the
failed admission log remains preserved.

## Original attempt: incomplete, not a product comparison

The baseline made 60 admitted MCP calls before its 175-second run was terminated
at the research tool budget. Three additional attempts were rejected. It had
retrieved the full 1,200-chart catalog twice and reached 12 substantive SQL
queries, but saved no business brief or working notes. Terminal CLI usage was
not returned: its cost is unknown, not zero. Treatment was not admitted; Jev
requests were zero. This is not evidence for or against SignalWeave.

Two method problems were retained, not rescored: the hidden remaining budget
and short termination drain did not allow a normal synthesis handoff at the
cap; a 6.9 MB retained source reply also exceeded the borrowed 2 MB inventory
limit, adding an unrelated collection error after termination. The revised
method shows remaining budget, reserves finalization effort, uses an appropriate
streaming file inventory, and keeps collection errors separate from episode and
brief status. The original is not converted into a completed baseline.

Independent review admitted a separately specified revised pair on the same
known question, not an untouched holdout or a continuation under the original
accounting. All three actual analyst attempts (including
the incomplete original) belong in any overall effort discussion. The revised
pair still stops at its tool/time bounds: remaining-budget guidance is not a
guarantee of completion, and unknown terminal usage will stop its second arm.

Provider cost, total warehouse work, actual delivery, owner satisfaction and
recurring reliability remain unproved by this phase. Native internal source
reads are not a complete warehouse-cost counter. A real human must still test
the installation and decide whether the resulting workflow is worth using.

## Product follow-through

After closing the pair, the default onboarding guidance was clarified: give a
source-backed answer before card setup/approval, and treat the first approved,
delivery-disabled evaluation as the separate recurring demonstration. It also
asks the agent to inspect the proposed source's exact parameters and aggregation
before approval and retain the working SQL/procedure in caller notes. This uses
the existing `inspect_resource(parameters=...)`, not a new API or approval gate.
These changes are not credited with the earlier readouts or a recurrence win.

An initial source-review concern about unavailable preview guidance was corrected:
the default root already excluded that tool. The demonstrated wording issue was
the start guide's conflation of first answer with approved-card evaluation.

### Exact-scope probe found a consequential product defect

The rebuilt `15ce3ce` native completed fresh scripted setup and returned the
updated guide without inference. But inspecting the draft's exact `Last week`
parameter still returned all 8,937 saved-query rows. Metadata echoed the requested
parameter beside results from saved `No filter`; it did not apply that parameter.
This is a real retrieval-contract defect, not a problem with Jev or fixture age.

The bounded repair rejects unsupported source parameters during both source
authorization and inspection, including Preset's inherited path. Charts execute
their saved query; dashboards additionally support `chart_ids`. This does not
add time-range override support or silently remove the requested filter. A
specific parameter error survives onboarding rather than misleadingly presenting
it as a permission/catalog failure. Company BI/SQL tools remain available for
the analysis; a repeated card must use a source that actually supplies its
intended evidence. Existing invalid cards need review, not automatic rewriting.

The original pair and the faulty probe remain unchanged. Rejecting a bad scope
closes silent substitution; it does not demonstrate that this daily card now
works. Correct source selection/aggregation and a complete shadow handoff remain
the next business acceptance test.
