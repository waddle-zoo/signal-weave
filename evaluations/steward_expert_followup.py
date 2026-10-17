"""Expert-assisted reporting follow-up on the original retained native draft.

Not a resumed V4 cohort, autonomous onboarding, imported approval or retry.
The synthetic expert explicitly approves existing meaning/scope through public
MCP operations. Two fresh reporters share equivalent confirmed definitions.
All four prior calls remain charged; total cap stays six calls and one Jev.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from evaluations.codex_trial_transport import codex_episode
from evaluations.domain_context_onboarding_trial import (
    failure_detail,
    native_context,
    pinned_codex,
    public_brief,
)
from evaluations.human_report_episode import HumanReportEpisode
from evaluations.public_owner_report_trial import LIMITS, REPORT, scenario
from evaluations.reviewed_setup_report_trial import before_invocation, summarize_usage
from evaluations.source_expert_reference import attach_steward_notes
from scripts.binary_provenance import verify_binary
from signalweave.models import InsightCard

MANIFEST = Path(__file__).with_name("data") / "steward-followup-manifest.json"
NOTES = Path(__file__).with_name("data") / "juniper-source-steward-v1.md"
REASON = (
    "Synthetic expert explicitly confirms this saved policy and the exact displayed source scopes. "
    "Commerce uses the steward-confirmed glossary population and complete UTC weekly comparison; "
    "returns metadata remains optional corroboration, not a second ledger. Only a delivery-disabled "
    "check of the supplied complete-period case is authorized; no scheduling, sending, causality "
    "claim or incomplete-postings branch qualification. This is coordinator assistance, not autonomous onboarding."
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_prior(root, identity, codex):
    manifest = json.loads(MANIFEST.read_text())
    for name, key in (("report.json", "report_sha256"), ("trace.jsonl", "trace_sha256"),
                      ("public-onboarding-input.json", "public_input_sha256")):
        if digest(root / name) != manifest[key]:
            raise ValueError("Prior evidence differs from the frozen follow-up manifest")
    prior = json.loads((root / "report.json").read_text())
    events = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
    accounted = summarize_usage(SimpleNamespace(events=events), zero_usage())
    if (prior["protocol"] != "public-steward-reference-v4" or not prior.get("failure")
            or prior["agent_invocations_started"] != 4 or prior["provider_attempts"] != 0
            or not accounted["usage_known"] or accounted["usage"] != prior["usage"]
            or accounted["agent_invocations_started"] != 4
            or any(e.get("provider") == "jev" for e in events)
            or prior["build"]["binary_sha256"] != identity["binary_sha256"]
            or prior["codex"]["sha256"] != codex["sha256"]):
        raise ValueError("Need the exact terminal four-call, zero-Jev cohort with known usage and unchanged binaries")
    authors = prior["episodes"]
    if (len(authors) != 2 or [e["arm"] for e in authors] != ["baseline", "signalweave"]
            or any(e["stage"] != "author" or e["agent"]["status"] != "complete" for e in authors)
            or authors[0]["independent_review"]["approved"] is not True
            or authors[1]["independent_review"]["approved"] is not False
            or authors[1]["card"]["status"] != "draft"):
        raise ValueError("Unexpected retained author/review state; do not select another setup")
    fixture, _, note_hash = attach_steward_notes(scenario(), NOTES)
    if (hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest() != prior["scenario_sha256"]
            or note_hash != prior["expert_notes"]["sha256"]):
        raise ValueError("Shared fixture/steward context changed")
    public = json.loads((root / "public-onboarding-input.json").read_text())
    request = next(q for q in authors[1]["owner_requests"] if q.get("kind") == "context")
    revisions = request["saved_artifact"]["revisions"]
    if len(revisions) != 1 or revisions[0]["status"] != "draft":
        raise ValueError("Need the original unrevised context draft")
    return manifest, prior, events, fixture, public, revisions[0]


def zero_usage():
    return {"input_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0,
            "output_tokens": 0, "responses": 0}


def policy_signature(raw):
    card = InsightCard.model_validate(raw)
    policy = card.execution_payload()
    policy.pop("version")
    return {"policy": policy, "routes": [m.model_dump(mode="json") for m in card.delivery_methods],
            "principal": [card.principal_id, card.principal_tenant]}


async def native_operation(native, audit, name, arguments):
    _, result = await native.call_tool(name, arguments)
    if audit is not None:
        audit.emit("native.operation", name=name, arguments=arguments, result=result)
    return result


async def existing_drafts(native, expected_card, expected_context, audit=None):
    current = await native_operation(native, audit, "get_insight_card", {"card_id": expected_card["id"], "response_mode": "full"})
    history = await native_operation(native, audit, "get_context_history", {"entry_id": expected_context["id"]})
    if (current["id"] != expected_card["id"] or current["version"] != expected_card["version"]
            or current["status"] != "draft" or policy_signature(current) != policy_signature(expected_card)
            or current["context_bindings"] != expected_card["context_bindings"]
            or history["revisions"] != [expected_context]):
        raise ValueError("Retained native state changed; no replacement/import/approval allowed")
    return current


async def expert_signoff(native, expected_card, expected_context, audit=None):
    current = await existing_drafts(native, expected_card, expected_context, audit)
    reviewed = await native_operation(native, audit, "review_domain_context", {
        "entry_id": expected_context["id"], "expected_revision": expected_context["revision"],
        "action": "approve", "reason": REASON})
    bound = await native_operation(native, audit, "bind_insight_context", {
        "card_id": current["id"], "expected_card_version": current["version"],
        "pins": [{"entry_id": reviewed["id"], "revision": reviewed["revision"], "required_for_action": True}],
        "reason": REASON})
    review = await native_operation(native, audit, "review_insight_card", {"card_id": current["id"]})
    args = review["approval_handoff"]["arguments_after_owner_confirmation"]
    await native_operation(native, audit, "approve_insight_card", {**args, "source_selection_reason": REASON})
    approved = await native_operation(native, audit, "get_insight_card", {"card_id": current["id"], "response_mode": "full"})
    pins = approved["context_bindings"]
    if (approved["status"] != "approved" or approved["version"] != current["version"] + 1
            or bound["version"] != approved["version"] or policy_signature(approved) != policy_signature(expected_card)
            or reviewed["status"] != "reviewed" or reviewed["revision"] != expected_context["revision"] + 1
            or reviewed["content"] != expected_context["content"] or len(pins) != 1
            or (pins[0]["entry_id"], pins[0]["revision"], pins[0]["required_for_action"])
                != (reviewed["id"], reviewed["revision"], True)):
        raise ValueError("Expert intervention changed policy or failed the exact reviewed dependency")
    return approved, reviewed


async def run(args):
    root, binary = Path(args.prior).resolve(), Path(args.binary).resolve()
    identity, codex = verify_binary(binary), await pinned_codex(args.codex_executable)
    manifest, prior, prior_events, fixture, public, context = load_prior(root, identity, codex)
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = Path(args.key_file).resolve()
    audit = Audit(path=output / "trace.jsonl", secrets=(key.read_text().strip(),))
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    budget = RequestBudget(limit=1 if args.run else 0)
    clock = datetime.fromisoformat(prior["read_clock"])
    offset = timedelta(seconds=prior["measurement_offset_seconds"])
    report = {"protocol": manifest["protocol"], "preflight_only": not args.run,
              "build": identity, "codex": codex, "limits": LIMITS, "episodes": [],
              "charged_prior_usage": prior["usage"], "charged_prior_calls": 4,
              "prior_report_sha256": manifest["report_sha256"], "scope": REASON,
              "runner_sha256": digest(__file__), "manifest_sha256": digest(MANIFEST),
              "note_sha256": digest(NOTES)}
    def merged():
        return SimpleNamespace(events=[*prior_events, *audit.events])

    def save():
        report.update(summarize_usage(merged(), zero_usage()))
        report["provider_attempts"] = budget.used
        report["new_agent_invocations_started"] = sum(e["kind"] == "api.request" and e.get("provider") == "openai" for e in audit.events)
        report["source_reads_by_stage"] = {stage: sum(e["kind"] == "source.read" and e["episode"] == stage for e in audit.events)
                                           for stage in sorted({e["episode"] for e in audit.events})}
        (output / "report.json").write_text(json.dumps(audit.redact(report), indent=2) + "\n")

    try:
        # Reconnect only this synthetic trial's retained home. No copying a DB
        # or imported approval; the normal setup reuses its unchanged config.
        owned_root = root / "private-native-state"
        if not (owned_root / "native-home/config.toml").is_file():
            raise ValueError("Original native home is missing; never reconstruct it from the report")
        if ((owned_root / "native-home").resolve() != owned_root / "native-home"
                or (owned_root / "company-mcp.json").is_symlink()
                or (owned_root / "native-home/config.toml").is_symlink()):
            raise ValueError("Retained paths must not redirect writes outside this trial")
        adapter.set_period(public["period"], clock, measurement_offset=offset)
        async with native_context(binary, key, public, adapter, audit, owned_root, request_budget=budget) as (native, skill):
            canonical = Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md"
            if hashlib.sha256(skill.encode()).hexdigest() != digest(canonical):
                raise ValueError("Installed skill differs from current source")
            expected = prior["episodes"][1]["card"]
            await existing_drafts(native, expected, context, audit)
            report["retained_drafts_verified"] = True
            if args.run:
                approved, reviewed = await expert_signoff(native, expected, context, audit)
                report["expert_intervention"] = {"reason": REASON, "card": approved, "context": reviewed}
                period = fixture["public"]["periods"][2]
                for author, treatment in zip(prior["episodes"], (False, True), strict=True):
                    before_invocation(merged(), LIMITS, codex["path"], codex["sha256"])
                    if (digest(binary) != identity["binary_sha256"] or digest(__file__) != report["runner_sha256"]
                            or digest(MANIFEST) != report["manifest_sha256"] or digest(NOTES) != report["note_sha256"]
                            or digest(canonical) != hashlib.sha256(skill.encode()).hexdigest()):
                        raise ValueError("Frozen input changed; stop without retry")
                    arm = "signalweave" if treatment else "baseline"
                    audit.episode = arm + ":report"
                    adapter.set_period(period, clock, measurement_offset=offset)
                    run_key = manifest["protocol"] + ":" + period["period_id"]
                    session = HumanReportEpisode(public, adapter, native if treatment else None,
                        notes=author["notes"], approved_card_id=approved["id"] if treatment else None,
                        approved_card_version=approved["version"] if treatment else None, run_key=run_key)
                    result = await codex_episode(session, key=None, budget=None, audit=audit,
                        model="gpt-6-luna", effort="medium", max_turns=12, max_tool_calls=12,
                        max_output_tokens=3000, timeout_seconds=180, codex_executable=codex["path"], accounting_drain=True,
                        instructions_override=REPORT + (("Evaluate the approved card once with the supplied key.\n" + skill) if treatment else ""),
                        prompt_override={"business": public_brief(public), "period": adapter.period_context,
                            "saved_notes": author["notes"], "expert_confirmation": REASON,
                            "approved_card": approved if treatment else None,
                            "card_id": approved["id"] if treatment else None, "idempotency_key": run_key})
                    report["episodes"].append({"arm": arm, "period_id": period["period_id"], "agent": result,
                        "submission": session.submission, "native_calls": session.native_calls,
                        "approved_card_execution_verified": session.evaluation_verified if treatment else None})
                    save()
                    if result["status"] != "complete" or session.submission is None or not report["usage_known"]:
                        raise ValueError("Report incomplete/usage unknown; no retry")
                    if treatment and not session.evaluation_verified:
                        raise ValueError("Native integration unproved; retain actual report separately")
            responses = [e for e in audit.events if e["kind"] == "api.response" and e.get("provider") == "jev"]
            report["provider_usage_known"] = (
                len(responses) == budget.used and not budget.exhausted
                and not any(e["kind"] in {"api.error", "api.rejected"} and e.get("provider") == "jev" for e in audit.events)
                and all(isinstance(e.get("usage"), dict) and all(type(e["usage"].get(k)) is int and e["usage"][k] >= 0
                            for k in ("input_tokens", "output_tokens")) for e in responses))
            if budget.used != int(args.run) or not report["provider_usage_known"]:
                raise ValueError("Expected exactly one successful live Jev request, or zero in preflight")
            report["provider_usage"] = [e.get("usage") for e in responses]
            report["completed"] = True
    except Exception as error:  # noqa: BLE001 - retain all partial work
        report["failure"] = failure_detail(error)
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior", "binary", "codex-executable", "key-file", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps({key: result.get(key) for key in ("completed", "failure", "agent_invocations_started", "provider_attempts", "usage")}))
    if not result.get("completed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
