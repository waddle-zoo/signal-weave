"""Research-only free-form clarification references, not a simulated expert answer.

Expose the same episode-bounded declarations to both authors. No semantic
matching, inferred eligibility, source payloads, approvals or future periods.
Missing declarations remain missing; a real expert may still be required.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

MAX_SOURCES = 64
MAX_REFERENCE_BYTES = 32_000
CONTRACT_FIELDS = (
    "tenant_id", "domain", "scope", "metric_names", "population", "grain",
    "roles", "available_comparison_windows", "comparison_contracts",
    "required_comparison_keys",
)


def attach_steward_notes(fixture, path):
    """Attach explicit fictional expert input, never infer it from raw values.

    This validates size and fixture identity only, not semantic correctness.
    Conflicts stay quoted for the author and independent policy reviewer.
    """
    payload = Path(path).read_bytes()
    text = payload.decode("utf-8")
    if not text.strip() or len(payload) > 16_000:
        raise ValueError("Provide nonempty steward notes of at most 16000 UTF-8 bytes")
    primary = [item for item in fixture["public"]["catalog"]
               if item.get("contract", {}).get("roles") == ["primary"]]
    if len(primary) != 1:
        raise ValueError("This development fixture needs one unambiguous declared primary source")
    result = deepcopy(fixture)
    if "source_steward_notes" in result["public"]["glossary"]:
        raise ValueError("Do not overwrite an existing steward declaration")
    result["public"]["glossary"]["source_steward_notes"] = text
    return result, primary[0]["adapter"] + "|" + primary[0]["resource"], hashlib.sha256(payload).hexdigest()


def source_reference(public):
    """Copy only declared glossary/contract fields, with exact source citations."""
    catalog = public["catalog"]
    if len(catalog) > MAX_SOURCES:
        raise ValueError("Expert reference exceeds its source budget; do not truncate silently")
    declarations = []
    seen = set()
    for item in catalog:
        ref = item["adapter"] + "|" + item["resource"]
        if ref in seen:
            raise ValueError("Ambiguous duplicate source reference")
        seen.add(ref)
        contract = item.get("contract", {})
        # Preserve declarations (including generic/contradictory identity), not
        # a new authorization decision. The trial's source bridge owns access.
        declarations.append({
            "ref": ref,
            "citation": ref + "#/contract",
            "declared_contract": {key: deepcopy(contract[key]) for key in CONTRACT_FIELDS if key in contract},
        })
    result = {
        "glossary": {"citation": "company-metric-glossary#/definitions",
                     "definitions": deepcopy(public["glossary"])},
        "sources": declarations,
        "projection_fields": list(CONTRACT_FIELDS),
        "scope": "Selected declared contract fields, not full contracts; source tools retain omitted details. "
                 "Each source retains its own population and role. "
                 "An example window is not proof of a durable comparison convention. "
                 "Absent, generic or conflicting declarations need actual expert clarification. "
                 "This reference neither supplies missing measurements nor grants approval.",
    }
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_REFERENCE_BYTES:
        raise ValueError("Expert reference exceeds its byte budget; do not truncate silently")
    return result


class SourceReferenceMixin:
    """Unknown free-form questions get references, never a fabricated answer."""

    async def specs(self):
        tools = await super().specs()
        for tool in tools:
            if tool["name"] == "ask_owner":
                tool["description"] = (
                    "Ask the fictional owner a policy topic or free-form source question. "
                    "Known topics return declared owner policy. Other questions return only "
                    "cited glossary/source references, NOT an expert answer or confirmation "
                    "that your question is resolved. Ask for real clarification if insufficient."
                )
                tool["parameters"]["properties"]["topic"] = {
                    "type": "string", "minLength": 1, "maxLength": 2000,
                }
        return tools

    async def call(self, name, args):
        if name == "ask_owner" and args["topic"] not in self.public["owner_answers"]:
            question = args["topic"]
            if not question.strip() or len(question) > 2000:
                raise ValueError("Ask a bounded nonempty question")
            reference = source_reference(self.public)
            self.owner_requests.append({"topic": question, "answer_status": "reference_only"})
            return {"topic": question, "known": False, "answer": None,
                    "answer_status": "reference_only", "reference": reference}
        return await super().call(name, args)
