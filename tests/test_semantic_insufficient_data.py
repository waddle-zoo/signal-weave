"""Offline adversarial coverage of the SDK Choice -> engine routing boundary."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import typesafe_sdk

from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    Observation,
    Outcome,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger


@pytest.fixture
def sdk(monkeypatch):
    """Capture real SDK question objects; replace all inference transport."""
    control = SimpleNamespace(
        calls=[], choice="insufficient_data", probability=0.99, watch_probability=0.99,
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def system_one(self, *, state, questions):
            control.calls.append({"state": state, "questions": questions})
            choices = {}
            nouls = {}
            for key, question in questions.items():
                if isinstance(question, typesafe_sdk.Choice):
                    selected = control.choice if key == "outcome" else "quality"
                    probability = control.probability if key == "outcome" else 0.99
                    options = list(question.criteria)
                    # Invalid returned options are intentional in the fail-closed test.
                    if selected not in options:
                        options.append(selected)
                    probabilities = {
                        option: probability if option == selected else
                        (1.0 - probability) / (len(options) - 1)
                        for option in options
                    }
                    choices[key] = SimpleNamespace(
                        choice=selected, probabilities=probabilities, confidence=probability,
                        destination="slack://model-invented-destination",
                        delivery_method_keys=["model-invented-route"],
                    )
                else:
                    assert isinstance(question, typesafe_sdk.Noul)
                    nouls[key] = SimpleNamespace(noul=control.watch_probability)
            return SimpleNamespace(
                choices=choices, nouls=nouls,
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", Client)
    return control


def route(outcome, *, key=None):
    return DeliveryMethod(
        key=key or outcome.value,
        outcome=outcome,
        label="Configured owner",
        destination=f"slack://configured-{key or outcome.value}",
        instructions="Ask the owner to resolve missing definitions before interpreting movement.",
    )


def card_and_snapshot(methods=()):
    source = SourceRef(
        key="metric", adapter="test", resource="query:metric", label="Metric comparison",
    )
    card = InsightCard(
        id="semantic-contract", title="Metric review",
        what_to_watch="Movement in the owner-defined metric",
        why_watch="Determine whether the operating owner needs to act",
        decision_guidance="Do not reconstruct missing metric definitions or populations.",
        sources=[source], delivery_methods=list(methods),
    )
    card.compiled_plan = base_plan(card)
    snapshot = ResourceSnapshot(
        source_key=source.key, adapter=source.adapter, resource=source.resource,
        title=source.label,
        observations=[Observation(
            source_key=source.key, subject_id="metric-1", subject_label="Metric",
            metric="owner_metric", current=80, baseline=100, change_pct=-20,
        )],
        evidence=[Evidence(
            source_key=source.key, subject_id="definition", subject_label="Definition",
            statement="The approved metric definition and population are unresolved.",
            provenance=["catalog:metric-definition"],
            source_url="https://catalog.example/metric",
        )],
    )
    return card, snapshot


def engine(**kwargs):
    return InsightEngine(
        judger=JevJudger(api_key="synthetic-test-key", max_retries=0), **kwargs,
    )


@pytest.mark.parametrize("outcomes", [
    (), (Outcome.NOTIFY,), (Outcome.ESCALATE,), (Outcome.INSUFFICIENT_DATA,),
    (Outcome.NOTIFY, Outcome.INSUFFICIENT_DATA), tuple(Outcome),
])
async def test_semantic_insufficiency_is_an_sdk_choice_without_a_delivery_route(sdk, outcomes):
    card, snapshot = card_and_snapshot([route(outcome) for outcome in outcomes])

    run = await engine().evaluate(card, [snapshot])

    assert len(sdk.calls) == 1
    question = sdk.calls[0]["questions"]["outcome"]
    assert isinstance(question, typesafe_sdk.Choice)
    expected = {"ignore", "investigate", "insufficient_data"} | set(outcomes)
    assert set(question.criteria) == expected
    assert set(run.result.probabilities) == expected
    assert run.result.probabilities["insufficient_data"] == pytest.approx(0.99)
    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.delivery_methods == [
        method for method in card.delivery_methods if method.outcome == Outcome.INSUFFICIENT_DATA
    ]
    # Healthy, fresh, comparable source: only the semantic answer can cause this result.
    assert snapshot.contract.source_status == "healthy"
    assert snapshot.error is None
    assert run.result.observations[0].change_pct == -20
    assert snapshot.evidence[0] in run.result.evidence
    assert "watch_0" not in sdk.calls[0]["questions"]
    assert run.result.watch_results == []


async def test_semantic_insufficiency_keeps_only_exact_configured_data_owner_routes(sdk):
    data_owner = route(Outcome.INSUFFICIENT_DATA, key="data-owner")
    backup_owner = route(Outcome.INSUFFICIENT_DATA, key="backup-owner")
    card, snapshot = card_and_snapshot([
        route(Outcome.NOTIFY), data_owner, route(Outcome.INVESTIGATE), backup_owner,
    ])
    before = card.model_dump(mode="json")

    run = await engine().evaluate(card, [snapshot])

    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.delivery_methods == [data_owner, backup_owner]
    assert card.model_dump(mode="json") == before
    assert "model-invented" not in run.result.model_dump_json()
    # Routing secrets remain code-owned; the semantic input retains policy and evidence.
    state = sdk.calls[0]["state"]
    assert "slack://configured-" not in json.dumps(state)
    assert state["card"]["decision_guidance"] == card.decision_guidance
    assert snapshot.evidence[0].model_dump(mode="json") in state["evidence"]


@pytest.mark.parametrize("selected", ["notify", "escalate", "invented_outcome"])
async def test_unoffered_outcome_cannot_invent_an_automatic_route(sdk, selected):
    sdk.choice = selected
    card, snapshot = card_and_snapshot()

    run = await engine().evaluate(card, [snapshot])

    assert selected not in sdk.calls[0]["questions"]["outcome"].criteria
    assert selected not in run.result.probabilities
    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []
    assert "model-invented" not in run.result.model_dump_json()


@pytest.mark.parametrize("selected", ["insufficient_data", "ignore", "notify", "escalate"])
@pytest.mark.parametrize("support", [0.55, 0.699])
async def test_low_support_never_becomes_an_automatic_action(sdk, selected, support):
    sdk.choice, sdk.probability = selected, support
    review_route = route(Outcome.INVESTIGATE)
    card, snapshot = card_and_snapshot([route(outcome) for outcome in Outcome])

    run = await engine().evaluate(card, [snapshot])

    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == [review_route]
    assert run.result.confidence == pytest.approx(support)
    assert run.result.probabilities[selected] == pytest.approx(support)


@pytest.mark.parametrize("defect,expected", [
    ("healthy", Outcome.NOTIFY),
    ("failed", Outcome.INSUFFICIENT_DATA),
    ("unknown", Outcome.INSUFFICIENT_DATA),
    ("ambiguous", Outcome.INVESTIGATE),
    ("stale", Outcome.INVESTIGATE),
    ("snapshot_expired", Outcome.INSUFFICIENT_DATA),
    ("missing_baseline", Outcome.INSUFFICIENT_DATA),
    ("source_error", Outcome.INSUFFICIENT_DATA),
])
async def test_confident_notify_still_obeys_required_source_health(sdk, defect, expected):
    sdk.choice = "notify"
    card, snapshot = card_and_snapshot([
        route(Outcome.NOTIFY), route(Outcome.INSUFFICIENT_DATA),
    ])
    if defect in {"failed", "unknown", "ambiguous", "stale"}:
        snapshot.contract.source_status = defect
    elif defect == "snapshot_expired":
        snapshot.source_captured_at = datetime.now(timezone.utc) - timedelta(days=3)
    elif defect == "missing_baseline":
        snapshot.observations[0].baseline = None
        snapshot.observations[0].change_pct = None
    elif defect == "source_error":
        snapshot.error = "Required query failed."

    run = await engine().evaluate(card, [snapshot])

    assert run.result.probabilities["notify"] == pytest.approx(0.99)
    assert run.result.outcome == expected
    assert run.result.delivery_methods == [
        method for method in card.delivery_methods if method.outcome == expected
    ]
    if defect != "healthy":
        assert all(method.outcome != Outcome.NOTIFY for method in run.result.delivery_methods)


@pytest.mark.parametrize("tenant,authorized,expected", [
    ("tenant-a", True, Outcome.NOTIFY),
    ("tenant-b", True, Outcome.INSUFFICIENT_DATA),
    ("tenant-a", False, Outcome.INSUFFICIENT_DATA),
])
async def test_confident_notify_cannot_bypass_catalog_scope(sdk, tenant, authorized, expected):
    sdk.choice = "notify"
    card, snapshot = card_and_snapshot([
        route(Outcome.NOTIFY), route(Outcome.INSUFFICIENT_DATA),
    ])

    class Adapter:
        name = "test"
        inspected = []

        async def list_resources(self):
            return [ResourceDescriptor(
                adapter=self.name, resource=snapshot.resource, kind="query",
                title="Scoped metric",
                contract=ResourceContract(tenant_id=tenant, authorized=authorized),
            )]

        async def inspect(self, source):
            self.inspected.append(source.resource)
            return snapshot

    adapter = Adapter()
    run = await engine(registry=SourceRegistry([adapter])).evaluate(
        card, principal=PrincipalContext(principal_id="owner", tenant_id="tenant-a"),
    )

    assert run.result.outcome == expected
    assert run.result.delivery_methods == [
        method for method in card.delivery_methods if method.outcome == expected
    ]
    if expected == Outcome.INSUFFICIENT_DATA:
        assert adapter.inspected == []
        assert run.result.observations == []
        assert snapshot.evidence[0].statement not in json.dumps(sdk.calls[0]["state"])
    else:
        assert adapter.inspected == [snapshot.resource]


@pytest.mark.parametrize("watch_support,expected", [
    (0.5, Outcome.INVESTIGATE), (0.99, Outcome.NOTIFY), (0.01, Outcome.NOTIFY),
])
async def test_required_watch_evidence_gate_survives_new_outcome(sdk, watch_support, expected):
    sdk.choice, sdk.watch_probability = "notify", watch_support
    card, snapshot = card_and_snapshot([route(Outcome.NOTIFY)])
    card.watch_for = ["A required business condition holds."]
    card.follow_up_guidance = "Resolve the required evidence before notification."
    card.compiled_plan = base_plan(card)

    run = await engine().evaluate(card, [snapshot])

    assert run.result.outcome == expected
    assert "insufficient_data" in sdk.calls[0]["questions"]["outcome"].criteria
    assert len(run.result.watch_results) == 1
    assert run.result.evidence_plan.status == (
        "complete" if expected == Outcome.NOTIFY else "incomplete"
    )
    assert bool(run.result.delivery_methods) is (expected == Outcome.NOTIFY)
