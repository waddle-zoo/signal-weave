"""Read and restore the immutable v4 reviewed-card fixture for evaluations only.

The SQLite restore is synthetic fixture setup, not native-home durability,
public approval, human approval, or a production import capability. Use a fresh,
exclusive evaluation database: ``save_card`` is an upsert and this helper's
absence check is not atomic against concurrent writers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from signalweave.models import InsightCard
from signalweave.store import SQLiteInsightCardStore

REPORT_SHA256 = "e4f4cef42971fefb466ba0eb9df0c6d267dce05fc13544dae9fcb397354b5048"
TRACE_SHA256 = "e534505dfc0eb8a6072d47de408be3308489ab18619db4a681c810208975a13b"

REVIEWED_CARD_ID = "card-pine-courier-promised-delivery-window-attainment-de4ba9eb"
REVIEWED_CARD_VERSION = 3
REVIEWED_OWNER = "onboarding-owner"
REVIEWED_SOURCE = {
    "key": "delivery_service",
    "adapter": "company_mcp",
    "resource": "resource-050a0fa424fb5741afb0",
    "label": "Delivery service",
    "parameters": {},
    "required": True,
    "required_comparison_keys": ["on_time_delivery"],
}


def _verified_bytes(path: Path, expected_sha256: str, label: str) -> bytes:
    data = path.read_bytes()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"{label} SHA-256 does not match the retained v4 artifact")
    return data


def _one_episode(episodes: list[Any], *, arm: str, stage: str) -> dict[str, Any]:
    matches = [
        episode
        for episode in episodes
        if isinstance(episode, dict)
        and episode.get("arm") == arm
        and episode.get("stage") == stage
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {arm} {stage} episode")
    return matches[0]


def _same_json_value(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_json_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _assert_reviewed_card(card: InsightCard) -> None:
    if card.id != REVIEWED_CARD_ID or card.version != REVIEWED_CARD_VERSION:
        raise ValueError("Card is not the retained approved v4 card revision")
    if card.status != "approved" or card.approved_by != REVIEWED_OWNER:
        raise ValueError("Retained card must remain approved by onboarding-owner")
    if card.principal_id != REVIEWED_OWNER or card.principal_tenant is None:
        raise ValueError("Retained card owner and tenant provenance are required")
    if card.approved_at is None:
        raise ValueError("Retained card approval timestamp is required")
    if card.context_bindings:
        raise ValueError("Retained v4 card must have no context bindings")
    sources = [source.model_dump(mode="json") for source in card.sources]
    if sources != [REVIEWED_SOURCE]:
        raise ValueError("Retained card source scope does not match the accepted v4 source")
    if (
        card.compiled_plan is None
        or card.compiled_plan.card_id != REVIEWED_CARD_ID
        or card.compiled_plan.card_version != REVIEWED_CARD_VERSION
    ):
        raise ValueError("Retained compiled plan must match the approved card revision")


def _validate_report(report: Any) -> InsightCard:
    if not isinstance(report, dict):
        raise ValueError("Retained v4 report must be a JSON object")
    if report.get("protocol") != "owner-handoff-v4":
        raise ValueError("Retained report protocol must be owner-handoff-v4")
    if report.get("usage_known") is not True or report.get("provider_usage_known") is not True:
        raise ValueError("Retained v4 report must have known provider usage")
    usage = report.get("usage")
    if not isinstance(usage, dict) or usage.get("responses") != 6:
        raise ValueError("Retained v4 report must record six known responses")
    if report.get("agent_invocations_started") != 6:
        raise ValueError("Retained v4 report must record six agent invocations")
    if report.get("provider_attempts") != 0:
        raise ValueError("Retained v4 report must record zero provider attempts")
    if report.get("pair_status") != "setups_reviewed":
        raise ValueError("Retained v4 report must record both setups reviewed")

    episodes = report.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("Retained v4 report must contain episode records")
    first_treatment = _one_episode(episodes, arm="signalweave", stage="first_author")
    first_card = first_treatment.get("first_card")
    if (
        not isinstance(first_card, dict)
        or first_card.get("id") != REVIEWED_CARD_ID
        or first_card.get("version") != 2
    ):
        raise ValueError("First treatment card must be the same card at version 2")

    second_treatment = None
    for arm in ("baseline", "signalweave"):
        episode = _one_episode(episodes, arm=arm, stage="second_author")
        setup = episode.get("setup")
        review = episode.get("independent_review")
        if not isinstance(setup, dict) or setup.get("unresolved") != []:
            raise ValueError(f"Second-author {arm} setup must have no unresolved questions")
        if not isinstance(review, dict) or review.get("approved") is not True:
            raise ValueError(f"Second-author {arm} independent review must be approved")
        if arm == "signalweave":
            second_treatment = episode

    assert second_treatment is not None
    card_data = second_treatment.get("card")
    if not isinstance(card_data, dict):
        raise ValueError("Second treatment episode must retain its approved card")
    try:
        card = InsightCard.model_validate(card_data)
    except Exception as exc:
        raise ValueError("Retained v4 card is not a valid InsightCard") from exc
    normalized_card = card.model_dump(mode="json")
    if any(
        key not in normalized_card or not _same_json_value(value, normalized_card[key])
        for key, value in card_data.items()
    ):
        raise ValueError("Retained card fields must validate without coercion or repair")
    _assert_reviewed_card(card)
    if card.version != first_card["version"] + 1:
        raise ValueError("Approved card must be exactly one revision after the first treatment card")
    if second_treatment.get("setup", {}).get("card_ids") != [card.id]:
        raise ValueError("Second treatment setup must identify the retained approved card")
    return card


def load_reviewed_setup(report_path: Path, trace_path: Path) -> tuple[dict, InsightCard]:
    """Verify and validate the retained v4 setup without changing either artifact.

    Hashes cover the exact original report and trace bytes. The returned card is
    the approved v3 snapshot; its approval is a synthetic development artifact,
    not a fresh public approval or human authorization. Callers must separately
    verify its tenant against the scenario they run.
    """
    report_bytes = _verified_bytes(Path(report_path), REPORT_SHA256, "v4 report")
    _verified_bytes(Path(trace_path), TRACE_SHA256, "v4 trace")
    try:
        report = json.loads(report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Retained v4 report is not valid UTF-8 JSON") from exc
    card = _validate_report(report)
    return report, card


def restore_reviewed_card(database: Path, card: InsightCard) -> None:
    """Seed the exact reviewed fixture into an evaluation-only SQLite store.

    This is not a production import API or an approval transition. The caller
    must supply a fresh, exclusive private-home database; the store's save
    method upserts, so this helper rejects an existing card ID before writing.
    """
    _assert_reviewed_card(card)
    store = SQLiteInsightCardStore(Path(database))
    try:
        store.get_card(card.id)
    except KeyError:
        pass
    else:
        raise ValueError(f"Refusing to overwrite existing reviewed card: {card.id}")

    expected = card.model_dump(mode="json")
    store.save_card(card)
    restored = store.get_card(card.id)
    if restored.model_dump(mode="json") != expected:
        raise RuntimeError("SQLite fixture restore did not preserve the exact card snapshot")
