# Shared context for analytics agents

Save the meaning your team has established once, then reuse it across different
cards and investigations. Domain context holds short, source-linked definitions,
observations and hypotheses—not raw warehouse data or an automatically generated
company truth graph.

For example, a Finance owner can clarify that net sales excludes refunds and
marketplace sales, link the relevant charts and definition document, and choose
when that definition should next be reviewed. A sales-reporting agent and a
campaign-investigation agent can retrieve the same reviewed entry without
repeating that onboarding conversation. They still fetch current measurements.

## Enable the optional tools

Set `SIGNALWEAVE_KNOWLEDGE_ENABLED=1` in the SignalWeave server environment, using
the default SQLite store. Restart the MCP process. A local stdio process and a
hosted HTTP service use the same storage and service contracts. A configured or
authenticated tenant/principal is required; clients cannot supply their identity
as a tool argument. Existing card approval and evaluation work independently.

The connected guide includes `domain_context` only when the extension is enabled.
Older binaries, including the published rc3 preview, do not contain this feature;
use the development checkout for evaluation until a matching native build is
published. This is an opt-in feature under evaluation, not a hosted-service offer.

Ask your agent:

> Remember our agreed definition of net sales, link the sources we inspected,
> and show me the entry and a proposed review date. After I confirm it, make
> it available to our other sales investigations.

| Tool | Purpose |
| --- | --- |
| `save_domain_context` | Save a free-form draft, or revise an entry against its expected revision |
| `review_domain_context` | Record an authorized approval or retirement and its reason |
| `retrieve_domain_context` | Retrieve bounded task/domain/source context, or entries due for review |
| `get_context_history` | Inspect bounded, currently authorized revision history |

The agent fills the structured source references; people provide ordinary
language and clarify business meaning. Every entry needs a domain, text, kind,
source references, provenance, and an explicit review date. Optional reader IDs
restrict visibility within the tenant; otherwise the entry is shared there.
Only the entry's owner can edit it. Visibility changes require explicit
confirmation. With request-scoped hosted identities, saving requires
`knowledge:write`, review requires `knowledge:review`, and publishing beyond the
writer's private audience or changing visibility also requires `knowledge:share`.
The identity gateway must map these trusted
scopes from your organization's roles. A reader cannot edit or publish a private
entry. A static bearer-token deployment is one configured identity, not
multi-user role separation. The host still obtains human confirmation; an
authenticated actor record is not proof of human consent.

## Reuse and keep it current

Retrieval uses indexed lexical matches and exact `adapter|resource` anchors.
It returns whole entries with their revisions, provenance, review status and
freshness. It does not choose the correct definition, reconcile conflicting
claims, infer causation, or grant access to a new source. Search/response budgets
are bounded, and detailed source authorization is checked before returning text.
A rejected source link hides its whole entry rather than leaking the linked text.

Edits and reviews append immutable revisions. Editing a reviewed entry creates
a draft; default retrieval does not silently fall back to its older reviewed
meaning. Reviewed hypotheses stay hypotheses. Expired and future-effective context
is marked explicitly, not treated as evidence about current measurements.

For a review reminder, an authorized agent polls
`retrieve_domain_context(review_due_only=true)`, prepares a short explanation of
what needs confirmation, and uses its caller-owned notification tools. Include
drafts explicitly when reviewing onboarding work. SignalWeave does not run a
scheduler or send notifications itself.

Context review, card approval and workflow certification are distinct. This first
slice does not automatically inject notes into Jev, pin them to a card, or
invalidate card certifications after a note changes. The agent must explicitly
review affected cards. Revision-bound evaluation and automated dependency
invalidation are follow-up proof gates in the [implementation plan](domain-context-plan.md).

## Evidence boundary

Contract tests cover persistence, isolation, review lifecycle and bounded
retrieval. They do not establish better final analysis than an agent with the
same company context in ordinary documents. The preregistered comparison in the
[plan](domain-context-plan.md#business-value-experiment-after-the-substrate-passes)
tests that outcome before making a performance or enterprise-value claim.
