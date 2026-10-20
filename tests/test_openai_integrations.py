from __future__ import annotations

import asyncio
import json
import urllib.parse

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from signalweave import chatgpt_auth
from signalweave.compiler import base_plan
from signalweave.local_setup import SetupError, read_config, setup_local
from signalweave.local_status import local_status
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightPlan,
    Observation,
    Outcome,
    SourceRef,
)
from signalweave.openai_judger import (
    ChatGPTPlanResponsesTransport,
    OpenAIDecisionJudger,
    OpenAIDecisionsTransport,
)
from signalweave.typesafe_adapter import JevPayloadError


def test_openai_policy_packet_preserves_all_facts_without_unrequested_role_sampling():
    source = SourceRef(key="measure", adapter="mcp", resource="measure:1", label="Measure")
    card = InsightCard(id="preserve-policy-facts", title="Policy facts",
                       what_to_watch="Source-defined measures", why_watch="Repeat the agreed policy",
                       sources=[source], decision_guidance="Apply the confirmed rule.")
    observations = [Observation(source_key=source.key, subject_id=f"row-{i}",
                                subject_label=f"Row {i}", metric=f"measure-{i}",
                                current=i, attributes={"late_detail": "x" * 1100})
                    for i in range(29)]
    evidence = [Evidence(source_key=source.key, subject_id="sql-only", subject_label="SQL row",
                         statement="Source SQL values", values={f"field-{i}": i for i in range(30)},
                         provenance=["source:query-definition"]).model_dump(mode="json")]
    state = {"observations": [o.model_dump(mode="json") for o in observations],
             "evidence": evidence, "source_errors": [{"source_key": "optional", "blocking": False}],
             "analyses": [], "context": None}
    packet = OpenAIDecisionJudger._input_state(state, card, base_plan(card), observations)
    bundle = packet["evidence_bundle"]
    assert bundle["observations"] == state["observations"]
    assert bundle["evidence"] == evidence
    assert bundle["source_errors"] == state["source_errors"]
    assert "evidence_rollup" not in bundle and "source_details" not in bundle
    assert bundle["card"]["decision_guidance"] == card.decision_guidance


@pytest.mark.asyncio
async def test_openai_oversized_packet_uses_receipt_backed_frontier_handoff(tmp_path, monkeypatch):
    from tests.test_deferred_judgment_handoff import configured_server, read_all_pages, tool

    class NoInferenceTransport:
        name = "openai-decisions"

        async def decide(self, *_):
            raise AssertionError("Oversized input must not reach the provider")

    monkeypatch.setenv("SIGNALWEAVE_MAX_DECISION_INPUT_TOKENS", "1024")
    judger = OpenAIDecisionJudger(NoInferenceTransport())
    server, catalog = configured_server(tmp_path, observation_count=29, judger=judger)
    response = await tool(server, "evaluate_insight_card")(
        card_id="deferred-card", idempotency_key="openai-wide:1", response_mode="compact",
    )
    assert response["result"]["judgment"]["status"] == "deferred"
    assert response["result"]["outcome"] is None
    assert response["receipt"]["delivery_enabled"] is False
    rows = await read_all_pages(server, response["receipt"]["receipt_id"],
                                ["judgment_state", "observations"])
    assert len(rows) == 29
    assert rows[-1]["subject_id"] == "row-0028"
    before = catalog.inspect_count
    replay = await tool(server, "evaluate_insight_card")(
        card_id="deferred-card", idempotency_key="openai-wide:1", response_mode="compact",
    )
    assert replay["replayed"] is True and catalog.inspect_count == before


@pytest.mark.asyncio
async def test_openai_local_budget_failure_names_actual_provider(monkeypatch):
    monkeypatch.setenv("SIGNALWEAVE_MAX_DECISION_INPUT_TOKENS", "1")
    judger = OpenAIDecisionJudger(type("NoCalls", (), {"name": "openai-decisions"})())
    with pytest.raises(JevPayloadError, match="openai-decisions payload") as failure:
        await judger._ask({"fact": "keep this entire fact"}, [{"name": "outcome"}])
    assert failure.value.stage == "judgment"
    assert failure.value.budget_tokens == 1
    assert failure.value.observed_tokens > 1


@pytest.mark.asyncio
async def test_openai_engine_byte_budget_also_defers_without_dropping_source_facts(tmp_path, monkeypatch):
    from tests.test_deferred_judgment_handoff import configured_server, read_all_pages, tool

    class NoInferenceTransport:
        name = "openai-decisions"

        async def decide(self, *_):
            raise AssertionError("The engine byte guard must run before inference")

    monkeypatch.setenv("SIGNALWEAVE_MAX_DECISION_INPUT_TOKENS", "1000000")
    server, catalog = configured_server(tmp_path, observation_count=333,
                                        judger=OpenAIDecisionJudger(NoInferenceTransport()))
    store = server._test_runtime.card_store
    card = store.get_card("deferred-card")
    anchor = card.sources[0]
    store.save_card(card.model_copy(update={"sources": [anchor, *[
        anchor.model_copy(update={"key": f"growth-{i}", "resource": f"dashboard:{7+i}"})
        for i in (1, 2)
    ]]}))
    catalog.resources.extend([
        catalog.resources[0].model_copy(update={"resource": f"dashboard:{7+i}"})
        for i in (1, 2)
    ])
    original_inspect = catalog.inspect

    async def wide_inspect(source):
        snapshot = await original_inspect(source)
        return snapshot.model_copy(update={"observations": [
            row.model_copy(update={"attributes": {**row.attributes, "detail": "x" * 2500}})
            for row in snapshot.observations
        ]})

    monkeypatch.setattr(catalog, "inspect", wide_inspect)
    response = await tool(server, "evaluate_insight_card")(
        card_id="deferred-card", idempotency_key="openai-byte-wide:1", response_mode="compact",
    )
    assert response["result"]["judgment"]["status"] == "deferred"
    budget = response["result"]["judgment"]["input_budget"]
    assert budget["stage"] == "judgment"
    assert budget["observed_bytes"] > budget["budget_bytes"] == 4_000_000
    assert budget["observed_tokens"] is None
    rows = await read_all_pages(server, response["receipt"]["receipt_id"],
                                ["judgment_state", "observations"])
    assert len(rows) == 999 and rows[-1]["attributes"]["detail"] == "x" * 2500
    assert response["receipt"]["delivery_enabled"] is False
    assert response["result"]["outcome"] is None


@pytest.mark.asyncio
async def test_openai_budget_counts_decoded_input_not_http_string_escaping(monkeypatch):
    from signalweave.typesafe_adapter import estimate_json_tokens

    state = {"facts": [{"field": "a quoted value", "value": i} for i in range(30)]}
    questions = [{"name": "outcome", "type": "choice", "choices": [{"value": "review"}]}]
    decoded = estimate_json_tokens({"input": state, "questions": questions})
    escaped = estimate_json_tokens({"input": json.dumps(state, separators=(",", ":")),
                                    "questions": questions})
    assert escaped > decoded
    monkeypatch.setenv("SIGNALWEAVE_MAX_DECISION_INPUT_TOKENS", str(decoded))

    class CaptureTransport:
        name = "openai-decisions"

        async def decide(self, input_text, received_questions):
            assert json.loads(input_text) == state
            assert received_questions == questions
            return {"outcome": {"type": "choice", "choice": "review"}}

    assert (await OpenAIDecisionJudger(CaptureTransport())._ask(state, questions))["outcome"]["choice"] == "review"


def _choice(name: str, selected: str, distribution: dict[str, float]) -> dict:
    return {
        "name": name,
        "type": "choice",
        "choice": selected,
        "probabilities": [
            {"value": key, "probability": value} for key, value in distribution.items()
        ],
        "confidence": distribution[selected],
    }


def test_openai_decisions_transport_sends_typed_request_and_parses_native_answers():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "answers": [
                    {"name": "supported", "type": "predicate", "probability": 0.84},
                    _choice("route", "notify", {"ignore": 0.1, "notify": 0.9}),
                ]
            },
        )

    transport = OpenAIDecisionsTransport("test-openai-key", transport=httpx.MockTransport(handler))
    questions = [
        {"type": "predicate", "name": "supported", "instructions": "Is it supported?"},
        {
            "type": "choice",
            "name": "route",
            "instructions": "Choose",
            "choices": [
                {"value": "ignore", "description": "No action"},
                {"value": "notify", "description": "Notify"},
            ],
        },
    ]

    answers = asyncio.run(transport.decide('{"evidence":[]}', questions))

    assert len(seen) == 1
    assert seen[0].url.path == "/v1/decisions"
    assert seen[0].headers["authorization"] == "Bearer test-openai-key"
    payload = json.loads(seen[0].content)
    assert payload["model"] == transport.model
    assert payload["input"] == '{"evidence":[]}'
    assert payload["questions"] == questions
    assert answers["supported"] == {"type": "predicate", "probability": 0.84}
    assert answers["route"]["choice"] == "notify"
    assert answers["route"]["probabilities"] == {"ignore": 0.1, "notify": 0.9}
    assert set(answers) == {"supported", "route"}


def test_decisions_transport_rejects_refusals_and_omitted_answers():
    transport = OpenAIDecisionsTransport(
        "test-key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"answers": [{"name": "supported", "type": "refusal"}]},
            )
        ),
    )
    question = [{"type": "predicate", "name": "supported", "instructions": "Is it supported?"}]
    with pytest.raises(RuntimeError, match="refused"):
        asyncio.run(transport.decide("synthetic", question))

    omitted = OpenAIDecisionsTransport(
        "test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"answers": []})),
    )
    with pytest.raises(RuntimeError, match="omitted answers"):
        asyncio.run(omitted.decide("synthetic", question))


def test_decisions_transport_rejects_malformed_probability_distributions():
    transport = OpenAIDecisionsTransport(
        "test-key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "answers": [
                        _choice("route", "notify", {"ignore": 0.2, "notify": 0.2}),
                    ]
                },
            )
        ),
    )
    with pytest.raises(RuntimeError, match="invalid typed response"):
        asyncio.run(
            transport.decide(
            "{}",
            [
                {
                    "type": "choice",
                    "name": "route",
                    "choices": [
                        {"value": "ignore"},
                        {"value": "notify"},
                    ],
                }
            ],
            )
        )


def test_decisions_transport_restricts_model_to_officially_supported_choice(monkeypatch):
    monkeypatch.setenv("OPENAI_DECISIONS_MODEL", "gpt-6.1-sol")
    with pytest.raises(ValueError, match="only gpt-6-luna"):
        OpenAIDecisionsTransport("test-key")


def test_chatgpt_plan_transport_uses_streaming_nonstored_responses_and_marks_estimates():
    seen: list[httpx.Request] = []
    output = {
        "watch_0": {
            "choice": "present",
            "probabilities": {"present": 0.9, "absent": 0.05, "unknown": 0.05},
            "confidence": 0.9,
        },
        "outcome": {
            "choice": "investigate",
            "probabilities": {"ignore": 0.05, "investigate": 0.9, "insufficient_data": 0.05},
            "confidence": 0.9,
        },
    }
    event = {"type": "response.completed", "response": {"output_text": json.dumps(output)}}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")

    transport = ChatGPTPlanResponsesTransport(
        lambda: "test-oauth-token", transport=httpx.MockTransport(handler)
    )
    questions = [
        {
            "type": "choice",
            "name": "watch_0",
            "choices": [
                {"value": "present"},
                {"value": "absent"},
                {"value": "unknown"},
            ],
        },
        {
            "type": "choice",
            "name": "outcome",
            "choices": [
                {"value": "ignore"},
                {"value": "investigate"},
                {"value": "insufficient_data"},
            ],
        },
    ]

    answers = asyncio.run(transport.decide("evidence", questions))

    payload = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/responses"
    assert seen[0].headers["authorization"] == "Bearer test-oauth-token"
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["text"]["format"]["type"] == "json_schema"
    assert "not calibrated API-native class probabilities" in payload["instructions"]
    assert answers["outcome"]["choice"] == "investigate"
    assert answers["outcome"]["probabilities"]["investigate"] == 0.9


@pytest.mark.parametrize(
    ("selected", "support", "expected"),
    [
        pytest.param(Outcome.IGNORE, 0.6, Outcome.INVESTIGATE, id="low-support-ignore"),
        pytest.param(Outcome.INVESTIGATE, 0.6, Outcome.INVESTIGATE, id="low-support-investigate"),
        pytest.param(
            Outcome.INSUFFICIENT_DATA,
            0.6,
            Outcome.INSUFFICIENT_DATA,
            id="low-support-insufficient-data-handoff",
        ),
        pytest.param(Outcome.NOTIFY, 0.6, Outcome.INVESTIGATE, id="low-support-notify"),
        pytest.param(Outcome.ESCALATE, 0.6, Outcome.INVESTIGATE, id="low-support-escalate"),
        pytest.param(Outcome.IGNORE, 0.7, Outcome.IGNORE, id="threshold-ignore"),
        pytest.param(Outcome.INVESTIGATE, 0.7, Outcome.INVESTIGATE, id="threshold-investigate"),
        pytest.param(
            Outcome.INSUFFICIENT_DATA,
            0.7,
            Outcome.INSUFFICIENT_DATA,
            id="threshold-insufficient-data",
        ),
        pytest.param(Outcome.NOTIFY, 0.7, Outcome.NOTIFY, id="threshold-notify"),
        pytest.param(Outcome.ESCALATE, 0.7, Outcome.ESCALATE, id="threshold-escalate"),
    ],
)
def test_judger_routes_by_support_floor_and_preserves_typed_handoff(
    selected: Outcome, support: float, expected: Outcome
):
    """Route low support safely while preserving the provider's handoff support."""

    configured_outcomes = [
        Outcome.IGNORE,
        Outcome.INVESTIGATE,
        Outcome.INSUFFICIENT_DATA,
        Outcome.NOTIFY,
        Outcome.ESCALATE,
    ]
    outcome_values = [outcome.value for outcome in configured_outcomes]

    def distribution(values: list[str], choice: str, choice_support: float) -> dict[str, float]:
        other_support = (1.0 - choice_support) / (len(values) - 1)
        return {
            value: choice_support if value == choice else other_support
            for value in values
        }

    class FakeTypedTransport:
        name = "test-provider"

        def __init__(self):
            self.questions: list[dict] = []

        async def decide(self, _input: str, questions: list[dict]) -> dict:
            self.questions = questions
            answers = {}
            for question in questions:
                name = question["name"]
                if question["type"] == "predicate":
                    answers[name] = {"type": "predicate", "probability": 0.8}
                    continue

                choices = [item["value"] for item in question["choices"]]
                choice = selected.value if name == "outcome" else choices[0]
                choice_support = support if name == "outcome" else 0.8
                probabilities = distribution(choices, choice, choice_support)
                answers[name] = {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": probabilities,
                    "confidence": probabilities[choice],
                }
            return answers

    card = InsightCard(
        id="generic-watch",
        title="Generic watch",
        what_to_watch="A generic monitored condition",
        why_watch="Route only when the typed decision supports it.",
        watch_for=["A generic condition is present"],
        questions=["Is the generic condition supported?"],
        decision_guidance="Apply the configured policy to the supplied evidence.",
        action_confidence_threshold=0.7,
        sources=[SourceRef(key="source", adapter="superset", resource="chart:1", label="Source")],
        delivery_methods=[
            DeliveryMethod(
                key="notify-route",
                outcome=Outcome.NOTIFY,
                label="Notify route",
                destination="slack://generic-notify",
            ),
            DeliveryMethod(
                key="escalate-route",
                outcome=Outcome.ESCALATE,
                label="Escalate route",
                destination="slack://generic-escalate",
            ),
        ],
    )
    plan = InsightPlan(
        card_id=card.id,
        selected_source_keys=["source"],
        comparison_windows=["previous_period"],
        capabilities=[],
        card_scope="generic",
    )
    transport = FakeTypedTransport()
    result = asyncio.run(
        OpenAIDecisionJudger(transport).judge(
            {"evidence": [], "analyses": []}, card, plan, []
        )
    )

    expected_distribution = distribution(outcome_values, selected.value, support)
    outcome_question = next(item for item in transport.questions if item["name"] == "outcome")
    assert {item["value"] for item in outcome_question["choices"]} == set(outcome_values)
    assert result.outcome == expected
    assert result.confidence == pytest.approx(support)
    assert result.probabilities == pytest.approx(expected_distribution)
    assert set(result.probabilities) == set(outcome_values)
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.watch_results[0].status.value == "present"
    assert result.question_results[0].status.value == "supported"

    if selected == Outcome.INSUFFICIENT_DATA and support < card.action_confidence_threshold:
        # Keep provider support with the data-gap handoff; it is not a business
        # confidence guarantee.
        assert result.outcome == Outcome.INSUFFICIENT_DATA
        assert result.confidence == pytest.approx(0.6)
        assert result.probabilities == pytest.approx(expected_distribution)
        assert "selected=insufficient_data, support=0.60; routed=insufficient_data." in result.rationale


@pytest.mark.parametrize(
    ("origins", "analysis_count", "source_evidence_count"),
    [
        pytest.param(["source"] * 6, 0, 6, id="sql-evidence-only"),
        pytest.param(["derived", "context"], 2, 0, id="derived-and-context-only"),
    ],
)
def test_openai_judger_summary_counts_source_evidence_separately(
    origins, analysis_count, source_evidence_count
):
    class FakeTypedTransport:
        name = "openai-decisions-test-double"

        async def decide(self, _input: str, questions: list[dict]) -> dict:
            answers = {}
            for question in questions:
                choices = [item["value"] for item in question["choices"]]
                selected = "notify" if question["name"] == "outcome" else choices[0]
                support = 0.9
                remainder = (1.0 - support) / (len(choices) - 1)
                probabilities = {
                    choice: support if choice == selected else remainder
                    for choice in choices
                }
                answers[question["name"]] = {
                    "type": "choice",
                    "choice": selected,
                    "probabilities": probabilities,
                    "confidence": support,
                }
            return answers

    source = SourceRef(
        key="sql-records", adapter="sql", resource="query:records", label="SQL records"
    )
    card = InsightCard(
        id="sql-evidence-summary",
        title="SQL evidence summary",
        what_to_watch="The supplied SQL evidence.",
        why_watch="Apply the configured policy.",
        sources=[source],
        decision_guidance="Notify when the supplied evidence supports the policy.",
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Ops",
                destination="agent://ops",
            )
        ],
    )
    evidence = [
        Evidence(
            source_key=source.key,
            subject_id=f"row-{index}",
            subject_label=f"Row {index}",
            statement=f"Evidence record {index}.",
            origin=origin,
        ).model_dump(mode="json")
        for index, origin in enumerate(origins)
    ]
    state = {
        "evidence": evidence,
        "analyses": [
            {"source_key": source.key, "status": "complete"}
            for _ in range(analysis_count)
        ],
        "source_errors": (
            [{"source_key": source.key, "message": "Stale source evidence."}]
            if "derived" in origins
            else []
        ),
        "context": None,
    }

    result = asyncio.run(
        OpenAIDecisionJudger(FakeTypedTransport()).judge(
            state,
            card,
            InsightPlan(
                card_id=card.id,
                selected_source_keys=[source.key],
                comparison_windows=["previous_period"],
                capabilities=[],
                card_scope="sql-records",
            ),
            [],
        )
    )

    assert (
        f"Evaluated {source_evidence_count} source evidence items, 0 normalized "
        f"observations, and {analysis_count} computed analyses"
    ) in result.summary
    assert [item.model_dump(mode="json") for item in result.evidence] == evidence
    assert result.outcome == Outcome.NOTIFY


def test_setup_stores_openai_key_privately_and_selects_requested_provider(tmp_path):
    key_file = tmp_path / "openai-input"
    key_file.write_text("sk-test-openai-secret\n", encoding="utf-8")
    key_file.chmod(0o600)
    home = tmp_path / "signalweave"

    setup_local(
        home,
        decision_provider="openai-decisions",
        openai_key_file=key_file,
        source="skip",
        non_interactive=True,
    )

    _, config = read_config(home)
    assert config["SIGNALWEAVE_DECISION_PROVIDER"] == "openai-decisions"
    assert config["OPENAI_API_KEY_FILE"] == "openai.key"
    assert "sk-test-openai-secret" not in (home / "config.toml").read_text()
    assert (home / "openai.key").read_text() == "sk-test-openai-secret\n"
    assert (home / "openai.key").stat().st_mode & 0o777 == 0o600
    status = local_status(home)
    assert status["decision_provider"]["selected"] == "openai-decisions"
    assert status["decision_provider"]["status"] == "configured"
    assert status["jev"]["status"] == "not_selected"


def test_chatgpt_oauth_pkce_signin_saves_private_tokens_and_refreshes_rotation(
    tmp_path, monkeypatch
):
    home = tmp_path / "private-home"
    token_calls: list[dict[str, str]] = []
    browser_url: list[str] = []

    def token_handler(request: httpx.Request) -> httpx.Response:
        form = urllib.parse.parse_qs(request.content.decode())
        token_calls.append({key: values[0] for key, values in form.items()})
        if form["grant_type"][0] == "authorization_code":
            return httpx.Response(
                200,
                json={
                    "id_token": "test-id-token",
                    "token_type": "Bearer",
                    "access_token": "first-access",
                    "refresh_token": "first-refresh",
                    "expires_in": 3600,
                    "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": "second-access",
                "token_type": "Bearer",
                "refresh_token": "second-refresh",
                "expires_in": 3600,
                "scope": "resource.invoke chatgpt.tokens.use.direct",
            },
        )

    monkeypatch.setattr(
        chatgpt_auth,
        "_validate_id_token",
        lambda _token, *, client_id, nonce: {
            "sub": "user-1",
            "email": "person@example.test",
            "nonce": nonce,
        },
    )

    class FakeLoopbackServer:
        server_port = 43125
        timeout = None

        def __init__(self, _address, _handler):
            pass

        def handle_request(self):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(browser_url[0]).query)
            self.oauth_result = {
                "code": "authorization-code",
                "state": params["state"][0],
                "client_id": "signalweave-client-id",
            }

        def server_close(self):
            return None

    monkeypatch.setattr(chatgpt_auth.http.server, "HTTPServer", FakeLoopbackServer)

    def open_browser(url: str) -> bool:
        browser_url.append(url)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert params["client_id"] == ["dynamic_agent_client"]
        assert params["code_challenge_method"] == ["S256"]
        assert "resource.invoke" in params["scope"][0]
        assert "chatgpt.tokens.use.direct" in params["scope"][0]
        return True

    state = chatgpt_auth.login(
        home,
        timeout_seconds=5,
        open_browser=open_browser,
        transport=httpx.MockTransport(token_handler),
    )

    assert state["status"] == "connected"
    assert state["account"] == "person@example.test"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(browser_url[0]).query)["redirect_uri"] == [
        "http://127.0.0.1:43125/auth/callback"
    ]
    assert (home / chatgpt_auth.AUTH_FILE).stat().st_mode & 0o777 == 0o600
    assert (home / chatgpt_auth.HOST_FILE).stat().st_mode & 0o777 == 0o600

    import json as json_module

    record_path = home / chatgpt_auth.AUTH_FILE
    record = json_module.loads(record_path.read_text())
    record["expires_at"] = 0
    record_path.write_text(json_module.dumps(record))
    record_path.chmod(0o600)
    access_token = asyncio.run(
        chatgpt_auth.get_access_token(home, transport=httpx.MockTransport(token_handler))
    )

    assert access_token == "second-access"
    assert token_calls[0]["grant_type"] == "authorization_code"
    assert token_calls[0]["code_verifier"]
    assert token_calls[1]["grant_type"] == "refresh_token"
    refreshed = json_module.loads(record_path.read_text())
    assert refreshed["refresh_token"] == "second-refresh"
    assert refreshed["token_type"] == "Bearer"
    assert record_path.stat().st_mode & 0o777 == 0o600


def test_chatgpt_invalid_refresh_grant_marks_reauthorization_without_losing_identity(
    tmp_path, monkeypatch
):
    home = tmp_path / "private-home"

    def token_handler(request: httpx.Request) -> httpx.Response:
        form = urllib.parse.parse_qs(request.content.decode())
        if form["grant_type"][0] == "authorization_code":
            return httpx.Response(
                200,
                json={
                    "id_token": "test-id-token",
                    "token_type": "Bearer",
                    "access_token": "first-access",
                    "refresh_token": "first-refresh",
                    "expires_in": 3600,
                    "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                },
            )
        return httpx.Response(
            400,
            headers={"openai-request-id": "req_test_123"},
            json={"error": {"code": "invalid_grant"}},
        )

    monkeypatch.setattr(
        chatgpt_auth,
        "_validate_id_token",
        lambda _token, *, client_id, nonce: {"sub": "user-1", "email": "person@example.test"},
    )

    class FakeLoopbackServer:
        server_port = 43126
        timeout = None

        def __init__(self, _address, _handler):
            pass

        def handle_request(self):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(browser_url[0]).query)
            self.oauth_result = {
                "code": "authorization-code",
                "state": params["state"][0],
                "client_id": "signalweave-client-id",
            }

        def server_close(self):
            return None

    browser_url: list[str] = []
    monkeypatch.setattr(chatgpt_auth.http.server, "HTTPServer", FakeLoopbackServer)
    chatgpt_auth.login(
        home,
        timeout_seconds=5,
        open_browser=lambda url: browser_url.append(url) is None or True,
        transport=httpx.MockTransport(token_handler),
    )
    record_path = home / chatgpt_auth.AUTH_FILE
    record = json.loads(record_path.read_text())
    record["expires_at"] = 0
    record_path.write_text(json.dumps(record))
    record_path.chmod(0o600)

    with pytest.raises(SetupError, match="invalid.*req_test_123"):
        asyncio.run(
            chatgpt_auth.get_access_token(home, transport=httpx.MockTransport(token_handler))
        )

    stored = json.loads(record_path.read_text())
    assert stored["reauth_required"] is True
    assert stored["subject"] == "user-1"
    assert stored["client_id"] == "signalweave-client-id"
    assert not {"access_token", "refresh_token", "expires_at"} & set(stored)
    assert chatgpt_auth.auth_status(home)["status"] == "reauth_required"


def test_chatgpt_login_rejects_invalid_timeout_without_creating_auth_state(tmp_path):
    home = tmp_path / "signalweave"
    with pytest.raises(SetupError, match="timeout must be a positive"):
        chatgpt_auth.login(home, timeout_seconds=0)
    assert not (home / chatgpt_auth.AUTH_FILE).exists()


def test_chatgpt_login_rejects_oauth_state_mismatch_before_token_exchange(tmp_path, monkeypatch):
    class CallbackServer:
        server_port = 43211
        timeout = None

        def __init__(self, _address, _handler):
            pass

        def handle_request(self):
            self.oauth_result = {
                "code": "attacker-code",
                "state": "wrong-state",
                "client_id": "attacker-client",
            }

        def server_close(self):
            return None

    def should_not_exchange(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected token exchange: {request.url}")

    monkeypatch.setattr(chatgpt_auth.http.server, "HTTPServer", CallbackServer)
    with pytest.raises(SetupError, match="state did not match"):
        chatgpt_auth.login(
            tmp_path / "signalweave",
            timeout_seconds=2,
            open_browser=lambda _url: True,
            transport=httpx.MockTransport(should_not_exchange),
        )
    assert not (tmp_path / "signalweave" / chatgpt_auth.AUTH_FILE).exists()


def test_recursive_unverified_jwt_is_rejected_before_jwks_network_access(monkeypatch):
    jwt = chatgpt_auth.jwt
    client = jwt.PyJWKClient(chatgpt_auth.JWKS_URL)
    monkeypatch.setattr(client, "fetch_data", lambda: pytest.fail("malformed token reached JWKS"))
    encode = jwt.utils.base64url_encode
    token = b".".join((encode(b'{"alg":"RS256"}'),
                       encode(b"[" * 20000 + b"]" * 20000), encode(b"invalid-signature"))).decode()
    with pytest.raises(jwt.InvalidTokenError):
        client.get_signing_key_from_jwt(token)


def test_chatgpt_id_token_validation_checks_signature_issuer_audience_and_nonce(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        chatgpt_auth.jwt,
        "PyJWKClient",
        lambda *_args, **_kwargs: type(
            "Jwks", (), {"get_signing_key_from_jwt": lambda _self, _token: type("Key", (), {"key": private_key.public_key()})()}
        )(),
    )
    claims = {
        "iss": chatgpt_auth.ISSUER,
        "aud": "registered-client",
        "sub": "synthetic-subject",
        "nonce": "expected-nonce",
        "iat": int(chatgpt_auth.time.time()),
        "exp": int(chatgpt_auth.time.time()) + 300,
    }
    token = chatgpt_auth.jwt.encode(claims, private_key, algorithm="RS256")

    validated = chatgpt_auth._validate_id_token(
        token, client_id="registered-client", nonce="expected-nonce"
    )
    assert validated["sub"] == "synthetic-subject"
    with pytest.raises(SetupError, match="nonce did not match"):
        chatgpt_auth._validate_id_token(
            token, client_id="registered-client", nonce="different-nonce"
        )
    with pytest.raises(SetupError, match="could not be verified"):
        chatgpt_auth._validate_id_token(
            token, client_id="different-client", nonce="expected-nonce"
        )
