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
