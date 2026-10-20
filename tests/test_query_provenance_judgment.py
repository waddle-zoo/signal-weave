"""Source query declarations help agents without inflating recurring judgments."""

from copy import deepcopy

from signalweave.engine import InsightEngine, _judgment_source
from signalweave.models import InsightCard, Observation, ResourceSnapshot, SourceRef
from tests.test_engine import SafetyTestDouble


def source():
    return ResourceSnapshot(source_key="primary", adapter="superset", resource="chart:42", title="Declared aggregate",
                            observations=[Observation(source_key="primary", subject_id="total", metric="sum_sales", current=90, baseline=100)],
                            metadata={"saved_query_definition": {"audience": "agent", "metrics": ["SUM(sales)"]},
                                      "data_quality": {"status": "partial", "note": "Keep this limitation"},
                                      "charts": [{"id": "42", "saved_query_definition": {"audience": "agent", "metrics": ["SUM(sales)"]}, "semantic_status": "extracted"},
                                                 {"id": "43", "saved_query_definition": {"audience": "agent", "all_columns": ["sales"]}, "semantic_status": "partial"}]})


def test_judgment_projection_preserves_facts_contract_quality_and_original_snapshot():
    original = source()
    before = original.model_dump(mode="json")
    projected = _judgment_source(original)
    assert "saved_query_definition" not in projected["metadata"]
    assert all("saved_query_definition" not in chart for chart in projected["metadata"]["charts"])
    assert projected["metadata"]["data_quality"] == before["metadata"]["data_quality"]
    assert projected["metadata"]["charts"][1]["semantic_status"] == "partial"
    assert projected["contract"] == before["contract"]
    assert original.model_dump(mode="json") == before
    assert "observations" not in projected and "evidence" not in projected


def test_unmarked_business_metadata_from_other_sources_is_not_removed():
    original = ResourceSnapshot(source_key="warehouse", adapter="company_mcp", resource="query:1", title="Query policy",
                                metadata={"saved_query_definition": {"statement": "An actual business fact"}})
    assert _judgment_source(original)["metadata"] == original.metadata


async def test_actual_judge_receives_no_added_query_definition_and_run_retains_it():
    class RecordingJudge(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            self.state = deepcopy(state)
            return await super().judge(state, card, plan, observations)
    judge = RecordingJudge()
    resource = source()
    card = InsightCard(id="query-provenance", title="Reported sales", what_to_watch="Reported sales change",
                       why_watch="Explain movement", sources=[SourceRef(key="primary", adapter="superset", resource="chart:42", label="Declared aggregate")])
    run = await InsightEngine(judge).evaluate(card, [resource])
    assert "saved_query_definition" not in str(judge.state["sources"])
    assert judge.state["observations"][0]["current"] == 90
    assert run.resources[0].metadata["saved_query_definition"]["metrics"] == ["SUM(sales)"]
    assert run.result.observations[0].current == 90
