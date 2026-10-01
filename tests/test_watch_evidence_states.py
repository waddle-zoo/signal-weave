"""Three-way semantic evidence states, through the real SDK/engine boundary.

Inference is replaced, not the compiler, judgment question construction or gates.
Missing semantic context can occur even when the source is fresh and healthy.
"""

from types import SimpleNamespace

import pytest
import typesafe_sdk

from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import ContextSnapshot, InsightCard, ResourceSnapshot
from signalweave.typesafe_adapter import JevJudger


@pytest.fixture
def sdk(monkeypatch):
    control = SimpleNamespace(
        calls=[], selected="unknown",
        probabilities={"present": 0.01, "absent": 0.01, "unknown": 0.98},
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def system_one(self, *, state, questions):
            control.calls.append(questions)
            assert isinstance(questions["watch_0"], typesafe_sdk.Choice)
            assert set(questions["watch_0"].criteria) == {"present", "absent", "unknown"}
            choices = {"watch_0": SimpleNamespace(
                choice=control.selected, probabilities=control.probabilities,
            ), "outcome": SimpleNamespace(
                choice="notify", probabilities={"notify": 0.99, "ignore": 0.01},
            )}
            return SimpleNamespace(choices=choices, nouls={}, usage=None)

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", Client)
    return control


async def evaluate(*, optional=False, failed_source=False, context=None):
    card = InsightCard(
        id="evidence-check", title="Operating review",
        what_to_watch="A reviewed operating condition",
        why_watch="Notify the owner only with adequate evidence.",
        watch_for=["The approved operating condition is present."],
        evidence_requirements={"watch:1": not optional},
        sources=[{"key": "source", "adapter": "test", "resource": "bounded-evidence",
                  "label": "Evidence"}],
        delivery_methods=[{"key": "owner", "outcome": "notify", "label": "Owner",
                           "destination": "agent://owner"}],
    )
    card.compiled_plan = base_plan(card)
    snapshot = ResourceSnapshot(
        source_key="source", adapter="test", resource="bounded-evidence", title="Evidence",
        evidence=[{"source_key": "source", "statement": "The requested context is unavailable."}],
        error="Source unavailable" if failed_source else None,
    )
    return await InsightEngine(JevJudger(api_key="offline-test", max_retries=0)).evaluate(
        card, [snapshot], context_override=context,
    )


@pytest.mark.parametrize("selected,probabilities,expected", [
    ("present", {"present": .98, "absent": .01, "unknown": .01}, "present"),
    ("absent", {"present": .01, "absent": .98, "unknown": .01}, "absent"),
    ("unknown", {"present": .01, "absent": .01, "unknown": .98}, "unknown"),
    ("present", {"present": .69, "absent": .01, "unknown": .30}, "unknown"),
    ("absent", {"present": .01, "absent": .69, "unknown": .30}, "unknown"),
    ("present", {"present": .70, "absent": .01, "unknown": .29}, "present"),
    ("absent", {"present": .01, "absent": .70, "unknown": .29}, "absent"),
])
async def test_semantic_state_and_distribution_are_retained(sdk, selected, probabilities, expected):
    sdk.selected, sdk.probabilities = selected, probabilities
    run = await evaluate()
    watch = run.result.watch_results[0]
    assert watch.status.value == expected
    assert watch.probability == probabilities["present"]
    assert watch.probabilities == probabilities
    assert len(sdk.calls) == 1  # No serial per-item inference call.
    assert run.result.outcome.value == ("investigate" if expected == "unknown" else "notify")
    assert bool(run.result.delivery_methods) is (expected != "unknown")
    assert run.result.evidence_plan.status == ("incomplete" if expected == "unknown" else "complete")


@pytest.mark.parametrize("selected,probabilities", [
    ("invented", {"present": .01, "absent": .98, "unknown": .01}),
    ("absent", {}),
    ("absent", {"absent": .99}),
    ("absent", {"present": .01, "absent": float("nan"), "unknown": .01}),
    ("absent", {"present": .01, "absent": float("inf"), "unknown": .01}),
    ("absent", {"present": -.01, "absent": 1.0, "unknown": .01}),
    ("absent", {"present": .01, "absent": .99, "unknown": .99}),
    ("absent", {"present": .98, "absent": .01, "unknown": .01}),
    ("absent", {"present": .01, "absent": .70, "unknown": .309}),
])
async def test_invalid_semantic_answer_cannot_complete_required_evidence(sdk, selected, probabilities):
    sdk.selected, sdk.probabilities = selected, probabilities
    run = await evaluate()
    assert run.result.watch_results[0].status.value == "unknown"
    assert run.result.watch_results[0].probabilities == {}
    assert run.result.outcome.value == "investigate"
    assert not run.result.delivery_methods


async def test_advisory_unknown_stays_visible_without_waiving_required_sources(sdk):
    run = await evaluate(optional=True)
    assert run.result.watch_results[0].status.value == "unknown"
    assert run.result.outcome.value == "notify"
    assert "watch:1" in run.result.evidence_plan.missing_slot_keys
    failed = await evaluate(optional=True, failed_source=True)
    assert failed.result.outcome.value == "insufficient_data"
    assert not failed.result.delivery_methods


@pytest.mark.parametrize("selected,expected", [("unknown", "investigate"), ("absent", "notify"), ("present", "notify")])
async def test_context_slot_tag_is_provenance_not_semantic_completion(sdk, selected, expected):
    sdk.selected = selected
    sdk.probabilities = {key: .98 if key == selected else .01 for key in ("present", "absent", "unknown")}
    context = ContextSnapshot(provider="approved-provider", version="1", facts=[{
        "fact_id": "related-fact", "slot_key": "watch:1", "subject_ref": "test|bounded-evidence",
        "relation": "related_to", "statement": "Evidence about this condition is unavailable.",
    }])
    run = await evaluate(context=context)
    slot = next(s for s in run.result.evidence_plan.slots if s.key == "watch:1")
    assert slot.status == ("pending" if selected == "unknown" else "fulfilled")
    assert slot.evidence_fact_ids == ["related-fact"]
    assert run.result.outcome.value == expected
