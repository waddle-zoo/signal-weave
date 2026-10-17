"""New bounded historical report series over an actual retained, authored setup."""

import argparse
import asyncio
import hashlib
import json
import shutil
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from evaluations.bootstrap_scenarios import public_episode
from evaluations.codex_trial_transport import codex_episode
from evaluations.domain_context_onboarding_trial import (
    failure_detail,
    native_context,
    pinned_codex,
    public_brief,
)
from evaluations.explicit_owner_conversation import AuditedNative
from evaluations.human_report_episode import HumanReportEpisode
from evaluations.public_owner_report_trial import (
    REPORT,
    attach_owner_clarification,
    development_scenario,
    scenario,
)
from evaluations.reviewed_setup_report_trial import before_invocation, summarize_usage
from evaluations.source_expert_reference import attach_steward_notes
from scripts.binary_provenance import source_fingerprint, verify_binary
from signalweave.models import InsightCard, SourceRef

MANIFEST = Path(__file__).with_name("data") / "retained-owner-periods-v1.json"
CONTEXT_MANIFEST = Path(__file__).with_name("data") / "retained-context-courier-v1.json"
CLARIFICATION = Path(__file__).with_name("data") / "courier-owner-clarification-v1.md"
NOTES = Path(__file__).with_name("data") / "juniper-source-steward-v1.md"
HELPERS = ("public_owner_report_trial.py", "domain_context_onboarding_trial.py", "human_report_episode.py",
           "explicit_owner_conversation.py", "codex_trial_transport.py", "source_expert_reference.py")
ZERO = {"input_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0, "output_tokens": 0, "responses": 0}
REPLAY = (
    "This is a retrospective shadow replay using today's approved setup, not a live-day alert. "
    "The supplied source intervals define the historical observation. Do not claim the policy "
    "was approved at that historical date or reuse onboarding measurements as this period's facts. "
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_context_preflight(path, report, manifest):
    if path is None:
        raise ValueError("Context readouts require --preflight from a completed zero-inference run")
    previous = json.loads(Path(path).read_text())
    if (previous.get("completed") is not True or previous.get("preflight_only") is not True
            or previous.get("protocol") != report["protocol"]
            or previous.get("frozen") != report["frozen"]
            or previous.get("build") != report["build"] or previous.get("codex") != report["codex"]
            or previous.get("prior_report_sha256") != report["prior_report_sha256"]
            or any(type(previous.get(field)) is not int or previous[field] != 0
                   for field in ("agent_invocations_started", "provider_attempts"))
            or previous.get("source_fidelity_verified_periods") != manifest["period_indices"]
            or any(previous.get(field) is not True for field in (
                "retained_context_verified", "card_unchanged", "context_unchanged", "connection_files_restored",
            ))):
        raise ValueError("Context preflight is incomplete or differs from the frozen current inputs")
    return digest(path)


def backup_connections(owned, output):
    backup = output / "original-connection-files"
    backup.mkdir(mode=0o700)
    records = []
    for index, original in enumerate((owned / "company-mcp.json", owned / "native-home/config.toml",
                                      owned / "native-home/typesafe.key")):
        if original.is_symlink() or not original.is_file():
            raise ValueError("Original research connection files must be regular non-symlink files")
        saved = backup / str(index)
        shutil.copy2(original, saved)
        saved.chmod(0o600)
        records.append((original, saved, digest(saved), stat.S_IMODE(original.stat().st_mode)))
    return records


def restore_connections(records):
    for original, saved, expected, mode in records:
        if original.is_symlink() or digest(saved) != expected:
            raise ValueError("Research connection restore target or backup changed")
        shutil.copy2(saved, original)
        original.chmod(mode)
        if digest(original) != expected:
            raise ValueError("Research connection restore did not preserve original bytes")
    # Remove these three experiment-owned backup files only after all originals
    # have been restored. Never leave a second credential copy after success.
    for _, saved, _, _ in records:
        saved.unlink()


def load_prior(root, *, context_readout=False):
    manifest = json.loads((CONTEXT_MANIFEST if context_readout else MANIFEST).read_text())
    if (digest(root / "report.json") != manifest["prior_report_sha256"]
            or digest(root / "trace.jsonl") != manifest["prior_trace_sha256"]):
        raise ValueError("Prior artifacts differ from the frozen, completed study")
    prior = json.loads((root / "report.json").read_text())
    if (prior.get("protocol") != manifest["prior_protocol"] or prior.get("completed") is not True
            or prior.get("usage_known") is not True
            or prior.get("agent_invocations_started") != manifest.get("prior_invocations", 6)):
        raise ValueError("Requires the completed original study, never an incomplete author retry")
    authors = {e["arm"]: e for e in prior["episodes"] if e["stage"] == "author"}
    if set(authors) != {"baseline", "signalweave"} or (
        not context_readout and not all(e["independent_review"]["approved"] for e in authors.values())
    ):
        raise ValueError("Both prior authored setups must have passed review")
    if context_readout and (prior.get("paired_reporting_complete") is not False
                            or prior.get("qualified_arms") != []):
        raise ValueError("Exploratory readouts must retain the original unqualified setup status")
    owned = root / "private-native-state"
    if not (owned / "native-home/config.toml").is_file() or any(p.is_symlink() for p in (
        owned, owned / "native-home", owned / "native-home/config.toml", owned / "company-mcp.json",
    )):
        raise ValueError("Original research home is missing or redirects writes; never reconstruct it")
    if context_readout:
        fixture, _ = attach_owner_clarification(development_scenario(), CLARIFICATION)
    else:
        fixture, _, _ = attach_steward_notes(scenario(), NOTES)
    if hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest() != prior["scenario_sha256"]:
        raise ValueError("Public fixture changed")
    return manifest, prior, authors, owned, fixture


async def credential(binary, home, key):
    process = await asyncio.create_subprocess_exec(
        str(binary), "credentials", "set", "jev", "--home", str(home), "--file", str(key),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), 60)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise RuntimeError("Research credential update failed")


async def run(args):
    root, binary = Path(args.prior).resolve(), Path(args.binary).resolve()
    context_readout = getattr(args, "context_readout", False)
    manifest_path = CONTEXT_MANIFEST if context_readout else MANIFEST
    manifest, prior, authors, owned, fixture = load_prior(root, context_readout=context_readout)
    build, codex = verify_binary(binary), await pinned_codex(args.codex_executable)
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    dummy = output / "dummy-key"
    dummy.write_text("synthetic-retained-periods-no-inference")
    dummy.chmod(0o600)
    key = Path(args.key_file).resolve() if args.run else dummy
    audit = Audit(path=output / "trace.jsonl", secrets=(key.read_text().strip(),))
    public = public_episode(fixture)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    budget = RequestBudget(limit=manifest["limits"]["jev_attempts"] if args.run else 0)
    clock, offset = datetime.now(timezone.utc), timedelta(seconds=prior["measurement_offset_seconds"])
    frozen = {name: digest(Path(__file__).with_name(name)) for name in HELPERS}
    notes_path = CLARIFICATION if context_readout else NOTES
    frozen.update({"runner": digest(__file__), "manifest": digest(manifest_path), "notes": digest(notes_path)})
    report = {"protocol": manifest["protocol"], "scope": manifest["scope"], "preflight_only": not args.run,
              "build": build, "codex": codex, "limits": manifest["limits"], "frozen": frozen, "episodes": [],
              "read_clock": clock.isoformat(), "measurement_offset_seconds": offset.total_seconds(),
              "prior_report_sha256": manifest["prior_report_sha256"], "prior_study_usage_not_recharged": prior["usage"],
              "source_fidelity_verified_periods": []}
    if context_readout:
        report.update(prior_onboarding_status=prior["onboarding_status"], onboarding_qualified=False,
                      context_entry_ids=manifest["context_entry_ids"])

    def save():
        report.update(summarize_usage(audit, ZERO))
        report["provider_attempts"] = budget.used
        responses = [e for e in audit.events if e["kind"] == "api.response" and e.get("provider") == "jev"]
        report["provider_usage"] = [e.get("usage") for e in responses]
        report["provider_usage_known"] = (len(responses) == budget.used and not budget.exhausted
            and not any(e["kind"] in {"api.error", "api.rejected"} and e.get("provider") == "jev" for e in audit.events)
            and all(isinstance(e.get("usage"), dict) and all(type(e["usage"].get(k)) is int
                    and e["usage"][k] >= 0 for k in ("input_tokens", "output_tokens")) for e in responses))
        (output / "report.json").write_text(json.dumps(audit.redact(report), indent=2) + "\n")

    def check():
        before_invocation(audit, manifest["limits"], codex["path"], codex["sha256"])
        current = {name: digest(Path(__file__).with_name(name)) for name in HELPERS}
        current.update({"runner": digest(__file__), "manifest": digest(manifest_path), "notes": digest(notes_path)})
        if (current != frozen or digest(binary) != build["binary_sha256"]
                or source_fingerprint() != build["source_sha256"]):
            raise RuntimeError("Frozen research inputs or native source changed; stop without retry")

    connections, connection_touched = [], False
    try:
        if context_readout and args.run:
            report["preflight_report_sha256"] = validate_context_preflight(getattr(args, "preflight", None), report, manifest)
        if context_readout:
            connections = backup_connections(owned, output)
        connection_touched = True
        await credential(binary, owned / "native-home", key)
        adapter.set_period(public["period"], clock, measurement_offset=offset)
        options = {"skill_workspace": output} if context_readout else {}
        async with native_context(binary, key, public, adapter, audit, owned, request_budget=budget, **options) as (native, skill):
            native = AuditedNative(native, audit)
            expected = authors["signalweave"]["card"]
            _, before = await native.call_tool("get_insight_card", {"card_id": expected["id"], "response_mode": "full"})
            assert before["status"] == "approved" and before["version"] == expected["version"], "Retained approval/version changed"
            assert InsightCard.model_validate(before).execution_payload() == InsightCard.model_validate(expected).execution_payload(), "Retained policy changed"
            skill_hash = hashlib.sha256(skill.encode()).hexdigest()
            expected_skill_hash = (digest(Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md")
                                   if context_readout else prior["installed_skill_sha256"])
            assert skill_hash == expected_skill_hash, "Installed skill differs from the study's specified version"
            report["installed_skill_sha256"] = skill_hash
            context_before = None
            if context_readout:
                _, context_before = await native.call_tool("retrieve_domain_context", {"entry_ids": manifest["context_entry_ids"]})
                expected_context = [c["result"] for c in authors["signalweave"]["native_calls"]
                                    if c["name"] == "review_domain_context" and c["result"]["id"] in manifest["context_entry_ids"]]
                assert len(expected_context) == len(manifest["context_entry_ids"]), "Original reviewed context is missing"
                assert context_before["entries"] == expected_context, "Retained current context changed; never reconstruct it"
                report["retained_context_verified"] = True
            for position, index in enumerate(manifest["period_indices"]):
                period = fixture["public"]["periods"][index]
                adapter.set_period(period, clock, measurement_offset=offset)
                if not args.run:
                    source = expected["sources"][0]
                    _, actual = await native.call_tool("inspect_resource", {"adapter": source["adapter"], "resource": source["resource"]})
                    reference_source = SourceRef.model_validate(source).model_copy(update={"key": actual["source_key"]})
                    reference = (await adapter.inspect(reference_source)).model_dump(mode="json")
                    assert all(actual[field] == reference[field] for field in ("observations", "evidence", "analytical_comparisons")), "Native source facts differ from export"
                    # The bridge enriches an export's minimal contract with its
                    # catalog declaration; an empty export stub is not the
                    # expected normalized business scope.
                    declared = next(a["contract"] for a in public["catalog"]
                                    if a["adapter"] == source["adapter"] and a["resource"] == source["resource"])
                    assert actual["contract"]["tenant_id"] == public["scenario_id"], "Native tenant differs"
                    assert all(actual["contract"].get(field) == declared.get(field) for field in (
                        "scope", "population", "grain", "metric_names", "available_comparison_windows",
                    )), "Native declared business scope differs from catalog"
                    report["source_fidelity_verified_periods"].append(index)
                    continue
                for arm in manifest["arms_by_period"][position]:
                    treatment, author = arm == "signalweave", authors[arm]
                    audit.episode = f"period-{index}:{arm}"
                    session = HumanReportEpisode(public, adapter, native if treatment else None,
                        notes=author["notes"], approved_card_id=expected["id"] if treatment else None,
                        approved_card_version=expected["version"] if treatment else None,
                        run_key=f"{manifest['protocol']}:{period['period_id']}")
                    prompt = {"business": public_brief(public), "saved_setup": author["setup"],
                              "saved_notes": author["notes"], "completed_policy_review": author["independent_review"],
                              "period": adapter.period_context, "card_id": expected["id"] if treatment else None,
                              "idempotency_key": session.run_key}
                    instructions = REPLAY + REPORT
                    if context_readout:
                        prompt.pop("completed_policy_review")
                        prompt["saved_notes"] = ""  # Both arms recover their own actual stored brief via tools.
                        prompt["saved_setup"] = {"unresolved": author["setup"]["unresolved"], "onboarding_qualified": False}
                        prompt["stored_brief"] = ({"context_entry_ids": manifest["context_entry_ids"], "card_id": expected["id"]}
                                                  if treatment else {"notes_id": "working"})
                        instructions += (
                            " Recover your own stored brief using the supplied handles. This is an exploratory "
                            "shadow readout of known synthetic periods, not certification of the prior incomplete "
                            "onboarding. Report supported facts and policy proposals where established; keep "
                            "unresolved quiet/freshness choices visible before any unattended delivery. "
                            "Neither readiness status nor a reviewer opinion is numerical source truth. "
                        )
                    if treatment:
                        instructions += "Evaluate the approved card once with the supplied key.\n" + skill
                    check()
                    result = await codex_episode(session, key=None, budget=None, audit=audit,
                        model="gpt-6-luna", effort="medium", max_turns=12, max_tool_calls=12,
                        max_output_tokens=3000, timeout_seconds=180, codex_executable=codex["path"], accounting_drain=True,
                        instructions_override=instructions, prompt_override=prompt)
                    entry = {"arm": arm, "period_index": index, "period_id": period["period_id"], "agent": result,
                             "submission": session.submission, "native_calls": session.native_calls}
                    report["episodes"].append(entry)
                    if context_readout and treatment:
                        entry["context_retrievals"] = [c for c in session.native_calls if c["name"] == "retrieve_domain_context"]
                    save()
                    if not report["usage_known"] or not report["provider_usage_known"] or result["status"] != "complete" or not session.submission:
                        raise RuntimeError("Report/usage incomplete; no retry")
                    if treatment:
                        evaluations = [c for c in session.native_calls if c["name"] == "evaluate_insight_card"]
                        receipt = evaluations[0]["result"].get("receipt", {}) if len(evaluations) == 1 else {}
                        if (receipt.get("card_id") != expected["id"] or receipt.get("card_version") != expected["version"]
                                or receipt.get("delivery_enabled") is not False
                                or receipt.get("status") not in {"delivery_disabled", "decision_deferred"}):
                            raise RuntimeError("Missing exact-card shadow evaluation; no retry")
                        entry["native_evaluation_verified"] = True
                    # Private labels are used only after this report. Never in model/source inputs.
                    label = fixture["private"]["periods"][period["period_id"]]
                    entry["routing_check_only"] = {"expected_outcome": label["outcome"], "expected_recipients": label["recipients"],
                        "matches": session.submission["outcome"] == label["outcome"]
                        and set(session.submission["recipients"]) == set(label["recipients"])}
            _, after = await native.call_tool("get_insight_card", {"card_id": expected["id"], "response_mode": "full"})
            assert after == before, "Reporting mutated the saved card"
            if context_readout:
                _, context_after = await native.call_tool("retrieve_domain_context", {"entry_ids": manifest["context_entry_ids"]})
                assert context_after["entries"] == context_before["entries"], "Reporting mutated reusable context"
                report["context_unchanged"] = True
            report.update(completed=True, card_unchanged=True)
    except Exception as error:  # noqa: BLE001 - retain failed paid calls
        report["failure"] = failure_detail(error)
    finally:
        if connection_touched:
            try:
                await credential(binary, owned / "native-home", dummy)
                report["credential_cleanup"] = "live copy replaced with dummy through native CLI"
            except Exception as error:  # noqa: BLE001
                report["credential_cleanup_failure"] = type(error).__name__
                report["completed"] = False
        if connections:
            try:
                restore_connections(connections)
                report["connection_files_restored"] = True
            except Exception as error:  # noqa: BLE001
                report["connection_restore_failure"] = type(error).__name__
                report["completed"] = False
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "prior", "codex-executable", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--key-file")
    parser.add_argument("--context-readout", action="store_true", help="Exploratory readouts of the unqualified courier setup; not a repaired onboarding result")
    parser.add_argument("--preflight", help="Matching completed context-readout preflight report required before live inference")
    args = parser.parse_args()
    if args.run and not args.key_file:
        parser.error("--run requires --key-file")
    result = asyncio.run(run(args))
    print(json.dumps({k: result.get(k) for k in ("completed", "failure", "agent_invocations_started", "provider_attempts", "usage")}))
    if not result.get("completed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
