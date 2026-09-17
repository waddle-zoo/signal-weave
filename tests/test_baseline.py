import httpx

from evaluations.cases import load_evaluation_cases
from evaluations.embedding_baseline import EmbeddingReasoningJudger
from semantic_monitor.compiler import base_plan


async def test_embedding_reasoning_adapter_uses_two_calls_and_typed_json():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [1.0, 0.0]},
                        {"index": 1, "embedding": [0.9, 0.1]},
                    ],
                    "usage": {"prompt_tokens": 12, "total_tokens": 12},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"outcome":"notify","recipient_key":"growth",'
                            '"rationale":"Related mobile evidence supports notification.",'
                            '"confidence":0.81,"probabilities":{"notify":0.81,"investigate":0.19}}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 8},
            },
        )

    case = next(case for case in load_evaluation_cases() if case.id == "mobile_conversion")
    dashboard = case.dashboard
    observations = [
        observation
        for chart in dashboard.charts
        for observation in chart.observations
    ]
    card = case.monitor_card
    judger = EmbeddingReasoningJudger(
        base_url="http://baseline/v1",
        model="luna",
        embedding_model="embedding-model",
        transport=httpx.MockTransport(handler),
    )
    state = {
        "evidence": [
            {
                "chart_id": observation.chart_id,
                "chart_title": observation.chart_title,
                "statement": "test evidence",
                "values": {},
            }
            for observation in observations
        ]
    }

    decision = await judger.judge(
        state,
        card,
        base_plan(card),
        observations,
    )

    assert decision.outcome.value == "notify"
    assert decision.recipient_key == "growth"
    assert decision.confidence == 0.81
    assert [request.url.path for request in requests] == ["/v1/embeddings", "/v1/chat/completions"]
    assert judger.metrics.requests == 2
    assert judger.metrics.input_tokens == 42
    assert judger.metrics.output_tokens == 8
