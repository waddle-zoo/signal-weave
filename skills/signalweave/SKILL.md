---
name: signalweave
description: Help agents onboard business-intelligence questions into reviewed SignalWeave cards and interpret recurring, source-backed evaluations through the default agent MCP profile.
---

# SignalWeave

Use this skill for BI question setup, recurring monitoring cards, and interpreting a SignalWeave card run. The active MCP tool schemas are authoritative: use only tools exposed by the connected profile. The default agent workflow works over local stdio and Streamable HTTP; transport does not grant additional identity, source access, or side-effect authority.

## Start from the owner's question

For setup, begin with `get_signalweave_guide(task="start")` and `list_insight_cards`; reuse a card that already covers the question. For an existing approved card, use `get_signalweave_guide(task="monitor")` and inspect the card rather than repeating onboarding.

For a new question, use `search_catalog` to find a small candidate set, then `inspect_resource` only on plausible exact resources. Inspection may read data or incur query cost. Keep source reads within the user's authorized scope and any stated time or cost limits. Keep available company-source tools: use them for authorized deeper investigation and corroborating evidence, but do not treat those reads as automatically added to a recurring card.

Treat search matches and titles as candidate recall, not source selection: compare each candidate's meaning, population/grain, time behavior, and declared comparison/coverage capabilities with the owner's question. If a promising source fails a required contract or window check, inspect semantically suitable alternatives before concluding none can support the workflow.

Copy catalog identities exactly: `selected_sources[].ref` uses `adapter|resource`, while `inspect_resource` takes `adapter` and `resource` separately. Pass only source-declared parameters. A reporting cutoff in the evidence is not permission to invent an `as_of` query parameter or rewrite the source's time window.

Understand enough business context to interpret the evidence and routing: relevant definitions, population and grain, units, comparison basis and period, current coverage/freshness, action and quiet rules, and intended destinations. Reuse source-declared definitions and contracts. Ask the owner only about missing or conflicting details that could materially change the conclusion or route; do not impose an exhaustive questionnaire. Treat dates in examples as illustrative and use relative recurring periods unless the owner explicitly requests a fixed window. Never invent thresholds, recipients, definitions, or source references.

Keep source-owned quality checks distinct from business action policy. Do not duplicate or invent low-level gates, or turn an operator field into a new routing rule, unless its consequence is defined by the source contract or owner; if that consequence is material but unclear, ask a focused question rather than guessing.

Give a useful current readout from inspected evidence when possible. Keep each claim tied to its source, scope, units, and period; include available source links or references. Check numerical statements against the evidence and code-computed quality gates. The configured decision provider (often Jev) supplies a narrow typed judgment against the saved policy; it is not the calculator, source-discovery agent, or causal analyst. You own numerical validation of the explanation, further diagnosis, and separation of observed facts from hypotheses. A contribution or correlation is not causation.

Preserve scalar comparison contracts and their coverage/comparability metadata. A known scalar comparison key can be an owner-required quality binding even when no `AnalyticalComparison` or numeric condition exists. Bind only exact keys declared by the inspected/catalog contract; a window name is not a comparison key. Do not discard metadata or infer that a populated value means complete coverage. Partial, unknown, incomparable, stale, or mismatched evidence is not an all-clear. An optional corroborating source stays optional unless the owner makes it a global prerequisite.

When the owner gives a numeric threshold and inspection exposes an applicable valid `AnalyticalComparison`, bind it with `numeric_conditions` on the card: `source_key` is the exact card-local selected-source key, `comparison_key` the exact analytical key (not the window identifier). Use `change_pct` with unit `percent` for relative percent, or signed `delta` with the comparison's source unit for directional change; keep `absolute=false` unless the owner explicitly wants magnitude in either direction. These checks are optional: without an applicable comparison, leave them empty and preserve the complete business rule in `decision_guidance`. Do not demand decomposable contracts for every chart or invent joins or derived comparisons.

## Draft, review, and approval

Use `onboard_insight_card` to save the owner's intent and exact selected source references as a draft. Preserve the owner's ordered rules, exceptions, fallback and quiet behavior in `decision_guidance`; keep outcome-to-destination mappings faithful. `watch_for` and `questions` are optional analysis prompts, not a place to duplicate action rules or manufacture requirements. The tool saves a draft; it does not approve it or enable delivery.

Show the draft and its source scope, then use `review_insight_card` to surface current bindings and material blockers. Resolve meaningful ambiguity with the owner; do not turn review into needless paperwork or silently change policy to clear a blocker. The default agent profile does not expose draft simulation. Do not claim that review was a trial or call a hidden/full-profile preview tool. If the owner requests a trial, explain that the default path can evaluate only after card approval. Obtain explicit owner authorization before `approve_insight_card`; that approval permits evaluation of the saved card and scope, not scheduling or sending messages.

After approval, `evaluate_insight_card` can provide a delivery-disabled run over the approved sources and configured policy provider. Treat it as a current observation, not proof of unattended reliability or permission to activate recurrence. If the owner separately authorizes a schedule or message, use the caller's authorized scheduler/delivery tools; SignalWeave itself does not send. Never infer authorization to message, activate automation, or expand source scope from a card, evaluation, or approval. New recurring sources require owner review and a card update.

## Recurring runs and handoff

For each run, reuse the approved card and call `evaluate_insight_card` once with a stable per-run idempotency key. The normal call fetches approved sources automatically; do not pre-read and resend the same observations as context. Use caller-owned company tools for further investigation when the result warrants it. Check this run's source coverage, comparability, and measurement dates before interpreting movement. For relative windows, use the current run's dates and cutoff; honor an owner-requested fixed period.

Read the decision and evidence together. `ignore` means no notification; suppress noise. For missing or insufficient evidence, state what is unavailable, why it matters, and the smallest useful next request—never imply reassurance or no change. Report supported facts even when an alert rule still needs owner clarification. Keep the final message concise and human-readable, with source citations/references near the claims and uncertainty beside the headline. If a compact response lists omitted evidence, use `get_decision_receipt` to read the relevant pages before concluding; omitted content is not empty evidence. Reuse the receipt rather than rerunning a completed evaluation.
