# Reusable domain context

Feature branch: `feat/domain-context-memory`, based on main `e8842ac`.

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

See the [preview evidence](evidence/domain-context-preview-2026-10-14.md) for
observed gates, retained failures and exact native identity. This milestone is
not complete; the feature remains opt-in and the PR remains draft.
