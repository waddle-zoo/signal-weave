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
| `bind_insight_context` | Pin reviewed shared context to a card; changes the card version and returns it to draft |
| `inspect_insight_context` | Check whether a card's exact dependencies still hold, without running queries |

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

## Bind meaning to a recurring card

Context review, card approval and workflow certification are distinct. After
reviewing a definition, ask the agent to put the relevant business rule into the
card's ordinary guidance and bind that exact context revision to the card. The
binding itself does not rewrite policy, execute linked sources, or send note
bodies into Jev. Your agent still interprets the context and explains the result.

For example:

> Use our reviewed net-sales definition for the weekly sales card. Preserve the
> definition in its guidance. Make that definition a prerequisite for policy
> automation; a campaign hypothesis should only be advisory. Show me the changed
> card before approving it again.

The card owner calls `bind_insight_context` with the expected card version and
the complete desired pin list (at most twelve). This replaces the dependency
set, increments the version, and clears approval and the compiled plan. An empty
list removes the dependencies and still requires renewed approval. Pins contain
only IDs, exact reviewed revisions and digests; the owner's reason is saved on
the card. Because cards are tenant-visible, only tenant-shared context can be
bound. A required pin cannot be a hypothesis.

Binding returns a compact receipt with top-level `card_id`, `version` and
`context_bindings`, not a nested full card. Use that returned `version` for the
next card revision, or call `get_insight_card` to inspect the stored card.
`revise_insight_card`, by contrast, returns its updated card under `card`.
The agent profile omits audit history from that receipt, not active policy or
context pins. Full history remains available through
`get_insight_card(include_history=true, response_mode="full")`.

If an owner also changes the business rule, use `revise_insight_card` to update
the card's ordinary policy fields. That operation preserves its source anchors
and context pins, increments the version and requires renewed review/approval.
A changed note does not automatically rewrite a card, and revising a card does
not refresh its pins; confirm both when meaning changes.

`inspect_insight_context` checks the current revision, review deadline, optional
effective date, linked-source authorization, connector identity and declared
source semantics. Changed definitions, newer drafts, retirement, private context,
revoked sources and changed workspaces require review. It does not silently use
an older reviewed note. Ordinary measurement changes and capture timestamps do
not change the meaning fingerprint. Unknown connector identity cannot be pinned;
company MCP bridges may need an explicit nonsecret context namespace (see the
[bridge guide](mcp-source-bridge.md)). Metadata checks are read-only but may make
requests to connected services; they are not analytical queries.

Advisory changes warn the agent without cancelling a run. If the owner marked
changed context `required_for_action`, evaluation returns a deferred judgment
with **no policy outcome**, while fetching the card's approved anchor evidence
for investigation. There is no model compilation, related-source expansion, or
policy inference in that handoff. It is neither an all-clear nor a prohibition
on reporting supported facts. Preview uses the same boundary. Source failures
remain explicit in the evidence.

Existing receipts remain historical. Evaluation retries and receipt reads attach
current dependency status separately; they never rewrite the archived decision.
A changed required dependency makes the live response non-actionable and removes
its delivery routes. New approval and current certification require current pins;
readiness reports flag changed dependencies rather than treating an old passing
digest as current proof. The extension must remain enabled to validate pins.

Idempotency fingerprints bind caller-supplied context, not newly fetched company
context. A retry recovers its original result without rerunning discovery. Some
older preview receipts used provider-derived context in their fingerprints;
recover those through `get_decision_receipt` rather than reusing the run key under
the new fingerprint scheme. CLI result files and briefs are archived run
artifacts; the live response carries current dependency and action availability.

Visibility revocation hides note text, not the fact that a previously shared
card cited an opaque entry ID and revision. Do not put private text or credentials
in card guidance or binding reasons. The source fingerprint covers **declared**
connector and contract semantics; it cannot detect undocumented changes or prove
that the underlying data is correct. Agents own review reminders and delivery.

## Evidence boundary

Contract tests cover persistence, isolation, review lifecycle and bounded
retrieval. They do not establish better final analysis than an agent with the
same company context in ordinary documents. The preregistered comparison in the
[plan](domain-context-plan.md#business-value-experiment-after-the-substrate-passes)
tests that outcome before making a performance or enterprise-value claim.
