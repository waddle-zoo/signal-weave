"""Exercise the production MCP path against a running local Superset.

The Superset transport is real: the trial discovers a dashboard, authorizes its
saved resource, reads its saved chart data, and persists a SignalWeave receipt.
Only the TypeSafe SDK transport is synthetic, so this proof spends no Jev
credits. It is an integration proof for onboarding and evidence plumbing, not
a semantic-quality claim about live Jev.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import typesafe_sdk

from evaluations.preset_jev_contract_trial import (
    ContractChoice,
    ContractClient,
    ContractNoul,
    ContractResponse,
)
from signalweave.mcp_server import create_mcp
from signalweave.runtime import build_runtime
from signalweave.superset_adapter import SupersetAdapter


def _tool(server: Any, name: str) -> Any:
    return server._tool_manager.get_tool(name).fn


class LocalShadowClient(ContractClient):
    """Return typed shadow relevance for the discovered local dashboard catalog.

    This keeps the transport deterministic without pretending that every
    resource is equally relevant. It is test-only plumbing; production still
    constructs ``JevJudger`` and calls the real TypeSafe SDK.
    """

    async def system_one(
        self, *, state: dict[str, Any], questions: dict[str, Any]
    ) -> ContractResponse:
        response = await super().system_one(state=state, questions=questions)

        def terms(value: str) -> set[str]:
            return {
                term
                for term in re.findall(r"[a-z0-9]+", value.lower())
                if len(term) > 3 or term.isdigit()
            }

        goal_terms = terms(str(state.get("goal", "")))
        candidates = state.get("candidate_resources")
        if isinstance(candidates, list):
            overlaps = [
                len(
                    goal_terms
                    & terms(str(candidate.get("title", "")))
                )
                for candidate in candidates
                if isinstance(candidate, dict)
            ]
            max_overlap = max(overlaps, default=0)
            for key, answer in response.nouls.items():
                if not key.startswith("resource_"):
                    continue
                index = int(key.removeprefix("resource_"))
                candidate = candidates[index] if index < len(candidates) else {}
                candidate_terms = terms(str(candidate.get("title", "")))
                overlap = len(goal_terms & candidate_terms)
                answer.noul = (
                    0.96 if max_overlap > 0 and overlap == max_overlap else 0.08
                )
                response.nouls[key] = SimpleNamespace(noul=answer.noul)
        return response


@contextmanager
def _runtime_environment(
    *,
    superset_url: str,
    username: str,
    password: str,
    tenant_id: str,
    principal_id: str,
    store_path: Path,
    max_snapshot_bytes: int | None,
    max_jev_payload_bytes: int | None,
) -> Iterator[None]:
    names = {
        "TYPESAFE_MODE",
        "TYPESAFE_API_KEY",
        "TYPESAFE_API_KEY_FILE",
        "SUPERSET_URL",
        "SUPERSET_USERNAME",
        "SUPERSET_PASSWORD",
        "SUPERSET_TENANT_ID",
        "SIGNALWEAVE_TENANT_ID",
        "SIGNALWEAVE_PRINCIPAL_ID",
        "SIGNALWEAVE_STORE_BACKEND",
        "SIGNALWEAVE_STORE_PATH",
        "SIGNALWEAVE_MAX_SNAPSHOT_BYTES",
        "SIGNALWEAVE_MAX_JEV_PAYLOAD_BYTES",
        "PRESET_URL",
        "PRESET_TENANT_ID",
        "PRESET_ACCESS_TOKEN",
        "PRESET_API_TOKEN_NAME",
        "PRESET_API_TOKEN_SECRET",
        "PRESET_API_BASE_URL",
    }
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(
            {
                "TYPESAFE_MODE": "jev",
                "TYPESAFE_API_KEY": "synthetic-local-shadow-key",
                "SUPERSET_URL": superset_url,
                "SUPERSET_USERNAME": username,
                "SUPERSET_PASSWORD": password,
                "SIGNALWEAVE_TENANT_ID": tenant_id,
                "SIGNALWEAVE_PRINCIPAL_ID": principal_id,
                "SIGNALWEAVE_STORE_BACKEND": "sqlite",
                "SIGNALWEAVE_STORE_PATH": str(store_path),
            }
        )
        if max_snapshot_bytes is not None:
            os.environ["SIGNALWEAVE_MAX_SNAPSHOT_BYTES"] = str(max_snapshot_bytes)
        if max_jev_payload_bytes is not None:
            os.environ["SIGNALWEAVE_MAX_JEV_PAYLOAD_BYTES"] = str(max_jev_payload_bytes)
        yield
    finally:
        for name in names:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def _select_match(
    matches: list[dict[str, Any]], title_contains: str | None
) -> dict[str, Any]:
    if not matches:
        raise RuntimeError("Superset discovery returned no authorized dashboard candidates")
    if title_contains:
        needle = title_contains.strip().lower()
        for match in matches:
            if needle in str(match.get("title", "")).lower():
                return match
        raise RuntimeError(
            f"Superset discovery returned no dashboard title containing {title_contains!r}; "
            f"discovery returned {len(matches)} visible candidates"
        )
    return matches[0]


def _chart_summary(
    resources: list[dict[str, Any]], *, observation_count: int
) -> dict[str, Any]:
    charts = [
        chart
        for resource in resources
        for chart in (resource.get("metadata") or {}).get("charts", [])
        if isinstance(chart, dict)
    ]
    return {
        "charts": len(charts),
        "observations": observation_count,
        "semantic_status": {
            status: sum(1 for chart in charts if chart.get("semantic_status") == status)
            for status in sorted({str(chart.get("semantic_status")) for chart in charts})
        },
        "viz_types": sorted(
            {str(chart.get("viz_type") or "unknown") for chart in charts}
        ),
    }


async def run_trial(
    *,
    superset_url: str = "http://127.0.0.1:8088",
    username: str = "admin",
    password: str = "admin",
    tenant_id: str = "local-superset-demo",
    principal_id: str = "local-superset-monitoring-agent",
    goal: str = (
        "Monitor the Sales Dashboard for meaningful movement in saved business "
        "signals and return one evidence-backed owner review."
    ),
    title_contains: str | None = "Sales Dashboard",
    max_snapshot_bytes: int | None = None,
    max_jev_payload_bytes: int | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    original_client = typesafe_sdk.AsyncTypeSafeClient
    original_noul = typesafe_sdk.Noul
    original_choice = typesafe_sdk.Choice
    ContractClient.calls = []
    typesafe_sdk.AsyncTypeSafeClient = LocalShadowClient
    typesafe_sdk.Noul = ContractNoul
    typesafe_sdk.Choice = ContractChoice
    try:
        with tempfile.TemporaryDirectory(prefix="signalweave-local-superset-") as directory:
            with _runtime_environment(
                superset_url=superset_url,
                username=username,
                password=password,
                tenant_id=tenant_id,
                principal_id=principal_id,
                store_path=Path(directory) / "signalweave.db",
                max_snapshot_bytes=max_snapshot_bytes,
                max_jev_payload_bytes=max_jev_payload_bytes,
            ):
                runtime = build_runtime()
                adapter = runtime.sources._adapters.get("superset")
                if not isinstance(adapter, SupersetAdapter):
                    raise RuntimeError("production runtime did not register the Superset adapter")
                if adapter.tenant_id != tenant_id:
                    raise RuntimeError(
                        "production runtime did not bind the Superset adapter to the tenant"
                    )
                provider_client = adapter.client
                server = create_mcp(runtime)
                discover = _tool(server, "discover_insight_sources")
                onboard = _tool(server, "onboard_insight_card")
                review_card = _tool(server, "review_insight_card")
                approve = _tool(server, "approve_insight_card")
                evaluate = _tool(server, "evaluate_insight_card")
                get_receipt = _tool(server, "get_decision_receipt")

                discovery = await discover(goal, adapter="superset", limit=10)
                match = _select_match(discovery["matches"], title_contains)
                selected_sources = [{"ref": match["ref"], "label": match["title"]}]
                onboarding = await onboard(
                    what_to_watch=goal,
                    why_watch="Give leadership one bounded evidence bundle instead of checking the dashboard manually.",
                    watch_for=[
                        "meaningful movement in the dashboard's saved business signals",
                        "missing or incomplete chart evidence",
                    ],
                    questions=[
                        "What changed and which saved charts support it?",
                        "Is the evidence complete enough for an owner to act?",
                    ],
                    decision_guidance=(
                        "Notify only when the evidence supports owner review; otherwise "
                        "investigate or report insufficient data."
                    ),
                    selected_sources=selected_sources,
                    adapter="superset",
                    limit=10,
                    title=f"{match['title']} monitoring",
                    delivery_methods=[
                        {
                            "key": "owner-review",
                            "outcome": "notify",
                            "label": "Owner review",
                            "destination": "slack://shadow-review",
                            "instructions": "Send the evidence bundle to the owner workflow.",
                        }
                    ],
                    retrieval_mode="fixed",
                    investigation_mode="none",
                )
                card_id = onboarding["card"]["id"]
                onboarding_review = (await review_card(card_id))["review"]
                approval_args = {"card_id": card_id, "actor": principal_id}
                if any(
                    blocker["code"] == "comparison-window-mismatch"
                    for blocker in onboarding_review.get("blockers", [])
                ):
                    approval_args.update(
                        {
                            "source_selection_fingerprint": onboarding_review[
                                "source_selection_fingerprint"
                            ],
                            "source_selection_reason": (
                                "The dashboard owner reviewed this fixed Sales Dashboard scope "
                                "and explicitly accepts previous_period for this monitor; "
                                "runtime evidence must still support the selected window."
                            ),
                        }
                    )
                approved = await approve(**approval_args)
                approved_review = approved.get("onboarding_review") or onboarding_review
                provider_after_approval = provider_client.requests_made
                jev_before_evaluation = len(ContractClient.calls)
                resource_identity = re.sub(
                    r"[^a-z0-9_-]+",
                    "-",
                    str(match.get("ref", "dashboard")).lower(),
                ).strip("-_") or "dashboard"
                idempotency_key = f"local-superset-shadow:{tenant_id}:{resource_identity}"
                evaluated = await evaluate(
                    card_id,
                    idempotency_key=idempotency_key,
                    actor=principal_id,
                )
                jev_after_evaluation = len(ContractClient.calls)
                provider_after_evaluation = provider_client.requests_made
                replay = await evaluate(
                    card_id,
                    idempotency_key=idempotency_key,
                    actor=principal_id,
                )
                jev_after_replay = len(ContractClient.calls)
                provider_after_replay = provider_client.requests_made
                receipt = get_receipt(idempotency_key=idempotency_key)

                result = evaluated["result"]
                resources = evaluated.get("resources") or []
                chart_summary = _chart_summary(
                    resources, observation_count=len(result.get("observations") or [])
                )
                dashboard_scope = next(
                    (
                        resource.get("metadata", {}).get("dashboard_scope")
                        for resource in resources
                        if isinstance(resource, dict)
                        and isinstance(resource.get("metadata"), dict)
                        and isinstance(resource.get("metadata", {}).get("dashboard_scope"), dict)
                    ),
                    {},
                )
                dashboard_scope_warning = (
                    "Some charts used the bounded saved-chart-query fallback because "
                    "the provider reported no saved query context; dashboard-native "
                    "filter state was not applied to those requests."
                    if dashboard_scope.get("chart_query_fallbacks", 0) > 0
                    else None
                )
                checks = {
                    "tenant_bound_runtime": adapter.tenant_id == tenant_id,
                    "discovery_found_requested_dashboard": match["ref"].startswith(
                        "superset|dashboard:"
                    ),
                    "human_reviewable_onboarding": onboarding["approval_required"] is True
                    and onboarding["status"] in {"ready_for_approval", "blocked"},
                    "owner_confirmation_resolved_onboarding": approved_review["status"]
                    == "ready_for_approval"
                    and not approved_review["blockers"]
                    and (
                        not onboarding_review["blockers"]
                        or "comparison-window-mismatch"
                        in approved_review["confirmed_blocker_codes"]
                    ),
                    "approval_gate_passed": approved["status"] == "approved",
                    "real_provider_data_crossed_runtime": provider_after_evaluation
                    > provider_after_approval
                    and any(
                        path.endswith("/data/")
                        for path in provider_client.request_path_counts
                    ),
                    "jev_evaluator_is_production_path": result["evaluator"] == "jev-latest",
                    "evidence_bundle_is_nonempty": bool(result.get("evidence"))
                    and bool(result.get("observations")),
                    "dashboard_chart_evidence_is_visible": chart_summary["charts"] > 0
                    and chart_summary["observations"] > 0,
                    "dashboard_scope_telemetry_visible": all(
                        isinstance(dashboard_scope.get(key), int)
                        for key in ("dashboard_scoped_requests", "chart_query_fallbacks")
                    ),
                    "delivery_is_disabled": receipt["receipt"]["status"] == "delivery_disabled"
                    and receipt["receipt"]["delivery_enabled"] is False,
                    "replay_is_idempotent": replay["replayed"] is True
                    and jev_after_replay == jev_after_evaluation
                    and provider_after_replay == provider_after_evaluation,
                    "replay_skips_jev": jev_after_evaluation > jev_before_evaluation
                    and jev_after_replay == jev_after_evaluation,
                    "provider_credentials_not_in_jev_state": all(
                        secret not in json.dumps(ContractClient.calls, sort_keys=True)
                        for secret in (username, password)
                    ),
                }
                report = {
                    "trial": "local-superset-runtime-shadow",
                    "description": "Real local Superset through production runtime/MCP onboarding and delivery-disabled Jev shadow evaluation.",
                    "real_local_superset_transport": True,
                    "synthetic_typesafe_transport": True,
                    "live_jev_semantics_proven": False,
                    "managed_hosting_proven": False,
                    "superset_url": superset_url,
                    "tenant_id": tenant_id,
                    "principal_id": principal_id,
                    "goal": goal,
                    "title_contains": title_contains,
                    "budgets": {
                        "max_snapshot_bytes": max_snapshot_bytes or 1_000_000,
                        "max_jev_payload_bytes": max_jev_payload_bytes or 2_000_000,
                    },
                    "discovery": {
                        "candidate_count": discovery.get("candidate_count"),
                        "match_count": len(discovery.get("matches") or []),
                        "selected_ref": match["ref"],
                        "selected_title": match["title"],
                        "candidate_strategy": discovery.get("candidate_strategy"),
                    },
                    "onboarding": {
                        "status": onboarding["status"],
                        "card_id": card_id,
                        "selected_sources": onboarding["card"]["sources"],
                        "initial_review_status": onboarding_review["status"],
                        "review_status": approved_review["status"],
                        "confirmed_blocker_codes": approved_review[
                            "confirmed_blocker_codes"
                        ],
                    },
                    "approval": {"status": approved["status"]},
                    "evaluation": {
                        "outcome": result["outcome"],
                        "confidence": result["confidence"],
                        "evaluator": result["evaluator"],
                        "evidence_count": len(result.get("evidence") or []),
                        "observation_count": len(result.get("observations") or []),
                        "chart_summary": chart_summary,
                        "jev_calls_for_evaluation": jev_after_evaluation
                        - jev_before_evaluation,
                    },
                    "receipt": {
                        "status": receipt["receipt"]["status"],
                        "delivery_enabled": receipt["receipt"]["delivery_enabled"],
                        "replayed": replay["replayed"],
                    },
                    "provider": {
                        "requests_made": provider_after_evaluation,
                        "request_path_counts": provider_client.request_path_counts,
                        "dashboard_scope": dashboard_scope,
                        "dashboard_scope_warning": dashboard_scope_warning,
                        "requests_for_evaluation": provider_after_evaluation
                        - provider_after_approval,
                        "requests_for_replay": provider_after_replay
                        - provider_after_evaluation,
                    },
                    "checks": checks,
                    "passed": all(checks.values()),
                    "not_proven": [
                        "live Jev semantic accuracy or business usefulness",
                        "hosted Preset permissions, plan, rate limits, or network path",
                        "managed SignalWeave hosting",
                    ],
                }
    finally:
        typesafe_sdk.AsyncTypeSafeClient = original_client
        typesafe_sdk.Noul = original_noul
        typesafe_sdk.Choice = original_choice

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--superset-url", default="http://127.0.0.1:8088")
    parser.add_argument("--superset-username", default="admin")
    parser.add_argument("--superset-password", default="admin")
    parser.add_argument("--tenant-id", default="local-superset-demo")
    parser.add_argument("--principal-id", default="local-superset-monitoring-agent")
    parser.add_argument("--goal", default=None)
    parser.add_argument("--dashboard-title-contains", default="Sales Dashboard")
    parser.add_argument("--max-snapshot-bytes", type=int)
    parser.add_argument("--max-jev-payload-bytes", type=int)
    parser.add_argument("--output", type=Path, default=Path("artifacts/local-superset-runtime-shadow.json"))
    args = parser.parse_args()
    report = asyncio.run(
        run_trial(
            superset_url=args.superset_url,
            username=args.superset_username,
            password=args.superset_password,
            tenant_id=args.tenant_id,
            principal_id=args.principal_id,
            goal=args.goal
            or (
                "Monitor the Sales Dashboard for meaningful movement in saved "
                "business signals and return one evidence-backed owner review."
            ),
            title_contains=args.dashboard_title_contains or None,
            max_snapshot_bytes=args.max_snapshot_bytes,
            max_jev_payload_bytes=args.max_jev_payload_bytes,
            output=args.output,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
