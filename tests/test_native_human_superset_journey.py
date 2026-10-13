from types import SimpleNamespace

import pytest

from evaluations.native_human_superset_journey import ReportSession


@pytest.mark.asyncio
async def test_both_arms_keep_identical_raw_source_tools():
    class Native:
        async def list_tools(self):
            return [SimpleNamespace(name="get_signalweave_guide", description="Guide", inputSchema={})]

    baseline = await ReportSession(None).specs()
    treatment = await ReportSession(None, Native()).specs()
    assert treatment[:-1] == baseline
    assert "read_chart_rows" in {item["name"] for item in baseline}
    assert treatment[-1]["name"] == "get_signalweave_guide"


@pytest.mark.asyncio
async def test_raw_rows_preserve_dates_and_mark_partial_query_scope():
    class Client:
        async def get_chart_metadata(self, chart_id):
            assert chart_id == "7"
            return {"slice_name": "Revenue", "params": {"granularity_sqla": "event_date"}}

        async def chart_data(self, chart):
            return [{"data": [{"event_date": "2025-01-01", "revenue": 5},
                              {"event_date": "2025-01-02", "revenue": 7}]}]

        @staticmethod
        def _rows_from_result_item(envelope):
            return envelope["data"]

    session = ReportSession(SimpleNamespace(client=Client()))
    first = await session.call("read_chart_rows", {"id": "chart:7", "limit": 1})
    assert first["rows"] == [{"event_date": "2025-01-01", "revenue": 5}]
    assert first["coverage"] == "partial_query_rows"
    assert first["next_offset"] == 1
    assert "not dashboard filter" in first["scope"]
    second = await session.call("read_chart_rows", {"id": "7", "offset": 1})
    assert second["rows"] == [{"event_date": "2025-01-02", "revenue": 7}]
    assert second["coverage"] == "partial_query_rows"
    assert second["next_offset"] is None


@pytest.mark.asyncio
async def test_local_report_does_not_claim_a_notification():
    session = ReportSession(None)
    report = {"report": "Sales fell; investigate.", "evidence_refs": ["chart:7"], "missing_context": []}
    result = await session.call("submit_report", report)
    assert session.submission == report
    assert result["delivery"] == "local_trial_report_only"
