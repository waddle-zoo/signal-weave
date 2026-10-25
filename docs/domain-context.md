# Shared context for analytics agents

Save the meaning your team has established once, then reuse it across different
cards and investigations. Domain context holds short, source-linked definitions,
observations and hypotheses—not raw warehouse data or an automatically generated
company truth graph.

For a delegated analyst's **current output** to feed a later policy decision,
use an explicitly approved [publication source](../examples/analysis_publication/README.md).
Reviewing a memory entry is not a substitute for that source delegation or
verification of its measurements.

For example, a Finance owner can clarify that net sales excludes refunds and
marketplace sales, link the relevant charts and definition document, and choose
when that definition should next be reviewed. A sales-reporting agent and a
campaign-investigation agent can retrieve the same reviewed entry without
repeating that onboarding conversation. They still fetch current measurements.

## Reuse your semantic layer, not a second metric definition

When your company already defines metrics in dbt, Cube, LookML or another
semantic layer, keep that system authoritative. Your agent should discover the
approved metric and query it through the company's tools rather than invent a
formula from similarly named charts.

Save the reusable meaning with its source: canonical metric ID and revision,
owner, population, reporting currency, grain, time basis and material filters.
Keep the source responsible for execution and return those identifiers with
its measurements. A card adds the business question, significance policy and
intended recipients; it does not replace the metric's definition or query engine.

For a recurring card, SignalWeave needs a configured source that can fetch the
agreed result. Existing company tools remain available to your agent, but are
not automatically inherited by the SignalWeave service. Use an existing BI
source or the [normalized MCP bridge](mcp-source-bridge.md); this is not a claim
that native dbt, Cube or LookML adapters ship today.

Two readers should agree when their metric revision, data snapshot, population,
currency and period agree. A request for gross rather than net revenue should
produce a different answer, not silently reuse an unrelated card. Missing or
conflicting meaning calls for a focused clarification. Reviewed notes preserve
agreement; they do not make a source correct or guarantee model determinism.

## Enable the optional tools

After local setup, enable shared context without editing configuration:

```sh
signalweave context enable
signalweave context status
```

Reconnect your agent's MCP process to apply the change. The setting persists in
the private home used by the registered agent. `signalweave status` also reports
context configuration. These are configuration checks, not proof of the state
of an already running process or of analytical quality.

For a deployed service, set `SIGNALWEAVE_KNOWLEDGE_ENABLED=1` in its environment
and restart it. Both paths require the SQLite store and a configured local or
authenticated request-scoped tenant/principal. Clients cannot supply their
identity as a tool argument. Existing card approval and evaluation work
independently. Process environment settings override local configuration; the
context status command makes that override visible.

`signalweave context disable` removes the tools on the next reconnect; it does
not delete stored context, cards or revision history. A card that pins context
can still require those dependencies: disabling the extension is not approval
to ignore them or to act on an old receipt.

The connected guide includes `domain_context` only when the extension is enabled.
This feature ships in the `v0.2.0rc4` native preview; upgrade older binaries
before enabling it. It remains opt-in and under evaluation, not a
hosted-service offer. See the [release reference](local-install-reference.md#release-compatibility).

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

For known references, `retrieve_domain_context(entry_ids=[...])` selects up to
twelve exact context IDs without searching names or loading history. It returns
currently visible revisions, not the old text of a card pin; compare the revision
and freshness with the card before relying on it. The ID set restricts any other
supplied filters. An empty ID list is invalid; omitted IDs retain normal search.
Hidden and unknown entries are both omitted. Count/byte budgets still apply, so
an ID request does not promise a complete packet or bypass source authorization.

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
reviewing an entry, decide whether it is advisory context or a policy dependency.
A reviewed advisory definition can be retrieved for future investigations without
binding it to a card. Bind only when the owner wants a changed or expired meaning
to defer that card's policy action. For a required dependency, put the concise
operational rule in the card's ordinary guidance and bind the exact reviewed,
tenant-shared revision. The pin records revision identity; it does not copy the
note body, rewrite policy, execute linked sources or send note text into Jev. Your
agent still interprets the context and explains the result. Binding increments
the card version, clears its approval, and requires a fresh card review and
approval; avoid binding advisory notes just to make them easier to find.

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

## Reproduce the synthetic native walkthrough

From a development checkout, build the current native executable and run:

```sh
uv sync --extra dev --extra binary
uv run python scripts/build_binary.py
uv run python -m evaluations.public_context_preflight --binary dist/signalweave --output artifacts/my-context-walkthrough
```

This needs no API key, Docker, prior trial files or personal agent configuration.
It starts a test-owned local company-MCP source bridge and an isolated native
home. Two reporting briefs share a reviewed sales definition; changing that
definition to a draft defers both cards' policy decisions while retaining source
evidence. The provider-request budget is zero. Results and synthetic inputs stay
in the exclusive output directory; choose a new directory for another run.

The fictional owner choices and source selection are scripted. Both briefs use
the same metric and source anchors. This demonstrates public API setup and
dependency behavior, not agent-led onboarding, live Jev decisions, independent
investigation discovery or improved reports. The executable must match the
checkout's source/skill fingerprint; this is not a test of an older release.

## Evidence boundary

Contract tests cover persistence, isolation, review lifecycle and bounded
retrieval. They do not establish better final analysis than an agent with the
same company context in ordinary documents. The preregistered comparison in the
[plan](domain-context-plan.md#business-value-experiment-after-the-substrate-passes)
tests that outcome before making a performance or enterprise-value claim.
