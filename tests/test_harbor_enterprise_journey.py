"""Preparation must not smuggle an expert's monitoring query into onboarding."""
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import harbor_enterprise_journey as journey
from evaluations.harbor_enterprise_fixture import build_fixture
from signalweave.mcp_source import MCPConnection


def test_initial_manifest_contains_only_source_owned_tier_definitions(tmp_path):
    value = journey.manifest(tmp_path / "active.sqlite3")
    connection = MCPConnection.model_validate(value["connections"][0])
    assert connection.context_namespace == journey.SOURCE_ID
    assert len(connection.resources) == 1
    source = connection.resources[0]
    assert source.descriptor.resource == journey.INITIAL_RESOURCE
    assert source.arguments["sql"] == "SELECT * FROM support_tier_sla ORDER BY support_tier"
    assert "ticket" not in source.arguments["sql"].lower()
    assert "2026" not in str(source.model_dump())
    assert "decision" not in source.arguments
    assert str(tmp_path / "active.sqlite3") in connection.transport.command
    assert "reviewer" not in str(value) and "private/full-history" not in str(value)


def test_verify_rejects_changed_method_before_reading_native_or_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(journey, "method", lambda: {"frozen": "current"})
    monkeypatch.setattr(journey, "verify_binary", lambda *args: pytest.fail("no binary read"))
    with pytest.raises(ValueError, match="method changed"):
        journey.verify({"protocol": journey.PROTOCOL, "method": {"frozen": "old"}}, tmp_path)


def test_actor_rejects_stale_prepared_manifest_before_claim(tmp_path, monkeypatch):
    """Old setup output without key_file must not consume an actor attempt."""
    root = tmp_path / "stale-study"
    root.mkdir()
    stale_study = {"protocol": journey.PROTOCOL, "method": journey.method()}
    (root / "study.json").write_text(json.dumps(stale_study), encoding="utf-8")
    monkeypatch.setattr(
        journey, "verify_binary", lambda *args: pytest.fail("stale manifest reached binary verification")
    )

    with pytest.raises(ValueError, match="Prepared study is incomplete"):
        asyncio.run(journey.actor(root, "baseline", "queue-onboarding", root / "review.json"))

    assert not list(root.glob("*.claimed"))
    assert not list(root.glob("actor-baseline-queue-onboarding*"))


def test_method_identity_includes_source_and_shared_transport_not_generated_answers():
    identities = journey.method()
    assert "evaluations/available_history.py" in identities
    assert "evaluations/company_people.py" in identities
    assert "skills/signalweave/SKILL.md" in identities
    assert all(Path(name).parts[0] != "artifacts" for name in identities)
    assert all(len(digest) == 64 for digest in identities.values())


def _cutoffs(count):
    start = datetime(2026, 2, 23, 6, tzinfo=timezone.utc)
    return [
        (start + timedelta(days=day)).isoformat().replace("+00:00", "Z")
        for day in range(count)
    ]


def _role_deck(effective_at="2027-01-01T00:00:00Z", message="The support commitment changed."):
    fields = {
        "role_brief": "A fictional Harbor employee.",
        "business_knowledge": "Knows their ordinary work.",
        "known_unknowns": "Does not know all source semantics.",
        "authority": "Can clarify their own team's work.",
    }
    people = {
        key: dict(fields)
        for key in ("owner", "queue-lead", "duty-manager", "operations", "data-operations")
    }
    return {
        "people": people,
        "planned_change": {"effective_at": effective_at, "message": message},
    }


class _Audit:
    def __init__(self):
        self.events = []
        self.world = None
        self.conversation_at_policy_event = None

    def emit(self, kind, **payload):
        self.events.append({"kind": kind, **payload})
        if kind == "company.owner_policy_event":
            self.conversation_at_policy_event = list(
                self.world.state["conversations"]["owner"]
            )


def _make_caller(tmp_path, *, arm="baseline", cutoffs=None, roles=None, native=None):
    cutoffs = cutoffs or _cutoffs(9)
    root = tmp_path / "study"
    workspace = root / arm / "workspace"
    workspace.mkdir(parents=True)
    roles_path = root / "roles.json"
    roles_path.write_text(json.dumps(roles or _role_deck()), encoding="utf-8")
    audit = _Audit()
    study = {
        "cutoffs": cutoffs,
        "roles": str(roles_path),
        "source_fixture": str(tmp_path / "source-fixture"),
        "codex": {"path": "/offline/fake-codex"},
    }
    caller = journey.Caller(study, root, arm, object(), native, audit)
    return caller, audit, roles_path


async def _register_baseline(caller, monitors):
    helper = caller.workspace / "policy.py"
    helper.write_text(
        "import json\n"
        "# Agent-authored policy fixture; the fake transport never executes it.\n"
        "def decide(source_result):\n"
        "    return {'outcome': 'ignore', 'evidence': source_result}\n",
        encoding="utf-8",
    )
    authored = []
    for monitor_id, cadence in monitors:
        authored.append(
            {
                "monitor_id": monitor_id,
                "cadence": cadence,
                "sql": "SELECT support_tier FROM support_tier_sla",
                "helper_path": "policy.py",
            }
        )
    (caller.workspace / "procedure.json").write_text(
        json.dumps({"monitors": authored}), encoding="utf-8"
    )
    await caller.register_procedure({"procedure_file": "procedure.json"})
    return helper


def _patch_clock_copy(monkeypatch):
    def copy_cutoff(_fixture, cutoff, destination):
        Path(destination).write_bytes(cutoff.encode("utf-8"))
        return {"as_of_utc": cutoff}

    monkeypatch.setattr(journey, "copy_active_snapshot", copy_cutoff)


def _patch_fake_check(monkeypatch, outcome_for=None):
    calls = []
    outcome_for = outcome_for or (lambda _monitor, _call_index: "ignore")

    async def fake_check(arm, monitors, **kwargs):
        call_index = len(calls)
        workspace = Path(kwargs["workspace"])
        call = {
            "arm": arm,
            "monitors": [
                {"monitor_id": item.monitor_id, "cutoff": item.cutoff}
                for item in monitors
            ],
        }
        calls.append(call)
        ledger = []
        for index, monitor in enumerate(monitors):
            outcome = outcome_for(monitor, call_index)
            source_result = {"rows": [{"monitor": monitor.monitor_id, "value": 3}]}
            source_bytes = json.dumps(
                source_result, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            input_value = {
                "monitor_id": monitor.monitor_id,
                "cutoff": monitor.cutoff,
                "sql": monitor.sql,
                "source_result": source_result,
            }
            input_bytes = json.dumps(
                input_value, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            decision = {"outcome": outcome, "evidence": [monitor.monitor_id]}
            result_bytes = json.dumps(
                decision, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            evidence_dir = workspace / f"fake-evidence-{call_index:03d}-{index:03d}"
            evidence_dir.mkdir()
            source_path = evidence_dir / "actual.json"
            result_path = evidence_dir / "decision.json"
            source_path.write_bytes(input_bytes)
            result_path.write_bytes(result_bytes)
            ledger.append(
                {
                    "sequence": index,
                    "monitor_id": monitor.monitor_id,
                    "cutoff": monitor.cutoff,
                    "status": "completed",
                    "outcome": outcome,
                    "decision": decision,
                    "source_result": source_result,
                    "source_ref": str(source_path.relative_to(workspace)),
                    "source_result_bytes": len(source_bytes),
                    "source_result_sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "input_bytes": len(input_bytes),
                    "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
                    "result_ref": str(result_path.relative_to(workspace)),
                    "result_bytes": len(result_bytes),
                    "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
                }
            )
        return {
            "arm": arm,
            "run_id": kwargs["run_id"],
            "workspace": str(workspace),
            "ledger": ledger,
            "known_errors": [],
            "business_grade": None,
        }

    monkeypatch.setattr("evaluations.enterprise_policy_caller.check_once", fake_check)
    monkeypatch.setattr(journey, "public_paths", lambda _workspace: [])
    return calls


def test_baseline_helper_is_frozen_and_notify_is_not_hidden_by_a_policy_gate(
    tmp_path, monkeypatch
):
    caller, _audit, _roles_path = _make_caller(tmp_path, cutoffs=_cutoffs(3))
    helper = asyncio.run(_register_baseline(caller, [("daily-queue", "daily")]))
    registered_hash = caller.state["procedure"]["procedure"]["monitors"][0][
        "helper_sha256"
    ]
    assert registered_hash == journey.sha(helper)

    helper.write_text(helper.read_text(encoding="utf-8") + "# changed after registration\n")
    calls = _patch_fake_check(monkeypatch)
    changed = asyncio.run(caller.run_until_review({}))
    assert changed["needs_setup"] is True
    assert calls == []

    helper.write_text(
        "import json\n"
        "def decide(source_result):\n"
        "    return {'outcome': 'notify', 'evidence': source_result}\n",
        encoding="utf-8",
    )
    # Register the exact new revision and verify the existing B fallback reaches
    # its own helper outcome even on a non-reporting weekday.
    (caller.workspace / "procedure.json").write_text(
        json.dumps(
            {
                "monitors": [
                    {
                        "monitor_id": "daily-queue",
                        "cadence": "daily",
                        "sql": "SELECT support_tier FROM support_tier_sla",
                        "helper_path": "policy.py",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    asyncio.run(caller.register_procedure({"procedure_file": "procedure.json"}))
    caller.state["day"] = 1
    calls = _patch_fake_check(monkeypatch, lambda _monitor, _call_index: "notify")
    result = asyncio.run(caller.run_until_review({}))
    assert calls[0]["arm"] == "B"
    assert result["attention"] is True
    assert result["checks"][0]["monitors"][0]["outcome"] == "notify"


def test_daily_and_weekly_monitors_follow_frozen_cutoffs_and_return_for_weekly_review(
    tmp_path, monkeypatch
):
    cutoffs = _cutoffs(9)
    caller, _audit, _roles_path = _make_caller(tmp_path, cutoffs=cutoffs)
    asyncio.run(
        _register_baseline(caller, [("daily", "daily"), ("weekly", "weekly")])
    )
    _patch_clock_copy(monkeypatch)
    calls = _patch_fake_check(monkeypatch)

    first = asyncio.run(caller.run_until_review({}))
    assert first["source_cutoff"] == cutoffs[0]
    assert [item["monitor_id"] for item in calls[0]["monitors"]] == ["daily", "weekly"]

    asyncio.run(caller.advance())
    weekly = asyncio.run(caller.run_until_review({}))
    assert weekly["source_cutoff"] == cutoffs[7]
    assert weekly["weekly_report_due"] is True
    assert [item["source_cutoff"] for item in weekly["checks"]] == cutoffs[1:8]
    observed = {item["monitor_id"]: [] for item in calls[0]["monitors"]}
    for call in calls:
        for monitor in call["monitors"]:
            observed[monitor["monitor_id"]].append(monitor["cutoff"])
    assert observed["daily"] == cutoffs[:8]
    assert observed["weekly"] == [cutoffs[0], cutoffs[7]]


def test_quiet_intermediate_check_ledger_and_actual_refs_reach_the_review_result(
    tmp_path, monkeypatch
):
    cutoffs = _cutoffs(9)
    caller, _audit, _roles_path = _make_caller(tmp_path, cutoffs=cutoffs)
    asyncio.run(_register_baseline(caller, [("daily-queue", "daily")]))
    _patch_clock_copy(monkeypatch)
    _patch_fake_check(monkeypatch)

    asyncio.run(caller.run_until_review({}))
    asyncio.run(caller.advance())
    result = asyncio.run(caller.run_until_review({}))

    assert [item["source_cutoff"] for item in result["checks"]] == cutoffs[1:8]
    assert [item["day"] for item in caller.state["checks"]] == list(range(8))
    for record in caller.state["checks"]:
        assert len(record["record"]["ledger"]) == 1
        ledger = record["record"]["ledger"][0]
        for name in (
            "source_ref", "source_result_bytes", "source_result_sha256",
            "result_ref", "result_bytes", "result_sha256",
        ):
            assert ledger[name]
    # Quiet checks ran while the actor was not yet asked to review. Their exact
    # evidence locations and byte identities must still be surfaced at review.
    for day_summary in result["checks"]:
        monitor = day_summary["monitors"][0]
        for name in (
            "source_ref", "source_result_bytes", "source_result_sha256",
            "result_ref", "result_bytes", "result_sha256",
        ):
            assert monitor[name]
        for reference_key in ("source_ref", "result_ref"):
            assert (caller.workspace / monitor[reference_key]).is_file()


def test_native_deferred_result_is_attention_and_keeps_its_actual_result_reference(
    tmp_path, monkeypatch
):
    caller, _audit, _roles_path = _make_caller(
        tmp_path, arm="signalweave", cutoffs=_cutoffs(3), native=object()
    )
    caller.state["day"] = 1
    caller.state["procedure"] = {
        "procedure": {
            "monitors": [
                {"monitor_id": "approved-card", "cadence": "daily", "card_id": "card-17"}
            ]
        }
    }
    caller.state["procedure_revisions"] = [{"registered": True}]
    monkeypatch.setattr(journey, "public_paths", lambda _workspace: [])
    native_result = {"result": None, "error": {"code": "deferred", "message": "Retry later"}}
    result_bytes = json.dumps(native_result, sort_keys=True, separators=(",", ":")).encode()
    artifact = caller.workspace / "native-deferred-result.json"
    artifact.write_bytes(result_bytes)

    async def fake_check(arm, monitors, **kwargs):
        assert arm == "T"
        assert [item.card_id for item in monitors] == ["card-17"]
        return {
            "arm": "T",
            "run_id": kwargs["run_id"],
            "workspace": str(kwargs["workspace"]),
            "ledger": [
                {
                    "monitor_id": "approved-card",
                    "status": "completed",
                    "native_result": native_result,
                    "result_ref": str(artifact.relative_to(caller.workspace)),
                    "result_bytes": len(result_bytes),
                    "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
                }
            ],
            "known_errors": [],
            "business_grade": None,
        }

    monkeypatch.setattr("evaluations.enterprise_policy_caller.check_once", fake_check)

    review = asyncio.run(caller.run_until_review({}))

    assert review["attention"] is True
    monitor = review["checks"][0]["monitors"][0]
    assert monitor["outcome"] is None
    assert monitor["result_ref"] == "native-deferred-result.json"
    assert monitor["result_bytes"] == len(result_bytes)
    assert monitor["result_sha256"] == hashlib.sha256(result_bytes).hexdigest()
    assert caller.state["checks"][0]["record"]["ledger"][0]["native_result"] == native_result


def test_weekly_only_procedure_handles_empty_days_through_final_cutoff(tmp_path, monkeypatch):
    cutoffs = _cutoffs(9)
    caller, _audit, _roles_path = _make_caller(tmp_path, cutoffs=cutoffs)
    asyncio.run(_register_baseline(caller, [("weekly-brief", "weekly")]))
    _patch_clock_copy(monkeypatch)
    calls = _patch_fake_check(monkeypatch)

    assert asyncio.run(caller.run_until_review({}))["weekly_report_due"] is True
    asyncio.run(caller.advance())
    seventh_day = asyncio.run(caller.run_until_review({}))
    assert seventh_day["source_cutoff"] == cutoffs[7]
    assert seventh_day["weekly_report_due"] is True
    assert [call["monitors"][0]["cutoff"] for call in calls] == [cutoffs[0], cutoffs[7]]

    asyncio.run(caller.advance())
    finished = asyncio.run(caller.run_until_review({}))
    assert finished["engagement_complete"] is True
    assert caller.state["complete"] is True
    assert caller.state["checks"][-1] == {
        "day": 8,
        "source_cutoff": cutoffs[8],
        "record": None,
        "reason": "No registered procedure is due; not a business all-clear.",
    }


def test_new_same_cutoff_invocation_does_not_reuse_a_prior_evaluation_identity(
    tmp_path, monkeypatch
):
    from evaluations import enterprise_policy_caller

    caller, _audit, _roles_path = _make_caller(tmp_path)
    asyncio.run(_register_baseline(caller, [("daily-queue", "daily")]))
    _patch_fake_check(monkeypatch, lambda *_args: "notify")
    fake_check = enterprise_policy_caller.check_once
    identities = []

    async def recording_check(*args, **kwargs):
        identities.append(kwargs["run_id"])
        return await fake_check(*args, **kwargs)

    monkeypatch.setattr(enterprise_policy_caller, "check_once", recording_check)
    first = asyncio.run(caller.run_until_review({}))
    second = asyncio.run(caller.run_until_review({}))

    assert first["source_cutoff"] == second["source_cutoff"]
    assert caller.state["day"] == 0
    assert len(caller.state["procedure_revisions"]) == 1
    assert len(identities) == len(set(identities)) == 2


def test_final_cutoff_is_checked_before_engagement_completes(tmp_path, monkeypatch):
    cutoffs = _cutoffs(9)
    caller, _audit, _roles_path = _make_caller(tmp_path, cutoffs=cutoffs)
    asyncio.run(_register_baseline(caller, [("daily-queue", "daily")]))
    _patch_clock_copy(monkeypatch)
    calls = _patch_fake_check(
        monkeypatch,
        lambda monitor, _call_index: "notify" if monitor.cutoff == cutoffs[-1] else "ignore",
    )

    assert asyncio.run(caller.run_until_review({}))["source_cutoff"] == cutoffs[0]
    asyncio.run(caller.advance())
    day_seven = asyncio.run(caller.run_until_review({}))
    assert day_seven["source_cutoff"] == cutoffs[7]
    asyncio.run(caller.advance())
    final = asyncio.run(caller.run_until_review({}))
    assert final["source_cutoff"] == cutoffs[-1]
    assert final["attention"] is True
    assert final["checks"][0]["monitors"][0]["outcome"] == "notify"
    assert calls[-1]["monitors"][0]["cutoff"] == cutoffs[-1]
    assert asyncio.run(caller.advance())["engagement_complete"] is True


@pytest.mark.parametrize("arm", ["baseline", "signalweave"])
def test_role_authored_change_is_audited_and_published_to_owner_conversation_before_return(
    arm, tmp_path
):
    cutoff = _cutoffs(1)[0]
    message = "Starting today, pause the handoff when the documented queue is incomplete."
    roles = _role_deck(effective_at=cutoff, message=message)
    caller, audit, _roles_path = _make_caller(
        tmp_path, arm=arm, cutoffs=[cutoff], roles=roles, native=object() if arm == "signalweave" else None
    )
    world = SimpleNamespace(state={"conversations": {"owner": []}})
    audit.world = world
    caller.world = world
    caller.state["procedure"] = {"procedure": {"monitors": []}}

    result = asyncio.run(caller.run_until_review({}))

    assert result["owner_update"] == message
    assert world.state["conversations"]["owner"] == [{"speaker": "person", "text": message}]
    event = next(item for item in audit.events if item["kind"] == "company.owner_policy_event")
    assert event["source_cutoff"] == cutoff
    assert event["message"] == message
    assert event["scripted_event"] is True
    assert audit.conversation_at_policy_event == world.state["conversations"]["owner"]
    assert caller.state["checks"] == []


def test_source_advance_copies_only_next_frozen_snapshot_without_mutating_future_history(
    tmp_path,
):
    cutoffs = _cutoffs(3)
    fixture = build_fixture(tmp_path / "source-fixture", cutoffs)
    private_root = Path(fixture["root"])
    reviewer_manifest = Path(fixture["manifest"])
    manifest_before = journey.sha(reviewer_manifest)
    metadata = json.loads(reviewer_manifest.read_text(encoding="utf-8"))
    snapshot_paths = [private_root / item["path"] for item in metadata["snapshots"]]
    snapshots_before = [journey.sha(path) for path in snapshot_paths]

    caller, _audit, _roles_path = _make_caller(tmp_path, cutoffs=cutoffs)
    caller.study["source_fixture"] = str(private_root)
    active = caller.root / caller.arm / "active.sqlite3"
    journey.copy_active_snapshot(private_root, cutoffs[0], active)

    try:
        advanced = asyncio.run(caller.advance())
        assert advanced["source_cutoff"] == cutoffs[1]
        assert journey.sha(active) == metadata["snapshots"][1]["sha256"]
        assert journey.sha(active) != metadata["snapshots"][2]["sha256"]
        assert [journey.sha(path) for path in snapshot_paths] == snapshots_before
        assert journey.sha(reviewer_manifest) == manifest_before

        exposed = journey.manifest(active)
        assert str(active) in json.dumps(exposed)
        assert str(private_root) not in json.dumps(exposed)
        future_path = snapshot_paths[2]
        from evaluations.harbor_enterprise_world import _workspace_file

        with pytest.raises(ValueError, match="relative file path|inside the current workspace"):
            _workspace_file(caller.workspace, str(future_path))
    finally:
        # The fixture deliberately seals its snapshot directory; restore temp
        # directory permissions only after the immutability assertions.
        os.chmod(private_root / "snapshots", 0o700)
        for path in snapshot_paths:
            os.chmod(path, 0o600)


def _admission_context(tmp_path, *, approved=True):
    root = tmp_path / "admission"
    root.mkdir()
    roles_path = root / "roles.json"
    roles_path.write_text(json.dumps(_role_deck()), encoding="utf-8")
    preflight = root / "preflight.json"
    preflight.write_text("{}\n", encoding="utf-8")
    study = {
        "limits": journey.LIMITS,
        "roles": str(roles_path),
        "roles_sha256": journey.sha(roles_path),
    }
    study_path = root / "study.json"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    review = root / "review.json"
    review.write_text(
        json.dumps(
            {
                "approved": approved,
                "study_sha256": journey.sha(study_path),
                "preflight_sha256": journey.sha(preflight),
                "limits": journey.LIMITS,
            }
        ),
        encoding="utf-8",
    )
    return root, study, review, roles_path


def _terminal(*, provider_requests=0, uncached=0, person_replies=None):
    return {
        "provider_requests": provider_requests,
        "usage": {"known": True, "usage": {"uncached_input_tokens": uncached}},
        "provider_usage": {"known": True},
        "person_replies": person_replies or [],
    }


def _claim(root, arm, phase, result=None):
    stem = f"actor-{arm}-{phase}"
    (root / f"{stem}.claimed").write_text("attempted\n", encoding="utf-8")
    if result is not None:
        (root / f"{stem}.json").write_text(json.dumps(result), encoding="utf-8")


def test_admission_requires_approved_frozen_role_deck_and_normalized_people_keys(tmp_path):
    root = tmp_path / "finalize"
    root.mkdir()
    protocol = root / "owner-protocol.md"
    protocol.write_text("Frozen fictional owner protocol.\n", encoding="utf-8")
    study = {
        "method": journey.method(),
        "owner_protocol": str(protocol),
        "owner_protocol_sha256": journey.sha(protocol),
    }
    (root / "study.json").write_text(json.dumps(study), encoding="utf-8")
    roles = root / "roles.json"
    deck = _role_deck()
    deck["people"].pop("data-operations")
    roles.write_text(json.dumps(deck), encoding="utf-8")
    with pytest.raises(ValueError, match="five named fictional employees"):
        journey.finalize(root, roles)

    roles.write_text(json.dumps(_role_deck()), encoding="utf-8")
    finalized = journey.finalize(root, roles)
    frozen_study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    assert finalized["finalized_before_inference"] is True
    assert frozen_study["roles_sha256"] == journey.sha(roles)
    assert set(json.loads(roles.read_text(encoding="utf-8"))["people"]) == {
        "owner", "queue-lead", "duty-manager", "operations", "data-operations"
    }

    frozen_study["limits"] = journey.LIMITS
    (root / "study.json").write_text(json.dumps(frozen_study), encoding="utf-8")
    preflight = root / "preflight.json"
    preflight.write_text("{}\n", encoding="utf-8")
    review = root / "review.json"
    review.write_text(
        json.dumps(
            {
                "approved": False,
                "study_sha256": journey.sha(root / "study.json"),
                "preflight_sha256": journey.sha(preflight),
                "limits": journey.LIMITS,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Independent admission"):
        journey.admission(root, "baseline", journey.PHASES[0], review, frozen_study)


def test_admission_retains_costs_enforces_phase_order_and_rejects_after_all_six_attempts(
    tmp_path,
):
    root, study, review, _roles_path = _admission_context(tmp_path)
    order = [(arm, phase) for arm in journey.ARMS for phase in journey.PHASES]
    provider_costs = [8, 8, 8, 8, 15, 1]
    retained_calls = 0

    with pytest.raises(ValueError, match="baseline-first order"):
        journey.admission(root, "signalweave", journey.PHASES[0], review, study)

    for index, (arm, phase) in enumerate(order):
        assert journey.admission(root, arm, phase, review, study) == retained_calls
        assert journey.LIMITS["provider_requests"] - retained_calls >= provider_costs[index]
        extra_reply_usage = (
            [{"known_usage": True, "usage": {"input_tokens": 100, "cached_input_tokens": 40}}]
            if index == 0
            else []
        )
        _claim(
            root,
            arm,
            phase,
            _terminal(
                provider_requests=provider_costs[index],
                uncached=10,
                person_replies=extra_reply_usage,
            ),
        )
        retained_calls += provider_costs[index]
        if index == 0:
            with pytest.raises(ValueError, match="One attempt per phase"):
                journey.admission(root, arm, phase, review, study)

    assert retained_calls == journey.LIMITS["provider_requests"]
    with pytest.raises(ValueError, match="One attempt per phase"):
        journey.admission(root, "signalweave", "recurring", review, study)


def test_admission_blocks_next_phase_on_missing_or_unknown_prior_cost(tmp_path):
    root, study, review, _roles_path = _admission_context(tmp_path)
    _claim(root, "baseline", "queue-onboarding")
    with pytest.raises(ValueError, match="no terminal accounting"):
        journey.admission(root, "baseline", "weekly-onboarding", review, study)

    (root / "actor-baseline-queue-onboarding.json").write_text(
        json.dumps(
            {
                **_terminal(provider_requests=2),
                "usage": {"known": False},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="usage is unknown"):
        journey.admission(root, "baseline", "weekly-onboarding", review, study)


def test_retained_uncached_cost_at_stop_boundary_rejects_the_final_phase(tmp_path):
    root, study, review, _roles_path = _admission_context(tmp_path)
    order = [(arm, phase) for arm in journey.ARMS for phase in journey.PHASES]
    for index, (arm, phase) in enumerate(order[:5]):
        if index == 0:
            reply_usage = [
                {
                    "known_usage": True,
                    "usage": {"input_tokens": 20, "cached_input_tokens": 10},
                }
            ]
            uncached = journey.LIMITS["between_stage_uncached_input_stop"] - 10
        else:
            reply_usage = []
            uncached = 0
        _claim(
            root,
            arm,
            phase,
            _terminal(uncached=uncached, person_replies=reply_usage),
        )

    with pytest.raises(ValueError, match="usage ceiling reached"):
        journey.admission(root, *order[5], review, study)


def test_admission_rejects_role_deck_drift_after_independent_approval(tmp_path):
    root, study, review, roles_path = _admission_context(tmp_path)
    deck = json.loads(roles_path.read_text(encoding="utf-8"))
    deck["planned_change"]["message"] = "A changed role deck is not the reviewed protocol."
    roles_path.write_text(json.dumps(deck), encoding="utf-8")

    with pytest.raises(ValueError, match="Employee role context changed"):
        journey.admission(root, "baseline", journey.PHASES[0], review, study)
