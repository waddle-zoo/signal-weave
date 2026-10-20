"""Opt-in native regression for point-in-time authoring; no policy inference."""

import json
import os
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.harbor_history import materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_preflight import DUMMY_KEY, ROOT, _setup
from evaluations.harbor_workflow_history import make_queue_history
from evaluations.harbor_workflow_journey import _call
from evaluations.harbor_workflow_sources import ADAPTER, QUEUE_RESOURCE, build_workflow_manifest
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _jev_proxy,
    _minimal_environment,
    _private_dir,
    _private_file,
)
from scripts.binary_provenance import verify_binary

pytestmark = pytest.mark.skipif(
    not os.environ.get("SIGNALWEAVE_TEST_BINARY"),
    reason="set SIGNALWEAVE_TEST_BINARY for the real native point-card authoring regression",
)


@pytest.mark.asyncio
async def test_native_point_card_revision_review_approval_preserves_no_comparison(tmp_path):
    binary = Path(os.environ["SIGNALWEAVE_TEST_BINARY"]).resolve()
    verify_binary(binary, ROOT)
    home = tmp_path / "home"
    _private_dir(home)
    _private_dir(home / "tmp")
    history = make_queue_history(complete_background_responses=True, recorded_response=False)
    snapshot = materialize_snapshot(history, weekly_cutoffs(history)[0], tmp_path / "source.sqlite3")
    manifest, key = tmp_path / "sources.json", tmp_path / "dummy.key"
    _private_file(manifest, json.dumps(build_workflow_manifest(snapshot, ROOT / ".venv/bin/python")))
    _private_file(key, DUMMY_KEY)
    audit, budget = Audit(secrets=(DUMMY_KEY,)), RequestBudget(0)
    await _setup(binary, home, key, manifest, audit)
    async with _jev_proxy(audit, budget) as proxy:
        environment = _minimal_environment(home, jev_url=proxy)
        environment["SIGNALWEAVE_PREFLIGHT_PYTHONPATH"] = str(ROOT)
        params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)],
                                      cwd=str(ROOT), env=environment)
        with open(os.devnull, "w") as errors:
            async with stdio_client(params, errlog=errors) as streams, ClientSession(*streams) as session:
                initialized = await _initialize_mcp_session(session)
                native = InstalledServer(session, initialized.instructions, audit)
                draft = await _call(native, "onboard_insight_card", {
                    "title": "Known work past its response clock",
                    "what_to_watch": "Known open priority work without a visible response past its tier clock",
                    "why_watch": "Prepare a focused internal manual-review draft when known work needs attention",
                    "decision_guidance": "Investigate when the current known unanswered priority breach count is at least one; otherwise ignore. This is not a whole-service all-clear.",
                    "selected_sources": [{"ref": f"{ADAPTER}|{QUEUE_RESOURCE}", "key": "queue"}],
                    "comparison_windows": ["previous_period"],
                    "max_source_age_hours": None,
                })
                card = draft["card"]
                revised = await _call(native, "revise_insight_card", {
                    "card_id": card["id"], "expected_card_version": card["version"],
                    "changes": {"comparison_windows": []},
                    "reason": "This fixture policy uses current state, not a comparison period",
                })
                assert revised["card"]["comparison_windows"] == []
                review = await _call(native, "review_insight_card", {"card_id": card["id"], "response_mode": "compact"})
                assert not any("Comparison windows are undeclared" in warning for warning in review["review"]["warnings"])
                handoff = review["approval_handoff"]
                assert handoff["dynamic_scope_requires_separate_acknowledgment"] is False
                approval = await _call(native, "approve_insight_card", {
                    **handoff["arguments_after_owner_confirmation"],
                    "source_selection_reason": "Fixture operator confirms this retrospective known-record scope for a technical, delivery-disabled contract check; not human onboarding consent",
                })
                assert approval["status"] == "approved"
                saved = await _call(native, "get_insight_card", {"card_id": card["id"], "response_mode": "full"})
                assert saved["comparison_windows"] == saved["compiled_plan"]["comparison_windows"] == []
                assert not {"percent_change", "baseline_comparison"} & set(saved["compiled_plan"]["capabilities"])
                inspected = await _call(native, "inspect_resource", {"adapter": ADAPTER, "resource": QUEUE_RESOURCE})
                assert inspected["evidence"][0]["values"]["known_unanswered_open_priority_past_response_clock"] == 0
    assert budget.used == 0 and budget.exhausted is False
    assert not any(event["kind"].startswith("api.") for event in audit.events)
