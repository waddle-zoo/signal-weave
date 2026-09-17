import json

import httpx

from evaluations.benchmark import _build_judger
from evaluations.cases import load_evaluation_cases
from evaluations.embedding_baseline import EmbeddingReasoningJudger
from signalweave.compiler import base_plan


def test_openai_benchmark_uses_a_valid_default_model(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    judger = _build_judger("openai")
    assert judger.model == "gpt-4o-mini"


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
                            "content": '{"outcome":"notify",'
                            '"rationale":"Related mobile evidence supports notification.",'
                            '"confidence":0.81,"watch_results":[{"key":"watch_0","probability":0.91}],'
                            '"question_results":[{"key":"question_0","probability":0.84}],'
                            '"probabilities":[{"key":"notify","probability":0.81},'
                            '{"key":"investigate","probability":0.19}]}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 8},
            },
        )

    case = next(case for case in load_evaluation_cases() if case.id == "mobile_conversion")
    card = case.card
    observations = [
        observation
        for resource in case.resources
        for observation in resource.observations
    ]
    judger = EmbeddingReasoningJudger(
        base_url="http://baseline/v1",
        model="luna",
        embedding_model="embedding-model",
        transport=httpx.MockTransport(handler),
    )
    state = {
        "evidence": [
            {
                "source_key": observation.source_key,
                "subject_id": observation.subject_id,
                "subject_label": observation.subject_label,
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
    assert [method.key for method in decision.delivery_methods] == ["growth", "engineering-oncall"]
    assert decision.confidence == 0.81
    assert [request.url.path for request in requests] == ["/v1/embeddings", "/v1/chat/completions"]
    assert judger.metrics.requests == 2
    assert judger.metrics.input_tokens == 42
    assert judger.metrics.output_tokens == 8


async def test_openai_responses_baseline_uses_strict_schema_and_counts_usage():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [1.0, 0.0]}
                        for index, _text in enumerate(payload["input"])
                    ],
                    "usage": {"prompt_tokens": 12},
                },
            )
        payload = json.loads(request.content)
        response_format = payload["text"]["format"]
        assert payload["store"] is False
        assert response_format["type"] == "json_schema"
        assert response_format["strict"] is True
        assert response_format["schema"]["additionalProperties"] is False
        assert response_format["schema"]["properties"]["probabilities"]["type"] == "array"
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "outcome": "notify",
                        "rationale": "Related mobile evidence supports notification.",
                        "confidence": 0.81,
                        "watch_results": [{"key": "watch_0", "probability": 0.91}],
                        "question_results": [{"key": "question_0", "probability": 0.84}],
                        "probabilities": [{"key": "notify", "probability": 0.81}],
                    }
                ),
                "usage": {"input_tokens": 30, "output_tokens": 8},
            },
        )

    case = next(case for case in load_evaluation_cases() if case.id == "mobile_conversion")
    observations = [
        observation
        for resource in case.resources
        for observation in resource.observations
    ]
    judger = EmbeddingReasoningJudger(
        base_url="http://baseline/v1",
        model="gpt-5.6-luna",
        embedding_model="text-embedding-3-small",
        api_key="test-only",
        transport=httpx.MockTransport(handler),
        responses_api=True,
    )
    state = {
        "evidence": [
            {
                "source_key": observation.source_key,
                "subject_id": observation.subject_id,
                "subject_label": observation.subject_label,
                "statement": "test evidence",
                "values": {},
            }
            for observation in observations
        ]
    }

    decision = await judger.judge(
        state,
        case.card,
        base_plan(case.card),
        observations,
    )

    assert decision.outcome.value == "notify"
    assert [method.key for method in decision.delivery_methods] == ["growth", "engineering-oncall"]
    assert decision.probabilities == {"notify": 0.81}
    assert [request.url.path for request in requests] == ["/v1/embeddings", "/v1/responses"]
    assert judger.metrics.requests == 2
    assert judger.metrics.input_tokens == 42
    assert judger.metrics.output_tokens == 8
