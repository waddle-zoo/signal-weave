"""Small, model-free orientation shipped with the MCP, not a workflow engine."""

from __future__ import annotations

from typing import Literal

GuideTask = Literal["start", "query", "report", "monitor"]

EVIDENCE_INTERPRETATION = (
    "Read measurements from observations/evidence and comparison totals when included in analyses. Watch and question results "
    "are policy judgments, not an inventory of available data: unknown does not erase measured values. "
    "Report supported facts even when a comparison is unavailable; preserve missing-value, coverage "
    "and action limits. Cite source references for measurements and receipt IDs for workflow outcomes only."
    " When present, analyses[].comparison retains original totals, segment counts and measurement windows; "
    "source_contracts retains capture dates and declared quality/freshness. Check these before rereading "
    "the same source. Page omitted receipt details instead of requerying to recover already-fetched facts."
)


def provider_label(provider: str) -> str:
    return {"openai-decisions": "OpenAI Decisions",
            "chatgpt-plan-responses": "ChatGPT-plan Responses"}.get(provider, "Jev")


def _with_provider(value, provider: str):
    label = provider_label(provider)
    if label == "Jev":
        return value
    if isinstance(value, str):
        return value.replace("Jev", label).replace("TypeSafe", "OpenAI")
    if isinstance(value, list):
        return [_with_provider(item, provider) for item in value]
    if isinstance(value, dict):
        return {key: _with_provider(item, provider) for key, item in value.items()}
    return value


def agent_getting_started(task: str = "start", *, decision_provider: str = "jev-latest") -> dict:
    """Describe the narrow card-guided Jev decision path for the local agent."""
    if task not in {"start", "monitor"}:
        raise ValueError("The agent profile supports only start or monitor")
    response = {
        "task": task,
        "purpose": "Reuse a human-reviewed card to fetch fresh evidence and get a typed Jev policy decision for your agent.",
        "jev_used": False,
        "inference_performed": False,
        "decision_provider": decision_provider,
        "evidence_interpretation": EVIDENCE_INTERPRETATION,
        "agent_owns": ["source discovery", "deep investigation", "causal analysis", "explanation", "schedule", "delivery"],
        "signalweave_owns": ["card storage", "approved source scope", "authorized retrieval", "Jev policy judgment", "evidence bundle", "durable decision receipt"],
        "steps": [
            {"tool": "list_insight_cards", "purpose": "Reuse an existing approved card when it already covers the recurring question."},
            {"tool": "search_catalog", "purpose": "Recall source candidates; titles and lexical matches are not semantic proof."},
            {"tool": "inspect_resource", "purpose": "Inspect likely sources, report the useful current findings with their periods and source-specific scopes, and clarify material missing context with the owner."},
            {"tool": "onboard_insight_card", "purpose": "Save the owner's intent and exact selected_sources as a draft."},
            {"tool": "revise_insight_card", "purpose": "Apply the owner's answers to the same saved card using its current version. Source anchors stay fixed; review and approval must happen again."},
            {"tool": "review_insight_card", "purpose": "Check the fixed card's declared-source coverage, comparison contracts, and policy blockers even after frontier-owned discovery; fixed review does not Jev-rank those sources."},
            {"tool": "approve_insight_card", "purpose": "Request explicit owner approval after showing the saved card and source scope."},
            {"tool": "evaluate_insight_card", "purpose": "On each recurring run, fetch approved sources and use Jev to apply the card's typed outcome policy; returns evidence and a durable receipt without delivering."},
            {"tool": "get_decision_receipt", "purpose": "Read only needed omitted receipt details with result_path, offset and limit; a deferred handoff's observation_facts is the first view. Paging makes no new queries or inference."},
        ],
        "limits": [
            "No runtime catalog expansion by SignalWeave; add sources with owner review when SignalWeave itself must fetch or judge them. The calling agent keeps its already-authorized company tools for follow-up; not every detail query needs to become a card source.",
            "Jev makes the card-bounded policy judgment; it does not discover the business, infer causality, or replace the frontier agent's deeper investigation.",
            "A returned evidence bundle is not a causal finding. Distinguish facts, hypotheses, and unknowns.",
            "A difference between the last two returned chart buckets is arithmetic, not proof of a like-for-like business decline. Verify period coverage and comparison basis; if unverified, put that caveat beside the headline, not only in setup questions. Never infer a currency from a metric name.",
            "When source contracts lack a comparison basis, leave the gap explicit: do not invent comparison keys or replace prior_calendar_month with last_two_returned without source evidence; prefer an existing declared aggregate, use coverage-only sources only for coverage, and do not page full detail just to recreate that aggregate.",
            "Large compact responses may omit detail. Read included observation_facts first on a deferred handoff, then page only relevant receipt details; omitted evidence is not empty or an all-clear.",
            "For a deferred judgment, read observation_facts first when included; otherwise page its raw observation path. Then page only relevant attributes, definitions, or source contracts. A complete row overview does not establish source coverage or comparability; missing values and dates stay unknown.",
            "SignalWeave does not schedule runs or send messages.",
            "Missing alert criteria can pause recurring automation while the agent still reports supported facts from inspected evidence. Do not withhold a useful current report merely because the notification policy needs owner confirmation.",
            "Before asking for card approval, inspect its exact proposed source parameters with inspect_resource. An unfiltered inspection does not verify a filtered recurring source. Check that the effective data and aggregation support the intended check; preserve the actual analytical SQL and procedure in caller notes when the agent must repeat them. Structural review alone does not demonstrate a working recurring analysis.",
            "Keep owner-only setup questions in the conversation, not the card's recurring questions. Save evidence-answerable business questions for repeated analysis and confirmed definitions in reusable context. Tool-supplied windows or confidence defaults do not establish the owner's business policy.",
            "Source inspection may execute queries; respect user-approved access and cost limits.",
        ],
        "next": "Start with what the person wants to understand, inspect the relevant evidence and give one useful current report. Preserve distinct source scopes and uncertainty. If the person wants recurrence, review the reusable card and ask only for the missing context needed for recurring decisions or delivery.",
    }
    if task == "start":
        response["first_readout"] = (
            "Give the initial source-backed answer before recurring card setup or approval. "
            "When the owner requests recurrence and explicitly approves the reviewed card, show the "
            "proposed human message from its first delivery-disabled evaluation as the recurring "
            "demonstration. Check with the owner "
            "or their designated data expert that it answers the question and fits the intended reader. "
            "Reuse what that reader already knows; explain material scope differences, changed definitions "
            "and real data gaps without copying the whole glossary into every update. Keep business "
            "purpose in why_watch and presentation preferences in caller-owned notes; use reviewed domain context only "
            "when its tools are available. These expectations are not current measurements. "
            "Ask only about consequential uncertainty; an unclear style preference must not suppress a "
            "supported analysis. Feedback is not new approval, scheduling or delivery permission, and a "
            "useful example is not proof of unattended reliability."
        )
    if task == "monitor":
        response.pop("next", None)
        response["steps"] = [
            {"tool": "evaluate_insight_card", "purpose": "Start here with the authorized approved card ID and a new run key for saved BI or configured query sources. For a delegated analyst publication, refresh it through the authorized caller workflow first. Fetch the approved sources, active card guidance and policy decision in one delivery-disabled call; no duplicate card/source fetch is required."},
            {"tool": "get_insight_card", "purpose": "Read the card separately when reviewing or changing its policy, not to duplicate the active guidance already returned by evaluation. Use the default compact view unless an audit needs full history."},
            {"tool": "get_decision_receipt", "purpose": "Read only needed omitted evidence pages or recover a completed run; this does not refetch sources or run inference."},
        ]
        response["evaluation_example"] = {
            "card_id": "<approved-card-id>",
            "idempotency_key": "<card-id>:<run-id>",
            "response_mode": "compact",
        }
        response["repeat"] = (
            "Use the approved policy and current source facts already in the packet; do not "
            "fetch the card, guide, or receipt again when they are already available. Reuse "
            "the approved card and a stable per-run idempotency key. For saved BI or configured "
            "query sources, evaluate before repeating source reads or analysis. For a delegated "
            "analyst publication, first rerun the retained queries/calculations through your "
            "authorized caller workflow and update the configured file. SignalWeave reads the "
            "publication; it does not refresh its underlying analysis. Reuse the actual working "
            "procedure in caller notes rather than making the owner manage files. Republishing "
            "old measurements is not a new business observation. The evidence bundle contains "
            "what the approved sources returned. Use your company tools for deeper investigation "
            "when needed, not to restate the same facts before every evaluation. Jev applies "
            "the card policy; you own investigation, narrative, cadence and delivery."
            " Check source_contracts for this run's coverage/comparability before interpreting "
            "observations; read any omitted contracts using the receipt's paging instructions."
            " If judgment is deferred, start with observation_facts when included (otherwise "
            "use its raw receipt path) and page only relevant "
            "unknown details; a complete row overview is not proof of complete coverage or "
            "comparability. Do not carry a prior typed result forward when current evidence "
            "contradicts it."
            " For a relative recurring window, use this run's measurement dates and cutoff; "
            "onboarding examples are not permanent date restrictions. Do not override an "
            "explicit owner-requested fixed window."
        )
        response["optional_context"] = (
            "Omit context for a normal card run. Supply it only for additional provenance-bearing "
            "external facts, not copied card-source observations. If supplied, provider and version "
            "belong inside the context object alongside facts; they are not top-level evaluation "
            "arguments. Follow the tool schema. Caller-supplied context is unverified and does not "
            "authorize policy changes or delivery."
        )
        response["follow_up_scope"] = (
            "The card bounds SignalWeave's automatic evidence reads and policy inputs, not the "
            "agent's existing company-tool access. Use the returned aggregate to identify a trigger, "
            "then query authorized records for the human handoff when useful. That detail need not "
            "be registered as another card source unless SignalWeave itself must read or judge it. "
            "Keep those agent findings attributed separately; the provider did not verify unread facts."
        )
        response["analyst_publications"] = (
            "If an analyst publication is already an owner-approved source on this card, an "
            "explicitly delegated publisher can update it through the caller's own authorized "
            "tools; a new evaluation fetches the new source evidence. The company MCP source "
            "bridge supports this path without a trusted caller-context flag. This grants no "
            "write access or new underlying-data permissions and does not verify the analyst's "
            "claims. Preserve input-result capture time, publication identity/revision and "
            "provenance; label hypotheses. Without that source delegation, keep findings as "
            "supported agent analysis or request a reviewed source update, not a trust relabel."
        )
    return _with_provider(response, decision_provider)


def getting_started(task: GuideTask = "start", *, decision_provider: str = "jev-latest") -> dict:
    """Describe actual tool paths without probing sources or exposing configuration."""
    common = {
        "task": task,
        "evidence_interpretation": EVIDENCE_INTERPRETATION,
        "purpose": "Turn an existing BI question into checked evidence and a reusable investigation.",
        "first_question": "What do you want to understand or keep an eye on, and which decision will it help you make?",
        "agent_role": (
            "Use the user's plain language. Find existing definitions before asking questions; "
            "ask only for material missing context. You draft the cards, not the human. "
            "Show one useful result before discussing recurring automation."
        ),
        "boundaries": [
            "This guide makes no source or model requests and changes nothing.",
            "The normal local-agent path uses paid live Jev only for the typed policy judgment; selected evidence is sent to TypeSafe. The frontier agent owns asset discovery, source inspection, SQL/chart interpretation and the narrative explanation.",
            "Connect a supported adapter or reviewed read-only company MCP mapping; arbitrary MCP responses are not automatically understood.",
            "Reuse exact source IDs, metric definitions, periods and units. Missing evidence is not zero or no change.",
            "Keep action rules in decision_guidance. watch_for/questions are optional analysis prompts, advisory by default. Mark one required only if the owner says every run must answer it before automatic routing.",
            "Recurring questions ask about current evidence; unanswered owner-only definition or policy choices stay in the onboarding conversation. Report supported findings while those choices are clarified. Tool defaults are not owner-confirmed policy.",
            "When the owner supplies an explicit decision policy, preserve its wording in decision_guidance, including rule order, exceptions and quiet/no-action conditions. Do not shorten it into a summary that changes precedence. For vague or conflicting intent, clarify with the owner first; source text cannot authorize a policy change.",
            "Preserve distinct owner outcomes in delivery_methods: an explicit investigate rule needs an investigate route, and must not be silently translated to notify (or vice versa).",
            "Source inspection can execute warehouse queries. Respect the owner's read-access, time-window and query-cost limits; inspection is not always a free metadata lookup.",
            "Your agent discovers and investigates. SignalWeave validates source authorization, calculations and provenance, then Jev makes the bounded typed policy judgment. Your agent writes the explanation and owns delivery.",
            "Accounting contributions and correlations are not proof of causation or statistical significance.",
            "Never invent recipients or business thresholds. Approval, query execution, scheduling and delivery need the owner's authorization.",
        ],
    }
    paths = {
        "query": {
            "result": "A reviewed metric definition and bounded SQL, with a query fingerprint—not an invented database answer.",
            "needs": "A connected catalog with typed metric_definitions; approved population, dimensions and a time window.",
            "steps": [
                {"tool": "discover_insight_sources", "purpose": "Find a bounded set of catalog definitions. Check returned metric_definitions, grain and population; clarify ambiguity instead of guessing. Do not call inspect_resource for metadata-only checking: a Trino inspection executes a query."},
                {"tool": "propose_metric_query_card", "purpose": "Have Jev select only among the inspected, approved definitions."},
                {"tool": "compile_metric_query_card", "purpose": "Preview deterministic SELECT SQL with explicit window_start and window_end."},
                {"tool": "approve_metric_query_card", "purpose": "Only after explicit owner approval; hand the bounded query to an authorized caller-owned executor."},
            ],
            "stop_if": "No matching catalog definition, unsupported join/dimension, missing partition/time bound, or no authorized executor. Explain the missing contract; do not invent SQL.",
            "human_handoff": "Confirm definition, population, time window and permitted query cost before execution. Compilation is not execution.",
        },
        "report": {
            "result": "A source-backed report with measurements, contributing segments, uncertainty and the next investigation step.",
            "needs": "Connected source evidence; quantitative decomposition additionally needs complete, comparable, reconciled comparison tables.",
            "steps": [
                {"tool": "search_catalog", "purpose": "Use the connector catalog to recall candidate assets; this is lexical recall, not a business decision."},
                {"tool": "inspect_resource", "purpose": "Let the frontier agent inspect definitions, comparisons, chart evidence and source health before choosing exact refs."},
                {"tool": "inspect_resource", "purpose": "Verify definitions, source health, comparison periods, controlling totals and provenance."},
                {"tool": "draft_insight_card", "purpose": "Save a minimal draft bound to inspected sources; no delivery route is needed for a one-off report. Use onboard_insight_card instead when discovery and drafting should be combined."},
                {"tool": "preview_investigation_report", "purpose": "Produce the first delivery-disabled report with live Jev and validated calculations."},
            ],
            "stop_if": "Coverage, definitions or calculations are incomplete. Report the gap and needed evidence, not a fabricated cause or an all-clear.",
            "human_handoff": "Lead with what changed, why it matters under the stated policy, supporting evidence, and what remains unknown. Keep audit detail available without overwhelming the owner.",
        },
        "monitor": {
            "result": "A reviewed investigation your existing agent can repeat, with auditable evidence and outcome-specific routing.",
            "needs": "Start with the report path; then confirm materiality, owner/destinations, cadence, quiet behavior and missing-evidence handling.",
            "steps": [
                {"tool": "list_insight_cards", "purpose": "Look for an existing reviewed investigation before creating another one."},
                {"tool": "onboard_insight_card", "purpose": "Save the free-form policy over the exact selected_sources chosen after frontier-agent inspection; the normal path is fixed/none."},
                {"tool": "preview_investigation_report", "purpose": "Show the actual evidence, numerical checks and proposed routes; do not enable delivery."},
                {"tool": "evaluate_card_workflow", "purpose": "Use owner-labeled historical snapshots for actionable, quiet and missing-evidence acceptance. For a single current check, set capture_current_sources=true in ONE case with an owner-supplied expected_outcome; do not reconstruct snapshots. A current check alone is not full acceptance. If historical cases are unavailable, explicitly record acceptance as unassessed rather than inventing cases or retrying malformed inputs."},
                {"tool": "review_insight_card", "purpose": "Show current policy, source bindings and remaining blockers to the owner."},
                {"tool": "approve_insight_card", "purpose": "Only after explicit owner approval of the saved policy and displayed source scopes. Copy approval_handoff arguments, including its snapshot fingerprint; the agent records the confirmation and source/definition choice in source_selection_reason. The owner need not write API fields. If the policy changes while awaiting confirmation, show it and ask again; do not substitute the latest-review shortcut. Pass workflow_report_id only for a passing full acceptance report. Owner authorization without that report remains unassessed, suitable only for caller-managed shadow evaluation, not proven unattended delivery. Other blockers must be fixed."},
                {"tool": "evaluate_insight_card", "purpose": "Reuse the approved card; one stable idempotency key per scheduled observation, the same key for retries. Pass response_mode=compact for the normal agent handoff; use full only for an exhaustive audit response."},
                {"tool": "get_decision_receipt", "purpose": "Recover the saved report and workflow handoff; suppress quiet outcomes, investigate gaps, and deliver only to approved recipients through the caller's tools."},
            ],
            "stop_if": "Do not enable unattended delivery when acceptance fails or is unassessed, the approved contract changes, required evidence fails, or scheduler/delivery is not configured. Do not claim monitoring is active merely because a card is approved.",
            "human_handoff": "Confirm who will run the schedule and send messages. This binary does neither by itself. Record proposed cadence with the caller's scheduler, not as an unsupported SignalWeave promise.",
        },
    }
    if task == "start":
        return {
            **common,
            "choose": {name: path["result"] for name, path in paths.items()},
            "next": "Call get_signalweave_guide with query, report or monitor. If this is a new investigation, start with report; do not force the user through a JSON form.",
        }
    if task not in paths:
        raise ValueError("Choose start, query, report or monitor")
    result = {**common, **paths[task]}
    if task in {"report", "monitor"}:
        result["preview_review"] = {
            "policy_fidelity": (
                "Compare the saved card with the owner's original rules, not just your summary. "
                "Check precedence, exceptions, threshold boundaries, missing-data handling and "
                "the quiet branch: state what happens when actionable conditions are not met. "
                "Preserve the owner's data-repair instructions as well as the escalation route. Check "
                "exact outcome-to-destination mappings. Copy destination identifiers from the "
                "authorized directory, never retype them from memory. A card-local route key, "
                "human label, and destination URI are different fields; when a caller has a "
                "canonical recipient directory, resolve the recipient by exact URI equality. Explain any proposed "
                "meaning change and obtain owner agreement before testing it."
            ),
            "before_preview": (
                "From inspected evidence and the owner's rules, independently propose the current "
                "outcome, recipients and supporting evidence. Ask the owner to confirm a labeled "
                "example when possible. Do not copy Jev's answer as the expected answer."
            ),
            "compare": (
                "Compare that expectation with the actual preview outcome, routes, required evidence "
                "slots and explanation coverage. A returned preview is execution, not correctness. "
                "Unknown required checks need investigation even if the headline outcome looks right."
            ),
            "source_coverage": (
                "For each requested explanation, preserve the inspected supporting source in the "
                "recurring card or an explicitly approved bounded investigation path. An asset read "
                "during setup is not automatically fetched on future runs. Corroborating context "
                "must not become an unconditional action prerequisite unless the owner requires it. "
                "Compare every saved source, including optional sources, with the snapshots used "
                "in calibration. An omitted optional source can still change a live judgment; "
                "test the complete saved source set in a delivery-disabled current preview."
            ),
            "repair": (
                "Resolve missing definitions or ambiguous checks with the owner. A watch should "
                "state one observable condition, not combine availability, timing and population "
                "into a vague checklist. Preserve the business rule; never lower confidence, "
                "remove a genuine requirement, or relabel the example to make it pass. "
                "A declared comparison window is not a typed analytical comparison. Bind numeric "
                "conditions only to inspected analytical_comparisons keys; otherwise preserve the "
                "English policy over available evidence and state the quantitative validation gap."
            ),
            "retest": (
                "After revision, inspect and preview again using the newly returned card ID. "
                "A passing historical evaluation does not replace the current preview or owner approval. "
                "Keep going through those remaining review steps; do not stop at a passing evaluation. "
                "If a tool lists missing prerequisites, complete just those steps and retry the handoff. "
                "Do not draft another card unless policy or source bindings actually need to change. "
                "Use evaluate_card_workflow with one "
                "capture_current_sources case for an owner-confirmed current expectation. A single "
                "case or an agent-proposed expectation is not independent historical acceptance. "
                "If agreement cannot be established, record the mismatch and keep delivery disabled."
            ),
            "historical_labels": (
                "For historical acceptance, each owner-labeled case needs explicit "
                "expected_delivery_method_keys, expected_delivery_destinations, "
                "required_evidence_source_keys and expected_retrieval_refs. An explicit empty "
                "list or mapping means none expected; omission means unassessed, not none. "
                "For historical snapshots, supply their timezone-aware as_of evaluation time "
                "and retain original capture timestamps. Historical replay uses only supplied "
                "snapshots/context; it does not test fetching new investigation evidence. "
                "Ask for missing labels rather than inventing them from the card or Jev's output. "
                "Include owner-reviewed near-boundary and exception cases when available; "
                "passing a small calibration set does not establish reliability on every later run."
            ),
        }
    result["decision_provider"] = decision_provider
    result["inference_performed"] = False
    return _with_provider(result, decision_provider)
