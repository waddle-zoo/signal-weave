"""Single local investigation run through the production MCP contract."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .mcp_server import create_mcp
from .models import InsightResult
from .runtime import Runtime, build_runtime


def _text(value: str) -> str:
    # Labels and source facts are data, including when they resemble Markdown.
    escaped = value.replace("\n", " ").replace("\r", " ").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", escaped)


def evidence_brief(result: InsightResult) -> str:
    lines = [f"# Investigation: {_text(result.card_id)}", "",
             f"Outcome: **{result.outcome.value}**. Delivery remains caller-owned.", ""]
    for report in result.analyses:
        comparison = report.comparison
        lines.extend([f"## {_text(report.metric)} by {_text(report.dimension)}", "",
                      f"Population: {_text(comparison.population)}.", "",
                      f"Definition: {_text(comparison.definition)}.", "",
                      f"Baseline: {comparison.baseline_start.isoformat()} to {comparison.baseline_end.isoformat()}.",
                      f"Current: {comparison.current_start.isoformat()} to {comparison.current_end.isoformat()}.", ""])
        if report.status != "complete":
            lines.extend(["Analysis unavailable: " + " ".join(_text(issue) for issue in report.issues), ""])
        else:
            lines.extend([f"{report.baseline:g} → {report.current:g}; change {report.delta:+g} {_text(report.unit)}.", ""])
            if report.within_effect is not None:
                lines.extend([f"Within-segment effect: {report.within_effect:+g} {_text(report.unit)}. "
                              f"Population-mix effect: {report.mix_effect:+g} {_text(report.unit)}.", "",
                              "Segment rates are unweighted; contributions are changes in the weighted aggregate rate.", ""])
            lines.extend(["| Segment | Baseline | Current | Contribution to change |", "|---|---:|---:|---:|"])
            for row in report.contributions:
                lines.append(f"| {_text(row.segment)} | {row.baseline:g} | {row.current:g} | {row.contribution:+g} |")
            lines.extend(["", f"Reconciliation residual: {report.residual:g} {_text(report.unit)}.", ""])
        lines.extend(["Method: " + report.method + ".", "",
                      "Query references: " + ", ".join(_text(ref) for ref in report.query_refs) + ".", "",
                      *[_text(limit) for limit in report.limitations], ""])
    if not result.analyses:
        lines.extend(["No quantitative comparison was supplied by the selected sources.", ""])
    lines.extend(["## Source evidence", ""])
    for evidence in result.evidence:
        lines.append(f"- {_text(evidence.subject_label)}: {_text(evidence.statement)}")
    if result.workflow:
        lines.extend(["", "## Next step", "", _text(result.workflow.instructions)])
    return "\n".join(lines) + "\n"


def _is_deferred_handoff(payload: dict[str, Any]) -> bool:
    receipt = payload.get("receipt")
    result = payload.get("result")
    judgment = result.get("judgment") if isinstance(result, dict) else None
    return (
        isinstance(receipt, dict) and receipt.get("status") == "decision_deferred"
    ) or (isinstance(judgment, dict) and judgment.get("status") == "deferred")


def _tool_payload(response: Any) -> dict[str, Any]:
    if isinstance(response, tuple):
        return response[1]
    return json.loads(next(item.text for item in response if getattr(item, "type", None) == "text"))


async def _archived_receipt_payload(server: Any, receipt_id: str) -> dict[str, Any]:
    """Read the immutable receipt form for artifacts, never the replay projection."""
    payload = _tool_payload(await server.call_tool("get_decision_receipt", {"receipt_id": receipt_id}))
    if payload.get("status") != "found" or not isinstance(payload.get("receipt"), dict) or not isinstance(payload.get("result"), dict):
        raise RuntimeError("Unable to read the saved investigation receipt for artifacts")
    receipt = dict(payload["receipt"])
    # Keep the established artifact layout: receipt metadata plus one top-level
    # canonical result, rather than duplicating the result inside the receipt.
    receipt.pop("result", None)
    return {"receipt": receipt, "result": payload["result"]}


def _archival_artifact_notice() -> str:
    return (
        "\n## Archived receipt note\n\n"
        "This artifact records the outcome and routes saved at evaluation time. "
        "It does not establish that an action is available under current context. "
        "Check the live run response's `policy_action_available` and "
        "`current_context_dependencies` before acting.\n"
    )


def _add_current_action_warning(payload: dict[str, Any]) -> None:
    if _is_deferred_handoff(payload):
        payload["current_action_warning"] = (
            "No policy outcome was produced; this is an investigation handoff, not an action instruction. "
            "Current context dependencies are reported separately."
        )
    elif payload.get("policy_result_is_historical") or payload.get("policy_action_available") is False:
        payload["current_action_warning"] = (
            "This receipt is historical for the current context; no current policy action is available. "
            "Review current_context_dependencies before deciding whether to rerun or act."
        )


def _deferred_evidence_paths(payload: dict[str, Any]) -> list[list[str]]:
    paths: list[list[str]] = []

    def add(path: Any) -> None:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(part, str) for part in path)
            and path not in paths
        ):
            paths.append(path)

    access = payload.get("evidence_access")
    if isinstance(access, dict):
        for section in access.get("available_sections", []):
            if isinstance(section, dict):
                add(section.get("path"))
        for section in access.values():
            if isinstance(section, dict):
                add(section.get("result_path"))
                for key, value in section.items():
                    if key.endswith("_path") and key != "inline_result_path":
                        add(value)
            elif isinstance(section, list):
                for item in section:
                    if isinstance(item, dict):
                        for key, value in item.items():
                            if key.endswith("_path") and key != "inline_result_path":
                                add(value)

    result = payload.get("result")
    if isinstance(result, dict):
        state = result.get("judgment_state")
        if isinstance(state, dict):
            for field in ("observations", "evidence"):
                if field in state:
                    add(["judgment_state", field])
        for field in ("source_by_key", "source_contracts", "retrieval", "context_dependencies_at_run"):
            if field in result:
                add([field])

    return paths


def deferred_evidence_brief(payload: dict[str, Any]) -> str:
    """Describe a deferred receipt without inventing a typed policy result."""
    receipt = payload.get("receipt")
    result = payload.get("result")
    receipt = receipt if isinstance(receipt, dict) else {}
    result = result if isinstance(result, dict) else {}
    judgment = result.get("judgment")
    judgment = judgment if isinstance(judgment, dict) else {}
    receipt_id = receipt.get("receipt_id") or "not included in response"

    lines = [
        f"# Investigation handoff: {_text(str(result.get('card_id') or receipt.get('card_id') or 'unknown card'))}",
        "",
        "No policy outcome was produced. This deferred receipt is not an `ignore`, `investigate`, `notify`, or other completed decision.",
        "",
        f"Receipt: {_text(str(receipt_id))}.",
    ]
    reason = judgment.get("reason")
    if isinstance(reason, str) and reason:
        lines.append(f"Deferred reason: {_text(reason)}.")
    attempts = judgment.get("provider_call_attempts")
    if isinstance(attempts, int) and not isinstance(attempts, bool):
        lines.append(f"Provider call attempts recorded for this judgment: {attempts}.")

    access = payload.get("evidence_access")
    if isinstance(access, dict) and isinstance(access.get("instruction"), str):
        lines.extend(["", _text(access["instruction"])])

    paths = _deferred_evidence_paths(payload)
    lines.extend(["", "Receipt evidence references:"])
    if paths:
        lines.extend(
            "- Receipt page path: "
            + _text(f"result_path={json.dumps(path, ensure_ascii=False, separators=(',', ':'))}")
            for path in paths
        )
    else:
        lines.append("- The response does not advertise receipt section paths; inspect the saved result JSON and receipt before requesting a specific page.")
    if isinstance(result.get("observation_facts"), dict):
        lines.append(
            "- `result.observation_facts` is an inline overview when present; use its advertised `result_path` for receipt pages, not an inline-only path."
        )

    lines.extend([
        "",
        "For needed omitted details, call `get_decision_receipt` with this receipt ID and one listed `result_path`, starting at `offset=0` and `limit=25`; follow each page's `next_offset`. Page only details needed for the investigation. Receipt reads do not create a policy outcome or send a message.",
        "",
        "The caller owns any further evidence review, investigation, explanation, owner-context review, rerun, and delivery. Do not treat this deferred handoff as an all-clear or as authorization to act.",
    ])
    return "\n".join(lines) + "\n"


def _write_once(path: Path, contents: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_text() != contents:
            raise ValueError("An investigation artifact already exists with different contents") from None
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(contents)


async def run_card(
    card_id: str, run_key: str, output_dir: Path | None = None, *, runtime: Runtime | None = None
) -> dict[str, Any]:
    """Use the same approval, tenant, Jev and receipt path as remote clients.

    A caller supplies one stable run key per reporting period. Retrying that key
    replays the saved result; the next period uses a new key and fresh sources.
    """
    server = create_mcp(runtime or build_runtime(), profile="full")
    response = await server.call_tool("evaluate_insight_card", {
        "card_id": card_id, "idempotency_key": run_key,
    })
    # FastMCP returns (content blocks, structured data) for structured tools.
    payload = _tool_payload(response)
    if "error" in payload.get("result", {}):
        raise RuntimeError("Stored investigation failed; inspect its receipt before creating a new run")
    archived_payload = None
    if output_dir is not None:
        archived_payload = await _archived_receipt_payload(server, payload["receipt"]["receipt_id"])
    _add_current_action_warning(payload)
    if _is_deferred_handoff(payload):
        brief = deferred_evidence_brief(payload)
        payload["handoff_brief"] = brief
        if output_dir is not None:
            receipt_id = payload["receipt"]["receipt_id"]
            folder = output_dir / hashlib.sha256(receipt_id.encode()).hexdigest()[:24]
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            if folder.is_symlink():
                raise ValueError("Investigation output directory must not be a symlink")
            assert archived_payload is not None
            archived_brief = deferred_evidence_brief(archived_payload) + _archival_artifact_notice()
            _write_once(folder / "result.json", json.dumps(archived_payload, ensure_ascii=False, indent=2) + "\n")
            _write_once(folder / "brief.md", archived_brief)
            payload["artifacts"] = {
                "result": str((folder / "result.json").resolve()),
                "brief": str((folder / "brief.md").resolve()),
            }
        return payload
    result_payload = archived_payload["result"] if archived_payload is not None else payload["result"]
    result = InsightResult.model_validate(result_payload)
    if output_dir is not None:
        receipt_id = payload["receipt"]["receipt_id"]
        folder = output_dir / hashlib.sha256(receipt_id.encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if folder.is_symlink():
            raise ValueError("Investigation output directory must not be a symlink")
        _write_once(folder / "result.json", result.model_dump_json(indent=2) + "\n")
        _write_once(folder / "brief.md", evidence_brief(result) + _archival_artifact_notice())
        payload["artifacts"] = {"result": str((folder / "result.json").resolve()),
                                "brief": str((folder / "brief.md").resolve())}
        if isinstance(result_payload.get("report"), dict):
            report_markdown = result_payload.get("report_markdown")
            if isinstance(report_markdown, str):
                _write_once(folder / "report.json", json.dumps(result_payload["report"], indent=2) + "\n")
                _write_once(folder / "report.md", report_markdown)
                payload["artifacts"].update({
                    "report": str((folder / "report.json").resolve()),
                    "report_markdown": str((folder / "report.md").resolve()),
                })
    return payload
