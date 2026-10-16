"""New bounded reporting cohort over the retained, approved Northstar card."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import tomllib
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.codex_trial_transport import codex_episode
from evaluations.domain_context_onboarding_trial import approval_digest, pinned_codex
from evaluations.explicit_owner_conversation import AuditedNative
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _jev_proxy,
)
from evaluations.raw_superset_onboarding import digest, usage_snapshot
from evaluations.raw_superset_tools import RawSupersetTools
from evaluations.raw_superset_workflow import REPORT_NATIVE, REPORT_RULES, ReportEpisode
from scripts.binary_provenance import verify_binary
from signalweave.models import InsightCard
from signalweave.superset_client import SupersetClient

PROTOCOL = "retained-raw-followup-v1"
MANIFEST = Path(__file__).with_name("data") / f"{PROTOCOL}.json"
SOURCE_URL = "http://127.0.0.1:18089"
PRIOR_PROTOCOL = "raw-northstar-workflow-v2"
PRIOR_REPORT_SHA256 = "2a4c0b4ebbfd09b23fe97b6be3ed89c8857ef347aaaae0fe841e8003a3d712e4"
PRIOR_TRACE_SHA256 = "d759fdb5f2e2d73f2742409cc0be97fe1eb5ca83f90996c93ee13580906c5c28"
CARD_POLICY_SHA256 = "970a730838db97e05d31e753f8052d87f7b7fcfb3140bd7dcf44f3a82184e54b"
RUN_KEY = "retained-raw-followup-v1:report"
ARM_ORDER = ("baseline", "signalweave")
SOURCE_ASSETS = {
    "1": {"source_url": f"{SOURCE_URL}/explore/?slice_id=1"},
    "10": {"source_url": f"{SOURCE_URL}/explore/?slice_id=10"},
}
ROW_FINGERPRINT_ENCODING = "sorted_json_row_multiset_v1"
EXPECTED_LIMITS = {
    "frontier_invocations": 2,
    "tools_per_episode": 24,
    "seconds_per_episode": 300,
    "model": "gpt-6-luna",
    "reasoning_effort": "xhigh",
    "max_output_tokens": 4000,
    "jev_attempts_total": 1,
    "jev_arm": "signalweave",
    "between_invocation_input_stop": 600000,
    "between_invocation_uncached_stop": 120000,
    "accounting_drain": True,
    "automatic_retries": 0,
}
HELPER_ROOT_NAMES = ("evaluations", "signalweave", "scripts")
BI_TOOLS = {
    "find_dashboards", "list_dashboard_charts", "read_chart_rows",
    "profile_saved_chart", "aggregate_chart_rows",
}
SHARED_TOOLS = BI_TOOLS | {"calculate", "read_working_notes", "record_report"}
REPORT_REQUEST = (
    "Complete the approved calendar-month sales readout. Then investigate the apparent Online hit "
    "with a matched first-N-days comparison between the latest month and the prior month, letting "
    "source coverage establish N. Keep that diagnostic separate from the approved calendar-month "
    "policy result."
)
REPORT_INSTRUCTIONS = (
    REPORT_RULES.replace(
        "recover your notes",
        "use your supplied retained notes as needed; read_working_notes is available",
    )
    + " Current factual claims require refreshed evidence from this run, not retained notes. "
      "Report the approved "
      "calendar-month result first, then the matched first-N-days diagnostic as a separate follow-up. "
      "Do not let the matched-day diagnostic replace or change the approved calendar-month policy. "
      "Use the exact declared source units; do not infer currency, cause, or recipients. No arbitrary "
      "SQL, shell, scheduling, or sending."
)


class RetainedReportEpisode(ReportEpisode):
    """Keep native reads bound to this card and this new receipt only."""

    def __init__(self, *args, source_state, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_receipt_ids: set[str] = set()
        self.source_state = source_state
        self.source_reads = []

    async def call(self, name, args):
        if name == "get_insight_card" and args.get("card_id") != self.approved_card_id:
            raise ValueError("Read only the retained approved card")
        if name == "get_decision_receipt":
            exact_key = args.get("idempotency_key") == self.run_key
            exact_receipt = args.get("receipt_id") in self.allowed_receipt_ids
            if exact_key == exact_receipt:
                raise ValueError("Read only this follow-up's receipt")
        result = await super().call(name, args)
        if name in {"profile_saved_chart", "read_chart_rows", "aggregate_chart_rows"}:
            self.source_reads.append(validate_actor_source_read(name, args, result, self.source_state))
        if name == "evaluate_insight_card":
            receipt_id = (result.get("receipt") or {}).get("receipt_id")
            if isinstance(receipt_id, str):
                self.allowed_receipt_ids.add(receipt_id)
        return result


def json_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def helper_hashes() -> dict[str, str]:
    """Hash a fixed source inventory, independent of later imports in the parent process."""
    repository = Path(__file__).resolve().parents[1]
    paths = sorted({path for root in HELPER_ROOT_NAMES
                    for path in (repository / root).rglob("*.py")
                    if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts})
    return {path.relative_to(repository).as_posix(): digest(path) for path in paths}


def validate_manifest(manifest: dict) -> None:
    if manifest.get("protocol") != PROTOCOL:
        raise ValueError("Unexpected follow-up protocol")
    if manifest.get("execution_status") != "planned":
        raise ValueError("Follow-up cohort is closed or not preregistered")
    prior = manifest.get("prior", {})
    if (prior.get("protocol") != PRIOR_PROTOCOL
            or prior.get("report_sha256") != PRIOR_REPORT_SHA256
            or prior.get("trace_sha256") != PRIOR_TRACE_SHA256
            or prior.get("card_policy_sha256") != CARD_POLICY_SHA256
            or prior.get("card_id") != "card-executive-monthly-net-sales-and-online-contribution-4da3a6cb"
            or prior.get("card_version") != 1
            or prior.get("run_key") != "raw-northstar-workflow-v2:report"
            or prior.get("receipt_id") != "receipt-134632e7393b45ce87792b6008abbf9c"):
        raise ValueError("Manifest does not pin the exact completed v2 record and card")
    if (manifest.get("run_key") != RUN_KEY or manifest.get("arm_order") != list(ARM_ORDER)
            or manifest.get("limits") != EXPECTED_LIMITS
            or manifest.get("source_assets") != SOURCE_ASSETS
            or manifest.get("row_fingerprint_encoding") != ROW_FINGERPRINT_ENCODING):
        raise ValueError("Manifest changed the fixed key, order, limits, or source identity")


def validate_preflight(previous: dict, frozen: dict) -> None:
    required_true = (
        "completed", "preflight_only", "source_probe_ok", "shared_tools_equal",
        "card_policy_valid", "prior_receipt_valid", "prior_artifacts_unchanged",
        "native_config_unchanged", "persisted_dummy_key_metadata_valid", "usage_known",
        "followup_key_unused",
    )
    if (previous.get("frozen") != frozen
            or previous.get("protocol") != PROTOCOL
            or previous.get("frontier_invocations_started") != 0
            or previous.get("jev_attempts") != 0
            or any(previous.get(field) is not True for field in required_true)):
        raise ValueError("Live run needs a matching successful zero-inference preflight")
    if previous.get("usage") != {
        "input_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0,
        "output_tokens": 0, "responses": 0,
    }:
        raise ValueError("Preflight must account for zero frontier requests")


def validate_prior_record(manifest: dict, root: Path, owner_file: Path):
    prior_spec = manifest["prior"]
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Prior root must be an existing ordinary directory")
    report_path, trace_path = root / "report.json", root / "trace.jsonl"
    if (report_path.is_symlink() or trace_path.is_symlink()
            or digest(report_path) != prior_spec["report_sha256"]
            or digest(trace_path) != prior_spec["trace_sha256"]):
        raise ValueError("Prior report or trace differs from the frozen v2 artifacts")
    prior = json.loads(report_path.read_text())
    if (prior.get("protocol") != PRIOR_PROTOCOL or prior.get("completed") is not True
            or prior.get("usage_known") is not True or prior.get("invocations") != 6
            or prior.get("upstream_jev_requests") != 1
            or prior.get("paired_reporting_complete") is not True
            or prior.get("card_policy_unchanged") is not True
            or prior.get("credential_scrubbed") is not True
            or prior.get("approval", {}).get("status") != "approved"):
        raise ValueError("Prior root is not the completed, approved v2 cohort")
    author_episodes = [episode for episode in prior.get("episodes", [])
                       if episode.get("stage") == "author"]
    authors = {episode.get("arm"): episode for episode in author_episodes}
    if set(authors) != {"baseline", "signalweave"}:
        raise ValueError("Prior cohort does not contain both retained author records")
    notes = {arm: episode.get("notes") for arm, episode in authors.items()}
    if any(not isinstance(value, str) or not value.strip() for value in notes.values()):
        raise ValueError("Each arm must retain its own nonempty author notes")
    treatment_reports = [episode for episode in prior.get("episodes", [])
                         if episode.get("stage") == "report" and episode.get("arm") == "signalweave"]
    if len(treatment_reports) != 1:
        raise ValueError("Prior v2 treatment report is missing or ambiguous")
    evaluations = [call for call in treatment_reports[0].get("native_calls", [])
                   if call.get("name") == "evaluate_insight_card"]
    if len(evaluations) != 1:
        raise ValueError("Prior v2 native evaluation is missing or ambiguous")
    call = evaluations[0]
    receipt = call.get("result", {}).get("receipt", {})
    if (call.get("arguments", {}).get("card_id") != prior_spec["card_id"]
            or call.get("arguments", {}).get("idempotency_key") != prior_spec["run_key"]
            or receipt.get("receipt_id") != prior_spec["receipt_id"]
            or receipt.get("delivery_enabled") is not False):
        raise ValueError("Prior v2 call does not match its pinned card and receipt")
    owner = json.loads(owner_file.read_text())
    declarations = owner.get("owner_declarations")
    if not isinstance(declarations, (dict, list)) or not declarations:
        raise ValueError("The retained owner declarations are missing")
    return prior, notes, declarations


def key_file_metadata(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected a regular private TypeSafe key file")
    metadata = path.stat()
    if (metadata.st_uid != os.geteuid() or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise ValueError("TypeSafe key file must be private, regular, and singly linked")
    return {"size": metadata.st_size, "mode": stat.S_IMODE(metadata.st_mode),
            "device": metadata.st_dev, "inode": metadata.st_ino, "mtime_ns": metadata.st_mtime_ns}


def retained_home_paths(prior_root: Path):
    home = prior_root / "native-home"
    config, dummy_key = home / "config.toml", home / "typesafe.key"
    if (home.is_symlink() or not home.is_dir() or config.is_symlink() or not config.is_file()):
        raise ValueError("The retained native home or its configuration is missing or redirected")
    return home, config, dummy_key


def static_frozen(manifest_path: Path, owner_file: Path, prior_root: Path,
                  binary_info: dict, codex: dict, config_path: Path, dummy_key: Path,
                  manifest: dict, notes: dict, source_captures: dict) -> dict:
    return {
        "protocol": PROTOCOL,
        "prior_root": str(prior_root),
        "native_home": str(prior_root / "native-home"),
        "build": binary_info,
        "codex": codex,
        "runner_sha256": digest(__file__),
        "manifest_sha256": digest(manifest_path),
        "owner_reference_sha256": digest(owner_file),
        "helpers": helper_hashes(),
        "prior": {
            "report_sha256": PRIOR_REPORT_SHA256,
            "trace_sha256": PRIOR_TRACE_SHA256,
            "card_id": manifest["prior"]["card_id"],
            "card_version": manifest["prior"]["card_version"],
            "card_policy_sha256": CARD_POLICY_SHA256,
            "run_key": manifest["prior"]["run_key"],
            "receipt_id": manifest["prior"]["receipt_id"],
            "owner_notes_sha256": {arm: hashlib.sha256(value.encode()).hexdigest()
                                    for arm, value in notes.items()},
        },
        "native_config_sha256": digest(config_path),
        "persisted_dummy_key_metadata": key_file_metadata(dummy_key),
        "coordinator_superset_url": coordinator_superset_url(config_path),
        "prior_source_captures": source_captures,
        "source_assets": SOURCE_ASSETS,
        "row_fingerprint_encoding": ROW_FINGERPRINT_ENCODING,
    }


def validate_card(card: dict, manifest: dict) -> None:
    expected = manifest["prior"]
    if (card.get("id") != expected["card_id"] or card.get("version") != expected["card_version"]
            or card.get("status") != "approved"
            or approval_digest("card", card) != expected["card_policy_sha256"]):
        raise ValueError("Retained native card is not the exact approved v2 policy")


def validate_old_receipt(result: dict, manifest: dict) -> None:
    receipt = result.get("receipt", {})
    expected = manifest["prior"]
    if (result.get("status") != "found" or receipt.get("receipt_id") != expected["receipt_id"]
            or receipt.get("idempotency_key") != expected["run_key"]
            or receipt.get("card_id") != expected["card_id"]
            or receipt.get("card_version") != expected["card_version"]
            or receipt.get("delivery_enabled") is not False):
        raise ValueError("The prior v2 receipt is missing or differs from its frozen identity")


async def read_prior_state(native, manifest):
    prior = manifest["prior"]
    _, card = await native.call_tool("get_insight_card", {
        "card_id": prior["card_id"], "response_mode": "full",
    })
    validate_card(card, manifest)
    _, receipt = await native.call_tool("get_decision_receipt", {"receipt_id": prior["receipt_id"]})
    validate_old_receipt(receipt, manifest)
    state = {"card_policy_sha256": approval_digest("card", card),
             "receipt_sha256": json_digest(receipt), "card_id": card["id"],
             "card_version": card["version"], "receipt_id": receipt["receipt"]["receipt_id"]}
    return state, card


async def require_followup_key_unused(native, manifest) -> None:
    try:
        _, existing = await native.call_tool("get_decision_receipt", {
            "idempotency_key": manifest["run_key"],
        })
    except Exception as error:
        if "unknown decision receipt" in str(error).lower():
            return
        raise ValueError("Cannot prove the follow-up idempotency key is unused") from None
    if existing.get("status") == "not_found":
        return
    raise ValueError("The follow-up idempotency key already has a durable receipt; no retry")


def prior_source_captures(prior_root: Path) -> dict[str, dict]:
    captures = {}
    with (prior_root / "trace.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("kind") != "tool.result" or event.get("name") not in {
                    "profile_saved_chart", "read_chart_rows", "aggregate_chart_rows"}:
                continue
            result = event.get("result")
            chart_id = str((result or {}).get("chart_id", ""))
            if chart_id not in SOURCE_ASSETS or not isinstance(result.get("query_definition"), dict):
                continue
            capture = {"query_definition_sha256": json_digest(result["query_definition"]),
                       "columns": result.get("columns")}
            if chart_id in captures and captures[chart_id] != capture:
                raise ValueError("Pinned v2 source query identity is internally inconsistent")
            captures[chart_id] = capture
    if set(captures) != set(SOURCE_ASSETS) or any(
            not isinstance(value.get("columns"), list) for value in captures.values()):
        raise ValueError("Pinned v2 trace lacks both saved-chart query definitions and columns")
    return captures


def coordinator_superset_url(config_path: Path) -> str:
    try:
        environment = tomllib.loads(config_path.read_text()).get("environment", {})
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("Retained native configuration is unreadable") from None
    url = environment.get("SUPERSET_URL") if isinstance(environment, dict) else None
    if url != SOURCE_URL:
        raise ValueError("Retained native home must use the expected loopback Superset URL")
    return url


def source_profile_identity(result: dict, chart_id: str,
                            prior_captures: dict[str, dict]) -> dict:
    prior = prior_captures[chart_id]
    row_hash = result.get("returned_rows_sha256")
    if (str(result.get("chart_id")) != chart_id
            or not isinstance(result.get("query_definition"), dict)
            or json_digest(result["query_definition"]) != prior["query_definition_sha256"]
            or result.get("columns") != prior["columns"]
            or result.get("returned_rows_fingerprint_encoding") != ROW_FINGERPRINT_ENCODING
            or not isinstance(row_hash, str) or len(row_hash) != 64
            or any(char not in "0123456789abcdef" for char in row_hash)):
        raise ValueError(f"Current saved chart {chart_id} differs from the pinned v2 source identity")
    return {"query_definition_sha256": prior["query_definition_sha256"],
            "columns": prior["columns"], "returned_rows_sha256": row_hash,
            "returned_rows_fingerprint_encoding": ROW_FINGERPRINT_ENCODING}


def validate_native_source_inspection(snapshot: dict, profile: dict, chart_id: str) -> dict:
    expected_url = SOURCE_ASSETS[chart_id]["source_url"]
    metadata = snapshot.get("metadata", {})
    saved = metadata.get("saved_query_definition", {})
    definition = profile["query_definition"]
    try:
        params = json.loads(definition["params"]) if isinstance(definition.get("params"), str) else definition.get("params", {})
    except (TypeError, ValueError):
        raise ValueError(f"Pinned saved chart {chart_id} has invalid parameters") from None
    selected = {key: params[key] for key in (
        "metrics", "groupby", "granularity_sqla", "time_grain_sqla", "time_range",
        "adhoc_filters", "row_limit", "all_columns",
    ) if key in params}
    if (snapshot.get("adapter") != "superset" or snapshot.get("resource") != f"chart:{chart_id}"
            or snapshot.get("source_url") != expected_url or snapshot.get("error") is not None
            or metadata.get("chart_id") != chart_id or metadata.get("result_columns") != profile["columns"]
            or saved.get("source_chart_id") != chart_id or saved.get("status") != "available"
            or saved.get("parameters") != selected):
        raise ValueError(f"Native inspection of saved chart {chart_id} differs from the pinned source")
    return {"resource": snapshot["resource"], "source_url": snapshot["source_url"],
            "query_definition_sha256": json_digest(profile["query_definition"]),
            "columns": profile["columns"]}


async def probe_sources(native, prior_captures, expected_rows=None) -> tuple[dict, dict]:
    source = make_sources()
    rows, inspections = {}, {}
    for chart_id in SOURCE_ASSETS:
        profile = await source.call("profile_saved_chart", {"id": chart_id})
        rows[chart_id] = source_profile_identity(profile, chart_id, prior_captures)
        if expected_rows is not None and rows[chart_id] != expected_rows.get(chart_id):
            raise RuntimeError(f"Current returned rows for chart {chart_id} differ from preflight")
        _, snapshot = await native.call_tool("inspect_resource", {
            "adapter": "superset", "resource": f"chart:{chart_id}",
        })
        inspections[chart_id] = validate_native_source_inspection(snapshot, profile, chart_id)
    return {"profiles": rows, "native_inspections": inspections}, source.telemetry


def validate_actor_source_read(name: str, args: dict, result: dict,
                               expected_state: dict[str, dict]) -> dict:
    provenance = result.get("source_provenance", {}) if name == "aggregate_chart_rows" else result
    chart_id = str(provenance.get("chart_id", args.get("id", "")))
    if chart_id not in expected_state:
        raise ValueError("Actor source read is outside the frozen saved-chart set")
    identity = {"query_definition_sha256": json_digest(provenance.get("query_definition")),
                "columns": provenance.get("columns"),
                "returned_rows_sha256": provenance.get("returned_rows_sha256"),
                "returned_rows_fingerprint_encoding": provenance.get("returned_rows_fingerprint_encoding")}
    expected = expected_state[chart_id]
    if (identity != expected or provenance.get("query_scope", {}).get("kind") != "saved_chart_query"):
        raise RuntimeError(f"Actor source read for chart {chart_id} differs from preflight")
    return {"tool": name, "chart_id": chart_id, **identity}


def make_sources():
    return RawSupersetTools(SupersetClient(SOURCE_URL, "admin", "admin"), enable_aggregation=True)


async def make_sessions(native, declarations, notes, manifest, source_state):
    prior = manifest["prior"]
    baseline = RetainedReportEpisode(make_sources(), declarations, notes["baseline"],
                                     approved_card_id=prior["card_id"], run_key=manifest["run_key"],
                                     source_state=source_state)
    treatment = RetainedReportEpisode(make_sources(), declarations, notes["signalweave"], native,
                                      approved_card_id=prior["card_id"], run_key=manifest["run_key"],
                                      source_state=source_state)
    base_specs, treatment_specs = await baseline.specs(), await treatment.specs()
    shared_treatment = [spec for spec in treatment_specs if spec["name"] not in REPORT_NATIVE]
    base_names = [spec["name"] for spec in base_specs]
    treatment_names = [spec["name"] for spec in treatment_specs]
    if (base_specs != shared_treatment
            or len(base_names) != len(set(base_names))
            or len(treatment_names) != len(set(treatment_names))
            or set(base_names) != SHARED_TOOLS
            or set(treatment_names) != SHARED_TOOLS | REPORT_NATIVE):
        raise ValueError("Both report arms must have the same five BI and shared analysis tools")
    return baseline, treatment, base_specs, treatment_specs


def _receipt_time(receipt: dict) -> datetime:
    value = receipt.get("created_at")
    if not isinstance(value, str):
        raise ValueError("New native receipt has no creation timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("New native receipt has an invalid creation timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError("New native receipt timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_new_receipt(evaluation: dict, lookup: dict, manifest: dict,
                         started_at: str) -> dict:
    receipt = evaluation.get("receipt", {})
    prior = manifest["prior"]
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError("Cohort start timestamp is invalid") from None
    if started.tzinfo is None:
        raise ValueError("Cohort start timestamp must include a timezone")
    started = started.astimezone(timezone.utc)
    created = _receipt_time(receipt)
    final = lookup.get("receipt", {})
    if (evaluation.get("replayed") is not False
            or lookup.get("status") != "found"
            or not isinstance(receipt.get("receipt_id"), str) or not receipt.get("receipt_id")
            or receipt.get("receipt_id") == prior["receipt_id"]
            or receipt.get("idempotency_key") != manifest["run_key"]
            or receipt.get("card_id") != prior["card_id"]
            or receipt.get("card_version") != prior["card_version"]
            or receipt.get("status") != "delivery_disabled"
            or receipt.get("delivery_enabled") is not False
            or receipt.get("delivery_mode") != "shadow"
            or created < started or created > datetime.now(timezone.utc)
            or final.get("receipt_id") != receipt.get("receipt_id")
            or any(final.get(field) != receipt.get(field) for field in (
                "idempotency_key", "card_id", "card_version", "status", "created_at",
                "delivery_enabled", "delivery_mode",
            ))):
        raise ValueError("The follow-up must create and retrieve one fresh, non-replayed shadow receipt")
    return {key: receipt.get(key) for key in (
        "receipt_id", "idempotency_key", "card_id", "card_version", "status", "created_at",
        "delivery_enabled", "delivery_mode",
    )}


def validate_jev_completion(events: list[dict], budget: RequestBudget) -> dict:
    requests = [event for event in events if event.get("provider") == "jev"
                and event.get("kind") == "api.request"]
    responses = [event for event in events if event.get("provider") == "jev"
                 and event.get("kind") == "api.response"]
    failures = [event for event in events if event.get("provider") == "jev"
                and event.get("kind") in {"api.error", "api.rejected"}]
    if (budget.used != 1 or len(requests) != 1 or len(responses) != 1 or failures
            or type(requests[0].get("request_id")) is not int or requests[0]["request_id"] < 1
            or requests[0].get("request_id") != responses[0].get("request_id")):
        raise ValueError("Completion requires exactly one successful, unrejected Jev request")
    usage = responses[0].get("usage")
    if (not isinstance(usage, dict)
            or any(type(usage.get(field)) is not int or usage[field] < 0
                   for field in ("input_tokens", "output_tokens"))):
        raise ValueError("Completion requires known nonnegative Jev input and output usage")
    return {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]}


@asynccontextmanager
async def retained_native(binary: Path, home: Path, prior_root: Path,
                          provider_key_file: Path, audit: Audit, budget: RequestBudget):
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    environment.update({"TYPESAFE_MAX_RETRIES": "0",
                        "TYPESAFE_API_KEY_FILE": str(provider_key_file)})
    async with _jev_proxy(audit, budget) as proxy:
        environment["TYPESAFE_BASE_URL"] = proxy
        params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)],
                                       cwd=str(prior_root), env=environment)
        with open(os.devnull, "w") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                async with ClientSession(*streams) as client:
                    initialized = await _initialize_mcp_session(client)
                    installed = InstalledServer(client, initialized.instructions, audit)
                    yield AuditedNative(installed, audit)


def output_disjoint(output: Path, prior_root: Path) -> None:
    if output == prior_root or output.is_relative_to(prior_root) or prior_root.is_relative_to(output):
        raise ValueError("Output must be isolated from the retained v2 root")


def check_prior_files(root: Path, manifest: dict) -> bool:
    return (digest(root / "report.json") == manifest["prior"]["report_sha256"]
            and digest(root / "trace.jsonl") == manifest["prior"]["trace_sha256"])


def close_manifest_before_first_actor(path: Path, manifest: dict, frozen: dict, report: dict) -> None:
    if manifest.get("execution_status") != "planned" or json.loads(path.read_text()) != manifest:
        raise RuntimeError("Preregistration changed or was already consumed; no alternate run")
    original_hash = digest(path)
    closed = {**manifest, "execution_status": "closed"}
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(closed, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    manifest.clear()
    manifest.update(closed)
    frozen["manifest_sha256"] = digest(path)
    report["preregistered_manifest_sha256"] = original_hash
    report["manifest_closed_before_first_actor"] = True
    report["frozen"] = frozen


def ensure_invocation_budget(audit: Audit, report: dict, limits: dict) -> None:
    usage = usage_snapshot(audit.events, report["frontier_invocations_started"])
    if (not usage["known"]
            or usage["usage"]["input_tokens"] >= limits["between_invocation_input_stop"]
            or usage["usage"]["uncached_input_tokens"] >= limits["between_invocation_uncached_stop"]):
        raise RuntimeError("Between-invocation usage stop; no retry or allowance transfer")
    if report["frontier_invocations_started"] >= limits["frontier_invocations"]:
        raise RuntimeError("Frontier invocation limit reached; cohort is terminal")


def has_source_failure(events: list[dict]) -> bool:
    return any(event.get("kind") == "tool.result" and event.get("name") in BI_TOOLS
               and isinstance(event.get("result"), dict)
               and event["result"].get("error") == "RawSupersetSourceError"
               for event in events)


def safe_error_message(error: Exception, audit: Audit, private_paths: list[str]) -> str:
    message = str(error)
    for path in private_paths:
        if path:
            message = message.replace(path, "[PRIVATE_KEY_FILE]")
    return audit.redact(message)[:1000]


async def run(args) -> dict:
    manifest_path = Path(getattr(args, "manifest", None) or MANIFEST).resolve()
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest)

    prior_argument = Path(args.prior_root).expanduser()
    if prior_argument.is_symlink():
        raise ValueError("Prior root must not be a symlink")
    prior_root = prior_argument.resolve(strict=True)
    output = Path(args.output).resolve()
    output_disjoint(output, prior_root)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    output.chmod(0o700)
    trace_path = output / "trace.jsonl"
    trace_path.touch(mode=0o600, exist_ok=False)
    trace_path.chmod(0o600)

    report = {
        "protocol": PROTOCOL,
        "scope": manifest["scope"],
        "prior_protocol": PRIOR_PROTOCOL,
        "prior_report_sha256": PRIOR_REPORT_SHA256,
        "prior_trace_sha256": PRIOR_TRACE_SHA256,
        "preflight_only": not args.run,
        "terminal_status": "running",
        "completed": False,
        "frontier_invocations_started": 0,
        "episodes": [],
        "limits": manifest["limits"],
        "private_artifacts": {"report": str(output / "report.json"), "trace": str(trace_path)},
    }
    audit = Audit(path=trace_path)
    budget = RequestBudget(1 if args.run else 0)
    native = None
    frozen = None
    before_state = None
    evaluation_result = None
    cohort_started_at = None
    binary = home = provider_key_file = None
    config_path = dummy_key = owner_file = codex = None
    provider_key_metadata = None
    private_paths = []
    notes = declarations = None

    def save():
        frontier = usage_snapshot(audit.events, report["frontier_invocations_started"])
        report["usage_known"] = frontier["known"]
        report["usage"] = frontier["usage"]
        report["observed_frontier_usage"] = frontier["observed"]
        jev_requests = [event for event in audit.events
                        if event.get("kind") == "api.request" and event.get("provider") == "jev"]
        jev_responses = [event for event in audit.events
                         if event.get("kind") == "api.response" and event.get("provider") == "jev"]
        jev_errors = [event for event in audit.events
                      if event.get("kind") in {"api.error", "api.rejected"}
                      and event.get("provider") == "jev"]
        report["jev_attempts"] = budget.used
        report["jev_usage_known"] = (len(jev_requests) == budget.used == len(jev_responses)
                                     and not jev_errors
                                     and all(isinstance(event.get("usage"), dict)
                                             and all(type(event["usage"].get(field)) is int
                                                     and event["usage"][field] >= 0
                                                     for field in ("input_tokens", "output_tokens"))
                                             for event in jev_responses))
        report["jev_usage"] = [event.get("usage") for event in jev_responses]
        report["tool_calls_by_episode"] = {
            entry["arm"]: entry.get("tool_calls") for entry in report["episodes"]
        }
        report["native_tool_calls_by_episode"] = {
            entry["arm"]: entry.get("native_tool_calls", 0) for entry in report["episodes"]
        }
        report["source_telemetry_by_episode"] = {
            entry["arm"]: entry.get("source_telemetry", {}) for entry in report["episodes"]
        }
        report["tool_result_events"] = sum(event.get("kind") == "tool.result" for event in audit.events)
        path = output / "report.json"
        path.write_text(json.dumps(audit.redact(report), ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)

    def ensure_static_inputs():
        if frozen is None:
            return
        current_binary = verify_binary(binary)
        current_codex = hashlib.sha256(Path(codex["path"]).read_bytes()).hexdigest()
        if (current_binary != frozen["build"] or helper_hashes() != frozen["helpers"]
                or digest(__file__) != frozen["runner_sha256"]
                or digest(manifest_path) != frozen["manifest_sha256"]
                or digest(owner_file) != frozen["owner_reference_sha256"]
                or current_codex != codex["sha256"]
                or not check_prior_files(prior_root, manifest)):
            raise RuntimeError("Frozen execution inputs changed; cohort is terminal")
        if (digest(config_path) != frozen["native_config_sha256"]
                or key_file_metadata(dummy_key) != frozen["persisted_dummy_key_metadata"]):
            raise RuntimeError("Retained native configuration or dummy-key metadata changed")
        if (provider_key_metadata is not None
                and key_file_metadata(provider_key_file) != provider_key_metadata):
            raise RuntimeError("Active provider-key metadata changed")

    try:
        if getattr(args, "superset_url", SOURCE_URL) != SOURCE_URL:
            raise ValueError("This protocol authorizes only the loopback Superset endpoint")
        owner_file = manifest_path.with_name(manifest["owner_reference_file"])
        _, notes, declarations = validate_prior_record(manifest, prior_root, owner_file)
        source_captures = prior_source_captures(prior_root)
        home, config_path, dummy_key = retained_home_paths(prior_root)
        binary = Path(args.binary).resolve(strict=True)
        binary_info = verify_binary(binary)
        codex = await pinned_codex(args.codex_executable)
        frozen = static_frozen(manifest_path, owner_file, prior_root, binary_info, codex,
                               config_path, dummy_key, manifest, notes, source_captures)
        report["frozen"] = frozen
        report["arm_order"] = list(ARM_ORDER)
        report["request"] = REPORT_REQUEST

        if args.run:
            override = os.environ.get("TYPESAFE_API_KEY_FILE") or getattr(args, "key_file", None)
            if not override:
                raise ValueError("Live run needs --key-file or TYPESAFE_API_KEY_FILE")
            requested_key_path = Path(override).expanduser()
            private_paths.extend((str(requested_key_path), str(requested_key_path.absolute())))
            if requested_key_path.is_symlink():
                raise ValueError("Live key-file path must not be a symlink")
            provider_key_file = requested_key_path.resolve(strict=True)
            private_paths.append(str(provider_key_file))
            if provider_key_file == dummy_key.resolve():
                raise ValueError("Live run must use an explicit provider key-file path")
            provider_key_metadata = key_file_metadata(provider_key_file)
            report["provider_key_source"] = (
                "TYPESAFE_API_KEY_FILE" if os.environ.get("TYPESAFE_API_KEY_FILE") else "--key-file"
            )
        else:
            provider_key_file = dummy_key
            report["provider_key_source"] = "persisted scrubbed dummy"

        async with retained_native(binary, home, prior_root, provider_key_file, audit, budget) as connected:
            native = connected
            before_state, active_card = await read_prior_state(native, manifest)
            frozen["retained_card_policy_sha256"] = before_state["card_policy_sha256"]
            frozen["prior_receipt_sha256"] = before_state["receipt_sha256"]
            source_probe, source_telemetry = await probe_sources(native, source_captures)
            source_state = source_probe["profiles"]
            frozen["source_state"] = source_state
            frozen["native_source_inspections"] = source_probe["native_inspections"]
            report["frozen"] = frozen
            report["prior_state_before"] = before_state
            report["source_profile_probe"] = source_state
            report["native_source_inspections"] = source_probe["native_inspections"]
            report["source_probe_telemetry"] = source_telemetry
            report["source_probe_ok"] = True
            baseline_session, treatment_session, base_specs, treatment_specs = await make_sessions(
                native, declarations, notes, manifest, source_state,
            )
            report["shared_tools_equal"] = (
                base_specs == [spec for spec in treatment_specs if spec["name"] not in REPORT_NATIVE]
            )
            report["shared_tool_names"] = [spec["name"] for spec in base_specs]
            report["treatment_native_tool_names"] = sorted(REPORT_NATIVE)
            report["card_policy_valid"] = True
            report["prior_receipt_valid"] = True
            report["persisted_dummy_key_metadata_valid"] = (
                key_file_metadata(dummy_key) == frozen["persisted_dummy_key_metadata"]
            )

            if args.run:
                preflight_path = getattr(args, "preflight", None)
                if not preflight_path:
                    raise ValueError("Live run requires --preflight")
                previous = json.loads(Path(preflight_path).read_text())
                validate_preflight(previous, frozen)
                close_manifest_before_first_actor(manifest_path, manifest, frozen, report)
            await require_followup_key_unused(native, manifest)
            report["followup_key_unused"] = True

            if not args.run:
                accounting = usage_snapshot(audit.events, 0)
                report["usage_known"] = accounting["known"]
                if not report["usage_known"] or budget.used != 0:
                    raise RuntimeError("Preflight must have known zero frontier and Jev requests")
                report["completed"] = True
                report["terminal_status"] = "preflight_complete"
                ensure_static_inputs()

            async def check_state(*, key_unused=True):
                ensure_static_inputs()
                current, _ = await read_prior_state(native, manifest)
                if current != before_state:
                    raise RuntimeError("Retained card or v2 receipt changed; cohort is terminal")
                if key_unused:
                    await require_followup_key_unused(native, manifest)
                current_sources, _ = await probe_sources(
                    native, source_captures, expected_rows=source_state,
                )
                if current_sources["native_inspections"] != frozen["native_source_inspections"]:
                    raise RuntimeError("Native saved-source inspection changed; cohort is terminal")

            async def invoke(arm: str, session: RetainedReportEpisode, instructions: str, prompt: dict):
                nonlocal evaluation_result
                limits = manifest["limits"]
                ensure_invocation_budget(audit, report, limits)
                await check_state()
                audit.episode = f"report:{arm}"
                report["frontier_invocations_started"] += 1
                save()
                try:
                    result = await codex_episode(
                        session, key=None, budget=None, audit=audit, model=limits["model"],
                        effort=limits["reasoning_effort"], max_turns=limits["tools_per_episode"],
                        max_tool_calls=limits["tools_per_episode"],
                        max_output_tokens=limits["max_output_tokens"],
                        timeout_seconds=limits["seconds_per_episode"],
                        codex_executable=args.codex_executable, accounting_drain=True,
                        instructions_override=instructions,
                        prompt_override={**prompt, "work_limit": {
                            "total_tool_calls_including_final_record": limits["tools_per_episode"],
                            "seconds": limits["seconds_per_episode"],
                            "between_invocation_input_stop": limits["between_invocation_input_stop"],
                            "between_invocation_uncached_stop": limits["between_invocation_uncached_stop"],
                            "instruction": "Reserve tool calls to record the final message. Stop on missing evidence or limits; do not retry the cohort.",
                        }},
                    )
                except Exception:
                    report["episodes"].append({
                        "arm": arm, "status": "transport_failure", "submission": session.submission,
                        "tool_calls": None, "native_tool_calls": len(session.native_calls),
                        "source_telemetry": session.sources.telemetry,
                    })
                    save()
                    evaluations = [call for call in session.native_calls
                                   if call.get("name") == "evaluate_insight_card"]
                    if len(evaluations) == 1:
                        evaluation_result = evaluations[0]["result"]
                    try:
                        await check_state(key_unused=evaluation_result is None)
                    except Exception as state_error:
                        report["post_episode_state_check_error"] = {
                            "type": type(state_error).__name__,
                        }
                        save()
                    raise
                entry = {
                    "arm": arm, "status": result.get("status"), "episode": result,
                    "submission": session.submission, "tool_calls": result.get("tool_calls"),
                    "native_tool_calls": len(session.native_calls),
                    "source_telemetry": session.sources.telemetry,
                }
                report["episodes"].append(entry)
                save()
                evaluations = [call for call in session.native_calls
                               if call.get("name") == "evaluate_insight_card"]
                if session.native and len(evaluations) == 1:
                    evaluation_result = evaluations[0]["result"]
                await check_state(key_unused=evaluation_result is None)
                if (not report["usage_known"] or result.get("status") != "complete"
                        or session.submission is None):
                    raise RuntimeError("Actor incomplete or frontier usage unknown; cohort is terminal")
                report["episodes"][-1]["source_reads"] = list(session.source_reads)
                if has_source_failure(audit.events):
                    raise RuntimeError("Source tool failure; cohort is terminal")
                if any(event.get("kind") in {"api.error", "api.rejected"}
                       and event.get("provider") == "jev"
                       for event in audit.events):
                    raise RuntimeError("Jev provider failure; cohort is terminal")

            if args.run:
                reviewed_policy = {
                    **InsightCard.model_validate(active_card).execution_payload(),
                    "delivery_methods": active_card["delivery_methods"],
                }
                common_prompt = {
                    "request": REPORT_REQUEST,
                    "reviewed_policy": reviewed_policy,
                    "owner_declarations": declarations,
                    "retained_notes": (
                        "Your own retained notes are available through read_working_notes if useful; "
                        "refresh current facts from this run's evidence."
                    ),
                    "delivery": "Shadow only; record intended policy outcome and recipient without sending.",
                }
                cohort_started_at = datetime.now(timezone.utc).isoformat()
                report["cohort_started_at"] = cohort_started_at
                await invoke(
                    "baseline", baseline_session,
                    REPORT_INSTRUCTIONS + " No native policy tools are available in this arm.",
                    common_prompt,
                )
                treatment_prompt = {
                    **common_prompt,
                    "approved_card_id": manifest["prior"]["card_id"],
                    "idempotency_key": manifest["run_key"],
                }
                await invoke(
                    "signalweave", treatment_session,
                    REPORT_INSTRUCTIONS
                    + " First call evaluate_insight_card exactly once with the supplied approved card ID "
                      "and new key. Then inspect the evaluation evidence and use the same company tools "
                      "for the matched-day follow-up. A policy result does not establish cause.",
                    treatment_prompt,
                )
                treatment_evaluations = [call for call in treatment_session.native_calls
                                         if call.get("name") == "evaluate_insight_card"]
                if len(treatment_evaluations) != 1:
                    raise ValueError("Treatment must return exactly one native card evaluation")
                evaluation_result = treatment_evaluations[0]["result"]
                _, new_receipt = await native.call_tool("get_decision_receipt", {
                    "idempotency_key": manifest["run_key"],
                })
                report["new_receipt"] = validate_new_receipt(
                    evaluation_result, new_receipt, manifest, cohort_started_at,
                )
                report["jev_usage"] = validate_jev_completion(audit.events, budget)
                report["jev_usage_known"] = True
                report["paired_reporting_complete"] = True
                report["completed"] = True
                report["terminal_status"] = "closed_complete"
            await check_state(key_unused=evaluation_result is None)
    except Exception as error:
        report["completed"] = False
        report["terminal_status"] = "closed_failure"
        report["error"] = {"type": type(error).__name__,
                            "message": safe_error_message(error, audit, private_paths)}
    finally:
        try:
            report["prior_artifacts_unchanged"] = check_prior_files(prior_root, manifest)
        except Exception:
            report["prior_artifacts_unchanged"] = False
        if report.get("prior_artifacts_unchanged") is False:
            report["completed"] = False
            report["terminal_status"] = "closed_failure"
        if config_path is not None and dummy_key is not None and frozen is not None:
            try:
                report["native_config_unchanged"] = digest(config_path) == frozen["native_config_sha256"]
                report["persisted_dummy_key_metadata_valid"] = (
                    key_file_metadata(dummy_key) == frozen["persisted_dummy_key_metadata"]
                )
            except Exception:
                report["native_config_unchanged"] = False
                report["persisted_dummy_key_metadata_valid"] = False
            if not report.get("native_config_unchanged") or not report.get("persisted_dummy_key_metadata_valid"):
                report["completed"] = False
                report["terminal_status"] = "closed_failure"
        if native is not None and before_state is not None:
            try:
                audit.episode = "final-read-only-state-check"
                async with retained_native(binary, home, prior_root, provider_key_file, audit, budget) as final_native:
                    after_state, _ = await read_prior_state(final_native, manifest)
                    if evaluation_result is None:
                        try:
                            await require_followup_key_unused(final_native, manifest)
                            report["followup_key_unused"] = True
                        except Exception as error:
                            report["followup_key_unused"] = False
                            report["followup_key_check_error"] = {"type": type(error).__name__}
                    else:
                        try:
                            _, final_receipt = await final_native.call_tool("get_decision_receipt", {
                                "idempotency_key": manifest["run_key"],
                            })
                            report["new_receipt"] = validate_new_receipt(
                                evaluation_result, final_receipt, manifest, cohort_started_at,
                            )
                            report["new_receipt_valid"] = True
                        except Exception as error:
                            report["new_receipt_valid"] = False
                            report["new_receipt_check_error"] = {"type": type(error).__name__}
                report["prior_state_after"] = after_state
                report["card_policy_unchanged"] = (
                    after_state["card_policy_sha256"] == before_state["card_policy_sha256"]
                )
                report["old_receipt_unchanged"] = (
                    after_state["receipt_sha256"] == before_state["receipt_sha256"]
                )
                if evaluation_result is not None:
                    report["followup_key_unused"] = False
                    report["followup_key_consumed_once"] = report.get("new_receipt_valid") is True
            except Exception as error:
                report["final_state_check_error"] = {"type": type(error).__name__}
                report["card_policy_unchanged"] = False
                report["old_receipt_unchanged"] = False
            if (report.get("card_policy_unchanged") is False
                    or report.get("old_receipt_unchanged") is False
                    or (evaluation_result is None and report.get("followup_key_unused") is False)
                    or report.get("new_receipt_valid") is False):
                report["completed"] = False
                report["terminal_status"] = "closed_failure"
        if report["terminal_status"] == "running":
            report["terminal_status"] = "preflight_complete" if report.get("completed") else "closed_failure"
        report["cohort_closed"] = report["terminal_status"] in {"closed_complete", "closed_failure"}
        save()

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--codex-executable", required=True)
    parser.add_argument("--prior-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--preflight")
    parser.add_argument("--key-file")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps({key: value for key, value in result.items()
                       if key not in {"source_profile_probe", "episodes"}}, ensure_ascii=False))
    if result.get("terminal_status") == "closed_failure":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
