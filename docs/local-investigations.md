# Repeat an analysis with an agent

The default SignalWeave MCP profile has one narrow job: keep an owner-reviewed
analysis brief with exact source references, then apply its policy to fresh
evidence through Jev on each run. Jev returns a typed outcome and probabilities;
the frontier agent owns deeper discovery, causal investigation, and narrative.

## Set up a card

Ask the agent to understand the recurring question, inspect likely sources, and
draft a card. The agent should ask the owner to resolve material uncertainty
before saving or approving it. Keep the card human-readable and practical:

- what should be watched and why;
- useful questions or conditions;
- exact source resources and any required parameters;
- context the agent should retain when interpreting results.

First use `list_insight_cards` to avoid duplicating an existing brief. It returns
ID-sorted pages (25 cards by default, at most 100) and a `next_offset` when more
remain. The agent profile returns identity/status summaries, not policy or
history; fetch a chosen card with `get_insight_card` before interpreting it.
Use `response_mode="full"` for a full stored-card page when auditing. The
`count` is the authorized, status-filtered total; `returned_count` is this page's
length. Paging bounds the response, not database scan cost; concurrent card
changes can shift offsets.

The agent uses `search_catalog` to recall source candidates and `inspect_resource` to
check them. Search results are not a relevance guarantee. Once exact references
are agreed, `onboard_insight_card` saves a draft. Show the draft and source
scope to the owner, use `review_insight_card` to surface setup issues, then
call `approve_insight_card` only after explicit approval.

The approved card is a reusable source brief, not executable workflow code or
proof that the selected assets are sufficient. If the agent later needs another
asset, explain the reason, update the card with the owner, and review it again.
The default profile never expands the source list during a run.

## Repeat the analysis

On each scheduled or manual run, the caller-owned agent invokes:

```text
evaluate_insight_card(card_id, idempotency_key=...)
```

SignalWeave reads the approved card, fetches only its fixed source references,
and asks Jev to apply the owner's policy. It saves a durable shadow receipt and
returns the typed outcome, probabilities, and evidence bundle. It never sends a
message. The default agent profile uses compact responses. When a result is too
large for the handoff, `evidence_access` explicitly lists the omitted sections.
Read relevant pages using `get_decision_receipt(receipt_id=..., result_path=["evidence"],
offset=0, limit=25)`, following `next_offset`. Nested field paths and list indexes
are supported. These reads use the stored receipt, not new queries or inference.
Omit `result_path` for the full audit. An omitted section is not empty evidence.
The agent then:

1. reads the card decision and evidence together, not as an unexplained alert;
2. uses its own authorized tools to investigate causes or gaps when the outcome
   warrants it;
3. separates observed facts from interpretations and hypotheses and writes the
   explanation for the intended reader; and
4. uses its own scheduler and delivery tools if the owner asked for repetition
   or notification.

A successful fetch does not mean the evidence is complete or comparable. A
partial response is not an all-clear. A contribution or correlation is not
causation. If important evidence is absent or contradictory, state the gap and
ask the owner or update the approved card instead of claiming the analysis is
finished.

Watch/question judgments describe policy interpretation, not which measurements
exist. An `unknown` watch must not erase available counts or values. Read the
source evidence and comparison totals; preserve supported facts from one period
even if the other period or the full comparison is unavailable. This does not
waive coverage, comparability or action requirements. Cite the source for a
measurement and the receipt for a workflow outcome—not interchangeably.

## What is and is not tested

Automated profile tests cover the MCP allowlist, approved-card execution,
idempotent receipts, and delivery-disabled behavior. A test double verifies the
MCP handoff; it is not live Jev evidence. Historical live-Jev and Northstar
replays are summarized in the [decision proof](live-jev-proof-2026-09-27.md).
Separately, the [enterprise onboarding trial](enterprise-onboarding-journeys-2026-10-02.md)
reports a synthetic first-use gap. Do not conflate onboarding failures with
Jev's card decision quality, and do not treat synthetic replays as customer
validation or a universal accuracy guarantee.

## Optional legacy profile

`signalweave serve --profile full` adds metric-query, evaluation,
certification, and webhook tools. It still uses the same core Jev-backed card
decision path, but is not needed for normal onboarding or recurring analysis.
