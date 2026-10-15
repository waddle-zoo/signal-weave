# Reusable domain context

Feature branch: `feat/domain-context-memory`, based on main `e8842ac`.

## Current acceptance ledger

| Requirement | Evidence and remaining work |
| --- | --- |
| Local and hosted context lifecycle | Native stdio and signed HTTP checks cover review, reuse, restart and changed revisions; hosted issuer is synthetic |
| Card-bound meaning and staleness | Contract tests cover exact pins, reapproval, deferred policy and historical receipts; no automatic notification service is claimed |
| Approved cards with live decisions | One scripted retail integration matched three supplied periods; stronger route/content checks still need a live run |
| Human-first, agent-led onboarding | CLI/protocol checks pass, but the last live authoring pair did not complete equivalent reviewed automation; a new cohort must demonstrate the corrected path |
| Useful recurring reports and investigations | Historical simulations remain evidence for their own versions; current cross-session final-agent outcomes, diverse connectors and meaningful changed-context cases remain unproven |
| Comparative business value | No current context-layer advantage over an equal-information agent baseline has been established; report usefulness, noise/misses, source work and complete costs are still required |

These are separate gates. Passing storage, authentication or a scripted decision
check cannot substitute for complete onboarding and useful final agent outcomes.

## New owner-workflow development cohort

Before live execution, freeze `owner-workflow-v1`: existing development fixture
`split=dev`, seed `20261015`, company index `1` (Pine Courier), and monitoring
period index `0`. The old fixtures, failed attempts and closed budgets stay
unchanged. This variant adds coordinator-authored fictional owner clarification
of the parcel population and source scope, available through the same owner and
glossary tools in both arms. It does not add future values or expected outcomes
to the agent's inputs. This is development feasibility, not a held-out benchmark.

Use the current fingerprint-verified native executable and pinned Codex CLI
`0.162.0-alpha.2`, `gpt-6-luna`, medium effort. Two author sessions create their
own setup, each followed by a separate synthetic owner-policy reviewer. Only
if both setups have no unresolved material context and both reviews approve may
two fresh agent sessions produce one current-period report each. Setup and
review work count; no automatic repair/retry or company/period replacement.

Limits: six Codex invocations total, 24 author tool calls, two reviewer tool
calls, twelve report tool calls; author/report time limits 240/180 seconds and
reviewer limit 90 seconds. Live Jev has a shared two-attempt hard cap; failures
count. Before another invocation, stop at 600,000 total input or 100,000 uncached
input tokens, or missing/unknown usage. These token thresholds do not cap one
in-flight turn. The opt-in accounting drain never authorizes extra tool work.

Both arms retain current source tools, glossary, exact owner facts, durable
notes and a bounded arithmetic calculator for reporting. Neither may run
arbitrary scripts; this is not a comparison with an unconstrained Codex agent.
SignalWeave's full native agent/context tool schemas are preserved; monitoring
does not authorize policy edits. Project-installed skill bytes are explicitly
supplied, not autodiscovered. CLI setup is isolated/non-interactive: this does
not establish that the interactive human wizard is seamless.

Keep setup artifacts, owner questions, independent reviews, native packets,
agent reports, source reads and all usage in an exclusive ignored output folder.
Score outcome, recipients, numeric claims and evidence against the existing
private labels only after the report; independently read the human-facing text
for omissions, unsupported causes, useful scope and next steps. A successful
recording or exact outcome alone is not proof of a useful report or business
lift. No schedule or external notification is authorized.

This cohort is now stopped after three invocations: baseline setup and its
synthetic policy review completed; treatment saved a draft and a correct initial
readout but left context unresolved without using the available clarification
tools. No policy review of that draft, recurring report or Jev call followed.
It does not test post-answer completion. Do not restart or silently enlarge it.

Independent review confirmed a separate product gap: the default profile could
not apply a later human answer to the same draft. The new
`revise_insight_card` operation closes that API gap without changing source
anchors or granting approval. Policy revisions are owner-scoped, versioned and
snapshot-checked; they clear prior approval, plan and current review. The skill
also explicitly preserves other authorized context/clarification tools. These
repairs still need a new, budgeted ask → answer → revise → review → report trial;
they do not turn the stopped one-shot attempt into successful onboarding.

### Separate two-turn owner-handoff cohort

Freeze `owner-handoff-v1` before paid execution. Keep the same Pine Courier
development scenario/seed and period index `0`; this is a repair feasibility
check, not a fresh holdout or a new estimate of enterprise accuracy. Keep all
earlier attempts and costs reported separately, with no automatic rerun.

Each arm first inspects sources and saves its working draft/notes, then pauses
with a focused policy question. The scripted owner is unavailable for answers
during this turn, but the common glossary already supplies the population and
source-scope definition in both arms. These definitions are available pre-turn
context, not withheld answers. Materiality, routing and the other declared owner
policies are supplied in a second charged, fresh session; the owner supplies the
same declared policy answers to both arms. Each agent resumes its saved work;
SignalWeave must revise the same card rather than silently create a replacement.
Both keep their source tools and retrievable glossary. The test supplies the
installed skill explicitly and uses non-interactive isolated native setup; it
does not establish automatic discovery or a real person's wizard experience.

After both resumed setups have no material unresolved questions and independent
synthetic reviewers accept their semantics, fresh agents prepare the fixed
period's report. Treatment must evaluate its exact approved card with the fixed
run key. Compare final human-facing claims, recipients, source evidence and
usefulness; a correct API receipt alone is not a successful report. No message
is sent and no schedule is created.

Record actual asked topics separately from answer topics delivered in the
second-turn packet. The legacy scorer's `owner_policy_complete` field measures
asked-topic coverage; it cannot prove policy understanding or replace independent
semantic review. A malformed tool argument may be corrected inside the charged
turn's tool cap. A changed saved-card state, a replacement card, incomplete
resumption or another author invocation is not such an argument correction.

Caps: eight Codex invocations total, 24 tools/240 seconds per author turn, two
tools/90 seconds per reviewer, twelve tools/180 seconds per report, and two live
Jev attempts shared across the cohort. Before another invocation stop at
1,200,000 aggregate input or 180,000 uncached input tokens, unknown usage,
incomplete resumption, failed semantic review, or a changed pinned CLI/native
fingerprint. Token thresholds do not bound an in-flight invocation. Account for
both first turns, answers, review work, failed requests and all reports. Do not
interpret deliberately awaiting-human first turns as product failures or as
completed onboarding. Stop incomplete second turns; do not repair within this
series. The earlier failed series remains in the evidence ledger.

## User outcome

An agent onboarding a second sales investigation should reuse the definitions,
source identities, caveats, and dated findings reviewed during the first one.
It should not rediscover the company's meaning of revenue, mistake a working
hypothesis for a fact, or silently reuse last quarter's ownership instructions.
The same tenant-scoped context must work in local stdio and hosted HTTP MCP.

Cards continue to hold the recurring brief and action policy. Existing approval
and workflow certification remain separate: approving prose does not prove the
workflow works. Frontier agents analyze and communicate; decision providers apply
the card policy. The context layer does not schedule agents or send messages.

## First slice

1. Persist small, free-form context entries, classified only as a definition,
   observation, or hypothesis. Each has a domain, source references, provenance,
   an explicit review date, revision, and authenticated author/reviewer.
2. Every edit or review is a new immutable revision with optimistic concurrency.
   Edits require renewed review. A reviewed hypothesis is still a hypothesis.
3. Retrieve a bounded packet by task words, domain, and exact source anchors.
   Use SQLite's existing local footprint, not a new graph server. Start with
   indexed lexical retrieval; do not claim semantic retrieval or causal inference.
4. Filter tenant/principal visibility before candidate selection. Recheck all
   referenced sources before returning an entry. Do not expose hidden titles,
   links, bodies, counts, or provider errors. Missing/bounded coverage is explicit.
   Editing is owner-only; request-scoped hosted curation/review/sharing requires
   explicit gateway scopes, and visibility changes need separate confirmation.
5. Return freshness and review status with each entry. Pollable review-due
   entries let the caller's agent create a concise reminder. No internal scheduler
   or delivery integration is introduced.
6. Expose the capability as an opt-in MCP extension while testing it. Existing
   cards and the released rc3 binary retain their established behavior. Retrieval
   does not automatically enlarge a card's approved source scope or send all
   context into Jev. Agents must retain evidence provenance and distinguish stale
   or unreviewed context from current facts.

The first slice is a context substrate, not proof of autonomous business value.
Automatic evaluation injection and context-dependent card recertification require
a subsequent, separately tested binding to specific context revisions.

## Preregistered proof gates

Before implementation, reserve these cases for independent review and testing:

| Family | Required behavior |
| --- | --- |
| Cross-dashboard definitions | A reviewed net-sales definition is reusable across two different cards and source anchors |
| Ambiguous names | Gross and net sales, bookings and recognized revenue remain distinct; no guessing an ambiguous definition |
| Time and change | Expired meaning, future-effective notes, and a changed definition are visible as review work, not fresh truth |
| Conflicts and hypotheses | Competing definitions and tentative drivers remain attributed; no confident synthesis by the retriever |
| Missing context | Empty/partial packets remain useful discovery inputs, not invented business rules or blanket analysis refusal |
| Isolation | Same identifiers in different tenants, private notes, revoked sources, and cross-boundary links reveal no hidden content |
| Durability | Restart, history, stale concurrent edit, review-then-edit, and retirement preserve the correct revision |
| Bounds | Large irrelevant catalogs, oversized entries, broad queries, and pagination cannot produce estate-sized model payloads |

Generate deterministic variations outside `src/`; report independent cases and
variation counts separately. Unit tests prove contracts, not frontier-agent lift.
Keep raw traces under ignored artifacts, not in the public docs directory.

## Business-value experiment after the substrate passes

Use held-out recurring sales/operations questions across several synthetic
companies. Compare the same agent with the same source tools, owner knowledge,
model, and budget in three arms: ordinary context documents; SignalWeave context;
and SignalWeave context plus the configured typed decision provider. Baseline
agents may persist/retrieve their own notes; do not manufacture a memory advantage
by deleting their context. Onboarding clarification counts as work in every arm.

Predeclare expected useful final messages, material omissions, false claims,
correct recipients, missed/noisy alerts, source reads, tokens, and total elapsed
time. Do not score only the provider's outcome label. Keep setup examples separate
from later periods and changed definitions. Independent reviewers inspect labels,
traces and messages. Promote only a slice that improves an actual measured outcome
without material correctness or isolation regressions; otherwise report the
negative result and change the design, not the expected answers.

This follows the earlier negative retrieval results: an approved anchor helps,
but ranking cannot invent missing cross-domain relationships. Explicit source
links and bounded context are inputs to investigation, not proof of causation.

## Revision binding implementation

The next slice adds exact shared-context pins, card-owner versioned rebinding,
connector/declared-semantic identity checks, and dependency status on recurring
runs. Notes stay outside provider inputs and receipts. Advisory dependencies warn;
owner-designated prerequisites defer policy while returning approved-anchor
evidence for investigation. Preview, approval, certification and historical
receipt reads must preserve this distinction. Polling remains caller-owned.

Proof must cover source reconfiguration, concurrent card edits, current and
historical ACLs, late context changes during inference, and native/HTTP transport
paths. Passing these contracts is not proof of an improvement in final agent
analysis. The equal-information business-value experiment remains required.

## First live canary: retained negative mechanism result

The first paired support case completed through live `gpt-6-luna` at medium
effort. Both arms had identical searchable full notes and cached source tools;
both produced the expected quiet outcome and read two sources in five calls.
The treatment did **not** call SignalWeave context retrieval. Consequently this
does not measure its usefulness, retrieval correctness, or performance advantage.
The three-case fixture is not three completed paired trials: only one was run.

The treatment's `recipients` field named the requested report audience, whereas
the scorer interpreted it as alert recipients. Protocol 2 separates
`alert_recipients` from `report_audience`; the original result is retained and
not retroactively relabeled. Content review is separate from either label.
The two invocations used 102,767 aggregate input tokens (76,544 cached) and
1,410 output tokens. No further invocation was started after reaching the
predeclared 100,000-input-token stop threshold. No Jev call or delivery occurred.

Before expansion, test the actual guide/skill-driven product path and whether
agents use the new capability. This component canary omitted the full production
guide and did not cover conversational onboarding, cross-session handoff, context
updates or dependency invalidation. Do not attribute its lack of lift to Jev or
declare enterprise value from successful tool execution.

### Next vertical slice before a larger trial

1. Bind a card to exact reviewed context revisions and connector-owned source
   identity. Define what changes require review without treating ordinary data
   movement or unknown metadata as a blanket reason to withhold supported facts.
2. Surface changed/expired dependencies to the agent with the affected cards and
   a concrete review request. Keep curation approval, executable workflow
   certification, and permission to deliver distinct.
3. Run the real guide/skill-driven onboarding path through current native and
   hosted MCP. Test a second agent reusing the same reviewed domain and a later
   owner clarification; do not substitute a precurated-note component harness.
4. Preregister the equal-information business comparison only after that path
   works. Preserve the baseline's source tools and persistent notes, distinguish
   routine report audiences from alert recipients, and score final messages.

The next agent smoke must start with the installed guide, not precurated notes:
an ambiguous sales definition, an owner clarification, two recurring cards that
reuse that clarification, a process/session handoff, and a later definition
change. Record the clarification and all setup effort in both arms. The baseline
retains the same complete documents, source tools, card policy and permission to
save notes or scripts. The treatment uses the actual native MCP and bundled
workflow skill, not a renamed fixture tool. First establish that the mechanism
is used and the final factual report is useful; do not expand a live trial after
a failed smoke. Predeclare a fresh cost cap before any further paid invocation,
and report onboarding plus recurring-run cost separately, including break-even.
No more episodes may be charged to the exhausted original canary budget.

### Onboarding smoke protocol 1

Before expanding to the two-card/reuse/change gates, test one cold-onboarding
pair using the existing holdout retail scenario (seed `20261001`, four assets).
Both arms start from the same business brief with the glossary withheld; source
facts and owner definitions/materiality/routes remain available through the same
tools. Each arm keeps its own notes. The treatment uses the verified native MCP
agent profile and the exact project-installed skill bytes, explicitly supplied
as instructions because the isolated Codex transport disables skill discovery.
This does not test automatic skill discovery or an interactive human wizard.

Use `gpt-6-luna`, medium effort, pinned Codex executable, baseline then treatment.
Allow at most two invocations, 24 tools per invocation and 240 seconds per
episode. Stop before starting another episode at 500,000 aggregate input tokens
or 75,000 uncached input tokens; missing usage also stops expansion. These are
between-episode stop thresholds, not hard in-flight token ceilings. Do not retry
an incomplete arm or reclassify its work as a free setup run. No scheduling or
delivery is authorized. Save unsuccessful traces as well as successes.

Inspect whether the setup preserves the intended definition, comparisons,
policy, destinations and relevant sources; whether the owner questions are
material; and whether the person gets a concise useful readout. Independent
content review is required: successful tool calls and synthetic approval are
not semantic sign-off. The baseline keeps the source tools and note persistence,
but this isolated transport cannot execute arbitrary scripts, so this first
smoke cannot establish superiority over an unconstrained BI agent. Report schema,
prompt and tool-result sizes alongside cached/uncached token usage, without
attributing all input volume to schema overhead. Later cross-session reuse,
definition changes, real Superset agent runs, other connectors and business
benefit remain separate gates even if both onboarding arms succeed.

Protocol 1 stopped after its baseline invocation because the owner-consent tool
required `id="working"` but the notes tools never returned that ID. It is an
invalid harness attempt, not evidence about either product arm. The agent
honestly reported the blocker. Recorded usage: 173,288 input tokens, including
149,504 cached (23,784 uncached), and 2,800 output tokens; 18 tools, 36.80 seconds.
The attempted treatment never ran. The neutral source fixture also lacked
comparison bounds/completeness, so caution about its current readout was correct.
Independent review nevertheless found an arithmetic error in that draft:
web net was $7,000 and shop net $3,000, totaling $10,000, not the reported
$14,000. The unchanged raw-field percentage was correct. Retain this factual
failure too; an invalid consent interface does not make the agent's math correct.

Protocol 2 returns the notes ID and approval target explicitly. Use the existing
connector-profile source fixture with declared analytical comparison bounds and
coverage, mapped to the generic company MCP transport rather than masquerading
as live BI connectors. This is a curated-source development smoke, not an untouched
holdout or proof of automatic semantic onboarding from arbitrary raw data. Retain
the sparse-fixture limitation as a separate coverage case; do not relabel its
unknown periods as complete. Charge protocol 1's known usage to the same
500k-input/75k-uncached between-invocation thresholds via `--prior-trace`.
At most two corrected invocations may follow (three charged invocations total).
Do not score the invalid baseline against the corrected treatment or claim a
speed benefit. Further incomplete arms still stop expansion without a free retry.

Protocol 2 is now terminal: baseline saved a correct factual readout with unresolved
population details; treatment saved useful context/card work but hit its tool
limit before a valid handoff. Treatment token usage is unknown, so expansion
stopped. The results do not establish comparative onboarding quality or cost.
Post-trial changes distinguish pending-owner-context handoffs from approved
automation and remove duplicate-notes requirements for card-backed work. They
must not retroactively convert the recorded attempt into a successful onboarding.

Before another live cohort, make the source glossary accessible and ensure a
domain expert can answer population questions, or deliberately expect an
awaiting-context handoff in **both** arms. Apply the same independent semantic
completion criteria to notes and cards. Source preconditions are explicit test
inputs, not facts inferred from a fixture label. The next outcome gate remains
owner-confirmed, complete onboarding followed by actual recurring Jev evaluation
and an agent's useful message; a pending draft does not satisfy it. Record full
usage or treat costs as unknown. No further invocation belongs to this stopped
budget series.

The current runner is protocol 3 (offline repairs, not live revalidated). It
allows both arms to hand off a useful readout and a focused unresolved question
without claiming automation is ready. Card-backed work need not duplicate its
saved context in the harness's separate notes tool. The existing company metric
glossary, previously withheld from the opening but accidentally unreachable,
is now available through the same on-demand tool in both arms. This makes the
document retrievable; it does not fabricate a population answer or retroactively
change either recorded run. Do not use this stopped series's unknown-usage trace
as permission to start further invocations.

See the [preview evidence](evidence/domain-context-preview-2026-10-14.md) for
observed gates, retained failures and exact native identity. This milestone is
not complete; the feature remains opt-in and the PR remains draft.

The native hosted path now has an inference-free opt-in protocol check:
`tests/test_context_native_http_integration.py`. Distinct signed client subjects
reuse reviewed context through actual HTTP MCP, including after server restart;
scope/tenant boundaries and overdue-draft review polling are exercised against
local Superset metadata authorization. The synthetic issuer and protocol note
do not establish customer SSO or analytical usefulness. This closes a transport
test gap, not the owner-confirmed onboarding/recurring-run business-value gate.

### Approved-card/live-provider integration before another agent cohort

A separately bounded native check exercised scripted fixture-owner approval,
reviewed context binding and three supplied retail periods through live Jev.
Its first attempt stopped on a test-only response-shape error after one request;
one corrected attempt used three more requests and matched the three expected
outcomes. Changed required context then deferred policy without another request.
This four-attempt series is closed, not permission to rerun until it passes more
assertions. The prior stopped Codex onboarding cohort remains stopped too.

Adversarial review found that the initial check did not verify exact routes or
nonempty provenance-bearing deferred evidence. Those are now explicit assertions
with offline mutation coverage; they were not live revalidated in this series.
Future checks retain native result packets as well as provider wire traces and
clean up copied credentials. These are still synthetic exports and scripted
approval, not independent human onboarding or frontier-agent business lift.

The default MCP path also had contradictory onboarding instructions: it told
agents to simulate before approval despite not exposing draft simulation. Its
ready next action is now `confirm_then_approve`; owner authorization still
precedes the first delivery-disabled evaluation. No approval, source, confidence
or certification guard is weakened by this instruction correction.

New research cohorts may opt into the evaluation transport's bounded accounting
drain: no tool work executes after its cap, and capped episodes still fail, but
the process can return final usage before termination. This does not recover
the earlier missing usage or establish a successful onboarding. The old default
hard-stop behavior and original results remain unchanged.
