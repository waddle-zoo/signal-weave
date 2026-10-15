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

See the [preview evidence](evidence/domain-context-preview-2026-10-14.md) for
observed gates, retained failures and exact native identity. This milestone is
not complete; the feature remains opt-in and the PR remains draft.
