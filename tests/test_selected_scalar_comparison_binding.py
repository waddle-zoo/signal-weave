"""Normal agent onboarding can bind known scalar quality without a decomposition."""

import pytest

from signalweave.mcp_server import create_mcp
from signalweave.models import (
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceComparisonContract,
)
from signalweave.onboarding import SelectedSourceInput
from tests.test_onboarding import OnboardingJevDouble, make_server


class ScalarSource:
    name = "measurements"

    def __init__(self, adapter_requirements=()):
        self.coverage = "complete"
        self.calls = 0
        self.comparison = SourceComparisonContract(
            key="accounts-change", metric="active_accounts", definition="Monthly active accounts",
            population="Reviewed account population", unit="count", comparison_window="previous_period",
            coverage="complete", comparable=True, query_refs=["saved-query:accounts"],
        )
        self.descriptor = ResourceDescriptor(
            adapter=self.name, resource="accounts", kind="measurement", title="Account activity",
            contract=ResourceContract(
                scope="Reviewed account population", population="Reviewed account population", grain="month",
                available_comparison_windows=["previous_period"],
                comparison_contracts=[self.comparison], required_comparison_keys=list(adapter_requirements),
            ),
        )

    async def list_resources(self):
        return [self.descriptor.model_copy(deep=True)]

    async def inspect(self, source):
        self.calls += 1
        contract = self.descriptor.contract.model_copy(deep=True, update={
            "comparison_contracts": [self.comparison.model_copy(update={
                "coverage": self.coverage, "comparable": self.coverage == "complete",
            })],
        })
        return ResourceSnapshot(
            source_key=source.key, adapter=self.name, resource=source.resource, title="Account activity",
            contract=contract, observations=[Observation(
                source_key=source.key, metric="active_accounts", current=120, baseline=100, unit="count",
            )],
        )


async def onboard(server, selected):
    _, result = await server.call_tool("onboard_insight_card", {
        "what_to_watch": "Monthly account activity", "why_watch": "Keep the account team informed",
        "decision_guidance": "Notify the account team for a supported complete comparison; otherwise investigate.",
        "selected_sources": [selected],
        "delivery_methods": [{"key": "accounts", "outcome": "notify", "label": "Account team",
                              "destination": "agent://accounts"}],
    })
    return result


@pytest.mark.parametrize("required", [True, False])
async def test_scalar_binding_lifecycle_and_optional_source_semantics(tmp_path, required):
    source = ScalarSource()
    base = make_server(tmp_path, catalog=source, judger=OnboardingJevDouble())
    server = create_mcp(base._test_runtime, profile="agent")
    result = await onboard(server, {"ref": "measurements|accounts", "key": "accounts",
                                    "required": required, "required_comparison_keys": ["accounts-change"]})
    card = result["card"]
    assert card["sources"][0]["required_comparison_keys"] == ["accounts-change"]
    assert card["numeric_conditions"] == []
    await server.call_tool("review_insight_card", {"card_id": card["id"]})
    await server.call_tool("approve_insight_card", {
        "card_id": card["id"], "use_current_source_selection_review": True,
        "source_selection_reason": "Owner reviewed the source and its scalar comparison scope.",
        "source_scope_confirmations": {"measurements|accounts": "Reviewed account population"},
    })
    source.coverage = "partial"
    _, run = await server.call_tool("evaluate_insight_card", {
        "card_id": card["id"], "idempotency_key": "accounts:partial-close",
    })
    # The provider double always selects notify: this tests deterministic gate
    # semantics, not the double's fidelity to the owner's business policy.
    assert run["result"]["outcome"] == ("insufficient_data" if required else "notify")
    quality = run["result"]["source_contracts"][0]["contract"]["comparison_contracts"][0]
    assert quality["coverage"] == "partial" and quality["comparable"] is False


@pytest.mark.parametrize("key", ["invented", "previous_period", "other-source-change"])
async def test_unknown_or_window_only_keys_rejected_before_inspection(tmp_path, key):
    source = ScalarSource()
    server = create_mcp(make_server(tmp_path, catalog=source)._test_runtime, profile="agent")
    with pytest.raises(Exception, match="declared by its reviewed catalog contract"):
        await onboard(server, {"ref": "measurements|accounts", "required_comparison_keys": [key]})
    assert source.calls == 0


async def test_caller_cannot_remove_adapter_requirements(tmp_path):
    source = ScalarSource(adapter_requirements=["accounts-change"])
    server = create_mcp(make_server(tmp_path, catalog=source)._test_runtime, profile="agent")
    result = await onboard(server, {"ref": "measurements|accounts", "required_comparison_keys": []})
    assert result["card"]["sources"][0]["required_comparison_keys"] == ["accounts-change"]


async def test_owner_binding_unions_distinct_adapter_requirement(tmp_path):
    source = ScalarSource(adapter_requirements=["adapter-baseline"])
    source.descriptor.contract.comparison_contracts.append(
        source.comparison.model_copy(update={"key": "adapter-baseline"})
    )
    server = create_mcp(make_server(tmp_path, catalog=source)._test_runtime, profile="agent")
    result = await onboard(server, {
        "ref": "measurements|accounts", "required_comparison_keys": ["accounts-change"],
    })
    assert result["card"]["sources"][0]["required_comparison_keys"] == [
        "accounts-change", "adapter-baseline",
    ]


@pytest.mark.parametrize("keys", [[" "], ["x" * 161], ["accounts-change"] * 21])
def test_selected_quality_keys_are_bounded(keys):
    with pytest.raises(ValueError):
        SelectedSourceInput(ref="measurements|accounts", required_comparison_keys=keys)
