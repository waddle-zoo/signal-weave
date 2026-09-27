"""Run the real Preset -> onboarding -> Jev shadow path.

This command intentionally requires a customer-authorized Preset environment
and a TypeSafe key. It is not a fixture benchmark and it does not assert an
expected business outcome. It proves that a human can describe a monitoring
goal, review the returned card, explicitly approve it, and obtain a durable
delivery-disabled Jev receipt from the hosted Preset evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from signalweave.mcp_server import create_mcp
from signalweave.preset_adapter import PresetAdapter
from signalweave.runtime import build_runtime


def _tool(server: Any, name: str) -> Any:
    """Use the same registered MCP tool functions as the deployment test suite."""

    return server._tool_manager.get_tool(name).fn


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    receipt = payload.get("receipt") or {}
    return {
        "card_id": payload.get("card", {}).get("id"),
        "outcome": result.get("outcome"),
        "confidence": result.get("confidence"),
        "evaluator": result.get("evaluator"),
        "evidence_count": len(result.get("evidence") or []),
        "observation_count": len(result.get("observations") or []),
        "receipt_id": receipt.get("receipt_id"),
        "receipt_status": receipt.get("status"),
        "delivery_enabled": receipt.get("delivery_enabled"),
        "replayed": payload.get("replayed"),
        "resource_count": len(payload.get("resources") or []),
    }


def _path_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Return positive provider-attempt deltas without exposing request data."""

    return {
        path: count - before.get(path, 0)
        for path, count in after.items()
        if count - before.get(path, 0) > 0
    }


def _canonical_digest(value: Any) -> str:
    """Hash a review artifact without depending on JSON formatting."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _provider_secret_values(client: Any) -> set[str]:
    """Read secret values only for an in-memory redaction assertion.

    The Preset API-token name is an identifier, not a secret.  Including it
    would make redaction checks report false positives for ordinary JSON keys
    or prose containing a short/common token name.
    """

    values: set[str] = set()
    for attribute in ("_api_token_secret", "_token"):
        value = getattr(client, attribute, None)
        if isinstance(value, str) and value:
            values.add(value)
    return values


def _provider_workspace_origin(client: Any) -> str:
    """Return the configured provider origin used by the current adapter."""

    origin = getattr(client, "base_url", None)
    if not isinstance(origin, str) or not origin:
        raise RuntimeError("the live acceptance trial requires a Preset workspace origin")
    return origin.rstrip("/")


def _secrets_absent(value: Any, secrets: set[str]) -> bool:
    """Prove serialized MCP artifacts do not contain loaded provider secrets."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return all(secret not in serialized for secret in secrets)


def _validate_reviewed_credential_proof(
    report: dict[str, Any], secrets: set[str]
) -> None:
    """Recompute credential loading and redaction against the current runtime.

    A draft is an operator-reviewed input, not a trusted source of transport
    facts.  In particular, approval must not succeed because an edited JSON
    artifact says credentials were loaded and redacted.  The current adapter
    must have a credential, and the complete reviewed artifact must still be
    free of that credential.
    """

    checks = report.get("provider_checks")
    if not isinstance(checks, dict):
        raise RuntimeError("reviewed draft is missing provider credential proof")
    credentials_loaded = bool(secrets)
    if credentials_loaded is not True:
        raise RuntimeError("the current Preset runtime did not load provider credentials")
    if checks.get("provider_credentials_loaded") is not credentials_loaded:
        raise RuntimeError(
            "reviewed draft provider credential proof does not match the current runtime"
        )
    actual_redaction = _secrets_absent(report, secrets)
    if actual_redaction is not True:
        raise RuntimeError("reviewed draft contains a loaded Preset provider secret")
    if checks.get("provider_secrets_absent_from_artifacts") is not actual_redaction:
        raise RuntimeError(
            "reviewed draft provider redaction proof does not match the current artifact"
        )


def _validate_reviewed_workspace_binding(
    report: dict[str, Any], current_origin: str
) -> str:
    """Reject approval when the current Preset origin differs from the draft."""

    checks = report.get("provider_checks")
    if not isinstance(checks, dict):
        raise RuntimeError("reviewed draft is missing Preset provider checks")
    reviewed_origin = checks.get("provider_workspace_origin")
    if not isinstance(reviewed_origin, str) or not reviewed_origin:
        raise RuntimeError("draft does not identify the reviewed Preset workspace")
    if reviewed_origin != current_origin:
        raise RuntimeError(
            "the current Preset workspace origin no longer matches the reviewed draft; "
            "re-run onboarding and review the new artifact"
        )
    return reviewed_origin


def _data_policy_proof(source: Any, client: Any) -> tuple[dict[str, Any], bool | None]:
    """Capture the configured Preset policy without exposing provider secrets."""

    policy = getattr(source, "policy", None)
    if policy is None or not hasattr(policy, "model_dump"):
        raise RuntimeError("the live acceptance trial requires Preset data-policy telemetry")
    data_policy = policy.model_dump(mode="json")
    if not isinstance(data_policy, dict):
        raise RuntimeError("Preset data-policy telemetry must be a mapping")
    return data_policy, getattr(client, "_force_refresh", None)


def _validate_data_policy_proof(checks: dict[str, Any]) -> None:
    """Ensure the reported query mode matches the configured Preset policy."""

    policy = checks.get("data_policy")
    force_refresh = checks.get("provider_force_refresh")
    if not isinstance(policy, dict):
        raise RuntimeError("draft is missing Preset data-policy telemetry")
    mode = policy.get("mode")
    if mode == "metadata_only":
        raise RuntimeError("metadata_only policy cannot satisfy a chart-data shadow")
    if mode == "cached_results":
        if force_refresh is not False:
            raise RuntimeError("cached_results policy did not prove force=false")
        if policy.get("allow_live_queries") is not False or policy.get("allow_refresh") is not False:
            raise RuntimeError("cached_results policy has live execution permissions enabled")
    if mode == "live_query":
        if force_refresh is not True:
            raise RuntimeError("live_query policy did not prove force=true")
        if policy.get("allow_live_queries") is not True or policy.get("allow_refresh") is not True:
            raise RuntimeError("live_query policy is missing explicit execution permissions")
    if mode not in {"cached_results", "live_query"}:
        raise RuntimeError(f"unsupported Preset data-policy mode: {mode!r}")
    maximums = {"max_result_rows": 10_000, "max_snapshot_bytes": 10_000_000}
    for key, maximum in maximums.items():
        value = policy.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            raise RuntimeError(f"Preset data-policy bound is invalid: {key}")


def _validate_approval_draft(report: dict[str, Any]) -> None:
    """Reject a draft artifact whose transport proof was edited after review."""

    if report.get("approval_requested") is not False:
        raise RuntimeError("approval input must be an unapproved onboarding draft")
    if report.get("passed") is True:
        raise RuntimeError("approval input must not already claim acceptance")
    if any(key in report for key in ("approval", "evaluation", "summary", "replay")):
        raise RuntimeError("approval input must not contain post-approval artifacts")
    onboarding = report.get("onboarding")
    if not isinstance(onboarding, dict) or onboarding.get("status") != "ready_for_approval":
        raise RuntimeError("only a ready_for_approval draft can be approved")
    if onboarding.get("approval_required") is not True:
        raise RuntimeError("draft does not require explicit approval")
    if onboarding.get("delivery_enabled") is not False:
        raise RuntimeError("draft enables delivery")
    checks = report.get("provider_checks")
    if not isinstance(checks, dict):
        raise RuntimeError("draft is missing provider transport checks")
    if checks.get("provider_transport_used") is not True:
        raise RuntimeError("draft does not prove that Preset transport was used")
    if not isinstance(checks.get("provider_workspace_origin"), str) or not checks[
        "provider_workspace_origin"
    ]:
        raise RuntimeError("draft does not identify the reviewed Preset workspace")
    if checks.get("provider_credentials_loaded") is not True:
        raise RuntimeError("draft does not prove that Preset credentials were loaded")
    if checks.get("provider_secrets_absent_from_artifacts") is not True:
        raise RuntimeError("draft does not prove provider secrets stayed out of artifacts")
    _validate_data_policy_proof(checks)
    request_count = checks.get("provider_requests_for_onboarding")
    if not isinstance(request_count, int) or request_count < 1:
        raise RuntimeError("draft has no recorded Preset onboarding request")
    catalog_count = checks.get("provider_catalog_searches_for_onboarding")
    if not isinstance(catalog_count, int) or not 1 <= catalog_count <= 21:
        raise RuntimeError("draft has invalid Preset catalog search fan-out")
    before = checks.get("provider_request_paths_before_onboarding")
    after = checks.get("provider_request_paths_after_onboarding")
    delta = checks.get("provider_request_paths_for_onboarding")
    if not all(isinstance(paths, dict) for paths in (before, after, delta)):
        raise RuntimeError("draft is missing Preset request path telemetry")
    if _path_delta(before, after) != delta:
        raise RuntimeError("draft Preset request path telemetry is inconsistent")
    if sum(delta.values()) != request_count:
        raise RuntimeError("draft Preset request count disagrees with path telemetry")
    if delta.get("/api/v1/dashboard/", 0) != catalog_count:
        raise RuntimeError("draft catalog search count disagrees with path telemetry")


def _load_reviewed_draft(path: Path) -> dict[str, Any]:
    """Load the exact draft artifact that a human is approving."""

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError(f"could not read the onboarding draft report: {path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"onboarding draft report is not valid JSON: {path}") from error
    if not isinstance(report, dict):
        raise RuntimeError("onboarding draft report must be a JSON object")
    if report.get("trial") != "preset-live-onboarding-shadow":
        raise RuntimeError("approval report is not a Preset onboarding shadow draft")
    if report.get("approval_requested") is True:
        raise RuntimeError("approval report has already been used for an approval run")
    if report.get("passed") is True or "evaluation" in report:
        raise RuntimeError("approval report already contains post-approval artifacts")
    onboarding = report.get("onboarding")
    if not isinstance(onboarding, dict):
        raise RuntimeError("approval report does not contain an onboarding draft")
    card = onboarding.get("card")
    if not isinstance(card, dict) or not isinstance(card.get("id"), str):
        raise RuntimeError("approval report does not contain a persisted card draft")
    if onboarding.get("status") != "ready_for_approval":
        raise RuntimeError("only a ready_for_approval draft can be approved")
    _validate_approval_draft(report)
    request = report.get("request")
    if not isinstance(request, dict):
        raise RuntimeError("approval report does not contain the original request")
    return report


def _resolve_preset_adapter(runtime: Any, requested: str | None) -> str:
    """Resolve a configured Preset route without assuming its connection ID."""

    names = runtime.sources.adapter_names()
    if requested:
        if requested not in names:
            raise RuntimeError(
                f"adapter {requested!r} is not installed; available adapters: "
                + ", ".join(names)
            )
        candidates = [requested]
    else:
        candidates = [
            name
            for name in names
            if isinstance(runtime.sources._get(name), PresetAdapter)
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "live Preset acceptance requires exactly one configured Preset adapter; "
                "pass --adapter when multiple hosted connections are installed"
            )
    if not isinstance(runtime.sources._get(candidates[0]), PresetAdapter):
        raise RuntimeError(
            f"{candidates[0]!r} is not a hosted Preset adapter; use the Preset environment route"
        )
    return candidates[0]


async def run_trial(
    *,
    goal: str,
    why: str,
    adapter: str | None,
    limit: int,
    destination: str,
    approve: bool,
    output: Path | None = None,
    review_report: Path | None = None,
) -> dict[str, Any]:
    if not goal.strip() or not why.strip():
        raise ValueError("goal and why are required")
    runtime = build_runtime()
    if runtime.principal is None:
        raise RuntimeError(
            "the live acceptance trial requires SIGNALWEAVE_TENANT_ID and "
            "SIGNALWEAVE_PRINCIPAL_ID so the Preset workspace is tenant-scoped"
        )
    if getattr(runtime.engine.judger, "name", None) != "jev-latest":
        raise RuntimeError("the live acceptance trial must run with the jev-latest judger")
    adapter = _resolve_preset_adapter(runtime, adapter)
    reviewed_draft: dict[str, Any] | None = None
    reviewed_card: dict[str, Any] | None = None
    reviewed_data_policy: dict[str, Any] | None = None
    reviewed_provider_force_refresh: bool | None = None
    reviewed_provider_workspace_origin: str | None = None
    stored_card_payload: dict[str, Any] | None = None
    review_path = review_report or output
    if approve:
        if review_path is None:
            raise RuntimeError(
                "approval requires --output or --review-report pointing to the previously "
                "reviewed onboarding draft"
            )
        reviewed_draft = _load_reviewed_draft(review_path)
        request = reviewed_draft["request"]
        for key, current in (
            ("goal", goal),
            ("why", why),
            ("destination", destination),
            ("limit", limit),
        ):
            if request.get(key) != current:
                raise RuntimeError(
                    f"approval request does not match the reviewed draft for {key!r}"
                )
        reviewed_card = reviewed_draft["onboarding"]["card"]
        if reviewed_draft.get("adapter") != adapter:
            raise RuntimeError("approval request does not match the reviewed Preset adapter")
        if reviewed_draft.get("tenant_id") != runtime.principal.tenant_id:
            raise RuntimeError("approval request does not match the reviewed tenant")
        try:
            stored_card = runtime.card_store.get_card(reviewed_card["id"])
        except (AttributeError, KeyError) as error:
            raise RuntimeError(
                "the reviewed card is not present in the configured card store; "
                "run approval against the same persistent store as the draft"
            ) from error
        stored_card_payload = stored_card.model_dump(mode="json")
        if _canonical_digest(reviewed_card) != _canonical_digest(stored_card_payload):
            raise RuntimeError(
                "the persisted card no longer matches the reviewed draft; "
                "re-run onboarding and review the new artifact"
            )
        if reviewed_card.get("version") != stored_card_payload.get("version"):
            raise RuntimeError("the persisted card version no longer matches the reviewed draft")
    preset_source = runtime.sources._get(adapter)
    provider_client = getattr(preset_source, "client", None)
    provider_workspace_origin = _provider_workspace_origin(provider_client)
    provider_secrets = _provider_secret_values(provider_client)
    if reviewed_draft is not None:
        reviewed_provider_workspace_origin = _validate_reviewed_workspace_binding(
            reviewed_draft, provider_workspace_origin
        )
        _validate_reviewed_credential_proof(reviewed_draft, provider_secrets)
    data_policy, provider_force_refresh = _data_policy_proof(preset_source, provider_client)
    _validate_data_policy_proof(
        {
            "data_policy": data_policy,
            "provider_force_refresh": provider_force_refresh,
        }
    )
    if reviewed_draft is not None:
        reviewed_checks = reviewed_draft.get("provider_checks")
        if not isinstance(reviewed_checks, dict):
            raise RuntimeError("reviewed draft is missing Preset provider checks")
        if not isinstance(reviewed_checks.get("data_policy"), dict):
            raise RuntimeError("reviewed draft is missing Preset data-policy telemetry")
        reviewed_data_policy = reviewed_checks["data_policy"]
        reviewed_provider_force_refresh = reviewed_checks.get("provider_force_refresh")
        if reviewed_checks.get("data_policy") != data_policy or reviewed_checks.get(
            "provider_force_refresh"
        ) != provider_force_refresh:
            raise RuntimeError(
                "configured Preset data policy no longer matches the reviewed draft; "
                "re-run onboarding and review the new artifact"
            )
    provider_requests_before = getattr(provider_client, "requests_made", None)
    if not isinstance(provider_requests_before, int):
        raise RuntimeError(
            "the live acceptance trial requires a Preset client with request telemetry"
        )
    provider_paths_before = getattr(provider_client, "request_path_counts", None)
    if provider_paths_before is not None and not isinstance(provider_paths_before, dict):
        raise RuntimeError("Preset request path telemetry must be a mapping")
    if isinstance(provider_paths_before, dict):
        provider_paths_before = dict(provider_paths_before)
    server = create_mcp(runtime)
    if reviewed_card is None:
        onboarding = await _tool(server, "onboard_insight_card")(
            what_to_watch=goal,
            why_watch=why,
            adapter=adapter,
            limit=limit,
            title=goal[:120],
            delivery_methods=[
                {
                    "key": "owner-review",
                    "outcome": "notify",
                    "label": "Owner review",
                    "destination": destination,
                    "instructions": "Send the evidence bundle to the existing owner workflow.",
                }
            ],
        )
    else:
        # Approval must operate on the persisted draft the operator reviewed;
        # it must not silently create and approve a second discovery result.
        onboarding = reviewed_draft["onboarding"]
    provider_requests_after_onboarding = getattr(provider_client, "requests_made", None)
    provider_paths_after_onboarding = getattr(provider_client, "request_path_counts", None)
    if isinstance(provider_paths_after_onboarding, dict):
        provider_paths_after_onboarding = dict(provider_paths_after_onboarding)
    provider_paths_for_onboarding = (
        _path_delta(provider_paths_before, provider_paths_after_onboarding)
        if isinstance(provider_paths_before, dict)
        and isinstance(provider_paths_after_onboarding, dict)
        else {}
    )
    provider_catalog_searches_for_onboarding = provider_paths_for_onboarding.get(
        "/api/v1/dashboard/", 0
    )
    provider_requests_for_onboarding = (
        provider_requests_after_onboarding - provider_requests_before
        if isinstance(provider_requests_after_onboarding, int)
        else None
    )
    if reviewed_draft is not None:
        # The approval process intentionally does not rerun onboarding. Carry
        # forward the first run's non-secret transport proof instead of
        # pretending that a second process observed those requests.
        prior_checks = reviewed_draft["provider_checks"]
        provider_requests_before = prior_checks.get(
            "provider_requests_before_onboarding"
        )
        provider_requests_after_onboarding = prior_checks.get(
            "provider_requests_after_onboarding"
        )
        provider_requests_for_onboarding = prior_checks.get(
            "provider_requests_for_onboarding"
        )
        provider_paths_before = prior_checks.get("provider_request_paths_before_onboarding")
        provider_paths_after_onboarding = prior_checks.get(
            "provider_request_paths_after_onboarding"
        )
        provider_paths_for_onboarding = prior_checks.get(
            "provider_request_paths_for_onboarding",
            _path_delta(
                provider_paths_before, provider_paths_after_onboarding
            )
            if isinstance(provider_paths_before, dict)
            and isinstance(provider_paths_after_onboarding, dict)
            else {},
        )
        provider_catalog_searches_for_onboarding = prior_checks.get(
            "provider_catalog_searches_for_onboarding",
            provider_paths_for_onboarding.get("/api/v1/dashboard/", 0)
            if isinstance(provider_paths_for_onboarding, dict)
            else 0,
        )
    report: dict[str, Any] = {
        "trial": "preset-live-onboarding-shadow",
        "adapter": adapter,
        "tenant_id": runtime.principal.tenant_id if runtime.principal else None,
        "request": {
            "goal": goal,
            "why": why,
            "destination": destination,
            "limit": limit,
        },
        "onboarding": onboarding,
        "approval_requested": approve,
        "provider_checks": {
            "provider_requests_before_onboarding": provider_requests_before,
            "provider_requests_after_onboarding": provider_requests_after_onboarding,
            "provider_requests_for_onboarding": provider_requests_for_onboarding,
            "provider_transport_used": (
                isinstance(provider_requests_for_onboarding, int)
                and provider_requests_for_onboarding > 0
            ),
            "provider_path_telemetry_available": isinstance(provider_paths_after_onboarding, dict),
            "provider_request_paths_before_onboarding": provider_paths_before,
            "provider_request_paths_after_onboarding": provider_paths_after_onboarding,
            "provider_request_paths_for_onboarding": provider_paths_for_onboarding,
            "provider_catalog_searches_for_onboarding": provider_catalog_searches_for_onboarding,
            "provider_workspace_origin": provider_workspace_origin,
            "provider_credentials_loaded": bool(provider_secrets),
            "provider_secrets_absent_from_artifacts": _secrets_absent(
                {"onboarding": onboarding}, provider_secrets
            ),
            "data_policy": data_policy,
            "provider_force_refresh": provider_force_refresh,
        },
        "passed": False,
        "not_proven": [
            "business usefulness or correctness without operator labels",
            "provider permission coverage beyond the sources selected by this card",
            "production delivery reliability or autonomous side effects",
            "managed SignalWeave hosting",
        ],
    }
    if reviewed_card is not None and stored_card_payload is not None:
        report["approval_basis"] = {
            "review_report": str(review_path),
            "card_id": reviewed_card["id"],
            "card_version": reviewed_card.get("version"),
            "reviewed_card_digest": _canonical_digest(reviewed_card),
            "stored_card_digest": _canonical_digest(stored_card_payload),
            "exact_draft_reused": True,
            "reviewed_data_policy": reviewed_data_policy,
            "reviewed_provider_force_refresh": reviewed_provider_force_refresh,
            "reviewed_provider_workspace_origin": reviewed_provider_workspace_origin,
            "current_provider_workspace_origin": provider_workspace_origin,
            "provider_workspace_unchanged": (
                reviewed_provider_workspace_origin == provider_workspace_origin
            ),
            "current_data_policy_digest": _canonical_digest(data_policy),
            "reviewed_data_policy_digest": _canonical_digest(reviewed_data_policy),
            "data_policy_unchanged": (
                reviewed_data_policy == data_policy
                and reviewed_provider_force_refresh == provider_force_refresh
            ),
        }
    if not approve:
        report["next_action"] = (
            "review the onboarding response, then rerun with --approve "
            "or make preset-live-trial-approve"
        )
    else:
        card_id = onboarding["card"]["id"]
        onboarding_contract = {
            "approval_required": onboarding.get("approval_required") is True,
            "delivery_disabled": onboarding.get("delivery_enabled") is False,
        }
        if onboarding["status"] != "ready_for_approval":
            report["next_action"] = "resolve the onboarding blockers before approval"
        else:
            provider_requests_before_evaluation = getattr(provider_client, "requests_made", None)
            provider_paths_before_evaluation = getattr(provider_client, "request_path_counts", None)
            if isinstance(provider_paths_before_evaluation, dict):
                provider_paths_before_evaluation = dict(provider_paths_before_evaluation)
            if not isinstance(provider_paths_before_evaluation, dict):
                raise RuntimeError(
                    "approved Preset acceptance requires request path telemetry"
                )
            approved = await _tool(server, "approve_insight_card")(
                card_id, actor="preset-shadow-owner"
            )
            idempotency_key = f"preset-shadow:{card_id}:v{approved['card']['version']}"
            metrics = getattr(getattr(runtime.engine, "judger", None), "metrics", None)
            jev_requests_before = getattr(metrics, "requests", None)
            evaluation = await _tool(server, "evaluate_insight_card")(
                card_id,
                idempotency_key=idempotency_key,
                actor="preset-shadow-scheduler",
            )
            jev_requests_after_first = getattr(metrics, "requests", None)
            provider_requests_after_first = getattr(provider_client, "requests_made", None)
            provider_paths_after_first = getattr(provider_client, "request_path_counts", None)
            if not isinstance(provider_paths_after_first, dict):
                raise RuntimeError("Preset request path telemetry disappeared during evaluation")
            provider_paths_after_first = dict(provider_paths_after_first)
            provider_paths_for_first_evaluation = _path_delta(
                provider_paths_before_evaluation, provider_paths_after_first
            )
            provider_requests_for_first_evaluation = (
                provider_requests_after_first - provider_requests_before_evaluation
                if isinstance(provider_requests_after_first, int)
                and isinstance(provider_requests_before_evaluation, int)
                else None
            )
            provider_data_requests_for_first_evaluation = sum(
                count
                for path, count in provider_paths_for_first_evaluation.items()
                if path.endswith("/data")
            )
            provider_paths_before_replay = dict(provider_paths_after_first)
            replay = await _tool(server, "evaluate_insight_card")(
                card_id,
                idempotency_key=idempotency_key,
                actor="preset-shadow-scheduler",
            )
            jev_requests_after_replay = getattr(metrics, "requests", None)
            provider_paths_after_replay = getattr(provider_client, "request_path_counts", None)
            if isinstance(provider_paths_after_replay, dict):
                provider_paths_after_replay = dict(provider_paths_after_replay)
            replay_made_no_provider_call = (
                isinstance(provider_paths_after_replay, dict)
                and provider_paths_after_replay == provider_paths_before_replay
            )
            receipt_lookup = _tool(server, "get_decision_receipt")(
                idempotency_key=idempotency_key
            )
            summary = _summary(evaluation)
            resources = evaluation.get("resources") or []
            preset_resources = [item for item in resources if item.get("adapter") == adapter]
            tenant_scoped_resources = bool(resources) and all(
                item.get("contract", {}).get("tenant_id") == runtime.principal.tenant_id
                for item in resources
            )
            replay_made_no_jev_call = (
                jev_requests_before is not None
                and jev_requests_after_first is not None
                and jev_requests_after_replay is not None
                and jev_requests_after_replay == jev_requests_after_first
            )
            jev_requests_for_first_evaluation = (
                jev_requests_after_first - jev_requests_before
                if jev_requests_before is not None and jev_requests_after_first is not None
                else None
            )
            report.update(
                {
                    "approval": {
                        "status": approved["status"],
                        "card_version": approved["card"]["version"],
                    },
                    "evaluation": evaluation,
                    "summary": summary,
                    "replay": replay,
                    "receipt_lookup": receipt_lookup,
                    "provider_checks": {
                        "onboarding_contract": onboarding_contract,
                        "provider_requests_before_onboarding": provider_requests_before,
                        "provider_requests_after_onboarding": provider_requests_after_onboarding,
                        "provider_requests_for_onboarding": provider_requests_for_onboarding,
                        "provider_path_telemetry_available": True,
                        "provider_request_paths_before_onboarding": provider_paths_before,
                        "provider_request_paths_after_onboarding": provider_paths_after_onboarding,
                        "provider_request_paths_for_onboarding": provider_paths_for_onboarding,
                        "provider_catalog_searches_for_onboarding": provider_catalog_searches_for_onboarding,
                        "provider_workspace_origin": provider_workspace_origin,
                        "provider_request_paths_before_first_evaluation": provider_paths_before_evaluation,
                        "provider_request_paths_after_first_evaluation": provider_paths_after_first,
                        "provider_request_paths_for_first_evaluation": provider_paths_for_first_evaluation,
                        "provider_requests_for_first_evaluation": provider_requests_for_first_evaluation,
                        "provider_data_requests_for_first_evaluation": provider_data_requests_for_first_evaluation,
                        "provider_transport_used": (
                            isinstance(provider_requests_for_onboarding, int)
                            and provider_requests_for_onboarding > 0
                        ),
                        "provider_credentials_loaded": bool(provider_secrets),
                        "provider_secrets_absent_from_artifacts": _secrets_absent(
                            {
                                "onboarding": onboarding,
                                "approval": approved,
                                "evaluation": evaluation,
                                "replay": replay,
                                "receipt_lookup": receipt_lookup,
                            },
                            provider_secrets,
                        ),
                        "data_policy": data_policy,
                        "provider_force_refresh": provider_force_refresh,
                        "preset_resources": len(preset_resources),
                        "all_resources_use_requested_preset_adapter": bool(resources)
                        and len(preset_resources) == len(resources),
                        "all_resources_match_runtime_tenant": tenant_scoped_resources,
                        "jev_requests_for_first_evaluation": jev_requests_for_first_evaluation,
                        "replay_made_no_jev_call": replay_made_no_jev_call,
                        "replay_made_no_provider_call": replay_made_no_provider_call,
                    },
                    "passed": (
                        approved["status"] == "approved"
                        and all(onboarding_contract.values())
                        and summary["evaluator"] == "jev-latest"
                        and summary["evidence_count"] > 0
                        and summary["observation_count"] > 0
                        and report["provider_checks"]["provider_transport_used"] is True
                        and report["provider_checks"]["provider_credentials_loaded"] is True
                        and report["provider_checks"][
                            "provider_secrets_absent_from_artifacts"
                        ] is True
                        and report["approval_basis"]["provider_workspace_unchanged"] is True
                        and bool(preset_resources)
                        and tenant_scoped_resources
                        and isinstance(jev_requests_for_first_evaluation, int)
                        and jev_requests_for_first_evaluation > 0
                        and isinstance(provider_requests_for_first_evaluation, int)
                        and provider_requests_for_first_evaluation > 0
                        and provider_data_requests_for_first_evaluation > 0
                        and summary["receipt_status"] == "delivery_disabled"
                        and summary["delivery_enabled"] is False
                        and replay.get("replayed") is True
                        and receipt_lookup.get("status") == "found"
                        and replay_made_no_jev_call
                        and replay_made_no_provider_call
                    ),
                }
            )
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True, help="What the owner wants monitored")
    parser.add_argument("--why", required=True, help="Why this monitoring matters")
    parser.add_argument(
        "--adapter",
        default=None,
        help="Configured Preset adapter name; auto-detects the sole Preset adapter by default",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--destination", default="slack://replace-me")
    parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Approve the exact ready_for_approval draft in --review-report or --output, "
            "then run shadow"
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--review-report",
        type=Path,
        help="Previously written draft report to bind to the approval step",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    report = asyncio.run(
        run_trial(
            goal=args.goal,
            why=args.why,
            adapter=args.adapter,
            limit=args.limit,
            destination=args.destination,
            approve=args.approve,
            output=args.output,
            review_report=args.review_report,
        )
    )
    if args.approve and not report["passed"]:
        raise SystemExit("live Preset onboarding/shadow acceptance did not pass")


if __name__ == "__main__":
    main()
