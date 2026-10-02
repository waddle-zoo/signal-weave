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
    server = create_mcp(runtime or build_runtime())
    response = await server.call_tool("evaluate_insight_card", {
        "card_id": card_id, "idempotency_key": run_key,
    })
    # FastMCP returns (content blocks, structured data) for structured tools.
    if isinstance(response, tuple):
        payload = response[1]
    else:
        payload = json.loads(next(item.text for item in response if getattr(item, "type", None) == "text"))
    if "error" in payload.get("result", {}):
        raise RuntimeError("Stored investigation failed; inspect its receipt before creating a new run")
    result = InsightResult.model_validate(payload["result"])
    if output_dir is not None:
        receipt_id = payload["receipt"]["receipt_id"]
        folder = output_dir / hashlib.sha256(receipt_id.encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if folder.is_symlink():
            raise ValueError("Investigation output directory must not be a symlink")
        _write_once(folder / "result.json", result.model_dump_json(indent=2) + "\n")
        _write_once(folder / "brief.md", evidence_brief(result))
        payload["artifacts"] = {"result": str((folder / "result.json").resolve()),
                                "brief": str((folder / "brief.md").resolve())}
        if "report" in payload:
            _write_once(folder / "report.json", json.dumps(payload["report"], indent=2) + "\n")
            _write_once(folder / "report.md", payload["report_markdown"])
            payload["artifacts"].update({
                "report": str((folder / "report.json").resolve()),
                "report_markdown": str((folder / "report.md").resolve()),
            })
    return payload
