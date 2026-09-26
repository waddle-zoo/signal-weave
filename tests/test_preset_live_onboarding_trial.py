from __future__ import annotations

from types import SimpleNamespace

import pytest

import evaluations.preset_live_onboarding_trial as trial


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

    async def onboard(**kwargs):
        calls.append("onboard")
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
            sources=SimpleNamespace(adapter_names=lambda: ["preset__preset-env"]),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(judger=SimpleNamespace(name="jev-latest")),
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
    assert report["next_action"].endswith("--approve")
    assert calls == ["onboard"]


@pytest.mark.asyncio
async def test_live_trial_accepts_only_jev_delivery_disabled_shadow(monkeypatch):
    async def onboard(**kwargs):
        return {"status": "ready_for_approval", "card": {"id": "card-1"}}

    async def approve(*args, **kwargs):
        return {"status": "approved", "card": {"id": "card-1", "version": 3}}

    async def evaluate(*args, **kwargs):
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
            "replayed": False,
        }

    monkeypatch.setattr(
        trial,
        "build_runtime",
        lambda: SimpleNamespace(
            sources=SimpleNamespace(adapter_names=lambda: ["preset__preset-env"]),
            principal=SimpleNamespace(tenant_id="northstar"),
            engine=SimpleNamespace(judger=SimpleNamespace(name="jev-latest")),
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
            }
        ),
    )

    report = await trial.run_trial(
        goal="Monitor growth",
        why="Support the growth team",
        adapter="preset__preset-env",
        limit=10,
        destination="slack://growth",
        approve=True,
    )

    assert report["passed"] is True
    assert report["summary"]["evaluator"] == "jev-latest"
    assert report["summary"]["receipt_status"] == "delivery_disabled"


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
