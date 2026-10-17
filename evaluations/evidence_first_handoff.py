"""Research-only evidence/audit presentation; does not evaluate or change policy."""

from __future__ import annotations

import copy
import json
from collections import Counter

from pydantic import ValidationError

from signalweave.reporting import InvestigationReport


def _identical_json(left, right):
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False


def evidence_first_handoff(compact: dict) -> dict:
    """Keep facts primary, with explicit receipt access for repetitive audit detail.

    This is deliberately not wired into the product. It is a candidate for a
    controlled reporter experiment, not a demonstrated improvement in analysis.
    Required, ambiguous and unrecognized assessments are never filtered.
    """
    candidate = copy.deepcopy(compact)
    if not isinstance(candidate, dict) or "report_audit" in candidate:
        return candidate
    result, receipt = candidate.get("result"), candidate.get("receipt")
    if not isinstance(result, dict) or not isinstance(receipt, dict):
        return candidate
    report = result.get("report")
    judgment = result.get("judgment")
    if judgment is not None and not isinstance(judgment, dict):
        return candidate
    receipt_id = receipt.get("receipt_id")
    if (not isinstance(report, dict) or not isinstance(receipt_id, str) or not receipt_id.strip()
            or candidate.get("evidence_access") is not None
            or (isinstance(judgment, dict) and judgment.get("status") == "deferred")
            or not isinstance(result.get("card_id"), str)
            or receipt.get("card_id") != result["card_id"] or report.get("card_id") != result["card_id"]):
        return candidate
    try:
        InvestigationReport.model_validate(report)
    except (ValidationError, TypeError):
        return candidate
    expected_lists = ("evidence", "coverage", "judgments", "unresolved_questions", "blockers", "warnings", "limitations")
    if any(not isinstance(report.get(key), list) for key in expected_lists):
        return candidate
    plan = result.get("evidence_plan")
    slots = plan.get("slots") if isinstance(plan, dict) else None
    if not isinstance(slots, list) or any(not isinstance(slot, dict) for slot in slots):
        return candidate
    semantic = [slot for slot in slots if slot.get("role") in {"watch", "question"}]
    keys = [slot.get("key") for slot in semantic]
    if any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
        return candidate

    aliases, texts = [], []
    groups = {}
    diagnostics = candidate.get("optional_policy_diagnostics")
    if isinstance(diagnostics, dict) and "omitted_optional_results" in diagnostics:
        return candidate
    values = diagnostics.get("values", {}) if isinstance(diagnostics, dict) else {}
    if not isinstance(values, dict):
        return candidate
    for role in ("watch", "question"):
        criteria = [slot for slot in semantic if slot.get("role") == role]
        field = f"{role}_results"
        assessments = values.get(field)
        if not criteria or not isinstance(assessments, list) or len(assessments) != len(criteria):
            continue
        by_key = {slot["key"]: slot for slot in criteria}
        if all(
            isinstance(item, dict) and isinstance(item.get("key"), str)
            and item["key"] in {f"{role}_{index}", f"{role}:{index + 1}", str(index)}
            and by_key.get(f"{role}:{index + 1}", {}).get("required") is False
            for index, item in enumerate(assessments)
        ):
            groups[field] = assessments
            for index in range(len(criteria)):
                slot = by_key[f"{role}:{index + 1}"]
                aliases.extend((f"{role}_{index}", slot["key"]))
                if len(semantic) == len(criteria):
                    aliases.append(str(index))
                text = slot.get("question")
                if isinstance(text, str) and text.strip():
                    texts.append(text)
    allowed_text = {text for text, count in Counter(texts).items() if count == 1 and not any(
        slot.get("question") == text and slot.get("required") is not False for slot in semantic
    )}
    if any(field in result for field in groups):
        return candidate  # The durable field target would be ambiguous.
    sections = []

    def section(path, reason):
        sections.append({"tool": "get_decision_receipt", "receipt_id": receipt_id,
                         "result_path": path, "offset": 0, "limit": 25, "reason": reason})

    if isinstance(result.get("evidence"), list) and _identical_json(report["evidence"], result["evidence"]):
        report.pop("evidence")
        section(["report", "evidence"], "Exact duplicate of result.evidence; primary evidence is unchanged.")
    for field, predicate in (
        ("judgments", lambda item: isinstance(item, dict) and item.get("reference") in aliases),
        ("unresolved_questions", lambda item: isinstance(item, str) and item in allowed_text),
    ):
        retained = [item for item in report[field] if not predicate(item)]
        if len(retained) != len(report[field]):
            report[field] = retained
            section(["report", field], "Optional semantic assessments only; not a measurement-availability finding.")
    if groups:
        for field in groups:
            section([field], "Optional semantic criterion judgments, not missing measurements.")
        remaining = {key: value for key, value in values.items() if key not in groups}
        diagnostics["values"] = remaining
        diagnostics["omitted_optional_results"] = sorted(groups)
    candidate["report_audit"] = {
        "scope": "Audit coverage and policy diagnostics, not an inventory of absent measurements. All blockers and warnings are retained.",
        "summary": result.pop("report"),
        "receipt_sections": sections,
        "instruction": "Read relevant original sections through the receipt when needed; absence from this projection is not missing source evidence. Paging performs no new source or model calls.",
    }
    return candidate
