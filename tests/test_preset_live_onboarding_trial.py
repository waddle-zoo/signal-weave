from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import evaluations.preset_live_onboarding_trial as trial
from signalweave.preset_adapter import PresetAdapter


class ToolManager:
    def __init__(self, tools):
        self._tools = {name: SimpleNamespace(fn=fn) for name, fn in tools.items()}

    def get_tool(self, name):
        return self._tools[name]


class FakeServer:
    def __init__(self, tools):
        self._tool_manager = ToolManager(tools)


@pytest.mark.asyncio
async def test_live_trial_requires_explicit_approval_before_shadow(monkeypatch, tmp_path):
    calls: list[str] = []
    provider_client = SimpleNamespace(requests_made=0)
    provider_adapter = PresetAdapter.__new__(PresetAdapter)
    provider_adapter.client = provider_client

    async def onboard(**kwargs):
        calls.append("onboard")
        provider_client.requests_made += 1
        return {"status": "needs_human_review", "card": {"id": "card-1"}}

    async def approve(*args, **kwargs):
        calls.append("approve")
        raise AssertionError("approval must not happen without --approve")

    async def evaluate(*args, **kwargs):
        calls.append("evaluate")
        raise AssertionError("evaluation must not happen without --approve")

    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
                sources=SimpleNamespace(
                    adapter_names=lambda: ["preset__preset-env"],
                    _get=lambda name: provider_adapter,
            ),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(
                judger=SimpleNamespace(
                    name="jev-latest", metrics=SimpleNamespace(requests=0)
                )
            ),
        ),
    )
    monkeypatch.setattr(
        trial,
        "create_mcp",
        lambda runtime: FakeServer(
            {
                "onboard_insight_card": onboard,
                "approve_insight_card": approve,
                "evaluate_insight_card": evaluate,
                "get_decision_receipt": lambda **kwargs: {
                    "status": "found",
                    "receipt": {"receipt_id": "receipt-1"},
                },
            }
        ),
    )

    report = await trial.run_trial(
        goal="Monitor growth",
        why="Support the growth team",
        adapter="preset__preset-env",
        limit=10,
        destination="slack://growth",
        approve=False,
        output=tmp_path / "report.json",
    )

    assert report["passed"] is False
    assert "make preset-live-trial-approve" in report["next_action"]
    assert calls == ["onboard"]


@pytest.mark.asyncio
async def test_live_trial_accepts_only_jev_delivery_disabled_shadow(monkeypatch, tmp_path):
    provider_client = SimpleNamespace(
        requests_made=0,
        request_path_counts={},
        _api_token_name="name",
        _api_token_secret="secret",
    )
    provider_adapter = PresetAdapter.__new__(PresetAdapter)
    provider_adapter.client = provider_client
    draft_card = {"id": "card-1", "version": 3}
    draft_report = {
        "trial": "preset-live-onboarding-shadow",
        "adapter": "preset__preset-env",
        "tenant_id": "northstar",
        "request": {
            "goal": "Monitor growth",
            "why": "Support the growth team",
            "destination": "slack://growth",
            "limit": 10,
        },
        "approval_requested": False,
        "passed": False,
        "onboarding": {
            "status": "ready_for_approval",
            "approval_required": True,
            "delivery_enabled": False,
            "card": draft_card,
        },
        "provider_checks": {
            "provider_requests_before_onboarding": 0,
            "provider_requests_after_onboarding": 1,
            "provider_requests_for_onboarding": 1,
            "provider_transport_used": True,
            "provider_credentials_loaded": True,
            "provider_secrets_absent_from_artifacts": True,
            "provider_catalog_searches_for_onboarding": 1,
            "provider_request_paths_before_onboarding": {},
            "provider_request_paths_after_onboarding": {"/api/v1/dashboard/": 1},
            "provider_request_paths_for_onboarding": {"/api/v1/dashboard/": 1},
        },
    }

    async def approve(*args, **kwargs):
        return {"status": "approved", "card": {"id": "card-1", "version": 3}}

    metrics = SimpleNamespace(requests=1)

    async def evaluate(*args, **kwargs):
        metrics.requests += 1
        provider_client.requests_made += 1
        provider_client.request_path_counts["/api/v1/chart/1/data"] = 1
        return {
            "result": {
                "outcome": "notify",
                "confidence": 0.9,
                "evaluator": "jev-latest",
                "evidence": [{"subject_id": "chart-1"}],
                "observations": [{"subject_id": "chart-1"}],
            },
            "receipt": {
                "receipt_id": "receipt-1",
                "status": "delivery_disabled",
                "delivery_enabled": False,
            },
            "resources": [
                {
                    "adapter": "preset__preset-env",
                    "contract": {"tenant_id": "northstar"},
                }
            ],
            "replayed": False,
        }

    replay_calls = 0

    async def replay_evaluate(*args, **kwargs):
        nonlocal replay_calls
        replay_calls += 1
        if replay_calls == 1:
            return await evaluate(*args, **kwargs)
        return {
            "result": {
                "outcome": "notify",
                "evaluator": "jev-latest",
                "evidence": [{"subject_id": "chart-1"}],
                "observations": [{"subject_id": "chart-1"}],
            },
            "replayed": True,
        }

    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
                sources=SimpleNamespace(
                    adapter_names=lambda: ["preset__preset-env"],
                    _get=lambda name: provider_adapter,
            ),
            principal=SimpleNamespace(tenant_id="northstar"),
            card_store=SimpleNamespace(
                get_card=lambda card_id: SimpleNamespace(
                    model_dump=lambda mode: draft_card
                )
            ),
            engine=SimpleNamespace(
                judger=SimpleNamespace(name="jev-latest", metrics=metrics)
            ),
        ),
    )
    monkeypatch.setattr(
        trial,
        "create_mcp",
        lambda runtime: FakeServer(
            {
                "approve_insight_card": approve,
                "evaluate_insight_card": replay_evaluate,
                "get_decision_receipt": lambda **kwargs: {
                    "status": "found",
                    "receipt": {"receipt_id": "receipt-1"},
                },
            }
        ),
    )

    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft_report), encoding="utf-8")
    report = await trial.run_trial(
        goal="Monitor growth",
        why="Support the growth team",
        adapter="preset__preset-env",
        limit=10,
        destination="slack://growth",
        approve=True,
        output=draft_path,
    )

    assert report["passed"] is True
    assert report["summary"]["evaluator"] == "jev-latest"
    assert report["summary"]["receipt_status"] == "delivery_disabled"
    assert report["provider_checks"]["onboarding_contract"] == {
        "approval_required": True,
        "delivery_disabled": True,
    }
    assert report["approval_basis"]["exact_draft_reused"] is True


@pytest.mark.asyncio
async def test_live_trial_auto_detects_custom_sole_preset_adapter(monkeypatch):
    onboarded_adapter: list[str] = []
    provider_client = SimpleNamespace(requests_made=0)
    provider_adapter = PresetAdapter.__new__(PresetAdapter)
    provider_adapter.client = provider_client

    async def onboard(**kwargs):
        onboarded_adapter.append(kwargs["adapter"])
        provider_client.requests_made += 1
        return {"status": "needs_human_review", "card": {"id": "card-1"}}

    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
                sources=SimpleNamespace(
                    adapter_names=lambda: ["preset__customer-workspace"],
                    _get=lambda name: provider_adapter,
            ),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(
                judger=SimpleNamespace(name="jev-latest", metrics=SimpleNamespace(requests=0))
            ),
        ),
    )
    monkeypatch.setattr(
        trial,
        "create_mcp",
        lambda runtime: FakeServer({"onboard_insight_card": onboard}),
    )

    await trial.run_trial(
        goal="Monitor growth",
        why="Support the growth team",
        adapter=None,
        limit=10,
        destination="slack://growth",
        approve=False,
    )

    assert onboarded_adapter == ["preset__customer-workspace"]


@pytest.mark.asyncio
async def test_live_trial_rejects_a_mutated_reviewed_card(monkeypatch, tmp_path):
    provider_adapter = PresetAdapter.__new__(PresetAdapter)
    provider_adapter.client = SimpleNamespace(
        requests_made=0,
        request_path_counts={},
    )
    reviewed_card = {"id": "card-1", "version": 1}
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(
        json.dumps(
            {
                "trial": "preset-live-onboarding-shadow",
                "adapter": "preset__preset-env",
                "tenant_id": "northstar",
                "request": {
                    "goal": "Monitor growth",
                    "why": "Support the growth team",
                    "destination": "slack://growth",
                    "limit": 10,
                },
                "approval_requested": False,
                "passed": False,
                "onboarding": {
                    "status": "ready_for_approval",
                    "approval_required": True,
                    "delivery_enabled": False,
                    "card": reviewed_card,
                },
                "provider_checks": {
                    "provider_requests_before_onboarding": 0,
                    "provider_requests_after_onboarding": 1,
                    "provider_requests_for_onboarding": 1,
                    "provider_transport_used": True,
                    "provider_credentials_loaded": True,
                    "provider_secrets_absent_from_artifacts": True,
                    "provider_catalog_searches_for_onboarding": 1,
                    "provider_request_paths_before_onboarding": {},
                    "provider_request_paths_after_onboarding": {"/api/v1/dashboard/": 1},
                    "provider_request_paths_for_onboarding": {"/api/v1/dashboard/": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
            sources=SimpleNamespace(
                adapter_names=lambda: ["preset__preset-env"],
                _get=lambda name: provider_adapter,
            ),
            principal=SimpleNamespace(tenant_id="northstar"),
            card_store=SimpleNamespace(
                get_card=lambda card_id: SimpleNamespace(
                    model_dump=lambda mode: {"id": "card-1", "version": 2}
                )
            ),
            engine=SimpleNamespace(judger=SimpleNamespace(name="jev-latest")),
        ),
    )

    with pytest.raises(RuntimeError, match="no longer matches"):
        await trial.run_trial(
            goal="Monitor growth",
            why="Support the growth team",
            adapter="preset__preset-env",
            limit=10,
            destination="slack://growth",
            approve=True,
            output=draft_path,
        )


@pytest.mark.asyncio
async def test_live_trial_rejects_mutated_transport_proof_before_approval(monkeypatch, tmp_path):
    provider_adapter = PresetAdapter.__new__(PresetAdapter)
    provider_adapter.client = SimpleNamespace(requests_made=0, request_path_counts={})
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(
        json.dumps(
            {
                "trial": "preset-live-onboarding-shadow",
                "adapter": "preset__preset-env",
                "tenant_id": "northstar",
                "request": {
                    "goal": "Monitor growth",
                    "why": "Support the growth team",
                    "destination": "slack://growth",
                    "limit": 10,
                },
                "approval_requested": False,
                "passed": False,
                "onboarding": {
                    "status": "ready_for_approval",
                    "approval_required": True,
                    "delivery_enabled": False,
                    "card": {"id": "card-1", "version": 1},
                },
                "provider_checks": {
                    "provider_requests_for_onboarding": 1,
                    "provider_transport_used": True,
                    "provider_credentials_loaded": True,
                    "provider_secrets_absent_from_artifacts": True,
                    "provider_catalog_searches_for_onboarding": 1,
                    "provider_request_paths_before_onboarding": {},
                    "provider_request_paths_after_onboarding": {},
                    "provider_request_paths_for_onboarding": {"/api/v1/dashboard/": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
            sources=SimpleNamespace(
                adapter_names=lambda: ["preset__preset-env"],
                _get=lambda name: provider_adapter,
            ),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(judger=SimpleNamespace(name="jev-latest")),
        ),
    )

    with pytest.raises(RuntimeError, match="path telemetry is inconsistent"):
        await trial.run_trial(
            goal="Monitor growth",
            why="Support the growth team",
            adapter="preset__preset-env",
            limit=10,
            destination="slack://growth",
            approve=True,
            output=draft_path,
        )


@pytest.mark.asyncio
async def test_live_trial_approval_requires_a_review_artifact(monkeypatch):
    provider_adapter = PresetAdapter.__new__(PresetAdapter)
    provider_adapter.client = SimpleNamespace(requests_made=0, request_path_counts={})
    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
            sources=SimpleNamespace(
                adapter_names=lambda: ["preset__preset-env"],
                _get=lambda name: provider_adapter,
            ),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(judger=SimpleNamespace(name="jev-latest")),
        ),
    )

    with pytest.raises(RuntimeError, match="approval requires"):
        await trial.run_trial(
            goal="Monitor growth",
            why="Support the growth team",
            adapter="preset__preset-env",
            limit=10,
            destination="slack://growth",
            approve=True,
        )


@pytest.mark.asyncio
async def test_live_trial_rejects_unscoped_or_non_jev_runtime(monkeypatch):
    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
            sources=SimpleNamespace(adapter_names=lambda: ["preset__preset-env"]),
            principal=None,
            engine=SimpleNamespace(judger=SimpleNamespace(name="jev-latest")),
        ),
    )

    with pytest.raises(RuntimeError, match="tenant-scoped"):
        await trial.run_trial(
            goal="Monitor growth",
            why="Support the growth team",
            adapter="preset__preset-env",
            limit=10,
            destination="slack://growth",
            approve=False,
        )

    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
            sources=SimpleNamespace(adapter_names=lambda: ["preset__preset-env"]),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(judger=SimpleNamespace(name="not-jev")),
        ),
    )

    with pytest.raises(RuntimeError, match="jev-latest"):
        await trial.run_trial(
            goal="Monitor growth",
            why="Support the growth team",
            adapter="preset__preset-env",
            limit=10,
            destination="slack://growth",
            approve=False,
        )
