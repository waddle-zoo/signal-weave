"""Opt-in review/policy supplement over closed stable-v2 homes; no reader reruns."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import tomllib
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit
from evaluations.decisions_semantic_trial import (
    PROTOCOL,
    ROOT,
    Episode,
    actor,
    grade_policy,
    grade_review,
    has_owner_routes,
    reader_instructions,
    save,
    save_ledger_snapshot,
)
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _installed_http_server,
    _manifest,
    _source_server,
    _SourceSession,
)
from evaluations.native_runtime_identity import inventory_native_runtime, verify_native_runtime
from evaluations.semantic_company import SemanticCompany
from scripts.binary_provenance import verify_binary

SOURCE_FILES = (
    "evaluations/semantic_review_supplement.py", "evaluations/decisions_semantic_trial.py",
    "evaluations/semantic_company.py", "evaluations/bootstrap_agent_trial.py",
    "evaluations/codex_trial_transport.py", "evaluations/codex_workspace.py",
    "evaluations/installed_trial_transport.py", "evaluations/native_runtime_identity.py",
    "scripts/binary_provenance.py", "skills/signalweave/SKILL.md",
    "evaluations/protocols/decisions-semantic-2026-10-25.json",
)
AMENDMENT = (
    "Prospective caller-interface correction applied equally to ordinary_context and signalweave: "
    "the original instruction said recipients were empty when no alert was warranted, contradicting "
    "the owner-requested data/definition review audience. The current shared reader instructions and "
    "submit_report schema include both review and business-alert audiences. The delivery schema names "
    "the sole authorized literal address agent://finance, and submit_report is explicitly terminal "
    "after confirmed delivery. Existing failures, reports and source hashes remain unchanged; no "
    "rescoring, argument repair, routing fallback or grading relaxation. Source-only provenance "
    "formatting also removes a duplicated measurement-publication prefix; publication records, "
    "measurement values and data snapshot IDs are unchanged."
)
REVIEW_QUESTION = (
    "Run the agreed Finance revenue review against current evidence. If a data or definition problem "
    "prevents a reliable business conclusion, explain what is known and what Finance needs to resolve. "
    "The fictional owner authorizes this review request ONLY to the exposed simulated local Finance "
    "inbox at agent://finance. Use send_finance_review and wait for delivery confirmation before the "
    "terminal submit_report, with the same message and its intended review audience. No external "
    "messages or schedule. Keep a data review distinct from a business-decline alert."
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    return {name: sha256(ROOT / name) for name in SOURCE_FILES}


def fresh_receipt(packet, key):
    return packet.get("replayed") is False and packet.get("receipt", {}).get("idempotency_key") == key


def assert_original_closed(original, company):
    """Check process arguments without recording them (they may contain private paths)."""
    listing = subprocess.run(["ps", "-axo", "pid=,command="], check=True, capture_output=True,
                             text=True).stdout
    home = str(original / company / "person/.signalweave")
    for line in listing.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or parts[0] == str(os.getpid()):
            continue
        command = parts[1]
        controller = "decisions_semantic_trial" in command and original.name in command
        serving_home = home in command and "serve" in command.split()
        if controller or serving_home:
            raise RuntimeError("Original company controller or native home is still running; do not clone")


def read_original(original, company):
    if original.name != "stable-v2-" + company:
        raise ValueError("--original must name the matching stable-v2 company run")
    report = json.loads((original / "report.json").read_text())
    protocol = json.loads((original / "protocol.json").read_text())
    if not (report.get("complete") or report.get("stopped") or report.get("failure")):
        raise ValueError("Original report has no terminal state; wait for its controller to close")
    records = [item for item in report["companies"] if item["company"] == company]
    if len(records) != 1:
        raise ValueError("Original report must contain exactly one matching company")
    prior = records[0]
    shared = prior["onboarding"]["submission"]
    if (prior["onboarding"]["agent"]["status"] != "complete"
            or not prior.get("onboarding_checks") or not all(prior["onboarding_checks"].values())
            or shared["card"]["status"] != "approved" or not has_owner_routes(shared["card"])):
        raise ValueError("Original onboarding did not preserve the approved Finance brief and routes")
    readers = prior.get("readers", [])
    if (len(readers) != 20 or {(r["index"], r["arm"]) for r in readers}
            != {(i, arm) for i in range(10) for arm in ("ordinary_context", "signalweave")}
            or any(r["agent"]["status"] != "complete" or not r.get("checks")
                   or not all(r["checks"].values()) for r in readers)):
        raise ValueError("Original run must retain all twenty successful canonical readers")
    if not protocol.get("refresh_after_onboarding") or not prior.get("measurement_refresh", {}).get("publication"):
        raise ValueError("Original run has no published measurement refresh")
    return protocol, prior


def clone_company(original, directory, company, seed, secret):
    """Copy only the closed home and ledger, including SQLite WAL companions."""
    assert_original_closed(original, company)
    old = original / company
    old_home = old / "person/.signalweave"
    ledger = old / f"{company}-{seed}.sqlite3"
    members = [old_home, *old_home.rglob("*"), ledger]
    if not old_home.is_dir() or not ledger.is_file() or any(p.is_symlink() for p in members):
        raise ValueError("Original home/ledger must be regular local files and directories")
    directory.mkdir(mode=0o700)
    home = directory / "person/.signalweave"
    shutil.copytree(old_home, home)
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(ledger) + suffix)
        if path.exists():
            if path.is_symlink():
                raise ValueError("Original ledger companion is a symlink")
            shutil.copy2(path, directory / path.name)
    config = home / "config.toml"
    parsed = tomllib.loads(config.read_text())
    if set(parsed) != {"version", "environment"} or parsed["version"] != 1:
        raise ValueError("Unexpected cloned native config format")
    configured_manifest = Path(parsed["environment"].get("SIGNALWEAVE_MCP_SOURCES_FILE", ""))
    if not configured_manifest.is_absolute():
        configured_manifest = old_home / configured_manifest
    if configured_manifest.resolve() != (old / "sources.json").resolve():
        raise ValueError("Original config must identify this company's MCP source manifest")
    settings = {key: value.replace(str(old), str(directory))
                for key, value in parsed["environment"].items()}
    settings.pop("OPENAI_API_KEY", None)
    settings["OPENAI_API_KEY_FILE"] = str(home / "openai.key")
    settings["SIGNALWEAVE_MCP_SOURCES_FILE"] = str(directory / "sources.json")
    config.write_text("version = 1\n\n[environment]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in settings.items()))
    (home / "openai.key").write_text(secret + "\n")
    for path in (directory, *directory.rglob("*")):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return SemanticCompany(directory, company, seed=seed)


def freeze_protocol(args, original_protocol, build, runtime):
    if build != original_protocol["build"] or runtime != original_protocol["runtime"]:
        raise ValueError("Supplement binary/runtime differs from the original stable-v2 run")
    return {
        "protocol": "semantic-review-supplement-v1", "company": args.company,
        "original": str(args.original), "original_report_sha256": sha256(args.original / "report.json"),
        "original_protocol_sha256": sha256(args.original / "protocol.json"),
        "original_build": original_protocol["build"], "original_runtime": original_protocol["runtime"],
        "build": build, "runtime": runtime, "source_hashes": source_hashes(),
        "protocol_sha256": sha256(PROTOCOL), "amendment": AMENDMENT,
        "plan": {"canonical_readers": 0, "review_episodes": 4, "native_policy_contrasts": 8,
                 "required_definition_edits": 1},
        "scope": "Separate supplement reusing actual fresh onboarding; not a reader retry or pooled result.",
        "source_conditions": "Restore the existing published ledger (10000 export scale); never publish again. "
                             "Review gap/conflict states retain that scale; only the explicit decline policy contrast uses 8200.",
        "stopping": "Preserve every attempt and stop on the first new error or failed gate; no retries.",
        "human_review": "Independent review of delivered and submitted briefs is still required.",
    }


@asynccontextmanager
async def cloned_native(args, company, directory, audit, frozen, transport):
    build = verify_binary(args.binary)
    if build != frozen["build"]:
        raise ValueError("Native binary changed after freezing")
    verify_native_runtime(args.binary, build, frozen["runtime"])
    home = directory / "person/.signalweave"
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    async with _source_server(_SourceSession(company, audit, company.tenant_id)) as url:
        manifest = _manifest({"scenario_id": company.tenant_id, "catalog": company.descriptors()}, url)
        for connection in manifest["connections"]:
            connection["context_namespace"] = "synthetic-semantic/" + company.tenant_id
        save(directory / "sources.json", manifest)
        if transport == "streamable-http":
            async with _installed_http_server(args.binary, home, directory, env, audit) as installed:
                yield installed
        else:
            params = StdioServerParameters(command=str(args.binary), args=["serve", "--home", str(home)],
                                           cwd=str(directory), env=env)
            with (directory / "native-stderr.txt").open("w") as errors:
                async with stdio_client(params, errlog=errors) as streams, ClientSession(*streams) as session:
                    initialized = await _initialize_mcp_session(session)
                    yield InstalledServer(session, initialized.instructions, audit)


async def run(args):
    if not args.live:
        raise ValueError("Paid execution requires --live")
    args.original, args.output = args.original.resolve(), args.output.resolve()
    if args.original == args.output or args.original in args.output.parents or args.output in args.original.parents:
        raise ValueError("Output and original directories must not overlap")
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    audit = Audit(path=args.output / "operator-trace.jsonl")
    result = {"company": args.company, "complete": False, "phase": "admission",
              "run_id": uuid.uuid4().hex, "review_handoffs": [], "policy_contrasts": [],
              "operator_calls": [], "ledger_snapshots": [], "delivery_enabled": False,
              "local_review_delivery": True, "provider_usage_instrumented": False}

    def checkpoint():
        save(args.output / "report.json", audit.redact(result))

    try:
        checkpoint()
        secret = args.key_file.read_text().strip()
        if not secret:
            raise ValueError("Empty private OpenAI credential")
        audit.secrets = (secret,)
        assert_original_closed(args.original, args.company)
        original_protocol, prior = read_original(args.original, args.company)
        build = verify_binary(args.binary)
        frozen = freeze_protocol(args, original_protocol, build, inventory_native_runtime(args.binary, build))
        save(args.output / "protocol.json", frozen)
        for name in ("report.json", "protocol.json"):
            shutil.copy2(args.original / name, args.output / ("original-" + name))
        result["phase"] = "clone"
        checkpoint()
        directory = args.output / args.company
        company = clone_company(args.original, directory, args.company, original_protocol["seed"], secret)
        result["ledger_snapshots"].append(save_ledger_snapshot(company, directory, "cloned-original"))
        if (sha256(args.original / "report.json") != frozen["original_report_sha256"]
                or sha256(args.original / "protocol.json") != frozen["original_protocol_sha256"]):
            raise ValueError("Original report/protocol changed during cloning")
        company.set_condition("quiet")
        publication = prior["measurement_refresh"]["publication"]
        with company._connect() as db:
            if (company._data_snapshot_id(db) != publication["data_snapshot_id"]
                    or [row[0] for row in db.execute("SELECT DISTINCT activity_bp FROM transactions")] != [10000]
                    or [row[0] for row in db.execute("SELECT publication_id FROM measurement_publications")]
                    != [publication["publication_id"]]):
                raise ValueError("Clone does not restore the exact existing post-publication ledger")
        result["ledger_snapshots"].append(save_ledger_snapshot(company, directory, "postpublication"))
        checkpoint()

        def unchanged_sources():
            if source_hashes() != frozen["source_hashes"]:
                raise ValueError("Frozen research helpers changed during the supplement")

        async with cloned_native(args, company, directory, audit, frozen, original_protocol["transport"]) as installed:
            async def call(name, arguments):
                unchanged_sources()
                attempt = {"phase": result["phase"], "tool": name, "arguments": copy.deepcopy(arguments),
                           "status": "started"}
                result["operator_calls"].append(attempt)
                checkpoint()
                try:
                    _, response = await installed.call_tool(name, arguments)
                    attempt.update(status="complete", response=response)
                    return response
                except BaseException:
                    attempt["status"] = "failed"
                    raise
                finally:
                    checkpoint()

            result["phase"] = "endpoint-revalidation"
            shared = copy.deepcopy(prior["onboarding"]["submission"])
            card = await call("get_insight_card", {"card_id": shared["card"]["id"], "response_mode": "full"})
            policy_fields = ("sources", "what_to_watch", "why_watch", "watch_for", "questions",
                             "decision_guidance", "delivery_methods", "numeric_conditions", "max_source_age_hours")
            if (card["status"] != "approved" or card["version"] != shared["card"]["version"]
                    or any(card.get(key) != shared["card"].get(key) for key in policy_fields)):
                raise ValueError("Cloned card differs from the successful original onboarding")
            pins = [{key: pin[key] for key in ("entry_id", "revision", "required_for_action")}
                    for pin in card["context_bindings"]]
            context = await call("retrieve_domain_context", {"entry_ids": [p["entry_id"] for p in pins]})
            expected_entries = {entry["id"]: entry for entry in shared["context"]["entries"]}
            for entry in context["entries"]:
                prior_entry = expected_entries[entry["id"]]
                if any(entry[key] != prior_entry[key] for key in ("revision", "status", "content")):
                    raise ValueError("Cloned reviewed definition changed since onboarding")
            if {e["id"] for e in context["entries"]} != {p["entry_id"] for p in pins}:
                raise ValueError("Cloned pinned definitions are missing")
            await call("bind_insight_context", {
                "card_id": card["id"], "expected_card_version": card["version"], "pins": pins,
                "reason": "Fictional source operator revalidated unchanged definitions and the published ledger at the new isolated endpoint."})
            review = await call("review_insight_card", {"card_id": card["id"]})
            await call("approve_insight_card", {
                **review["approval_handoff"]["arguments_after_owner_confirmation"],
                "source_selection_reason": "Fictional source owner confirms these exact returned source scopes at the cloned endpoint; unchanged Finance policy and no external delivery."})
            shared["card"] = await call("get_insight_card", {"card_id": card["id"], "response_mode": "full"})
            shared["context"] = context
            if (shared["card"]["status"] != "approved" or not has_owner_routes(shared["card"])
                    or any(card.get(key) != shared["card"].get(key) for key in policy_fields)):
                raise ValueError("Endpoint revalidation changed the approved owner policy")
            result["revalidated_brief"] = shared
            checkpoint()

            for condition in ("gap", "definition_conflict"):
                company.set_condition(condition)
                result["ledger_snapshots"].append(save_ledger_snapshot(company, directory, "review-" + condition))
                for arm in ("ordinary_context", "signalweave"):
                    result["phase"] = f"review-{condition}-{arm}"
                    episode = Episode(company, installed if arm == "signalweave" else None,
                                      notes=shared, review_delivery=True)
                    record = {"condition": condition, "arm": arm, "status": "started",
                              "human_review": "pending independent review"}
                    result["review_handoffs"].append(record)
                    checkpoint()
                    review_audit = Audit(path=directory / (result["phase"] + ".jsonl"), secrets=(secret,))
                    started = time.monotonic()
                    unchanged_sources()
                    try:
                        response = await actor(episode, review_audit, args.codex, reader_instructions(arm == "signalweave"), {
                            "question": REVIEW_QUESTION, "as_of": "2026-10-25",
                            "run_key": f"review-supplement:{result['run_id']}:{condition}:{arm}"})
                        record.update(agent=response, status=response["status"], checks=grade_review(episode, company))
                    finally:
                        record.update(submission=episode.submission, inbox=episode.inbox, calls=episode.calls,
                                      seconds=time.monotonic() - started)
                        checkpoint()
                    if response["status"] != "complete" or not all(record["checks"].values()):
                        result["stopped"] = "Review handoff failed; no retry or later phase"
                        return result

            for condition in ("quiet", "decline", "gap", "definition_conflict"):
                company.set_condition(condition)
                result["ledger_snapshots"].append(save_ledger_snapshot(company, directory, "policy-" + condition))
                for repeat in range(2):
                    result["phase"] = f"policy-{condition}-{repeat}"
                    key = f"review-supplement:{result['run_id']}:policy:{condition}:{repeat}"
                    packet = await call("evaluate_insight_card", {
                        "card_id": card["id"], "idempotency_key": key, "response_mode": "full"})
                    checks = grade_policy(condition, packet)
                    checks["fresh_receipt"] = fresh_receipt(packet, key)
                    result["policy_contrasts"].append({"condition": condition, "repeat": repeat, "packet": packet,
                        "checks": checks, "independent_source_values": company.expected()})
                    checkpoint()
                    if not all(checks.values()):
                        result["stopped"] = "Saved-policy contrast failed; no retry or later phase"
                        return result

            result["phase"] = "definition-edit"
            entry = next(entry for entry in context["entries"] if any(
                pin["entry_id"] == entry["id"] and pin["required_for_action"] for pin in pins))
            content = copy.deepcopy(entry["content"])
            content["body"] += " Finance is reviewing a proposed change to this definition; this edit is not approved."
            edited = await call("save_domain_context", {
                "entry_id": entry["id"], "expected_revision": entry["revision"], "content": content})
            company.set_condition("decline")
            result["ledger_snapshots"].append(save_ledger_snapshot(company, directory, "definition-edit"))
            key = f"review-supplement:{result['run_id']}:definition-edit"
            packet = await call("evaluate_insight_card", {
                "card_id": card["id"], "idempotency_key": key, "response_mode": "full"})
            checks = {
                "new_draft": edited["status"] == "draft" and edited["revision"] == entry["revision"] + 1,
                "no_policy_outcome": packet["result"]["outcome"] is None,
                "reason": packet["result"]["judgment"]["reason"] == "context_review_required",
                "no_routes": packet["result"]["delivery_methods"] == [],
                "source_evidence_retained": any(s.get("evidence") for s in packet["result"].get("source_by_key", {}).values()),
                "fresh_receipt": fresh_receipt(packet, key),
            }
            result["definition_change"] = {"edited_context": edited, "packet": packet, "checks": checks}
            result["complete"] = all(checks.values())
            if not result["complete"]:
                result["stopped"] = "Required-definition edit failed; no retry"
        return result
    except BaseException as error:
        result["complete"] = False
        result["failure"] = {"type": type(error).__name__, "message": audit.redact(str(error))[:1500]}
        result["stopped"] = "Error or interruption; no retry or later phase"
        return result
    finally:
        checkpoint()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "key-file", "codex", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--company", choices=("retail", "saas", "marketplace"), required=True)
    parser.add_argument("--live", action="store_true", help="Permit paid Codex and Decisions calls")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("This supplement makes paid calls; explicitly pass --live")
    for name in ("binary", "key_file", "codex", "original", "output"):
        setattr(args, name, getattr(args, name).resolve())
    if args.output.exists():
        parser.error("Output already exists; choose a new exclusive directory")
    return args


def main(argv=None):
    report = asyncio.run(run(parse_args(argv)))
    print(json.dumps({"company": report["company"], "complete": report["complete"],
                      "stopped": report.get("stopped")}))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
