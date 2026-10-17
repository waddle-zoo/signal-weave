"""Bounded, research-only references to explicitly supplied owner declarations.

The caller must pass only the owner declaration map, never a public fixture or
source snapshot. This helper returns a reference, not a resolved answer: cited
source material and owner clarification are still needed.
"""

import hashlib
import json
from collections.abc import Mapping

MAX_DECLARATIONS = 32
MAX_DECLARATION_BYTES = 16_000
MAX_QUESTION_LENGTH = 2_000


def declared_owner_reference(owner_declarations, question):
    """Echo a free-form question with a copy of all supplied declarations.

    Mapping keys are exact citations and values are exact policy statements.
    Each digest is SHA-256 over the statement's UTF-8 bytes. Nothing here
    matches topics, resolves policy, infers missing statements, or grants
    approval.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_LENGTH:
        raise ValueError("Provide a nonempty question of at most 2000 characters")
    if not isinstance(owner_declarations, Mapping):
        raise ValueError("Owner declarations must be an explicit citation-to-statement map")

    declarations_copy = dict(owner_declarations)
    if len(declarations_copy) > MAX_DECLARATIONS:
        raise ValueError("Owner declaration map exceeds its 32-item budget")

    try:
        encoded_map = json.dumps(
            declarations_copy, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError) as exc:
        raise ValueError("Owner declarations must be UTF-8 strings") from exc
    if len(encoded_map) > MAX_DECLARATION_BYTES:
        raise ValueError("Owner declaration map exceeds its 16000 UTF-8 byte budget")

    statements = []
    for citation, statement in declarations_copy.items():
        if not isinstance(citation, str) or not citation.strip():
            raise ValueError("Every owner declaration needs a nonempty string citation")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("Every owner declaration needs a nonempty string policy statement")
        digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()
        statements.append({
            "citation": citation,
            "policy_statement": statement,
            "statement_sha256": digest,
        })

    return {
        "question": question,
        "answer": None,
        "known": False,
        "answer_status": "declared_reference_only",
        "reference": {
            "scope": (
                "Every supplied declaration is reproduced verbatim with its citation "
                "and the SHA-256 digest of its UTF-8 statement. This is a reference, "
                "not a resolved answer or approval; consult the cited source material "
                "and accountable owner to resolve the question. No missing policy is "
                "inferred or synthesized."
            ),
            "declarations": statements,
        },
    }
