from __future__ import annotations

import json
from pathlib import Path

from evaluations.card_guided_owner_holdout import load_holdout_cases

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "evaluations/data/card-guided-owner-holdout.json"
LABELS = ROOT / "evaluations/data/card-guided-owner-holdout-labels.json"


def test_owner_holdout_labels_are_separate_from_jev_facing_payloads():
    cases = load_holdout_cases(CONFIG, LABELS)

    assert len(cases) == 6
    assert all(case.gold_roles for case in cases)
    assert all(case.gold_evidence_roles for case in cases)
    for case in cases:
        public_payload = json.dumps(
            {
                "card": case.card.execution_payload(),
                "descriptors": [item.model_dump(mode="json") for item in case.descriptors],
                "snapshots": [item.model_dump(mode="json") for item in case.snapshots.values()],
            }
        )
        for hidden_key in ("gold_role", "gold_evidence_role", "retrieval_role", "evidence_role"):
            assert hidden_key not in public_payload


def test_owner_holdout_has_explicit_context_for_each_labeled_evidence_role():
    cases = load_holdout_cases(CONFIG, LABELS)
    label_payload = json.loads(LABELS.read_text())

    for case in cases:
        guidance = case.card.decision_guidance.lower()
        assert "focal" in guidance
        assert "corroboration" in guidance
        assert "diagnostic" in guidance
        assert set(label_payload["cases"][case.scenario_id]) == set(case.gold_evidence_roles)
