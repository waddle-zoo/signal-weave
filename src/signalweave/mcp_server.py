from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field, StrictBool
from starlette.requests import Request
from starlette.responses import JSONResponse

from .bootstrap import BootstrapManifest, BootstrapService
from .engine import EvaluationPayloadError
from .evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    WorkflowCaseInput,
    card_acceptance_digest,
    has_current_evidence_admission_policy,
)
from .getting_started import GuideTask, agent_getting_started, getting_started, provider_label
from .models import (
    CardDeliveryMethods,
    CertificationRecord,
    ComparisonWindows,
    ContextSnapshot,
    DecisionFeedback,
    DecisionFeedbackKind,
    DecisionReceipt,
    DeliveryMethod,
    EvidenceRequirementKey,
    InsightCard,
    InsightCardStatus,
    InvestigationMode,
    InvestigationQuestions,
    MetricQueryCard,
    OnboardingBlockerCode,
    OnboardingCorrection,
    OnboardingCorrectionKind,
    Outcome,
    PrincipalContext,
    QueryCardStatus,
    ReceiptStatus,
    RetrievalMode,
    SourceRef,
    WatchConditions,
)
from .numeric_conditions import NumericCondition
from .onboarding import (
    InsightAuthoringService,
    SelectedSourceInput,
    bind_numeric_condition_requirements,
    proposal_summary,
    resolve_comparison_windows,
)
from .onboarding import source_scope_confirmations as expected_source_scope_confirmations
from .query_planner import QueryWindow, compile_query, plan_query
from .readiness import deployment_readiness
from .reporting import build_investigation_report, render_investigation_report
from .retrieval_quality import (
    RetrievalQualityCase,
    RetrievalQualityEvaluator,
    RetrievalQualityThresholds,
)
from .runtime import Runtime, build_runtime, load_deployment_secret
from .store import (
    InMemoryCertificationReportStore,
    InMemoryDecisionFeedbackStore,
    InMemoryDecisionReceiptStore,
    JsonMetricQueryCardStore,
)
from .typesafe_adapter import JevPayloadError


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def _evaluation_fingerprint(
    card: InsightCard,
    *,
    actor: str,
    context: ContextSnapshot | None,
    parent_receipt_id: str | None = None,
    workflow_step_key: str | None = None,
) -> str:
    payload = {
        "card_id": card.id,
        "card_version": card.version,
        "actor": actor or "mcp-client",
        "parent_receipt_id": parent_receipt_id,
        "workflow_step_key": workflow_step_key,
        "principal_tenant": card.principal_tenant,
        # Version numbers are useful audit labels but are not an integrity
        # boundary by themselves. Include the executable card contract so a
        # same-version overwrite cannot replay a receipt for different policy.
        "execution_payload": card.execution_payload(),
        "context": (
            context.model_dump(mode="json", exclude={"captured_at"}) if context else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_card(card: InsightCard) -> dict[str, Any]:
    """Keep active policy; authoring history remains available through get_insight_card."""
    return card.model_dump(
        mode="json",
        exclude={"onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"},
    )


ResponseMode = Literal["compact", "full"]
MCPProfile = Literal["agent", "full"]

AGENT_PROFILE_TOOLS = frozenset({
    "get_signalweave_guide",
    "search_catalog",
    "inspect_resource",
    "onboard_insight_card",
    "review_insight_card",
    "approve_insight_card",
    "list_insight_cards",
    "get_insight_card",
    "evaluate_insight_card",
    "get_decision_receipt",
})


def _compact_text(value: Any, limit: int = 420) -> Any:
    """Bound free-form connector text in the normal agent response path."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _compact_contract(contract: Any) -> dict[str, Any]:
    """Keep typed source-selection facts while dropping connector duplication."""
    if not isinstance(contract, dict):
        return {}
    keep = {
        "tenant_id",
        "domain",
        "scope",
        "metric_names",
        "metric_definitions",
        "comparison_contracts",
        "available_comparison_windows",
        "required_comparison_keys",
        "population",
        "grain",
        "freshness_sla_hours",
        "lineage",
        "roles",
        "source_status",
        "authorized",
    }
    compact: dict[str, Any] = {}
    for key in keep:
        if key not in contract:
            continue
        value = contract[key]
        if key == "metric_definitions" and isinstance(value, list):
            compact[key] = [
                {
                    field: _compact_text(item[field], 700)
                    if field in {"description", "population", "grain"}
                    else item[field]
                    for field in (
                        "key",
                        "label",
                        "description",
                        "relation",
                        "dialect",
                        "aggregation",
                        "measure_column",
                        "time_column",
                        "supported_grains",
                        "dimensions",
                        "partition_column",
                        "aliases",
                        "population",
                        "grain",
                        "lineage",
                    )
                    if field in item
                }
                for item in value
                if isinstance(item, dict)
            ]
        elif key == "comparison_contracts" and isinstance(value, list):
            compact[key] = [
                {
                    field: _compact_text(item[field], 700)
                    if field in {"definition", "population", "detail"}
                    else item[field]
                    for field in (
                        "key",
                        "metric",
                        "definition",
                        "population",
                        "unit",
                        "comparison_window",
                        "coverage",
                        "comparable",
                        "detail",
                        "query_refs",
                    )
                    if field in item
                }
                for item in value
                if isinstance(item, dict)
            ]
        elif key in {"scope", "population", "grain"}:
            compact[key] = _compact_text(value, 900)
        else:
            compact[key] = value
    return compact


def _compact_metadata(metadata: Any) -> dict[str, Any]:
    """Retain common adapter identity and ownership fields, not arbitrary blobs."""
    if not isinstance(metadata, dict):
        return {}
    allowed = {
        "owner",
        "scope",
        "tenant",
        "read_only",
        "related_refs",
        "chart_id",
        "dashboard_id",
        "query_id",
        "dataset",
        "metric",
        "tags",
        "inspection",
        "source_status",
    }
    return {
        key: _compact_text(value, 600)
        if key in {"owner", "scope", "tenant", "dataset", "metric", "inspection"}
        else value
        for key, value in metadata.items()
        if key in allowed
    }


def _compact_match(match: Any, *, include_description: bool = True) -> dict[str, Any]:
    """Compact a discovery candidate without changing its identity or ranking."""
    if not isinstance(match, dict):
        return {}
    result = {
        key: match[key]
        for key in (
            "ref",
            "adapter",
            "resource",
            "kind",
            "title",
            "source_url",
            "relevance",
            "recommended",
            "suggested_role",
            "role_probability",
            "retrieval_signals",
        )
        if key in match
    }
    if include_description and "description" in match:
        result["description"] = _compact_text(match["description"], 700)
    if "contract" in match:
        result["contract"] = _compact_contract(match["contract"])
    if "metadata" in match:
        result["metadata"] = _compact_metadata(match["metadata"])
    return result


def _compact_discovery(discovery: Any) -> dict[str, Any]:
    """Make the discovery packet useful to an agent without repeating raw catalog data."""
    if not isinstance(discovery, dict):
        return {}
    result = {
        key: discovery[key]
        for key in (
            "catalog_fingerprint",
            "goal",
            "candidate_refs",
            "candidate_count",
            "candidate_limit",
            "truncated",
            "no_match",
            "candidate_strategy",
            "evaluator",
            "authorized_tenant",
            "catalog_provider",
            "catalog_strategy",
            "catalog_cursor",
            "warnings",
        )
        if key in discovery
    }
    result["matches"] = [
        _compact_match(match, include_description=False)
        for match in discovery.get("matches", [])
        if isinstance(match, dict)
    ]
    return result


def _compact_review_candidate(candidate: Any) -> dict[str, Any]:
    """Compact the human review row while preserving every approval-relevant field."""
    if not isinstance(candidate, dict):
        return {}
    result = {
        key: candidate[key]
        for key in (
            "ref",
            "adapter",
            "resource",
            "kind",
            "title",
            "source_url",
            "domain",
            "tenant_id",
            "source_status",
            "available_comparison_windows",
            "selected",
            "recommended",
            "relevance",
            "suggested_role",
            "role_probability",
            "reason",
            "retrieval_signals",
        )
        if key in candidate
    }
    metadata = candidate.get("metadata", {})
    if isinstance(metadata, dict):
        contract_fields = {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "tenant_id",
                "domain",
                "scope",
                "metric_names",
                "metric_definitions",
                "comparison_contracts",
                "available_comparison_windows",
                "required_comparison_keys",
                "population",
                "grain",
                "freshness_sla_hours",
                "lineage",
                "roles",
                "source_status",
                "authorized",
            }
        }
        adapter_metadata = metadata.get("adapter_metadata")
        result["metadata"] = _compact_contract(contract_fields)
        if adapter_metadata:
            result["metadata"]["adapter_metadata"] = _compact_metadata(adapter_metadata)
    if "description" in candidate:
        result["description"] = _compact_text(candidate["description"], 700)
    return result


def _compact_review(review: Any) -> dict[str, Any]:
    """Keep the review decision boundary, replacing repeated source payloads."""
    if not isinstance(review, dict):
        return {}
    result = {
        key: review[key]
        for key in (
            "card_id",
            "status",
            "readiness_status",
            "blockers",
            "source_selection_fingerprint",
            "source_selection_confirmation",
            "source_scope_confirmations",
            "confirmed_blocker_codes",
            "principal_id",
            "principal_tenant",
            "authorization_evidence",
            "discovery_receipt",
            "selected_source_refs",
            "recommended_source_refs",
            "missing_recommended_refs",
            "selected_outside_bounded_candidates",
            "ambiguous_candidate_groups",
            "questions",
            "warnings",
            "evidence_requirements",
        )
        if key in review
    }
    result["source_candidates"] = [
        _compact_review_candidate(candidate)
        for candidate in review.get("source_candidates", [])
        if isinstance(candidate, dict)
    ]
    return result


def _compact_plan(plan: Any) -> Any:
    """Plans are already typed; only bound free-form query text when present."""
    if not isinstance(plan, dict):
        return plan
    result = dict(plan)
    result["metric_query_plans"] = [
        {
            key: value
            for key, value in item.items()
            if key not in {"sql", "query", "description"}
        }
        for item in plan.get("metric_query_plans", [])
        if isinstance(item, dict)
    ]
    return result


def _compact_card(card: Any) -> dict[str, Any]:
    """Return active card fields; keep review packets only while a card is a draft."""
    if not isinstance(card, dict):
        return {}
    result = dict(card)
    result.pop("onboarding_review_history", None)
    result.pop("onboarding_corrections", None)
    if result.get("status") == InsightCardStatus.APPROVED.value:
        # The approval review can contain the full discovery candidate catalog.
        # It remains in storage and is available through response_mode="full".
        result.pop("onboarding_review", None)
    elif result.get("onboarding_review"):
        result["onboarding_review"] = _compact_review(result["onboarding_review"])
    if result.get("compiled_plan"):
        result["compiled_plan"] = _compact_plan(result["compiled_plan"])
    return result


def _compact_summary(summary: Any) -> dict[str, Any]:
    """Remove discovery/review duplicates from the high-level proposal summary."""
    if not isinstance(summary, dict):
        return {}
    result = dict(summary)
    result.pop("discovery", None)
    result.pop("onboarding_review", None)
    result["details_available"] = True
    return result


def _compact_bundle(bundle: Any) -> dict[str, Any]:
    """Compact a resolved evidence bundle while keeping candidate identity."""
    if not isinstance(bundle, dict):
        return {}
    result = dict(bundle)
    result["related_matches"] = [
        _compact_match(match)
        for match in bundle.get("related_matches", [])
        if isinstance(match, dict)
    ]
    # Omitted candidates are useful for an audit trail, but their repeated
    # contracts and descriptions can dominate the next model context in a
    # noisy enterprise catalog. Keep stable identity and ranking signals;
    # selected/related sources retain the typed contract and evidence needed
    # for the decision.
    result["omitted_matches"] = [
        {
            key: match[key]
            for key in (
                "ref",
                "adapter",
                "resource",
                "kind",
                "title",
                "relevance",
                "recommended",
                "suggested_role",
                "role_probability",
                "retrieval_signals",
            )
            if key in match
        }
        for match in bundle.get("omitted_matches", [])
        if isinstance(match, dict)
    ]
    return result


def _compact_simulation_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep structured evidence and omit only the rendered markdown duplicate."""
    result = dict(response)
    result.pop("report_markdown", None)
    result["report_markdown_available"] = True
    result["card"] = _compact_card(result.get("card"))
    result["plan"] = _compact_plan(result.get("plan"))
    retrieval = result.get("retrieval")
    if isinstance(retrieval, dict):
        result["retrieval"] = _compact_bundle(retrieval)
    resources = result.get("resources")
    if isinstance(resources, list):
        result["resources"] = [
            {
                key: resource[key]
                for key in (
                    "source_key",
                    "adapter",
                    "resource",
                    "title",
                    "description",
                    "source_url",
                    "error",
                    "captured_at",
                    "source_captured_at",
                )
                if key in resource
            }
            | ({"metadata": _compact_metadata(resource.get("metadata"))}
               if resource.get("metadata") else {})
            | ({"contract": _compact_contract(resource.get("contract"))}
               if resource.get("contract") else {})
            for resource in resources
            if isinstance(resource, dict)
        ]
    if isinstance(result.get("result"), dict):
        result["result"] = dict(result["result"])
        if isinstance(result["result"].get("retrieval"), dict):
            result["result"]["retrieval"] = result["retrieval"]
    return result


AGENT_HANDOFF_BYTES = 64 * 1024
RECEIPT_PAGE_BYTES = 32 * 1024
_COMPACT_OBSERVATION_ATTRIBUTE_BYTES = 2 * 1024
_COMPACT_OBSERVATION_ATTRIBUTE_VALUE_BYTES = 1024
_COMPACT_OBSERVATION_OMITTED_KEYS = 24
_COMPACT_OBSERVATION_KEY_CHARS = 160
_COMPACT_OBSERVATION_PREFIX_ITEMS = 100


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _compact_observation(observation: Any, index: int) -> Any:
    """Keep normalized facts and compact attributes; point omitted detail to its receipt."""
    if not isinstance(observation, dict):
        return observation
    compact = dict(observation)
    attributes = compact.get("attributes")
    if not isinstance(attributes, dict) or not attributes:
        return compact

    kept: dict[str, Any] = {}
    omitted: list[str] = []
    kept_bytes = 0
    for key, value in attributes.items():
        name = str(key)
        normalized_name = name.casefold().replace("-", "_")
        raw_provenance = (
            "provenance" in normalized_name
            or normalized_name in {
                "raw", "raw_data", "raw_payload", "connector_payload", "source_payload",
            }
        )
        item_bytes = _json_bytes({name: value})
        if (
            raw_provenance
            or item_bytes > _COMPACT_OBSERVATION_ATTRIBUTE_VALUE_BYTES
            or kept_bytes + item_bytes > _COMPACT_OBSERVATION_ATTRIBUTE_BYTES
        ):
            omitted.append(name)
            continue
        kept[name] = value
        kept_bytes += item_bytes

    if not omitted:
        return compact
    compact["attributes"] = kept
    shown_keys = [key[:_COMPACT_OBSERVATION_KEY_CHARS] for key in omitted[:_COMPACT_OBSERVATION_OMITTED_KEYS]]
    compact["attributes_omitted"] = {
        "count": len(omitted),
        "keys": shown_keys,
        "keys_complete": (
            len(omitted) <= _COMPACT_OBSERVATION_OMITTED_KEYS
            and all(len(key) <= _COMPACT_OBSERVATION_KEY_CHARS for key in omitted)
        ),
        "receipt_path": ["observations", str(index), "attributes"],
    }
    return compact


def _deferred_observation_facts(observations: list[Any]) -> dict[str, Any]:
    """Index every normalized field without duplicating bulky raw attributes."""
    fields = sorted({
        key
        for observation in observations
        if isinstance(observation, dict)
        for key in observation
        if key != "attributes"
    })
    rows = []
    attributes_present_indices = []
    for index, observation in enumerate(observations):
        full_ref = ["judgment_state", "observations", str(index)]
        if not isinstance(observation, dict):
            rows.append({"index": index, "full_ref": full_ref, "value": observation})
            continue
        row = {
            "index": index,
            "full_ref": full_ref,
            "values": [observation[field] if field in observation else None for field in fields],
        }
        missing_fields = [field for field in fields if field not in observation]
        if missing_fields:
            row["missing_fields"] = missing_fields
        if "attributes" in observation:
            attributes_present_indices.append(index)
        rows.append(row)
    return {
        "record_count": len(observations),
        "fields": fields,
        "rows": rows,
        "rows_complete": True,
        "attributes_path_suffix": ["attributes"],
        "attributes_present_indices": attributes_present_indices,
        "value_encoding": (
            "Each row's values align by position with fields. Null and absent values are unknown; "
            "missing_fields distinguishes an absent key from explicit null. For indices in "
            "attributes_present_indices, append attributes_path_suffix to full_ref to read untouched attributes."
        ),
    }


def _deferred_source_access(source_by_key: dict[str, Any]) -> list[dict[str, Any]]:
    """Give exact receipt paths for source detail without inlining snapshots."""
    path_fields = {
        "snapshot_path": None,
        "metadata_path": "metadata",
        "contract_path": "contract",
        "analytical_comparisons_path": "analytical_comparisons",
        "observations_path": "observations",
        "evidence_path": "evidence",
    }
    sources = []
    for source_key, snapshot in source_by_key.items():
        if not isinstance(source_key, str) or not isinstance(snapshot, dict):
            continue
        base = ["source_by_key", source_key]
        entry: dict[str, Any] = {"source_key": source_key, "snapshot_path": base}
        adapter = snapshot.get("adapter")
        resource = snapshot.get("resource")
        if isinstance(adapter, str) and isinstance(resource, str):
            entry["source_id"] = f"{adapter}|{resource}"
        for path_name, field in path_fields.items():
            if field is not None and field in snapshot:
                entry[path_name] = [*base, field]
        sources.append(entry)
    return sources


def _receipt_result_page(result: dict[str, Any], path: list[str], offset: int, limit: int) -> dict:
    """Read a lossless, byte-bounded slice without refetching data or inference."""
    if not path or len(path) > 8 or not all(isinstance(key, str) and len(key) <= 256 for key in path):
        raise ValueError("result_path must contain one to eight field names or list indexes")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    value: Any = result
    for key in path:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isascii() and key.isdecimal() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ValueError("result_path does not exist in this receipt")
    kind = "list" if isinstance(value, list) else "object" if isinstance(value, dict) else "scalar"
    entries = list(value.items()) if kind == "object" else value if kind == "list" else [value]
    page: dict[str, Any] = {
        "path": path, "kind": kind, "offset": offset, "total": len(entries),
        "items": [], "has_more": False, "next_offset": None, "oversized_item": None,
        "byte_budget": RECEIPT_PAGE_BYTES,
    }
    for index in range(offset, min(len(entries), offset + limit)):
        entry = {"key": entries[index][0], "value": entries[index][1]} if kind == "object" else entries[index]
        if _json_bytes({**page, "items": [*page["items"], entry]}) > RECEIPT_PAGE_BYTES - 1024:
            if not page["items"]:
                page["oversized_item"] = {
                    "index": index,
                    "path": [*path, entries[index][0] if kind == "object" else str(index)] if kind != "scalar" else path,
                    "instruction": "Read this nested path, or explicitly request the full receipt for an oversized scalar. No value was truncated.",
                }
            break
        page["items"].append(entry)
    next_offset = offset + len(page["items"])
    page["has_more"] = next_offset < len(entries)
    page["next_offset"] = next_offset if page["has_more"] else None
    page["section_complete"] = offset == 0 and next_offset == len(entries) and page["oversized_item"] is None
    page["coverage"] = "complete_section" if page["section_complete"] else "partial_section"
    return page


def _compact_evaluation_response(response: dict[str, Any]) -> dict[str, Any]:
    """Return one evidence bundle without repeating the same payload three times.

    ``evaluate_insight_card`` persists the complete result in the decision
    receipt.  The normal agent handoff only needs the active card, receipt
    metadata, and the structured result; returning the top-level resources,
    plan, retrieval bundle, and rendered markdown again needlessly expands the
    next model context. Large results use explicit receipt-backed paging,
    never silent evidence truncation. This does not alter the saved judgment.
    """
    result = dict(response.get("result") or {})
    had_markdown = isinstance(result.pop("report_markdown", None), str)
    observations = result.get("observations")
    if isinstance(observations, list):
        result["observations"] = [
            _compact_observation(item, index)
            for index, item in enumerate(observations)
        ]
    if isinstance(result.get("retrieval"), dict):
        result["retrieval"] = _compact_bundle(result["retrieval"])
    compact: dict[str, Any] = {
        "receipt": response.get("receipt"),
        "replayed": bool(response.get("replayed", False)),
        "result": result,
        "response_mode": "compact",
        "details_available": True,
    }
    if "card" in response:
        compact["card"] = _compact_card(response.get("card"))
    compact["report_markdown_available"] = had_markdown
    if _json_bytes(compact) > AGENT_HANDOFF_BYTES:
        receipt_id = (response.get("receipt") or {}).get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("A large compact handoff requires a durable receipt for evidence reads")
        summary_fields = (
            "card_id", "outcome", "judgment", "summary", "rationale", "confidence", "probabilities",
            "warnings", "retrieval", "evidence_plan", "delivery_methods", "source_keys",
            "evaluator", "evaluated_at",
        )
        compact["result"] = {}
        for key in summary_fields:
            if key in result and _json_bytes(result[key]) <= 4096:
                candidate = {**compact["result"], key: result[key]}
                if _json_bytes(candidate) <= 24 * 1024:
                    compact["result"] = candidate
        sections = []
        for key, value in result.items():
            entry = {"path": [key], "count": len(value) if isinstance(value, (list, dict)) else 1}
            if len(key) > 256 or len(sections) >= 50 or _json_bytes([*sections, entry]) > 12 * 1024:
                break
            sections.append(entry)
        evidence_access = {
            "coverage": "not_included_in_handoff", "complete": False,
            "tool": "get_decision_receipt",
            "receipt_id": receipt_id,
            "available_sections": sections,
            "section_directory_total": len(result),
            "section_directory_complete": len(sections) == len(result),
            "instruction": "Read relevant receipt sections with result_path, offset and limit before explaining or delivering an action. An omitted section is not empty or an all-clear. The full result remains stored; pages perform no new source or model calls.",
        }
        judgment = result.get("judgment")
        if isinstance(judgment, dict) and judgment.get("status") == "deferred":
            judgment_state = result.get("judgment_state")
            if isinstance(judgment_state, dict):
                for field, access_key in (
                    ("observations", "observation_coverage"),
                    ("evidence", "evidence_coverage"),
                ):
                    values = judgment_state.get(field)
                    if isinstance(values, (list, dict)):
                        evidence_access[access_key] = {
                            "result_path": ["judgment_state", field],
                            "total": len(values),
                            "included": 0,
                            "coverage": "partial_section",
                            "next_offset": 0,
                        }
            source_by_key = result.get("source_by_key")
            if isinstance(source_by_key, dict):
                evidence_access["source_snapshot_coverage"] = {
                    "result_path": ["source_by_key"],
                    "total": len(source_by_key),
                    "included": 0,
                    "coverage": "partial_section",
                    "next_offset": 0,
                }
        source_contracts = result.get("source_contracts")
        if isinstance(source_contracts, list):
            prefix = []
            for source_contract in source_contracts:
                candidate_prefix = [*prefix, source_contract]
                candidate = {
                    **compact,
                    "result": {**compact["result"], "source_contracts": candidate_prefix},
                    "evidence_access": evidence_access,
                }
                # Keep room for facts and explicit coverage. Quality precedes
                # optional report details; never substitute catalog assertions.
                if _json_bytes(candidate) > AGENT_HANDOFF_BYTES - 8 * 1024:
                    break
                prefix = candidate_prefix
            compact["result"]["source_contracts"] = prefix
            evidence_access["source_contract_coverage"] = {
                "result_path": ["source_contracts"],
                "total": len(source_contracts),
                "included": len(prefix),
                "coverage": "complete_section" if len(prefix) == len(source_contracts) else "partial_section",
                "next_offset": None if len(prefix) == len(source_contracts) else len(prefix),
            }
            evidence_access["instruction"] += (
                " Read omitted source_contracts before interpreting comparability or coverage; "
                "a populated observation is not a complete comparison."
            )
        if isinstance(judgment, dict) and judgment.get("status") == "deferred":
            judgment_state = result.get("judgment_state")
            raw_observations = (
                judgment_state.get("observations")
                if isinstance(judgment_state, dict) else None
            )
            source_by_key = result.get("source_by_key")
            if isinstance(source_by_key, dict):
                evidence_access["source_directory"] = _deferred_source_access(source_by_key)
            if isinstance(raw_observations, list):
                facts = _deferred_observation_facts(raw_observations)
                evidence_access["instruction"] = (
                    "This judgment is deferred and has no policy outcome. Read result.observation_facts "
                    "first for every normalized observation; this is an inline projection, not a stored receipt section. "
                    "Use the advertised result_path or row full_ref for receipt reads, and source_directory paths for source-specific "
                    "metadata, definitions, and contracts only when needed. Page raw attributes or duplicate "
                    "evidence only when they add needed provenance. A complete fact overview does not assert "
                    "complete source coverage or a comparable period. Missing/null values and unsupported "
                    "measurement bounds remain unknown; do not infer date boundaries from run timestamps or row order. "
                    "Receipt pages perform no source or model calls."
                )
                facts_access = {
                    "location": "inline_projection",
                    "inline_result_path": ["observation_facts"],
                    "result_path": ["judgment_state", "observations"],
                    "total": len(raw_observations),
                    "included": len(raw_observations),
                    "coverage": "complete_normalized_observation_rows",
                    "attributes_included": False,
                    "attributes_path_suffix": ["attributes"],
                    "source_coverage_asserted": False,
                }
                candidate_result = {**compact["result"], "observation_facts": facts}
                candidate_access = {**evidence_access, "observation_facts": facts_access}
                candidate = {
                    **compact,
                    "result": candidate_result,
                    "evidence_access": candidate_access,
                }
                if _json_bytes(candidate) > AGENT_HANDOFF_BYTES:
                    candidate_access = dict(candidate_access)
                    candidate_access.pop("source_directory", None)
                    candidate = {
                        **compact,
                        "result": candidate_result,
                        "evidence_access": candidate_access,
                    }
                if _json_bytes(candidate) <= AGENT_HANDOFF_BYTES:
                    compact["result"] = candidate_result
                    evidence_access.clear()
                    evidence_access.update(candidate_access)
                    if "source_directory" not in evidence_access:
                        evidence_access["instruction"] = (
                            "This judgment is deferred and has no policy outcome. Read result.observation_facts "
                            "first, then use source_snapshot_coverage.result_path to page source_by_key. Each "
                            "snapshot preserves its adapter/resource identity and nested metadata, definitions, "
                            "and contracts. Page raw attributes or duplicate evidence only when they add needed "
                            "provenance. A complete fact overview does not assert source coverage or comparability; "
                            "missing values and measurement bounds remain unknown."
                        )
                else:
                    fallback_access = {
                        **evidence_access,
                        "observation_facts": {
                            "location": "receipt_only",
                            "result_path": ["judgment_state", "observations"],
                            "total": len(raw_observations),
                            "included": 0,
                            "coverage": "not_included_within_handoff_byte_bound",
                            "next_offset": 0,
                        },
                    }
                    fallback_access["instruction"] = (
                        "This judgment is deferred and has no policy outcome. The complete normalized "
                        "observation_facts overview exceeds this handoff's byte bound and was not included. "
                        "Use get_decision_receipt to page judgment_state.observations and source_by_key only "
                        "as needed; no rows were sampled or truncated in storage. Read source contracts "
                        "separately for coverage and comparability. Missing values and measurement bounds "
                        "remain unknown; pages make no new source or model calls."
                    )
                    if _json_bytes({**compact, "evidence_access": fallback_access}) > AGENT_HANDOFF_BYTES:
                        fallback_access.pop("source_directory", None)
                    evidence_access.clear()
                    evidence_access.update(fallback_access)
        observations = result.get("observations")
        if isinstance(observations, list):
            def observation_coverage(included: int) -> dict[str, Any]:
                complete = included == len(observations)
                return {
                    "result_path": ["observations"],
                    "total": len(observations),
                    "included": included,
                    "coverage": "complete_section" if complete else "partial_section",
                    "next_offset": None if complete else included,
                }

            compact["result"]["observations"] = []
            evidence_access["observation_coverage"] = observation_coverage(0)
            compact["evidence_access"] = evidence_access
            if _json_bytes(compact) > AGENT_HANDOFF_BYTES and "card" in compact:
                compact.pop("card")
                compact["card_details_available"] = True
            prefix: list[Any] = []
            for item in observations[:_COMPACT_OBSERVATION_PREFIX_ITEMS]:
                candidate_prefix = [*prefix, item]
                candidate_access = {
                    **evidence_access,
                    "observation_coverage": observation_coverage(len(candidate_prefix)),
                }
                candidate = {
                    **compact,
                    "result": {**compact["result"], "observations": candidate_prefix},
                    "evidence_access": candidate_access,
                }
                if _json_bytes(candidate) > AGENT_HANDOFF_BYTES and "card" in compact:
                    compact.pop("card")
                    compact["card_details_available"] = True
                    candidate = {
                        **compact,
                        "result": {**compact["result"], "observations": candidate_prefix},
                        "evidence_access": candidate_access,
                    }
                if _json_bytes(candidate) > AGENT_HANDOFF_BYTES:
                    break
                prefix = candidate_prefix
            compact["result"]["observations"] = prefix
            evidence_access["observation_coverage"] = observation_coverage(len(prefix))
        compact["evidence_access"] = evidence_access
        if _json_bytes(compact) > AGENT_HANDOFF_BYTES:
            compact.pop("card", None)
            compact["card_details_available"] = True
        if _json_bytes(compact) > AGENT_HANDOFF_BYTES:
            raise ValueError("Compact receipt metadata exceeds the handoff bound; explicitly request the full audit")
    return compact


CARD_AUTHORING_GUIDANCE = (
    "\n\nAuthoring guidance: use the minimal business fields accepted by draft_insight_card, "
    "propose_insight_card, or onboard_insight_card; do not copy a stored InsightCard, "
    "plan, review, or history object back as authoring input. Preserve the normal technical "
    "defaults unless an operator explicitly changes them: the default action confidence "
    "threshold is 0.70, a model-support floor rather than an accuracy guarantee, and a "
    "threshold of 1.0 may prevent automation. Keep fixed source references and operator "
    "profiles as provided; do not invent bounded expansion or investigation. Treat each "
    "SourceRef and its parameters as authoritative: reuse exact approved declarations and "
    "returned evidence; never reconstruct, rename, or invent keys or parameters. Keep the owner's intent "
    "free-form. Map every owner-requested delivery rule to its outcome and exact destination, "
    "not only the setup examples; outcomes meant to stay silent need no delivery entry. "
    "Keep delivery_methods.key as the stable caller-owned route identifier and copy the exact "
    "caller-owned destination endpoint. If the calling agent has a separate recipient directory, "
    "resolve the canonical recipient by exact endpoint equality; never use a human label or a "
    "card-local alias as a substitute. Never invent a recipient; ask for missing expected cases when an intended route is not covered. "
    "Passing partial examples is not proof of the whole policy. "
    "The frontier agent owns catalog search, source inspection, SQL/chart interpretation and the narrative investigation. "
    "Use list_resources/search_catalog and inspect_resource before passing exact selected_sources; "
    "the normal selected-source path is fixed/none and does not ask Jev to discover or rank assets. "
    "For recurring analytical reports, inspect existing source definitions and comparisons first; "
    "draft the smallest investigation preserving the business intent, then use "
    "preview_investigation_report to show the first actual report. "
    "Before seeing the preview, independently derive the current expected outcome and routes "
    "from inspected evidence and owner policy; ask the owner to confirm a labeled example when "
    "possible. Then compare actual behavior, required evidence slots and explanation coverage, "
    "not merely whether the preview tool returned. Never label a model answer with itself. "
    "An asset inspected during setup is not automatically included in future runs: preserve "
    "needed corroborating sources in the card or an explicitly approved investigation path. "
    "Do not make optional corroboration an unconditional action prerequisite. Resolve missing definitions, "
    "unsupported questions, partial populations and conflicting measurements before proposing "
    "unattended reporting. Reuse existing trusted SQL and metric definitions, but verify them "
    "against source results. Ask only material unresolved business questions. Do not equate "
    "differently defined nearby metrics with a conflict in the selected metric. "
    "Compare definitions within the same intended population and metric; clarify ambiguous owner "
    "wording before making it a recurring condition. A complete report "
    "means its bounded evidence checks passed, not that the full business policy is certified. "
    "For recurring cards, distinguish reusable owner intent from the dates and values of the "
    "onboarding example. Use each run's actual source measurement period and cutoff for a "
    "relative window; preserve a fixed historical window only when the owner explicitly requests it. "
    "If complete/comparable evidence is an owner prerequisite, bind required_comparison_keys "
    "to inspected contract.comparison_contracts keys or applicable analytical_comparisons keys. "
    "A scalar coverage contract does not require a decomposable analytical comparison. "
    "Do not leave a known coverage requirement unbound merely because numerical analysis is unavailable. "
    "For threshold rules, distinguish a current level, signed between-period change in units, relative "
    "change, relative change in percent, and a segment's contribution to that change. Do not silently choose among them. "
    "For exact numerical boundaries over available analytical comparisons, add numeric_conditions "
    "bound to the inspected source, comparison key, measurement and exact unit; let code perform "
    "those comparisons. Use measurement=change_pct with unit=percent for relative thresholds. "
    "Rates use fractions (12% is 0.12); do not infer a unit conversion. "
    "numeric_conditions are optional: when no applicable analytical comparison exists, "
    "leave them empty and keep the owner's complete rule in decision_guidance. Never invent "
    "a comparison key or confuse a declared requirement with available source evidence. "
    "Leave absolute=false for directional increases or decreases. absolute=true compares "
    "magnitude in BOTH directions; it is not a synonym for a change measured in units. "
    "Keep the owner's action policy in decision_guidance. Numeric checks do not select actions, "
    "and incomplete matching reports stay unknown. Do not duplicate numerical checks as "
    "required semantic watch items merely to restate the policy. A required watch/question is "
    "advisory by default; set evidence_requirements=true only for a question or watch item "
    "the owner explicitly requires before automatic routing. Required sources and explicitly "
    "bound comparisons remain separate hard requirements. "
    "Separate authorized source scope from required decision dependencies: use required=true "
    "only for an owner-confirmed prerequisite for every policy outcome: its absence forces "
    "insufficient_data. Mark optional or branch-specific context sources required=false. Confirm missing-source "
    "behavior with the owner for each relevant case; an optional source's absence must not "
    "block unrelated policy branches. "
    "Instructions about how to write a report (for example, avoid causal claims) belong in "
    "follow_up_guidance, not watch_for: writing instructions are not observable evidence. "
    "watch_for and questions may be empty when the policy requires no separate semantic assessment. "
    "evidence_requirements maps only existing one-based watch:N or question:N slots to booleans. "
    "Review counterexamples such as a large but unchanged level, offsetting segment changes, "
    "a threshold-boundary case, and missing population coverage. Derive expected actions from "
    "the owner's policy independently of the model's answers; surface disagreements for review. "
    "Test other periods and negative cases with independent expectations before enabling "
    "unattended delivery. If only current evidence is available, capture one owner-labeled "
    "current case or preview it; do not invent historical snapshots. Owner approval without "
    "full acceptance remains unassessed and is suitable only for caller-managed shadow review. "
    "Never infer causation from a contribution breakdown. Scheduling, final "
    "narrative generation and delivery remain with the caller-owned agent."
)


def create_mcp(
    runtime: Runtime | None = None,
    *,
    profile: MCPProfile = "agent",
    principal_resolver: Callable[[Context], PrincipalContext] | None = None,
    http_principal_resolver: Callable[[], PrincipalContext] | None = None,
    auth_settings: Any | None = None,
    token_verifier: Any | None = None,
    require_principal: bool = False,
) -> FastMCP:
    if profile not in {"agent", "full"}:
        raise ValueError("MCP profile must be 'agent' or 'full'")
    default_card_response_mode: ResponseMode = "compact" if profile == "agent" else "full"
    runtime = runtime or build_runtime(mode="agent" if profile == "agent" else "jev")
    if require_principal and runtime.principal is None and principal_resolver is None:
        raise RuntimeError(
            "the HTTP MCP server requires a deployment or request principal; "
            "use stdio for an intentionally unscoped local process"
        )
    authoring = InsightAuthoringService(
        runtime.sources, runtime.engine, principal=runtime.principal
    )
    metric_query_store = runtime.metric_query_store or JsonMetricQueryCardStore(
        os.getenv("METRIC_QUERY_CARD_STORE", "data/metric-query-cards.json")
    )
    decision_receipts = runtime.decision_receipts or InMemoryDecisionReceiptStore()
    decision_feedback = runtime.decision_feedback or InMemoryDecisionFeedbackStore()
    certification_reports = runtime.certification_reports or InMemoryCertificationReportStore()
    idempotency_locks: dict[str, asyncio.Lock] = {}
    decision_provider = str(getattr(runtime.engine.judger, "name", "jev-latest"))
    mcp = FastMCP(
        "signal-weave",
        instructions=(
            "Start with get_signalweave_guide. The default agent profile stores a human-reviewed card, "
            "fetches only its approved source scope, and calls Jev for the card's typed policy judgment. "
            "Use search_catalog and inspect_resource to discover and verify sources, onboard_insight_card "
            "to save the owner's intent and exact source references, then review and obtain explicit approval. "
            "Give the person a useful current analysis from inspected evidence, with each source's scope and "
            "period. Pending alert criteria require confirmation before automation; they do not prevent "
            "reporting supported facts. Honor an owner's explicit fallback rather than demanding an "
            "exhaustive rule for every possible movement. "
            "On each recurring run, call evaluate_insight_card once with a stable idempotency key. It returns "
            "a durable, delivery-disabled decision and evidence bundle. Jev applies the card's policy. The "
            "normal call needs no context argument: approved sources are fetched automatically. Do not "
            "repackage their observations as context or repeat source reads before evaluation. Use your "
            "source tools for additional investigation when needed. The "
            "frontier agent owns deeper discovery, causal investigation, narrative, scheduling, and delivery. "
            "Use get_decision_receipt to recover a result after a retry. Do not call prepare_insight_run as a "
            "second fetch for the same run. Dynamic source expansion is outside this profile. The full profile "
            "is an explicit opt-in for metric-query, evaluation, certification, and webhook tools."
            if profile == "agent"
            else (
                "Full SignalWeave MCP profile. For repeated analysis, begin with get_signalweave_guide, "
                "use onboard_insight_card to create a human-reviewed fixed-source card, and use "
                "evaluate_insight_card to return a typed Jev evaluation of its approved policy and an "
                "evidence bundle. The calling agent owns deeper investigation and narrative. "
                "prepare_insight_run is an advanced source-only path for callers that explicitly own "
                "the subsequent decision step; do not use it instead of evaluate_insight_card when "
                "SignalWeave/Jev should apply the card policy. Advanced metric-query, certification, "
                "and webhook capabilities are also exposed in this profile. A caller-owned scheduler "
                "handles delivery."
            ) + CARD_AUTHORING_GUIDANCE
        ).replace("Jev", provider_label(decision_provider)),
        auth=auth_settings,
        token_verifier=token_verifier,
    )

    def request_principal(ctx: Context | None) -> PrincipalContext | None:
        """Resolve a trusted gateway principal without accepting tool input as identity."""
        if principal_resolver is None:
            if require_principal and runtime.principal is None:
                raise RuntimeError("the identity gateway did not provide a principal")
            return runtime.principal
        if ctx is None:
            raise RuntimeError(
                "request-scoped principal resolution requires an MCP request context"
            )
        principal = principal_resolver(ctx)
        if principal is None:
            raise RuntimeError("the identity gateway did not provide a principal")
        return principal

    def assert_card_scope(card: InsightCard, principal: PrincipalContext | None) -> None:
        if principal is None:
            return
        if card.principal_tenant != principal.tenant_id:
            raise ValueError(
                "insight card is outside the authenticated principal tenant; "
                "rediscover or create it under the current principal"
            )

    def get_scoped_card(card_id: str, principal: PrincipalContext | None) -> InsightCard:
        card = runtime.card_store.get_card(card_id)
        assert_card_scope(card, principal)
        return card

    def assert_metric_card_scope(
        card: MetricQueryCard, principal: PrincipalContext | None
    ) -> None:
        if principal is None:
            return
        if card.principal_tenant != principal.tenant_id:
            raise ValueError(
                "metric query card is outside the authenticated principal tenant; "
                "rediscover or create it under the current principal"
            )

    def get_scoped_metric_card(
        card_id: str, principal: PrincipalContext | None
    ) -> MetricQueryCard:
        card = metric_query_store.get_card(card_id)
        assert_metric_card_scope(card, principal)
        return card

    def assert_evaluation_case_scope(
        cases: list[CardEvaluationCase], principal: PrincipalContext | None
    ) -> None:
        if principal is None:
            return
        for case in cases:
            foreign = [
                f"{resource.adapter}|{resource.resource}"
                for resource in case.resources
                if resource.contract.tenant_id != principal.tenant_id
                or not resource.contract.authorized
            ]
            if foreign:
                raise ValueError(
                    "evaluation case contains resources outside the authenticated principal "
                    f"tenant: {', '.join(sorted(foreign))}"
                )

    async def context_for_card(
        card: InsightCard,
        context: ContextSnapshot | None,
        principal: PrincipalContext | None,
    ) -> ContextSnapshot | None:
        """Resolve trusted deployment context without trusting tool payloads."""
        if context is not None:
            return context
        provider = runtime.context_provider or runtime.engine.context_provider
        if provider is None:
            return None
        try:
            resources = await runtime.sources.resolve(
                card.sources,
                authorized_tenants=[principal.tenant_id] if principal else None,
            )
            return await provider.get_context(card, resources)
        except Exception as error:  # noqa: BLE001 - context is visible but optional
            return ContextSnapshot(
                provider=provider.name,
                version="unavailable",
                trust="unverified",
                warnings=[f"Context provider failed: {type(error).__name__}: {error}"],
            )

    def persist_certification(
        *,
        kind: str,
        subject_id: str,
        tenant_id: str,
        subject_version: str,
        report: dict[str, Any],
    ) -> CertificationRecord:
        report_id = str(report.get("evaluation_id") or report.get("manifest_name") or uuid4().hex)
        record = CertificationRecord(
            report_id=f"{kind}:{subject_id}:{report_id}:{uuid4().hex[:12]}",
            kind=kind,  # type: ignore[arg-type]
            subject_id=subject_id,
            tenant_id=tenant_id,
            subject_version=subject_version,
            status=str(report.get("status", "blocked")),  # type: ignore[arg-type]
            dataset_ids=[str(item) for item in report.get("dataset_ids", [])],
            input_digest=str(report.get("input_digest", "")),
            label_digest=str(report.get("label_digest", "")),
            report=report,
        )
        certification_reports.save(record)
        return record

    def append_onboarding_review(
        card: InsightCard, review: Any
    ) -> InsightCard:
        history = [*card.onboarding_review_history, review][-20:]
        return card.model_copy(
            update={
                "onboarding_review": review,
                "onboarding_review_history": history,
            }
        )

    def assert_dynamic_review_scope(card: InsightCard, adapter: str | None) -> None:
        """Prevent a connector-scoped review from hiding dynamic evidence.

        ``adapter`` is useful for a fixed, single-connector card. Once a card
        asks SignalWeave to expand or investigate, an adapter-scoped review can
        certify a source selection without ever showing the other connectors
        that the runtime may use. That is an onboarding correctness bug, not a
        harmless pagination choice.
        """
        dynamic_scope = (
            card.retrieval_mode != RetrievalMode.FIXED
            or card.investigation_mode != InvestigationMode.NONE
        )
        if adapter and dynamic_scope and len(runtime.sources.adapter_names()) > 1:
            raise ValueError(
                "Dynamic multi-connector cards must be reviewed against the full authorized "
                "catalog; omit adapter so related evidence from every connector is visible."
            )

    async def prepare_insight_card(
        card: InsightCard,
        context: ContextSnapshot | None = None,
        *,
        principal: PrincipalContext | None = None,
    ) -> tuple[InsightCard, Any]:
        """Resolve optional related sources without mutating the stored card."""
        bundle = await authoring.resolve_bundle(card, context, principal=principal)
        expanded = card
        if [source.model_dump(mode="json") for source in bundle.selected_sources] != [
            source.model_dump(mode="json") for source in card.sources
        ]:
            expanded = card.model_copy(
                update={"sources": bundle.selected_sources, "compiled_plan": None}
            )
        return expanded, bundle

    async def evaluate_approved_card_once(
        card_id: str,
        *,
        idempotency_key: str | None,
        actor: str,
        context: ContextSnapshot | None = None,
        principal: PrincipalContext | None = None,
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
    ) -> dict[str, Any]:
        card = runtime.card_store.get_card(card_id)
        assert_card_scope(card, principal)
        if card.status != InsightCardStatus.APPROVED:
            raise ValueError(
                f"Insight card {card_id} is a draft; simulate it, then approve it before evaluation"
            )
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        parent_id = parent_receipt_id.strip() if parent_receipt_id else None
        step_key = workflow_step_key.strip() if workflow_step_key else None
        if step_key and not parent_id:
            raise ValueError("workflow_step_key requires parent_receipt_id")
        if parent_id:
            parent = decision_receipts.get_by_receipt_id(parent_id)
            if parent is None:
                raise ValueError("parent_receipt_id does not identify a decision receipt")
            if parent.card_id != card.id:
                raise ValueError("parent_receipt_id belongs to a different insight card")
        context = await context_for_card(card, context, principal)
        fingerprint = _evaluation_fingerprint(
            card,
            actor=actor,
            context=context,
            parent_receipt_id=parent_id,
            workflow_step_key=step_key,
        )
        existing = decision_receipts.get_by_idempotency_key(key)
        if existing is not None:
            if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                raise ValueError(
                    "idempotency key is already bound to a different card, actor, version, "
                    "or context"
                )
            if existing.status == ReceiptStatus.PREPARED:
                raise ValueError("idempotency key is already being evaluated; retry shortly")
            return {
                "receipt": existing.model_copy(update={"status": ReceiptStatus.REPLAYED}).model_dump(
                    mode="json", exclude={"result"}
                ),
                "replayed": True,
                "result": existing.result,
            }
        prepared = DecisionReceipt(
            receipt_id=f"receipt-{uuid4().hex}",
            idempotency_key=key,
            request_fingerprint=fingerprint,
            card_id=card.id,
            card_version=card.version,
            actor=actor or "mcp-client",
            parent_receipt_id=parent_id,
            workflow_step_key=step_key,
            context_provider=context.provider if context else None,
            context_version=context.version if context else None,
            status=ReceiptStatus.PREPARED,
        )
        if not decision_receipts.claim(prepared):
            existing = decision_receipts.get_by_idempotency_key(key)
            if existing is not None and existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                raise ValueError(
                    "idempotency key is already bound to a different card, actor, version, "
                    "or context"
                )
            if existing is not None and existing.status == ReceiptStatus.PREPARED:
                raise ValueError("idempotency key is already being evaluated; retry shortly")
            if existing is None:
                raise RuntimeError("unable to claim idempotency key")
            return {
                "receipt": existing.model_copy(update={"status": ReceiptStatus.REPLAYED}).model_dump(
                    mode="json", exclude={"result"}
                ),
                "replayed": True,
                "result": existing.result,
            }
        try:
            evaluation_card, bundle = await prepare_insight_card(
                card, context, principal=principal
            )
            run = await runtime.engine.evaluate(
                evaluation_card, context_override=context, principal=principal
            )
            evaluated_result = run.result.model_copy(update={"retrieval": bundle})
            result = evaluated_result.model_dump(mode="json")
            result["source_contracts"] = [
                {
                    "source_key": resource.source_key,
                    "adapter": resource.adapter,
                    "resource": resource.resource,
                    "source_url": resource.source_url,
                    "captured_at": resource.captured_at.isoformat(),
                    "source_captured_at": (
                        resource.source_captured_at.isoformat() if resource.source_captured_at else None
                    ),
                    "contract": resource.contract.model_dump(mode="json"),
                }
                for resource in run.resources
            ]
            report = build_investigation_report(run.card, evaluated_result, run.resources)
            result["report"] = report.model_dump(mode="json")
            result["report_markdown"] = render_investigation_report(report)
        except Exception as error:  # noqa: BLE001 - persist failed claims for replay safety
            handoff = getattr(error, "prepared_handoff", None)
            if (
                isinstance(error, JevPayloadError)
                and error.stage == "judgment"
                and isinstance(handoff, dict)
            ):
                deferred_card = handoff["card"]
                resources = handoff["resources"]
                plan = handoff["plan"]
                materials = handoff["materials"]
                source_by_key = {
                    resource.source_key: resource.model_dump(mode="json")
                    for resource in resources
                }
                result = {
                    "card_id": deferred_card.id,
                    "outcome": None,
                    "delivery_enabled": False,
                    "delivery_methods": [],
                    "source_keys": list(source_by_key),
                    "judgment": {
                        "status": "deferred",
                        "reason": "local_judgment_payload_over_budget",
                        "input_budget": {
                            "stage": error.stage,
                            "observed_bytes": error.observed_bytes,
                            "budget_bytes": error.budget_bytes,
                            "observed_tokens": error.observed_tokens,
                            "budget_tokens": error.budget_tokens,
                        },
                        "provider_call_attempts": error.provider_call_attempts,
                        "attempt_scope": "current_judgment",
                        "provider_call_attempted": (
                            None
                            if error.provider_call_attempts is None
                            else error.provider_call_attempts > 0
                        ),
                    },
                    "judgment_state": materials.state,
                    "source_by_key": source_by_key,
                    "source_contracts": [
                        {
                            "source_key": resource.source_key,
                            "adapter": resource.adapter,
                            "resource": resource.resource,
                            "source_url": resource.source_url,
                            "captured_at": resource.captured_at.isoformat(),
                            "source_captured_at": (
                                resource.source_captured_at.isoformat()
                                if resource.source_captured_at else None
                            ),
                            "contract": resource.contract.model_dump(mode="json"),
                        }
                        for resource in resources
                    ],
                    "retrieval": bundle.model_dump(mode="json"),
                }
                receipt = prepared.model_copy(
                    update={
                        "delivery_mode": "shadow",
                        "status": ReceiptStatus.DECISION_DEFERRED,
                        "outcome": None,
                        "delivery_enabled": False,
                        "delivery_method_keys": [],
                        "result": result,
                    }
                )
                decision_receipts.save(receipt)
                return {
                    "receipt": receipt.model_dump(mode="json", exclude={"result"}),
                    "replayed": False,
                    "card": _evaluation_card(deferred_card),
                    "plan": plan.model_dump(mode="json"),
                    "result": result,
                }
            failure: dict[str, Any] = {"error": f"{type(error).__name__}: {error}"}
            if isinstance(error, (EvaluationPayloadError, JevPayloadError)):
                failure["jev_payload_budget"] = {
                    "stage": error.stage,
                    "observed_bytes": error.observed_bytes,
                    "budget_bytes": error.budget_bytes,
                    "status": "exceeded",
                }
            decision_receipts.save(
                prepared.model_copy(
                    update={
                        "status": ReceiptStatus.FAILED,
                        "outcome": Outcome.INSUFFICIENT_DATA,
                        "result": failure,
                    }
                )
            )
            raise
        receipt = prepared.model_copy(
            update={
                "delivery_mode": "shadow",
                "status": ReceiptStatus.DELIVERY_DISABLED,
                "outcome": run.result.outcome,
                "delivery_enabled": False,
                "delivery_method_keys": [method.key for method in run.result.delivery_methods],
                "result": result,
            }
        )
        decision_receipts.save(receipt)
        return {
            "receipt": receipt.model_dump(mode="json", exclude={"result"}),
            "replayed": False,
            "card": _evaluation_card(run.card),
            "retrieval": bundle.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "result": result,
        }

    async def evaluate_approved_card(
        card_id: str,
        *,
        idempotency_key: str | None,
        actor: str,
        context: ContextSnapshot | None = None,
        principal: PrincipalContext | None = None,
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
    ) -> dict[str, Any]:
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        lock = idempotency_locks.setdefault(key, asyncio.Lock())
        async with lock:
            response = await evaluate_approved_card_once(
                card_id,
                idempotency_key=key,
                actor=actor,
                context=context,
                principal=principal,
                parent_receipt_id=parent_receipt_id,
                workflow_step_key=workflow_step_key,
            )
            if "error" not in response["result"]:
                if response["result"].get("judgment", {}).get("status") == "deferred":
                    return response
                if "report" in response["result"]:
                    response["report"] = response["result"]["report"]
                    response["report_markdown"] = response["result"]["report_markdown"]
                else:
                    # Do not fabricate a historical report using today's card
                    # or renderer. The original decision remains readable.
                    response["report_unavailable_reason"] = (
                        "This receipt has no archived investigation report. "
                        "Use a new run key to evaluate current evidence."
                    )
            return response

    async def selected_query_sources(
        selected_sources: list[dict[str, Any]],
        principal: PrincipalContext | None,
    ) -> list[SourceRef]:
        if not selected_sources:
            raise ValueError("metric query cards require at least one selected source")
        catalog = {
            f"{resource.adapter}|{resource.resource}": resource
            for resource in await runtime.sources.list_resources(
                authorized_tenants=[principal.tenant_id] if principal else None
            )
        }
        refs: list[SourceRef] = []
        for index, item in enumerate(selected_sources):
            ref = str(item.get("ref") or "")
            if "|" not in ref:
                adapter = str(item.get("adapter") or "")
                resource = str(item.get("resource") or "")
                ref = f"{adapter}|{resource}"
            descriptor = catalog.get(ref)
            if descriptor is None:
                raise ValueError(f"selected metric source is not in the authorized catalog: {ref}")
            adapter, _, resource = ref.partition("|")
            refs.append(
                SourceRef(
                    key=str(item.get("key") or f"source-{index + 1}-{_slug(resource)}"),
                    adapter=adapter,
                    resource=resource,
                    label=str(item.get("label") or descriptor.title),
                    parameters=item.get("parameters") or {},
                    required=bool(item.get("required", True)),
                )
            )
        return refs

    def _guide(task: str, ctx: Context | None) -> dict[str, Any]:
        request_principal(ctx)
        if profile == "agent":
            return agent_getting_started(task, decision_provider=decision_provider)
        return getting_started(task, decision_provider=decision_provider)  # type: ignore[arg-type]

    if profile == "agent":

        @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
        def get_signalweave_guide(
            task: Literal["start", "monitor"] = "start",
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            """Explain card onboarding and recurring decisions using the configured provider."""
            return _guide(task, ctx)

    else:

        @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
        def get_signalweave_guide(
            task: GuideTask = "start", ctx: Context | None = None,
        ) -> dict[str, Any]:
            """Explain the optional legacy full-profile workflows."""
            return _guide(task, ctx)

    @mcp.tool()
    async def list_resources(
        adapter: str | None = None, ctx: Context | None = None
    ) -> list[dict[str, Any]]:
        """List safe, inspectable resources exposed by installed source adapters."""
        principal = request_principal(ctx)
        resources = await runtime.sources.list_resources(
            adapter,
            authorized_tenants=[principal.tenant_id] if principal else None,
        )
        return [resource.model_dump(mode="json") for resource in resources]

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    async def search_catalog(
        query: str,
        adapter: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Recall authorized catalog candidates without using Jev.

        This is lexical/connector-owned recall for a frontier agent. It does
        not decide which asset answers a business question; inspect the
        returned candidates and pass the exact approved refs to onboarding.
        Use an empty query to browse a bounded page when the titles are unknown.
        """
        principal = request_principal(ctx)
        page = await runtime.sources.search_resources(
            query,
            adapter_name=adapter,
            limit=limit,
            cursor=cursor,
            authorized_tenants=[principal.tenant_id] if principal else None,
        )
        return page.model_dump(mode="json")

    @mcp.tool()
    async def inspect_resource(
        adapter: str,
        resource: str,
        label: str | None = None,
        parameters: dict[str, Any] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Inspect one source resource without making an insight decision."""
        source = SourceRef(
            key=f"inspect-{_slug(adapter)}-{_slug(resource)}",
            adapter=adapter,
            resource=resource,
            label=label or resource,
            parameters=parameters or {},
        )
        principal = request_principal(ctx)
        snapshot = await runtime.sources.inspect(
            source,
            authorized_tenants=[principal.tenant_id] if principal else None,
        )
        return snapshot.model_dump(mode="json")

    @mcp.tool()
    async def discover_insight_sources(
        goal: str,
        adapter: str | None = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=25,
                description="Maximum number of bounded authoring candidates (1-25).",
            ),
        ] = 10,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Find optional Jev-ranked source candidates for an insight goal.

        Prefer ``list_resources``/``search_catalog`` plus ``inspect_resource``
        when a frontier agent is available. This tool is a convenience for
        callers that explicitly want Jev to rank a bounded catalog.
        """
        discovery = await authoring.discover(
            goal,
            adapter=adapter,
            limit=limit,
            principal=request_principal(ctx),
        )
        return discovery.model_dump(mode="json")

    @mcp.tool()
    async def assess_bootstrap(
        manifest: dict[str, Any], ctx: Context | None = None
    ) -> dict[str, Any]:
        """Check whether installed adapters are ready for bounded card onboarding.

        The caller supplies real probe goals and capability requirements. This
        performs read-only catalog and sample-inspection checks; it does not
        import data, create cards, or change adapter permissions.
        """
        principal = request_principal(ctx)
        bootstrap_manifest = BootstrapManifest.model_validate(manifest)
        report = await BootstrapService(runtime.sources).assess(
            bootstrap_manifest, principal=principal
        )
        payload = report.model_dump(mode="json")
        record = persist_certification(
            kind="bootstrap",
            subject_id=bootstrap_manifest.tenant_id,
            tenant_id=bootstrap_manifest.tenant_id,
            subject_version=bootstrap_manifest.name,
            report=payload,
        )
        return {**payload, "certification_report_id": record.report_id}

    @mcp.tool()
    async def evaluate_card_workflow(
        card_id: str,
        cases: Annotated[list[WorkflowCaseInput], Field(min_length=1, max_length=500)],
        thresholds: dict[str, Any] | None = None,
        max_concurrency: int = 8,
        acceptance_outcomes: list[Outcome] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Replay one stored card against owner-labeled snapshots before promotion.

        Each case contains ``id``, ``expected_outcome`` and either exact
        ``resources`` snapshots or ``capture_current_sources=true`` to fetch
        this card's selected sources. Current capture can execute source queries;
        use it only within the owner's query budget. At most one case can capture
        current evidence. It is NOT historical or full-policy acceptance.
        For historical snapshots, set an aware ``as_of`` timestamp; this evaluates
        source freshness against that clock without permitting current-source capture.
        A supplied snapshot captured after ``as_of`` is rejected before evaluation.
        Copy snapshot objects unchanged; resource strings are not snapshots.
        For acceptance, the owner must explicitly provide
        ``expected_delivery_method_keys``, ``expected_delivery_destinations``,
        ``required_evidence_source_keys``, and ``expected_retrieval_refs``;
        explicit ``[]``/``{}`` means that none are expected. Omitted labels are
        blocked before Jev. Optional evidence/retrieval labels stay in the
        evaluator and are never included in the Jev state. Historical snapshots
        are supplied by the caller; production delivery is not performed by
        this tool.
        Set acceptance_outcomes to the owner's intended dispositions to test
        onboarding with strict behavioral coverage and exact endpoint labels.
        This is empirical evidence, not human authorization or causal proof.

        By default retrieval must exactly match expected_retrieval_refs. Supply
        allowed_retrieval_refs to permit bounded optional corroborating context:
        expected refs remain mandatory, unlisted retrieval still fails. These
        owner labels do not grant source access or select sources for the card.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        if not cases:
            raise ValueError("at least one labeled evaluation case is required")
        inputs = [WorkflowCaseInput.model_validate(case) for case in cases]
        current_case_ids = [case.id for case in inputs if case.capture_current_sources]
        if len(current_case_ids) > 1:
            raise ValueError("At most one current-source case is allowed; supply distinct historical snapshots for other cases.")
        if current_case_ids and acceptance_outcomes is not None:
            raise ValueError("Current-source capture is a shadow check, not acceptance certification; supply independent historical snapshots for acceptance_outcomes.")
        # Validate ALL inputs before a source query or inference is attempted.
        parsed_cases = [
            CardEvaluationCase.model_validate({
                **case.model_dump(
                    exclude={"capture_current_sources", "resources"}, exclude_unset=True
                ),
                "resources": case.resources or [], "card": card,
            }) for case in inputs
        ]
        assert_evaluation_case_scope(parsed_cases, principal)
        parsed_thresholds = CardEvaluationThresholds.model_validate(thresholds) if thresholds is not None else None
        evaluator = CardWorkflowEvaluator(runtime.engine, max_concurrency=max_concurrency, principal=principal)
        for input_case, parsed in zip(inputs, parsed_cases, strict=True):
            if input_case.capture_current_sources:
                parsed.resources = await runtime.sources.resolve(
                    card.sources, authorized_tenants=[principal.tenant_id] if principal else None,
                )
        assert_evaluation_case_scope(parsed_cases, principal)
        report = await evaluator.evaluate(
            parsed_cases,
            thresholds=parsed_thresholds,
            acceptance_outcomes=acceptance_outcomes,
        )
        payload = report.model_dump(mode="json")
        if current_case_ids:
            payload["current_source_case_ids"] = current_case_ids
            if payload["status"] == "approved":
                payload["status"] = "shadow"
        record = persist_certification(
            kind="card_workflow",
            subject_id=card.id,
            tenant_id=card.principal_tenant or (principal.tenant_id if principal else "deployment"),
            subject_version=str(card.version),
            report=payload,
        )
        return {**payload, "certification_report_id": record.report_id}

    @mcp.tool()
    async def evaluate_retrieval_quality(
        cases: list[dict[str, Any]],
        thresholds: dict[str, Any] | None = None,
        max_concurrency: int = 8,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Measure adapter candidate recall and Jev source recommendations.

        ``expected_resource_refs`` are evaluator-only owner labels. They are
        never copied into the discovery goal or candidate state sent to Jev.
        """
        principal = request_principal(ctx)
        if not cases:
            raise ValueError("at least one labeled retrieval case is required")
        principal_payload = principal.model_dump(mode="json") if principal else None
        parsed_cases = [
            RetrievalQualityCase.model_validate({**case, "principal": principal_payload})
            for case in cases
        ]
        report = await RetrievalQualityEvaluator(
            authoring, max_concurrency=max_concurrency
        ).evaluate(
            parsed_cases,
            thresholds=(
                RetrievalQualityThresholds.model_validate(thresholds)
                if thresholds is not None
                else None
            ),
        )
        payload = report.model_dump(mode="json")
        record = persist_certification(
            kind="retrieval_quality",
            subject_id="retrieval-catalog",
            tenant_id=principal.tenant_id if principal else "deployment",
            subject_version=principal.tenant_id if principal else "deployment",
            report=payload,
        )
        return {**payload, "certification_report_id": record.report_id}

    @mcp.tool()
    def get_certification_report(
        report_id: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Return one durable bootstrap or evaluation report by ID."""
        record = certification_reports.get(report_id)
        principal = request_principal(ctx)
        if principal is not None and record.tenant_id != principal.tenant_id:
            raise ValueError("certification report is outside the authenticated principal tenant")
        return record.model_dump(mode="json")

    @mcp.tool()
    def list_certification_reports(
        subject_id: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        """List durable certification evidence for an optional card or tenant."""
        principal = request_principal(ctx)
        records = certification_reports.list(subject_id=subject_id)
        if principal is not None:
            records = [record for record in records if record.tenant_id == principal.tenant_id]
        return {
            "reports": [record.model_dump(mode="json") for record in records],
            "count": len(records),
        }

    @mcp.tool()
    def get_enterprise_readiness(ctx: Context | None = None) -> dict[str, Any]:
        """Summarize the tenant's bootstrap, card, and certification gates.

        This is an evidence index for a caller-owned UI or agent, not a claim
        that SignalWeave is enterprise-ready. A clean result means the tenant
        has the minimum proof to begin a controlled shadow deployment.
        """
        principal = request_principal(ctx)
        tenant_id = principal.tenant_id if principal else "deployment"
        records = certification_reports.list()
        if principal is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        cards = [
            card
            for card in runtime.card_store.list_cards()
            if principal is None or card.principal_tenant == tenant_id
        ]

        def latest(*, kind: str, subject_id: str | None = None) -> CertificationRecord | None:
            matching = [
                record
                for record in records
                if record.kind == kind
                and (subject_id is None or record.subject_id == subject_id)
            ]
            return max(matching, key=lambda record: record.created_at) if matching else None

        gates: list[dict[str, str]] = []
        bootstrap = latest(kind="bootstrap", subject_id=tenant_id)
        if bootstrap is None:
            gates.append(
                {
                    "code": "bootstrap-certification-missing",
                    "severity": "blocked",
                    "message": "No source-boundary bootstrap report exists for this tenant.",
                }
            )
        elif bootstrap.status != "approved" and bootstrap.report.get("status") != "ready":
            gates.append(
                {
                    "code": "bootstrap-needs-review",
                    "severity": "blocked" if bootstrap.status == "blocked" else "review",
                    "message": f"Bootstrap report is {bootstrap.status}; resolve its warnings or blockers.",
                }
            )

        if not cards:
            gates.append(
                {
                    "code": "no-cards",
                    "severity": "review",
                    "message": "Create and review at least one insight card before shadow deployment.",
                }
            )

        card_summaries: list[dict[str, Any]] = []
        for card in sorted(cards, key=lambda item: item.id):
            review_status = (
                card.onboarding_review.readiness_status
                if card.onboarding_review is not None
                else "missing"
            )
            workflow = latest(kind="card_workflow", subject_id=card.id)
            policy_current = bool(workflow and has_current_evidence_admission_policy(workflow.report))
            acceptance_current = bool(
                workflow and workflow.report.get("acceptance_passed") is True
                and workflow.report.get("card_execution_digests", {}).get(card.id) == card_acceptance_digest(card)
            )
            summary = {
                "card_id": card.id,
                "version": card.version,
                "status": card.status.value,
                "onboarding_status": review_status,
                "workflow_certification": (
                    {
                        "report_id": workflow.report_id,
                        "status": workflow.status,
                        "created_at": workflow.created_at.isoformat(),
                        "subject_version": workflow.subject_version,
                        "stale": workflow.subject_version != str(card.version) or not policy_current,
                        "evidence_admission_policy_current": policy_current,
                        "acceptance_current": acceptance_current,
                    }
                    if workflow
                    else None
                ),
            }
            card_summaries.append(summary)
            if review_status == "blocked":
                gates.append(
                    {
                        "code": "card-onboarding-blocked",
                        "severity": "blocked",
                        "message": f"Card {card.id} has blocking onboarding conditions.",
                    }
                )
            elif card.status != InsightCardStatus.APPROVED or review_status != "ready_for_approval":
                gates.append(
                    {
                        "code": "card-needs-approval",
                        "severity": "review",
                        "message": f"Card {card.id} is not approved for shadow evaluation.",
                    }
                )
            if workflow is None:
                gates.append(
                    {
                        "code": "workflow-certification-missing",
                        "severity": "review",
                        "message": f"Card {card.id} has no owner-labeled workflow certification.",
                    }
                )
            elif workflow.subject_version != str(card.version):
                gates.append(
                    {
                        "code": "workflow-certification-stale",
                        "severity": "blocked",
                        "message": (
                            f"Card {card.id} is version {card.version}, but its latest "
                            f"workflow certification covers version {workflow.subject_version}. "
                            "Replay the certification set before shadow evaluation."
                        ),
                    }
                )
            elif not policy_current:
                gates.append({
                    "code": "workflow-admission-policy-stale",
                    "severity": "blocked",
                    "message": (
                        f"Card {card.id} certification predates the current evidence admission policy. "
                        "Review required versus advisory checks and replay certification; the old audit is retained."
                    ),
                })
            elif workflow.status != "approved":
                gates.append(
                    {
                        "code": "workflow-certification-needs-review",
                        "severity": "review",
                        "message": f"Card {card.id} workflow certification is {workflow.status}.",
                    }
                )
            elif not acceptance_current:
                gates.append({
                    "code": "workflow-acceptance-missing-or-stale",
                    "severity": "review",
                    "message": f"Card {card.id} needs a passing acceptance replay of its current "
                               "policy, sources, plan and destinations. A preview or partial "
                               "certification does not prove onboarding works.",
                })

        retrieval = latest(kind="retrieval_quality", subject_id="retrieval-catalog")
        if retrieval is None:
            gates.append(
                {
                    "code": "retrieval-certification-missing",
                    "severity": "review",
                    "message": "No tenant retrieval-quality certification exists.",
                }
            )
        elif retrieval.status != "approved":
            gates.append(
                {
                    "code": "retrieval-certification-needs-review",
                    "severity": "review",
                    "message": f"Retrieval certification is {retrieval.status}.",
                }
            )

        status = (
            "blocked"
            if any(gate["severity"] == "blocked" for gate in gates)
            else "needs_review"
            if gates
            else "ready_for_shadow"
        )
        return {
            "tenant_id": tenant_id,
            "status": status,
            "context_provider": {
                "configured": runtime.context_provider is not None
                or runtime.engine.context_provider is not None,
            },
            "source_adapters": runtime.sources.adapter_names(),
            "bootstrap": bootstrap.model_dump(mode="json") if bootstrap else None,
            "cards": card_summaries,
            "retrieval_certification": retrieval.model_dump(mode="json") if retrieval else None,
            "gates": gates,
        }

    @mcp.tool()
    async def propose_insight_card(
        what_to_watch: str,
        why_watch: str,
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        selected_sources: list[SelectedSourceInput] | None = None,
        adapter: str | None = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=25,
                description="Maximum number of bounded authoring candidates (1-25).",
            ),
        ] = 10,
        title: str | None = None,
        comparison_windows: ComparisonWindows | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        action_confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description=(
                    "Model-support floor for automatic action, not an accuracy guarantee. "
                    "The normal default is 0.70; 1.0 may prevent automation."
                ),
            ),
        ] = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope: fixed uses the selected source references as provided; "
                    "expand allows additional authorized sources when the adapter registry "
                    "supports bounded related-source retrieval."
                )
            ),
        ] = RetrievalMode.FIXED,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Investigation scope: none disables follow-up; bounded enables bounded "
                    "follow-up investigation and requires a live SourceRegistry. Use bounded "
                    "only when the owner wants additional source-based why/driver analysis "
                    "beyond the card's approved anchors and relationship-linked context; "
                    "a multi-source card does not require a second follow-up stage."
                )
            ),
        ] = InvestigationMode.NONE,
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        response_mode: Annotated[
            ResponseMode,
            Field(
                description=(
                    "Response detail for the client. compact preserves typed policy, source identity, "
                    "rankings and approval facts while removing duplicated catalog payloads; full "
                    "returns the exhaustive audit packet."
                )
            ),
        ] = "full",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Propose and save a draft free-form insight card.

        ``selected_sources`` contains exact refs chosen by the caller after
        catalog search/inspection; each item may also provide adapter
        parameters such as Superset chart IDs. The result is a draft until a
        human or policy service approves it. If omitted, the legacy convenience
        discovery path may ask Jev to rank a bounded catalog.
        """
        proposal = await authoring.propose(
            what_to_watch,
            why_watch,
            watch_for=watch_for,
            questions=questions,
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements,
            decision_guidance=decision_guidance,
            follow_up_guidance=follow_up_guidance,
            selected_sources=selected_sources,
            adapter=adapter,
            limit=limit,
            title=title,
            comparison_windows=comparison_windows,
            delivery_methods=[
                DeliveryMethod.model_validate(method) for method in (delivery_methods or [])
            ],
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=RetrievalMode(retrieval_mode),
            investigation_mode=InvestigationMode(investigation_mode),
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            principal=request_principal(ctx),
        )
        stored_card = proposal.card.model_copy(update={"compiled_plan": proposal.plan})
        runtime.card_store.save_card(stored_card)
        proposal = proposal.model_copy(update={"card": stored_card})
        proposal_payload = proposal.model_dump(mode="json", exclude={"card": {
            "onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"
        }})
        summary = proposal_summary(proposal)
        if response_mode == "compact":
            proposal_payload["discovery"] = _compact_discovery(proposal_payload.get("discovery"))
            proposal_payload["plan"] = _compact_plan(proposal_payload.get("plan"))
            proposal_payload["onboarding_review"] = _compact_review(
                proposal_payload.get("onboarding_review")
            )
            summary = _compact_summary(summary)
        return {
            "proposal": proposal_payload,
            "summary": summary,
            "response_mode": response_mode,
            "details_available": True,
        }

    @mcp.tool()
    async def onboard_insight_card(
        what_to_watch: str,
        why_watch: str,
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        selected_sources: list[SelectedSourceInput] | None = None,
        adapter: str | None = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=25,
                description="Maximum number of bounded authoring candidates (1-25).",
            ),
        ] = 10,
        title: str | None = None,
        comparison_windows: ComparisonWindows | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        action_confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description=(
                    "Model-support floor for automatic action, not an accuracy guarantee. "
                    "The normal default is 0.70; 1.0 may prevent automation."
                ),
            ),
        ] = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope: fixed uses the selected source references as provided; "
                    "expand allows additional authorized sources when the adapter registry "
                    "supports bounded related-source retrieval."
                )
            ),
        ] = RetrievalMode.FIXED,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Investigation scope: none disables follow-up; bounded enables bounded "
                    "follow-up investigation and requires a live SourceRegistry. Use bounded "
                    "only when the owner wants additional source-based why/driver analysis "
                    "beyond the card's approved anchors and relationship-linked context; "
                    "a multi-source card does not require a second follow-up stage."
                )
            ),
        ] = InvestigationMode.NONE,
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        response_mode: Annotated[
            ResponseMode,
            Field(
                description=(
                    "Response detail for the client. compact is the normal agent path; full retains "
                    "the duplicated catalog and review audit packet."
                )
            ),
        ] = "compact",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Onboard one free-form card in a single human-reviewable call.

        This is an ergonomic wrapper around the same typed proposal path;
        it never approves a card, sends a push, or accepts identity from tool
        arguments. The response is shaped for a caller-owned UI or agent:
        draft card, exact authorized source scope, typed plan, blockers, questions,
        and the exact next action needed to reach approval. When selected_sources
        is supplied, the caller/agent owns discovery and Jev is not used for
        catalog ranking or analytical investigation.
        """
        result = await propose_insight_card(
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for,
            questions=questions,
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements,
            decision_guidance=decision_guidance,
            follow_up_guidance=follow_up_guidance,
            selected_sources=selected_sources,
            adapter=adapter,
            limit=limit,
            title=title,
            comparison_windows=comparison_windows,
            delivery_methods=delivery_methods,
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=retrieval_mode,
            investigation_mode=investigation_mode,
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            response_mode=response_mode,
            ctx=ctx,
        )
        proposal = result["proposal"]
        review = proposal["onboarding_review"]
        if review["readiness_status"] == "blocked":
            next_action = "answer_setup_questions"
        elif review["readiness_status"] == "needs_human_review":
            next_action = "review_candidate_sources"
        else:
            next_action = "simulate_then_approve"
        return {
            "status": review["readiness_status"],
            "next_action": next_action,
            "approval_required": True,
            "delivery_enabled": False,
            "card": proposal["card"],
            "plan": proposal["plan"],
            "discovery": proposal["discovery"],
            "review": review,
            "setup_questions": proposal["setup_questions"],
            "summary": result["summary"],
            "response_mode": response_mode,
            "details_available": True,
        }

    @mcp.tool()
    async def bootstrap_insight_card(
        goal: Annotated[str, Field(description="In plain English, what should be monitored or answered?")],
        purpose: Annotated[str, Field(description="Why does this matter, and who needs the result?")],
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        selected_sources: list[SelectedSourceInput] | None = None,
        policy: Annotated[
            str | None,
            Field(description="Optional plain-English rule for what matters, what to ignore, or when to investigate."),
        ] = None,
        delivery_guidance: Annotated[
            str | None,
            Field(description="Optional plain-English guidance for the agent's follow-up report or handoff."),
        ] = None,
        source_hint: Annotated[
            str | None,
            Field(description="Optional free-form hint such as a dashboard, warehouse, or connector; not a source key."),
        ] = None,
        adapter: Annotated[
            str | None,
            Field(description="Optional registered adapter name, such as superset, trino, looker, or hex."),
        ] = None,
        title: Annotated[str | None, Field(description="Optional human-readable card title.")] = None,
        comparison_windows: ComparisonWindows | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope. The compact default is fixed to the exact selected sources. "
                    "Choose expand only when the owner explicitly wants bounded runtime source selection."
                )
            ),
        ] = RetrievalMode.FIXED,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Follow-up scope. The compact default is none: the caller's frontier agent owns "
                    "additional investigation. Choose bounded only when the owner explicitly wants "
                    "SignalWeave/Jev to select additional authorized sources."
                )
            ),
        ] = InvestigationMode.NONE,
        response_mode: Annotated[
            ResponseMode,
            Field(
                description=(
                    "Response detail for the client. compact is the normal agent path; full retains "
                    "the duplicated catalog and review audit packet."
                )
            ),
        ] = "compact",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Start onboarding from a few plain-language fields.

        This is the compact agent-facing entry point. The frontier agent should
        search/list and inspect the catalog first, then pass exact selected
        source refs, numeric conditions and outcome-to-destination mappings.
        SignalWeave validates those bindings; it never invents a source,
        threshold or recipient and never approves the card on the caller's behalf.
        Omitting selected_sources invokes the legacy Jev-ranked convenience path;
        use that only when the caller explicitly wants Jev to help with retrieval.
        """
        context = purpose
        if source_hint:
            context += f"\nSource/context hint from the owner: {source_hint}"
        return await onboard_insight_card(
            what_to_watch=goal,
            why_watch=context,
            watch_for=watch_for,
            questions=questions,
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements,
            selected_sources=selected_sources,
            decision_guidance=policy,
            follow_up_guidance=delivery_guidance,
            adapter=adapter,
            title=title,
            comparison_windows=comparison_windows,
            delivery_methods=delivery_methods,
            retrieval_mode=retrieval_mode,
            investigation_mode=investigation_mode,
            response_mode=response_mode,
            ctx=ctx,
        )

    @mcp.tool()
    async def draft_insight_card(
        title: str,
        what_to_watch: str,
        why_watch: str,
        sources: list[SourceRef],
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        comparison_windows: ComparisonWindows | None = None,
        action_confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description=(
                    "Model-support floor for automatic action, not an accuracy guarantee. "
                    "The normal default is 0.70; 1.0 may prevent automation."
                ),
            ),
        ] = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope: fixed uses the selected source references as provided; "
                    "expand allows additional authorized sources when the adapter registry "
                    "supports bounded related-source retrieval."
                )
            ),
        ] = RetrievalMode.FIXED,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Investigation scope: none disables follow-up; bounded enables bounded "
                    "follow-up investigation and requires a live SourceRegistry."
                )
            ),
        ] = InvestigationMode.NONE,
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Draft a card over explicit source resources; no push is sent.

        Use the minimal business fields described in ``CARD_AUTHORING_GUIDANCE``;
        returned storage objects are not draft inputs.
        """
        if not sources:
            raise ValueError("at least one source reference is required")
        principal = request_principal(ctx)
        source_refs = [SourceRef.model_validate(source) for source in sources]
        numeric_conditions = [
            NumericCondition.model_validate(condition)
            for condition in (numeric_conditions or [])
        ]
        source_refs = bind_numeric_condition_requirements(source_refs, numeric_conditions)
        contracts = {}
        if comparison_windows is None:
            for source in source_refs:
                descriptor = await runtime.sources.authorize(
                    source, authorized_tenants=[principal.tenant_id] if principal else None,
                )
                if descriptor is not None:
                    contracts[f"{source.adapter}|{source.resource}"] = descriptor.contract
        card = InsightCard(
            id=f"card-{_slug(title)}-{uuid4().hex[:12]}",
            title=title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for or [],
            questions=questions or [],
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements or {},
            decision_guidance=(decision_guidance or "").strip(),
            follow_up_guidance=(follow_up_guidance or "").strip(),
            sources=source_refs,
            comparison_windows=resolve_comparison_windows(comparison_windows, source_refs, contracts),
            delivery_methods=[
                DeliveryMethod.model_validate(method) for method in (delivery_methods or [])
            ],
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=RetrievalMode(retrieval_mode),
            investigation_mode=InvestigationMode(investigation_mode),
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            principal_id=principal.principal_id if principal else None,
            principal_tenant=principal.tenant_id if principal else None,
        )
        plan = await runtime.engine.compile(card)
        card = card.model_copy(update={"compiled_plan": plan})
        runtime.card_store.save_card(card)
        return {
            "card": _evaluation_card(card),
            "plan": plan.model_dump(mode="json"),
            "status": card.status.value,
        }

    @mcp.tool()
    async def propose_metric_query_card(
        question: str,
        why: str,
        selected_sources: list[dict[str, Any]],
        requested_dimensions: list[str] | None = None,
        requested_time_grain: str | None = None,
        title: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Create a draft plain-language metric card over approved definitions.

        Jev selects a catalog definition and any requested semantic dimensions;
        code then stores the typed plan. SQL is emitted only by
        ``compile_metric_query_card`` with an explicit bounded time window.
        """
        if not question.strip() or not why.strip():
            raise ValueError("question and why are required")
        principal = request_principal(ctx)
        source_refs = await selected_query_sources(selected_sources, principal)
        selector = getattr(runtime.engine.judger, "select_metric_plan", None)
        if not callable(selector):
            raise RuntimeError("the configured Jev judger does not support metric planning")
        plan = await plan_query(
            registry=runtime.sources,
            selector=runtime.engine.judger,
            goal=f"{question.strip()}\nPurpose: {why.strip()}",
            source_refs=source_refs,
            requested_dimensions=requested_dimensions,
            requested_time_grain=requested_time_grain,
        )
        card_title = (title or question.strip().rstrip("."))[:200] or "Metric query"
        card = MetricQueryCard(
            id=f"metric-{_slug(card_title)}-{uuid4().hex[:12]}",
            title=card_title,
            question=question,
            why=why,
            sources=source_refs,
            requested_dimensions=requested_dimensions or [],
            requested_time_grain=requested_time_grain,
            query_plan=plan,
            principal_id=principal.principal_id if principal else None,
            principal_tenant=principal.tenant_id if principal else None,
        )
        metric_query_store.save_card(card)
        return {"card": card.model_dump(mode="json"), "status": card.status.value}

    @mcp.tool()
    def compile_metric_query_card(
        card_id: str,
        window_start: str,
        window_end: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Compile a stored metric card into deterministic, bounded SQL."""
        card = get_scoped_metric_card(card_id, request_principal(ctx))
        if card.query_plan is None:
            raise ValueError("metric query card has no approved metric plan")
        compiled = compile_query(card.query_plan, QueryWindow(window_start, window_end))
        return {
            "status": "preview" if card.status == QueryCardStatus.DRAFT else "approved",
            "card": card.model_dump(mode="json"),
            "compiled_query": compiled.model_dump(mode="json"),
        }

    @mcp.tool()
    def approve_metric_query_card(
        card_id: str, actor: str = "mcp-client", ctx: Context | None = None
    ) -> dict[str, Any]:
        """Approve a metric card for a caller-owned Trino or SQL executor."""
        principal = request_principal(ctx)
        card = get_scoped_metric_card(card_id, principal)
        if card.query_plan is None:
            raise ValueError("metric query card needs a resolved metric plan before approval")
        approved = metric_query_store.set_card_status(card_id, QueryCardStatus.APPROVED)
        approved = approved.model_copy(
            update={
                "approved_by": principal.principal_id if principal else actor,
                "approved_at": datetime.now(timezone.utc),
            }
        )
        metric_query_store.save_card(approved)
        return {"status": approved.status.value, "card": approved.model_dump(mode="json")}

    @mcp.tool()
    def list_metric_query_cards(
        status: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        """List stored metric query cards for a UI or agent."""
        principal = request_principal(ctx)
        selected_status = QueryCardStatus(status) if status else None
        cards = [
            card
            for card in metric_query_store.list_cards()
            if principal is None or card.principal_tenant == principal.tenant_id
            if selected_status is None or card.status == selected_status
        ]
        return {"cards": [card.model_dump(mode="json") for card in cards], "count": len(cards)}

    @mcp.tool()
    def get_metric_query_card(
        card_id: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Return one stored metric query card."""
        return get_scoped_metric_card(card_id, request_principal(ctx)).model_dump(mode="json")

    @mcp.tool()
    async def evaluate_insight_card(
        card_id: str,
        idempotency_key: str | None = None,
        actor: str = "mcp-client",
        context: ContextSnapshot | None = None,
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
        response_mode: Annotated[
            ResponseMode,
            Field(
                description=(
                    "Use compact for the normal agent handoff: small results retain evidence; "
                    "large results include receipt-backed paging instructions and explicit "
                    "coverage. Use full for an exhaustive audit response."
                )
            ),
        ] = "compact" if profile == "agent" else "full",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Run an approved card in delivery-disabled shadow mode.

        The result uses the configured decision provider and is durable. A local
        judgment-payload limit after source retrieval returns a ``deferred``
        judgment, not a policy outcome; its complete state is available through
        receipt pages. SignalWeave never sends configured delivery methods; a
        caller-owned agent may inspect the receipt and decide what to do next.
        The durable receipt retains the full result; compact mode only shapes
        this MCP response for the next agent turn.

        ``source_contracts`` retains this run's source quality and comparison
        coverage in the receipt. Check it before interpreting observations;
        large handoffs explicitly page omitted contracts rather than treating
        missing coverage as complete.

        Omit ``context`` for a normal run: approved source evidence is fetched
        automatically. Additional external facts may use a versioned context
        object; its provider/version fields belong inside that object. Do not
        copy already-fetched source observations into context.
        """
        principal = request_principal(ctx)
        trusted_actor = principal.principal_id if principal else actor
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        response = await evaluate_approved_card(
            card_id,
            idempotency_key=idempotency_key,
            actor=trusted_actor,
            context=context_snapshot,
            principal=principal,
            parent_receipt_id=parent_receipt_id,
            workflow_step_key=workflow_step_key,
        )
        return (
            _compact_evaluation_response(response)
            if response_mode == "compact"
            else response
        )

    @mcp.tool()
    def get_decision_receipt(
        idempotency_key: str | None = None,
        receipt_id: str | None = None,
        result_path: Annotated[list[str] | None, Field(
            min_length=1, max_length=8,
            description="Path within the stored receipt result. Use an advertised result_path or full_ref, not an inline_result_path.",
        )] = None,
        offset: Annotated[int, Field(
            ge=0, description="Zero-based collection item offset; use the returned next_offset to continue.",
        )] = 0,
        limit: Annotated[int, Field(
            ge=1, le=100,
            description="Maximum collection items per page (1-100), not a token or byte budget. Byte bounds may return fewer items.",
        )] = 25,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Recover one durable shadow result and its operator labels.

        A caller can use either the scheduler's idempotency key or the
        receipt id returned by ``evaluate_insight_card``. Deferred judgments
        have no outcome; their full prepared state is available through pages.
        The card scope check
        runs before any receipt data is returned. Set result_path to field names
        (for example ["evidence"] or ["report", "issues"]) and optional list
        indexes for a byte-bounded page. Objects return key/value entries;
        lists retain exact items. offset and limit count collection items, not
        tokens or bytes. Follow next_offset until has_more is false.
        Pages do not rerun sources or models. Omit result_path for the full audit.
        """
        principal = request_principal(ctx)
        key = idempotency_key.strip() if idempotency_key else None
        requested_receipt_id = receipt_id.strip() if receipt_id else None
        if idempotency_key is not None and not key:
            raise ValueError("idempotency_key must not be empty")
        if receipt_id is not None and not requested_receipt_id:
            raise ValueError("receipt_id must not be empty")
        if bool(key) == bool(requested_receipt_id):
            raise ValueError("provide exactly one of idempotency_key or receipt_id")
        receipt = (
            decision_receipts.get_by_idempotency_key(key)
            if key
            else decision_receipts.get_by_receipt_id(requested_receipt_id)
        )
        if receipt is None:
            raise ValueError("unknown decision receipt")
        get_scoped_card(receipt.card_id, principal)
        if result_path is not None:
            return {
                "status": "found",
                "receipt": receipt.model_dump(mode="json", exclude={"result"}),
                "result_page": _receipt_result_page(receipt.result, result_path, offset, limit),
            }
        feedback = decision_feedback.list(receipt_id=receipt.receipt_id)
        return {
            "status": "found",
            "receipt": receipt.model_dump(mode="json"),
            "result": receipt.result,
            "feedback": [item.model_dump(mode="json") for item in feedback],
        }

    @mcp.tool()
    async def resolve_insight_sources(
        card_id: str,
        context: ContextSnapshot | None = None,
        response_mode: Annotated[
            ResponseMode,
            Field(description="Use compact for normal agent retrieval or full for exhaustive audit detail."),
        ] = "full",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Preview the bounded Jev-ranked evidence bundle for a stored card."""
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        if context_snapshot is None:
            context_snapshot = await context_for_card(card, None, principal)
        bundle = await authoring.resolve_bundle(
            card, context_snapshot, principal=principal
        )
        bundle_payload = bundle.model_dump(mode="json")
        return {
            "card": _evaluation_card(card),
            "bundle": _compact_bundle(bundle_payload)
            if response_mode == "compact"
            else bundle_payload,
            "response_mode": response_mode,
            "details_available": True,
        }

    @mcp.tool()
    async def review_insight_card(
        card_id: str,
        adapter: str | None = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=25,
                description="Maximum number of bounded authoring candidates (1-25).",
            ),
        ] = 10,
        response_mode: Annotated[
            ResponseMode,
            Field(description="Use compact for normal agent review or full for exhaustive audit detail."),
        ] = "full",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Review a draft's source coverage before a human approves it.

        This is an onboarding review, not an automatic policy change. It shows
        bounded Jev-ranked candidates, why they were surfaced, and which
        recommendations the draft omitted so a client-owned UI or agent can ask
        for confirmation or revise the card.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        assert_dynamic_review_scope(card, adapter)
        original = card.model_dump(mode="json")
        review = await authoring.review(
            card,
            adapter=adapter,
            limit=limit,
            principal=principal,
        )
        if get_scoped_card(card_id, principal).model_dump(mode="json") != original:
            raise ValueError("Card changed during review; review the current card before approval.")
        card = append_onboarding_review(card, review)
        runtime.card_store.save_card(card)
        review_payload = review.model_dump(mode="json")
        return {
            # The stored card carries the complete latest review for auditability.
            # Do not put that uncompact candidate packet back into the caller's
            # context when it explicitly requested the normal agent response.
            "card": (
                _compact_card(_evaluation_card(card))
                if response_mode == "compact"
                else _evaluation_card(card)
            ),
            "review": _compact_review(review_payload)
            if response_mode == "compact"
            else review_payload,
            "response_mode": response_mode,
            "details_available": True,
        }

    @mcp.tool()
    async def simulate_insight_card(
        card_id: str,
        context: ContextSnapshot | None = None,
        response_mode: Annotated[
            ResponseMode,
            Field(description="Use compact for structured agent evidence or full to include rendered markdown and raw snapshots."),
        ] = "full",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Evaluate a draft without treating the result as an approved push action."""
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        if context_snapshot is None:
            context_snapshot = await context_for_card(card, None, principal)
        evaluation_card, bundle = await prepare_insight_card(
            card, context_snapshot, principal=principal
        )
        run = await runtime.engine.evaluate(
            evaluation_card,
            context_override=context_snapshot,
            principal=principal,
        )
        result = run.result.model_copy(update={"retrieval": bundle})
        report = build_investigation_report(run.card, result, run.resources)
        response = {
            "status": "preview",
            "delivery_enabled": False,
            "card": (
                _compact_card(_evaluation_card(run.card))
                if response_mode == "compact"
                else _evaluation_card(run.card)
            ),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "retrieval": bundle.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "report_markdown": render_investigation_report(report),
        }
        if response_mode == "compact":
            response = _compact_simulation_response(response)
        response["response_mode"] = response_mode
        response["details_available"] = True
        return response

    @mcp.tool()
    async def preview_investigation_report(
        card_id: str,
        context: ContextSnapshot | None = None,
        response_mode: Annotated[
            ResponseMode,
            Field(description="Use compact for normal agent reports or full to include rendered markdown."),
        ] = "full",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Run a first analytical report before approving a recurring investigation.

        Uses the normal delivery-disabled simulation, real source adapters and Jev.
        The report exposes validated calculations, coverage, provenance and unresolved
        work. It never approves a card or certifies policy from one example. A caller
        should review this report, repair missing context, test other periods, and
        obtain owner authorization before scheduling evaluate_insight_card.
        """
        return await simulate_insight_card(
            card_id=card_id,
            context=context,
            response_mode=response_mode,
            ctx=ctx,
        )

    @mcp.tool()
    def record_insight_card_correction(
        card_id: str,
        kind: OnboardingCorrectionKind,
        source_ref: str | None = None,
        note: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Record caller-owned onboarding feedback without changing card policy.

        An external agent or knowledge graph can consume this append-only signal
        on a later onboarding attempt. SignalWeave does not silently alter the
        selected sources, thresholds, or delivery policy from feedback alone.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        correction = OnboardingCorrection(
            correction_id=f"correction-{uuid4().hex}",
            card_id=card.id,
            card_version=card.version,
            kind=OnboardingCorrectionKind(kind),
            source_ref=source_ref,
            note=note.strip(),
            principal_id=principal.principal_id if principal else None,
            principal_tenant=principal.tenant_id if principal else None,
        )
        updated = card.model_copy(
            update={"onboarding_corrections": [*card.onboarding_corrections, correction]}
        )
        runtime.card_store.save_card(updated)
        return {
            "status": "recorded",
            "correction": correction.model_dump(mode="json"),
            "card": updated.model_dump(mode="json"),
        }

    @mcp.tool()
    def record_decision_feedback(
        idempotency_key: str,
        kind: DecisionFeedbackKind,
        feedback_id: str | None = None,
        expected_outcome: str | None = None,
        expected_delivery_method_keys: list[str] | None = None,
        note: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Append an operator label to a completed decision receipt.

        Feedback is caller-owned evaluation data. It never changes a card,
        thresholds, Jev state, or delivery policy automatically.
        """
        principal = request_principal(ctx)
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        receipt = decision_receipts.get_by_idempotency_key(key)
        if receipt is None:
            raise ValueError("unknown decision receipt for idempotency_key")
        if receipt.status in {ReceiptStatus.PREPARED, ReceiptStatus.DECISION_DEFERRED}:
            raise ValueError("decision is not complete; feedback can be recorded after evaluation")
        card = get_scoped_card(receipt.card_id, principal)
        stable_feedback_id = feedback_id.strip() if feedback_id else None
        if feedback_id is not None and not stable_feedback_id:
            raise ValueError("feedback_id must not be empty")
        actor = principal.principal_id if principal else "mcp-client"
        expected_routes = expected_delivery_method_keys or []
        feedback = DecisionFeedback(
            feedback_id=stable_feedback_id or f"feedback-{uuid4().hex}",
            receipt_id=receipt.receipt_id,
            idempotency_key=receipt.idempotency_key,
            card_id=card.id,
            card_version=receipt.card_version,
            kind=DecisionFeedbackKind(kind),
            expected_outcome=Outcome(expected_outcome) if expected_outcome else None,
            expected_delivery_method_keys=expected_routes,
            note=note.strip(),
            actor=actor,
            principal_tenant=principal.tenant_id if principal else None,
            context_provider=receipt.context_provider,
            context_version=receipt.context_version,
        )
        comparable_fields = (
            "receipt_id",
            "idempotency_key",
            "card_id",
            "card_version",
            "kind",
            "context_provider",
            "context_version",
            "expected_outcome",
            "expected_delivery_method_keys",
            "note",
            "actor",
            "principal_tenant",
        )

        def replay_if_same(existing: DecisionFeedback | None) -> dict[str, Any] | None:
            if existing is None:
                return None
            if any(
                getattr(existing, field) != getattr(feedback, field)
                for field in comparable_fields
            ):
                raise ValueError("feedback_id is already bound to different feedback")
            return {
                "status": "replayed",
                "feedback": existing.model_dump(mode="json"),
                "receipt_id": receipt.receipt_id,
            }

        if stable_feedback_id:
            existing = decision_feedback.get(stable_feedback_id)
            replay = replay_if_same(existing)
            if replay is not None:
                return replay
        try:
            decision_feedback.save(feedback)
        except ValueError:
            if stable_feedback_id:
                replay = replay_if_same(decision_feedback.get(stable_feedback_id))
                if replay is not None:
                    return replay
            raise
        return {
            "status": "recorded",
            "feedback": feedback.model_dump(mode="json"),
            "receipt_id": receipt.receipt_id,
        }

    @mcp.tool()
    def list_decision_feedback(
        card_id: str | None = None,
        idempotency_key: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Read caller-owned labels for a card or one decision receipt."""
        principal = request_principal(ctx)
        if idempotency_key:
            receipt = decision_receipts.get_by_idempotency_key(idempotency_key.strip())
            if receipt is None:
                raise ValueError("unknown decision receipt for idempotency_key")
            scoped_card = get_scoped_card(receipt.card_id, principal)
            if card_id and card_id != scoped_card.id:
                raise ValueError("card_id does not match the decision receipt")
            card_id = scoped_card.id
            feedback = decision_feedback.list(idempotency_key=receipt.idempotency_key)
        elif card_id:
            scoped_card = get_scoped_card(card_id, principal)
            feedback = decision_feedback.list(card_id=scoped_card.id)
        else:
            if principal is not None:
                raise ValueError("card_id or idempotency_key is required for a scoped request")
            feedback = decision_feedback.list()
        return {
            "feedback": [item.model_dump(mode="json") for item in feedback],
            "count": len(feedback),
        }

    @mcp.tool()
    async def approve_insight_card(
        card_id: str,
        actor: str = "mcp-client",
        adapter: str | None = None,
        source_selection_fingerprint: str | None = None,
        source_selection_reason: str | None = None,
        use_current_source_selection_review: bool = False,
        source_scope_confirmations: dict[str, str] | None = None,
        dynamic_scope_acknowledged: bool = False,
        workflow_report_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Approve only after explicit owner review and a delivery-disabled simulation.

        For a fixed card with no dynamic investigation, an owner may confirm its
        exact selected sources despite duplicate titles or omitted recommendations. A
        source-owned comparison contract is still required for automatic notify or
        escalate routes; owner prose cannot create a missing window, comparison key,
        population, or grain. For a card that explicitly requests bounded related-source
        retrieval or investigation, pass dynamic_scope_acknowledged=true alongside the
        current review fingerprint and owner reason. This acknowledges the bounded runtime
        expansion; it does not authorize unbounded discovery. These confirmations do not
        override a source that declares an incompatible window, source health, permissions,
        or runtime evidence-quality gates.
        Pass the same optional adapter scope used by review_insight_card, plus its
        source_selection_fingerprint and the owner's
        source_selection_reason explaining which definitions/populations were chosen
        and why. Changed policy/catalog invalidates that confirmation. This cannot
        override source health, permissions, missing policy or other blockers.
        Clients that have just reviewed the current card may set
        use_current_source_selection_review=true and provide the owner reason
        instead of copying the opaque fingerprint. The server binds approval to
        the current stored review and still revalidates its fingerprint against
        the current catalog; this is a convenience for agents and does not waive
        any blocker or owner confirmation.
        If the review lists selected source scopes, also pass
        source_scope_confirmations with the exact declared scope text by source ref.
        This makes the scope decision auditable; it does not make an incompatible
        population safe.
        Feedback corrections alone never approve or resolve a card.
        Pass a successful acceptance-mode evaluate_card_workflow report as
        workflow_report_id to bind approval to tested policy, sources, plan and
        endpoints. Without it this is owner authorization only, not certification.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        assert_dynamic_review_scope(card, adapter)
        if use_current_source_selection_review:
            if source_selection_fingerprint is not None:
                raise ValueError(
                    "Do not pass source_selection_fingerprint when "
                    "use_current_source_selection_review=true."
                )
            current_review = card.onboarding_review
            if current_review is None or not current_review.source_selection_fingerprint:
                raise ValueError(
                    "No current source-selection review is stored. Call "
                    "review_insight_card before using use_current_source_selection_review."
                )
            source_selection_fingerprint = current_review.source_selection_fingerprint
        original = card.model_dump(mode="json")
        if not card.sources:
            raise ValueError("an insight card needs at least one selected source before approval")
        acceptance_record = None
        if workflow_report_id is not None:
            acceptance_record = certification_reports.get(workflow_report_id)
            report = acceptance_record.report
            if (acceptance_record.kind != "card_workflow"
                    or acceptance_record.subject_id != card.id
                    or acceptance_record.tenant_id != (card.principal_tenant or (principal.tenant_id if principal else "deployment"))
                    or acceptance_record.subject_version != str(card.version)
                    or acceptance_record.status != "approved"
                    or report.get("acceptance_passed") is not True
                    or not has_current_evidence_admission_policy(report)
                    or report.get("card_execution_digests", {}).get(card.id) != card_acceptance_digest(card)):
                raise ValueError("Workflow acceptance report is failed, stale, outside this card/tenant, "
                                 "or not an acceptance test. Replay owner-labeled setup cases for the "
                                 "current card with evaluate_card_workflow(acceptance_outcomes=...).")
        # Approval must revalidate the same bounded catalog view used by the
        # caller's review. Without this, a review scoped to one connector and
        # approval scoped to the whole registry produce different fingerprints
        # even when the selected source and card are unchanged.
        onboarding_review = await authoring.review(
            card, adapter=adapter, principal=principal
        )
        if source_selection_fingerprint is not None or source_selection_reason is not None:
            reason = (source_selection_reason or "").strip()
            if not source_selection_fingerprint or not reason or len(reason) > 4000:
                raise ValueError("Provide both source_selection_fingerprint and a nonempty "
                                 "source_selection_reason (at most 4000 characters).")
            dynamic_scope = (card.retrieval_mode != RetrievalMode.FIXED
                             or card.investigation_mode != InvestigationMode.NONE)
            if dynamic_scope and not dynamic_scope_acknowledged:
                raise ValueError(
                    "Dynamic source-selection confirmation requires dynamic_scope_acknowledged=true. "
                    "The owner must explicitly acknowledge bounded runtime related-source retrieval; "
                    "unbounded discovery is never authorized."
                )
            previous = card.onboarding_review
            if (previous is None or not hmac.compare_digest(
                    source_selection_fingerprint, previous.source_selection_fingerprint)
                    or not hmac.compare_digest(source_selection_fingerprint,
                                               onboarding_review.source_selection_fingerprint)):
                raise ValueError("Source selection review is stale or missing. Call review_insight_card "
                                 "and obtain owner confirmation of the current policy and catalog.")
            confirmable = {OnboardingBlockerCode.DEFINITION_CONFLICT,
                           OnboardingBlockerCode.CANDIDATE_SELECTION_REVIEW}
            scoped_sources = expected_source_scope_confirmations(onboarding_review)
            if scoped_sources:
                supplied_scopes = source_scope_confirmations or {}
                if supplied_scopes != scoped_sources:
                    raise ValueError(
                        "Selected sources declare population scopes. Provide exact "
                        "source_scope_confirmations for every selected scoped source "
                        "from review_insight_card; this is an explicit owner-review record."
                    )
                confirmable.add(OnboardingBlockerCode.SOURCE_SCOPE_REVIEW)
            # An expand/investigate card intentionally delegates a bounded
            # related-source search to SignalWeave at run time.  When the
            # owner has supplied and revalidated an explicit anchor, the
            # catalog-pagination warning is exactly what
            # ``dynamic_scope_acknowledged`` is meant to acknowledge.  Do not
            # extend this exception to cards without an anchor: those still
            # need a source selected from an authorized discovery result.
            dynamic_scope = (
                card.retrieval_mode != RetrievalMode.FIXED
                or card.investigation_mode != InvestigationMode.NONE
            )
            if dynamic_scope and card.sources:
                confirmable.add(OnboardingBlockerCode.CATALOG_INCOMPLETE)
            resolved = [
                blocker for blocker in onboarding_review.blockers
                if blocker.code in confirmable
            ]
            remaining = [b for b in onboarding_review.blockers if b not in resolved]
            if resolved:
                remaining_questions = [q for q in onboarding_review.questions
                                       if q not in {b.question for b in resolved}]
                blocking = any(b.severity.value == "block" for b in remaining)
                needs_review = any(b.severity.value == "review" for b in remaining)
                onboarding_review = onboarding_review.model_copy(update={
                    "blockers": remaining, "questions": remaining_questions,
                    "status": "needs_human_input" if remaining_questions else "ready_for_approval",
                    "readiness_status": "blocked" if blocking else "needs_human_review"
                    if needs_review else "ready_for_approval",
                    "source_selection_confirmation": reason,
                    "source_scope_confirmations": (
                        dict(source_scope_confirmations or {}) if scoped_sources else {}
                    ),
                    "confirmed_blocker_codes": [b.code for b in resolved],
                })
        if onboarding_review.readiness_status != "ready_for_approval":
            codes = ", ".join(blocker.code.value for blocker in onboarding_review.blockers)
            raise ValueError(
                "insight card is not ready for approval; resolve onboarding blockers: "
                + (codes or "human review required")
                + ". Call review_insight_card for evidence. For an owner-confirmed fixed source "
                "selection (investigation_mode=none), pass its source_selection_fingerprint "
                "and source_selection_reason. Other blockers must be repaired, not acknowledged."
            )
        card = append_onboarding_review(card, onboarding_review)
        if card.compiled_plan is None:
            plan = await runtime.engine.compile(card)
            card = card.model_copy(update={"compiled_plan": plan})
        if get_scoped_card(card_id, principal).model_dump(mode="json") != original:
            raise ValueError("Card changed during approval; review and simulate the current card "
                             "and obtain its owner's approval again.")
        runtime.card_store.save_card(card)
        approved = runtime.card_store.set_card_status(card_id, InsightCardStatus.APPROVED)
        approved = approved.model_copy(
            update={
                "approved_by": principal.principal_id if principal else actor,
                "approved_at": datetime.now(timezone.utc),
            }
        )
        runtime.card_store.save_card(approved)
        return {
            "status": approved.status.value,
            "card": _evaluation_card(approved),
            "onboarding_review": onboarding_review.model_dump(mode="json"),
            "workflow_acceptance": {
                "status": "passed" if acceptance_record else "unassessed",
                "report_id": acceptance_record.report_id if acceptance_record else None,
                "human_authorization_required": True,
            },
        }

    @mcp.tool()
    def list_insight_cards(
        status: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        """List stored cards for a client-owned UI or agent."""
        principal = request_principal(ctx)
        selected_status = InsightCardStatus(status) if status else None
        cards = [
            card
            for card in runtime.card_store.list_cards()
            if principal is None or card.principal_tenant == principal.tenant_id
            if selected_status is None or card.status == selected_status
        ]
        return {
            "cards": [card.model_dump(mode="json") for card in cards],
            "count": len(cards),
        }

    @mcp.tool()
    def get_insight_card(
        card_id: str,
        include_history: bool = False,
        response_mode: Annotated[
            ResponseMode,
            Field(description="Use compact for normal agent reads or full for the complete stored review packet."),
        ] = default_card_response_mode,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Return active policy and plan by stable ID.

        Compact reads of approved cards omit the discovery review packet; use
        response_mode="full" to inspect it. Set include_history=true in full
        mode for prior reviews and correction audit records.
        """
        principal = request_principal(ctx)
        if include_history and response_mode == "compact":
            raise ValueError("include_history=true requires response_mode='full'")
        payload = get_scoped_card(card_id, principal).model_dump(
            mode="json",
            exclude=set() if include_history else {"onboarding_review_history", "onboarding_corrections"},
        )
        if response_mode == "compact":
            return {
                **_compact_card(payload),
                "response_mode": response_mode,
                "details_available": True,
            }
        return payload

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    async def prepare_insight_run(
        card_id: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Fetch exact approved sources without making a Jev decision.

        This source-only handoff is an advanced alternative for a caller that
        intentionally owns the decision step. The normal recurring-card path
        is evaluate_insight_card, which applies the approved policy with Jev.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        if card.status != InsightCardStatus.APPROVED:
            raise ValueError("prepare_insight_run requires an owner-approved card")
        if card.retrieval_mode != RetrievalMode.FIXED or card.investigation_mode != InvestigationMode.NONE:
            raise ValueError(
                "prepare_insight_run supports fixed card sources only; set retrieval_mode=fixed "
                "and investigation_mode=none, then explicitly include every source the agent needs"
            )
        if not card.sources:
            raise ValueError("prepare_insight_run requires at least one approved card source")

        resources = await runtime.sources.resolve(
            card.sources,
            authorized_tenants=[principal.tenant_id] if principal else None,
        )
        payloads = [resource.model_dump(mode="json") for resource in resources]
        errors = [
            {"source_key": resource.source_key, "error": resource.error}
            for resource in resources
            if resource.error
        ]
        return {
            "status": "partial" if errors else "fetched",
            "run_id": str(uuid4()),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "card": _evaluation_card(card),
            "sources": payloads,
            "source_count": len(payloads),
            "source_errors": errors,
            "persisted": False,
            "jev_used": False,
            "decision_made": False,
            "delivery_enabled": False,
            "agent_contract": (
                "Analyze only the returned source evidence in the context of the card. Separate "
                "observations from hypotheses; verify source health, freshness, definition, and "
                "comparison period, and state missing or conflicting evidence. A fetched source "
                "is not proof that the requested analysis is complete. Do not claim causation from "
                "correlation alone. The calling agent owns any follow-up queries, schedule, and delivery."
            ),
        }

    @mcp.resource("insight://catalog")
    def insight_catalog(ctx: Context | None = None) -> str:
        """Human-readable catalog for an MCP client."""
        principal = request_principal(ctx)
        return json.dumps(
            {
                "cards": [
                    card.model_dump(mode="json")
                    for card in runtime.card_store.list_cards()
                    if principal is None or card.principal_tenant == principal.tenant_id
                ]
            },
            indent=2,
        )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        """Small liveness endpoint for a container or scheduler."""
        return JSONResponse(
            {
                "status": "ok",
                "service": "signal-weave",
                "source_adapters": runtime.sources.adapter_names(),
            }
        )

    @mcp.custom_route("/readyz", methods=["GET"])
    async def readyz(request: Request) -> JSONResponse:
        """Report startup readiness without requiring a secret-bearing token."""
        del request
        report = deployment_readiness(
            runtime,
            request_scoped_principal=bool(http_principal_resolver or principal_resolver),
            profile=profile,
        )
        return JSONResponse(report, status_code=200 if report["startup_ready"] else 503)

    async def evaluate_webhook(request: Request) -> JSONResponse:
        """Push-triggered card evaluation endpoint for schedulers and source alerts."""
        if http_principal_resolver is None:
            expected_token = load_deployment_secret("PUSH_WEBHOOK_TOKEN")
            if not expected_token:
                return JSONResponse(
                    {"error": "push webhook authentication is not configured"}, status_code=503
                )
            if not hmac.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {expected_token}"
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            max_body_bytes = int(os.getenv("SIGNALWEAVE_MAX_HTTP_BODY_BYTES", "1048576"))
        except ValueError:
            max_body_bytes = 1048576
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse({"error": "invalid content-length"}, status_code=400)
            if declared_length > max_body_bytes:
                return JSONResponse({"error": "request body is too large"}, status_code=413)
        body = await request.body()
        if len(body) > max_body_bytes:
            return JSONResponse({"error": "request body is too large"}, status_code=413)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "request body must be valid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)
        card_id = payload.get("card_id")
        if not card_id:
            return JSONResponse({"error": "card_id is required"}, status_code=400)
        idempotency_key = payload.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return JSONResponse(
                {"error": "idempotency_key is required for push evaluation"}, status_code=400
            )
        try:
            principal = (
                http_principal_resolver() if http_principal_resolver else runtime.principal
            )
        except RuntimeError:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if principal is None:
            return JSONResponse(
                {"error": "push webhook principal is not configured"}, status_code=503
            )
        actor = principal.principal_id
        try:
            context = (
                ContextSnapshot.model_validate(payload["context"]).model_copy(
                    update={"trust": "unverified"}
                )
                if payload.get("context")
                else None
            )
            result = await evaluate_approved_card(
                card_id,
                idempotency_key=str(idempotency_key),
                actor=actor,
                context=context,
                principal=principal,
                parent_receipt_id=(
                    str(payload["parent_receipt_id"])
                    if payload.get("parent_receipt_id")
                    else None
                ),
                workflow_step_key=(
                    str(payload["workflow_step_key"])
                    if payload.get("workflow_step_key")
                    else None
                ),
            )
        except (KeyError, ValueError) as error:
            message = str(error)
            status_code = 409 if "draft" in message or "already being evaluated" in message else 404
            return JSONResponse({"error": str(error)}, status_code=status_code)
        return JSONResponse(result)

    if profile == "full":
        mcp.custom_route("/webhooks/evaluate", methods=["POST"])(evaluate_webhook)
    else:
        for tool in mcp._tool_manager.list_tools():
            if tool.name not in AGENT_PROFILE_TOOLS:
                mcp.remove_tool(tool.name)

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.
