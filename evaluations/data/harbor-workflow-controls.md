# Harbor formative workflow materials

These are **development inputs**, not executed agent trials or business results.
They address the [workflow study's admission findings](../../docs/workflow-research-plan.md#product-and-de-admission-review-of-harbor-workflows).
The old retrospective fixture and every stopped paid cohort remain unchanged.

## Owner knowledge, separate from source facts

A product-domain author prepared [two fictional owner briefs](harbor-workflow-owner-briefs.json)
using product/business-analysis skills, without agent outcomes or fixture totals.
Each includes an ordinary opening request, prior intent, expert facts/unknowns,
audience, proposed policy and a distinct unresolved alternative. These are not
gold cards or approval of an unseen card. A future analyst must inspect sources,
obtain material clarification, show its actual saved brief, and obtain the
exercise owner's explicit approval before evaluation.

| Requested version | Proposed meaning | Still outside its scope |
| --- | --- | --- |
| Weekly support brief | Latest fully ended UTC creation week; pool misses/eligible counts among priority tickets with known resolutions; at least 20% merits a manual-review callout | Not all-ticket attainment, an age-matched deterioration test, complete event history or a causal conclusion |
| Queue handoff | Known open priority tickets without a visible response, strictly past their tier's response clock; any qualifying item merits a review draft | Responded-but-open resolution work is different; unknown assignees, customer harm and causes cannot be invented |

The round rate threshold and one-ticket review rule are fictional prior policy,
not calibrated industry defaults or values selected for treatment success. The
source must never import these briefs, expected decisions or private assessment.
Both future arms receive the same owner/expert access. Drafting is not sending,
and approval of a card does not authorize a schedule or external delivery.

## Controlled source histories

[`harbor_workflow_history.py`](../harbor_workflow_history.py) builds separate
raw histories from the existing operational fixture. It adds eighty opaque-ID
enterprise/north tickets in one creation week. They initially have no known
resolution, later resolve, and optionally have a timely recorded response.
The first published creation manifest includes the additional work; this is not
a late-manifest correction experiment. The original fixture's separate delays,
priority correction and resolution retraction/revival remain.

Four priority/response combinations distinguish workload volume, unanswered
priority work and responded-but-open resolution work. A separately labeled
`complete_background_responses` control gives ordinary tickets recorded timely
responses, available with their creation. This is a deliberately constructed
quiet background—not a neutral rewrite of first-response behavior, representative
incident prevalence or repair of an earlier cohort.

Under that control, independent raw-history calculations and actual bounded SQL
check qualifying unanswered priority counts of zero → eighty → zero only for
the priority/no-recorded-response variant. Other combinations add substantial
work without satisfying that rule. The ordinary snapshot is byte-identical to
its matched no-addition control; the future additions cannot leak into it.
These are factual case checks, not Jev classifications or final-agent outcomes.
This simple count rule is also expressible in SQL; the control cannot establish
an intrinsic Jev advantage over a correctly authored reusable query/script.
Measure actual onboarding/reuse effort and final outcomes instead of forcing
the baseline to reason through the same arithmetic again on every observation.

The earlier preflight's unanswered aggregate includes nonpriority tickets and
cannot answer this narrower rule. The new
[`harbor_workflow_sources.py`](../harbor_workflow_sources.py) adds one fixed SQL
resource with separate known priority response/resolution clock counts, while
retaining the original reads. It adds no threshold, outcome, recipient or causal
claim. Both future arms receive the SQL and the original raw-query tools; they
can obtain ticket details separately. This is disclosed operator source
preparation, not an ability the product or acting agent has already demonstrated.

Three weekly observations exercise the queue trajectory. A separate event-
triggered follow-up after resolution arrives, but before the next week ends,
keeps the added cohort in the weekly brief's latest-closed-week population.
Do not substitute the later weekly observation: by then another cohort is latest.
The follow-up is a dependent continuation, not another independent weekly sample.

An additional delayed-resolution-arrival variant leaves tickets reported open
even after their private effective resolution time. It tests as-known evidence:
agents must not read future arrivals or mistake creation-count reconciliation for
resolution-event completeness. No source event establishes why work increased,
whether a customer was harmed or who an individual assignee is.

## Before actor execution

Run the [source checks](../../tests/test_harbor_workflow_history.py) and independent
review. Freeze exact inputs, owner interaction, source scope, model/tool budgets,
native identity and assessment rules in a new cohort. Do not reopen an old quota
series. These materials alone do not admit paid execution.

For historical native runs, keep the synthetic business clock explicit and use
an owner-reviewed retrospective scope without a present-day freshness SLA.
Do not rebase capture dates to today, monkeypatch a production clock or claim
that this establishes live operational freshness. Test that property separately.

Assess the actual human message and saved artifacts, not just the internal
outcome name. Accept a supported review recommendation without requiring one
particular analysis path. Missing optional evidence cannot erase known facts;
an unresolved alternative definition must not be silently chosen. Neither a
quiet trigger nor a high-support policy result means the whole service is healthy.
Keep baseline source tools, context, durable notes and safe reusable queries.

### Next bounded feasibility journey (not admitted)

The proposed first complete pair uses the queue-handoff variant. One analyst per
arm discovers the same sources, produces a first useful readout and saves its
own reusable brief/card. The exercise owner/expert then reviews the actual
artifacts—not an unseen template—before approval. A later analyst per arm uses
those retained artifacts through ordinary, changed and recovery observations.
This is four analyst invocations, not four independent companies or proof of
long-running autonomy. The three observations remain dependent continuations.

A caller-owned local shadow-message sink can record the actual draft recipient,
body, evidence references and acknowledgement state. If the feasibility run
advances source time after each completed requested brief within one analyst
context, disclose that orchestration; it is not a deployed scheduler or fresh
agent session per week. Quiet alerts and explicitly requested routine briefs
must remain distinct. Never advance time on a failed/unfinished check or expose
later source files through the read tools.

Both arms must be able to discover the same saved SQL definitions: adding a
native manifest alone does not expose that preparation to baseline's company
catalog. Account for operator preparation and expert review, and retain the
baseline's own reusable queries/notes. Do not require an analyst publication or
special metric-registry submission merely to finish a human readout.

Proposed ceiling: four Luna 6 xhigh analyst invocations and six Jev requests,
no retries; between-invocation stops at 700,000 input tokens, 150,000 uncached
input tokens, unknown usage or changed inputs. These are not in-flight token
limits or a dollar cap. Further owner/reviewer model use must be explicitly
budgeted rather than silently counted as free. This ceiling and temporary idle-
sleep prevention have been requested from the user, not approved by this file.
Freeze the actual runner, scope, final assessment and host choice before use.
The larger prospective study and ordinary-workspace/human tracks remain open.

### Staged complete-journey caller

[`harbor_workflow_journey.py`](../harbor_workflow_journey.py) implements that
bounded path, separately from the closed authoring cohort. `prepare` creates
identical historical inputs, separate active source copies for both arms, a
private native setup and the candidate's actual installed skill. It makes no
analyst or policy requests. Preparation is scripted operator work, not proof of
a person's installation experience.

```sh
.venv/bin/python -m evaluations.harbor_workflow_journey prepare \
  --binary dist/signalweave --codex "$(command -v codex)" \
  --key-file "$TYPESAFE_API_KEY_FILE" --output artifacts/harbor-complete-journey-new
```

Paid actors require a separately reviewed execution scope, approved budget and
host choice; preparation alone does not authorize `--execute`. Each author arm
finishes with its actual ordinary reply and reusable notes. Treatment drafts
and reviews its own fixed-source card; neither author may approve or evaluate.
There is no mandatory publication or special answer-submission endpoint.

Before recurrence, an expert must inspect **both actual** first replies and
retained artifacts, including the treatment's saved policy and source scope.
Supply a private review JSON with `approved_for_shadow_recurrence=true`,
`reviewer`, `reviewer_type` (`human` or `simulated_expert`), `reason`, and
`artifacts` mapping each arm to its saved `review_artifact_digest`. Include
`assessments` with the actual semantic findings for each arm and a separate
`source_selection_reason` recording the confirmed definitions/populations and
why those sources fit; that specific confirmation becomes the native approval
reason, not a generic approval phrase. These digests
only identify what was reviewed; the file does not prove semantic correctness
or that a real person participated. Record the actual expert assessment too.
An inadequate card/brief is an onboarding finding, not permission to substitute
an expert-authored gold card or silently repair the closed actor's result.

```sh
# Only after the required execution approval, once per arm/phase:
.venv/bin/python -m evaluations.harbor_workflow_journey actor \
  --study artifacts/harbor-complete-journey-new --arm signalweave \
  --phase onboarding --execute
# Repeat for baseline, review both actual outputs, then:
.venv/bin/python -m evaluations.harbor_workflow_journey actor \
  --study artifacts/harbor-complete-journey-new --arm signalweave \
  --phase recurring --review-file /path/to/actual-expert-review.json --execute
# Run baseline recurrence with the same review and its own retained notes.
```

One later context per arm handles three dependent observations. The caller
advances its active source only after `save_brief` persists the actual requested
brief. Alert-recipient keys may be empty for a routine no-trigger update; this
is not an alert-only savings experiment. The sink is local, delivery-disabled
and has no invented acknowledgement. The agent finishes in ordinary language.
The baseline retains the same company SQL tools, prepared query definitions,
owner access and its own portable queries/notes. Native reads, actor work,
coordinator setup/review and provider requests must remain separately accounted.

`process_complete` records a finished invocation plus retained workflow work,
not correct analysis, right recipients, good communication or comparative lift.
`policy_path_exercised` separately requires distinct, non-replayed, non-deferred
Jev receipts for the reviewed card at all requested cutoffs and known provider
usage. A finished report without that exposure is not a successful Jev treatment.
Inspect every actual brief and its source support before making those claims.
No automatic retries are offered. A failed, unknown-usage or over-limit actor
prevents further actors; the token thresholds apply between invocations and
cannot cap an in-flight turn. Original failed/censored cohorts remain untouched.
The transport's legacy `max_turns`/`max_output_tokens` arguments are not CLI
caps; the enforced limits are the response deadline, tool allowance and provider
request allowance, with token stops between actor invocations.

Use `summary --study <directory>` to inspect the actual replies, shadow briefs
and recorded effort. Its `recorded_total_usage` totals frontier CLI tokens only;
Jev usage is shown separately per stage. These are not invoices, human effort
or the cost of manually preparing the source bridge. The prepared study also
records scripted setup time and which human/operator effort remains unmeasured.
Current v2 preparation passed with zero provider attempts and scoped internal
review; actor execution remains unapproved. The initial v1 preparation and
pre-fix software checks stay separate, not rescored as final-method evidence.

### Shared-source execution prerequisite

The companion [workflow MCP](../harbor_workflow_mcp.py) now exposes
`list_saved_queries` as well as its four raw-source tools. It returns the same
four prepared SQL definitions, hashes and scopes as the native catalog, without
deployment transports, credentials or private future history. This closes the
discovery asymmetry described above; it does not prove an analyst will use the
right query or save a correct card.

The [persistent-session source preflight](../harbor_workflow_preflight.py) runs
one temporary private native setup, then reuses one default-profile native MCP
session and one companion session while the caller advances the active data
copy through three historical states. Immutable input snapshots remain retained.
Both surfaces read current data from the same path; the native configuration
and connection are not recreated for each observation.
These are two **outer** client sessions. The native adapter opens a child source
session for each inspection (twelve here); this is not two total end-to-end MCP
sessions, pooled upstream connections or a performance result.

The first actual capture completed: twelve native and twelve companion exports
matched exact direct SQL rows, with thirty evidence blocks across both surfaces.
The priority unanswered-clock count changed 0 → 80 → 0. All four SQL definitions
matched on both catalogs at each clock. The report records source aliases,
contracts, provenance, input hashes and unchanged listed method hashes. Its
provider budget was zero, with zero attempts or rejected-request events.

Reproduce with a matching locally built native candidate, into a **new** output:

```sh
.venv/bin/python -m evaluations.harbor_workflow_preflight --binary dist/signalweave --output artifacts/harbor-workflow-new-source-capture
```

The local `artifacts/harbor-workflow-persistent-source-v1/report.json` SHA-256 is
`d2c8311e15d990584387aa9d2032927bde52a050c1d8cc29a17f5b3b8e5d090a`.
The executable's production fingerprint matched this checkout; it is the same
dirty-tree `0.2.0rc3` source candidate recorded in the earlier source checkpoint,
not an exact clean-HEAD build or a new published release. This is actual local
SQLite/company-MCP transport, not a vendor-hosted connector, real-person setup,
card approval, policy evaluation or an agent's useful final message.

Independent review recomputed the v1 capture from its retained snapshots and
confirmed those recorded facts. It also found two checker gaps: accepting
unrelated nonempty provenance and losing a validated companion result when the
following native read fails. The v1 report remains unchanged; its exact method
is retained locally as `method.py`, hash
`0614b249425dc601c5b3cdfc00f027abc1cb1c397c3c39eda5a1164768bf0134`.

The repaired validator compares row and metadata provenance to the direct SQL
read set. Per-resource progress retains companion evidence before native work;
an injected native failure verifies this negative path. A **separate v2 capture**
passed the same source observations on byte-identical input snapshots with zero
provider attempts. It is a technical repeat, not additional business cases.
Independent review cleared that exact report and the scoped repairs, not actor
admission. Its local report SHA-256 is
`54a831f362ba1df9c20cd19d02f24eff834af7ba594d0f30d68db684057004cd`.

Final source-checkpoint verification passed lint and **4,370 tests**, with
**12 opt-in skips**, in 308.49s on Python 3.12.10. Eighteen guard/MCP checks also
passed on Python 3.11.6 in 21.98s. These are software checks, not agent episodes.
The final full log SHA-256 is
`2a746bac72909565eafd607e67c4bf251debbc30391984e1244b6c9da132f0e4`;
the Python 3.11 log is
`a4e335f4096dea2bc6366ca577a96897c7a2ac91bed6bbd2212eb1fa7d4cffe9`.
The earlier full-suite run predates the guard repair and remains diagnostic.

## Validation checkpoint

The controlled-history checks passed 29 tests in 107.24s, including independent
raw-state/SQL reconciliation and the resolved-cohort follow-up. Internal DE
review closed two fixture findings: a redundant same-arrival manifest revision
was removed, and the follow-up was moved before the selected cohort rolls over.
The initial failed test's broad selection of future resolution revisions remains
in its diagnostic log; the repair selects the actual added ticket identities.

The opt-in terminal-reply path passed 117 offline return-path tests in 1.54s.
Independent code review first rejected post-completion activity inheriting an
earlier reply; added regressions and an EOF-validity guard close that finding.
The same transport checks plus the new fixed-manifest check separately passed
118 tests on Python 3.11.6 in 1.28s. These use fake Codex processes, not live
agents. The first whole-suite run predates that final repair and is diagnostic
only. Final `make verify` passed lint and **4,352 tests**, with **12 opt-in
skips**, in 306.23s on Python 3.12.10. Research code/test fingerprints remained
unchanged during that final run; no production source or native build changed.
These are software counts, not business observations.

Ignored evidence logs (SHA-256):

- `artifacts/harbor-workflow-history-focused-v1.log`: `45531b200893503b8bb8dc2968263c6fa573618890935fe1ba409deda8a5227f`
- `artifacts/harbor-workflow-history-reviewed-focused.log`: `d10d785b9bc09d12e8dcfee60eb6f6af5800635ecd42fa6f898fd64495efb7c9`
- `artifacts/codex-final-message-reviewed-focused.log`: `560ff04b90193ced3c9d5b9679ea03ddc5549a568abcf6d3d73739fad7862805`
- `artifacts/harbor-workflow-python311-focused.log`: `c44c54bed6b06cb5ea6d71e44cea72ce89435af50550d00131d5b354d5b46644`
- Earlier whole-suite diagnostic: `d0f55ae80376d0ba93d7797fb8bad401c5d623f098cbbf6dbb26ad37546867b0`
- Final `artifacts/harbor-workflow-controls-full-verify-v2.log`: `7c03baa90e504662e6f59cc450bb30ef5e76131a540d1e53b14ff3843e3ead0c`

No new acting analyst, Jev request, actual human session, card approval, sent
message or paired business outcome has run in this checkpoint. Source materials,
internal review and software checks cannot substitute for those results.
