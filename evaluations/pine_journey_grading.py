"""Mechanical source/coverage checks for enterprise_full_journey world JSON.

This is not a prose grader. It independently counts raw source rows/events,
then checks world structure: owner confirmation, each cutoff delivered, evidence
attachments readable/hash-matched, and inbox replies linked to sent messages.
The PM review separately judges message meaning and numeric claims in prose.

API: ``grade_pine_world(path_to_world_json)``. The world JSON's parent must
contain ``snapshot-0.sqlite3`` through ``snapshot-2.sqlite3`` and the paths
recorded in each message's attachment objects. World input keys follow
enterprise_full_journey.py: messages, owner_conversations, operator_actions,
feedback_reads, current_day, complete. No generator, projector, source adapter,
production metric, actor label, provider, or network is imported or called.
Defaults bind the executed study's archived bytes. Separately materialized
sources must supply their own pre-recorded ``expected_source_hashes``; byte
identity is not assumed across SQLite builds. All semantic checks still run.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CUTOFFS = ("2026-09-21T06:00:00Z", "2026-09-28T06:00:00Z", "2026-10-05T06:00:00Z")
SOURCE_SHA256 = (
    "30c6913e4db97a379bd6a09789837a991204e64eb284204a9bcbdef4c11c860e",
    "9d97d146a2d233eb174ec50f80112da04c83bbe392aba669b6cb8ec0722d34bf",
    "1f397e613df914d3e2babe742c9517dd503378d04337beed2e795d431a4b2d3c",
)
DISPATCH = "dispatch"
DATA_OPS = "data-operations"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_readonly(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular SQLite source: {path}")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("source timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def _period(db: sqlite3.Connection, start: str, end: str,
            tier: str | None = None) -> dict[str, int | float]:
    sql = """SELECT COUNT(*) eligible,
      COALESCE(SUM(CASE WHEN delivered_at_utc IS NOT NULL
        AND delivered_at_utc <= due_at_utc THEN 1 ELSE 0 END),0) on_time
      FROM parcels WHERE due_at_utc >= ? AND due_at_utc < ?
      AND cancelled_at_utc IS NULL"""
    args: list[Any] = [start, end]
    if tier is not None:
        sql += " AND service_tier = ?"
        args.append(tier)
    row = db.execute(sql, args).fetchone()
    result: dict[str, int | float] = {"on_time": row["on_time"], "eligible": row["eligible"]}
    result["rate_pct"] = 100 * row["on_time"] / row["eligible"] if row["eligible"] else 0.0
    return result


def _events(db: sqlite3.Connection, cutoff: str) -> dict[str, Any]:
    """Select visible event revisions independently and reconcile projected state."""
    rows = db.execute(
        "SELECT event_id,revision,parcel_id,event_type,effective_at_utc,available_at_utc "
        "FROM parcel_events WHERE available_at_utc <= ? ORDER BY event_id,revision",
        (cutoff,),
    ).fetchall()
    latest = {}
    for row in rows:
        if row["event_id"] not in latest or row["revision"] > latest[row["event_id"]]["revision"]:
            latest[row["event_id"]] = row
    visible = {}
    for row in latest.values():
        if row["effective_at_utc"] <= cutoff:
            key = (row["parcel_id"], row["event_type"])
            if key in visible:
                raise ValueError(f"duplicate visible event state: {key}")
            visible[key] = row
    counts = defaultdict(int)
    fields = {
        "registration": ("registered_at_utc", "registration_available_at_utc"),
        "cancellation": ("cancelled_at_utc", "cancellation_available_at_utc"),
        "delivery": ("delivered_at_utc", "delivery_available_at_utc"),
    }
    parcels = db.execute("SELECT * FROM parcels").fetchall()
    for parcel in parcels:
        for kind, (effective, available) in fields.items():
            row = visible.get((parcel["parcel_id"], kind))
            observed = None if row is None else (row["effective_at_utc"], row["available_at_utc"])
            projected = (parcel[effective], parcel[available])
            projected = None if projected == (None, None) else projected
            if observed != projected:
                raise ValueError(f"parcel/event mismatch for {parcel['parcel_id']} ({kind})")
            counts[kind] += row is not None
    if sum(counts.values()) != len(visible) or counts["registration"] != len(parcels):
        raise ValueError("unrecognized event or registration population mismatch")
    return {"visible_event_revisions": len(rows), "registered": counts["registration"],
            "cancelled": counts["cancellation"], "delivered": counts["delivery"]}


def _source(path: Path, index: int, *, expected_sha256: str | None = None) -> dict[str, Any]:
    digest = _sha(path)
    expected = SOURCE_SHA256[index] if expected_sha256 is None else expected_sha256
    if digest != expected:
        raise ValueError("snapshot bytes differ from the archived independent source")
    db = _open_readonly(path)
    try:
        clock_rows = db.execute("SELECT * FROM source_snapshot").fetchall()
        if len(clock_rows) != 1:
            raise ValueError("source must have one as-of clock row")
        clock = dict(clock_rows[0])
        if clock["as_of_utc"] != CUTOFFS[index]:
            raise ValueError("source as-of clock does not match archive sequence")
        if clock["current_end_utc"] != clock["as_of_utc"][:10] + "T00:00:00Z":
            raise ValueError("current week is not closed at the UTC cutoff")
        prior_start, current_start, end = (clock[k] for k in
            ("baseline_start_utc", "current_start_utc", "current_end_utc"))
        if (_utc(current_start) - _utc(prior_start) != timedelta(days=7)
                or _utc(end) - _utc(current_start) != timedelta(days=7)):
            raise ValueError("periods are not consecutive full UTC weeks")
        raw = {
            "prior": {tier: _period(db, prior_start, current_start, None if tier == "ALL" else tier)
                      for tier in ("ALL", "priority", "standard")},
            "current": {tier: _period(db, current_start, end, None if tier == "ALL" else tier)
                        for tier in ("ALL", "priority", "standard")},
        }
        delta = raw["current"]["ALL"]["rate_pct"] - raw["prior"]["ALL"]["rate_pct"]
        events = _events(db, clock["as_of_utc"])

        manifest_count = 0
        for manifest in db.execute("SELECT * FROM due_week_manifests"):
            if manifest["available_at_utc"] > clock["as_of_utc"]:
                raise ValueError("future manifest leaked into source snapshot")
            week_end = (_utc(manifest["week_start_utc"]) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
            sql = "SELECT COUNT(*) FROM parcels WHERE due_at_utc >= ? AND due_at_utc < ?"
            args: list[Any] = [manifest["week_start_utc"], week_end]
            if manifest["service_tier"] != "ALL":
                sql += " AND service_tier = ?"
                args.append(manifest["service_tier"])
            if db.execute(sql, args).fetchone()[0] != manifest["registered_parcel_count"] or manifest["expected_parcel_count"] != manifest["registered_parcel_count"]:
                raise ValueError("source manifest does not reconcile to raw registration counts")
            manifest_count += 1

        cache = {}
        flags = []
        for label, start in (("prior", prior_start), ("current", current_start)):
            rows = db.execute(
                "SELECT * FROM cached_export_revisions WHERE week_start_utc=? AND service_tier='ALL' "
                "AND export_available_at_utc<=? ORDER BY revision DESC", (start, clock["as_of_utc"])).fetchall()
            row = rows[0] if rows else None
            cache[label] = None if row is None else {
                "revision": row["revision"], "on_time": row["on_time_parcels"],
                "eligible": row["eligible_parcels"], "available_at_utc": row["export_available_at_utc"]}
            expected = raw[label]["ALL"]
            if row is None or row["on_time_parcels"] != expected["on_time"]:
                flags.append(f"{label}_cache_row_or_numerator_gap")
            elif row["eligible_parcels"] is None:
                flags.append("cache_denominator_missing")
            elif row["eligible_parcels"] != expected["eligible"]:
                flags.append("cache_denominator_mismatch")
        cache_valid = not flags
        return {"source_id": str(index), "source_sha256": digest, "clock": clock,
                "raw": raw, "delta_pp": delta, "raw_comparison_valid": True,
                "cache": cache, "cache_comparison_valid": cache_valid,
                "quality_flags": flags, "event_counts": events,
                "manifest_rows_checked": manifest_count}
    finally:
        db.close()


def _attachment_check(world: dict[str, Any], root: Path, issues: list[str]) -> dict[str, int]:
    checked = missing = 0
    for message in world.get("messages", []):
        refs = message.get("evidence_refs", [])
        attachments = message.get("attachments", [])
        if not refs:
            issues.append(f"message {message.get('id')} has no evidence references")
            missing += 1
            continue
        by_ref = {a.get("original_ref"): a for a in attachments if isinstance(a, dict)}
        for ref in refs:
            attachment = by_ref.get(ref)
            if attachment is None:
                issues.append(f"message {message.get('id')} has no inbox attachment for {ref}")
                missing += 1
                continue
            target = (root / attachment.get("path", "")).resolve()
            if not target.is_relative_to(root.resolve()) or target.is_symlink() or not target.is_file():
                issues.append(f"message {message.get('id')} attachment is inaccessible: {ref}")
                missing += 1
            elif _sha(target) != attachment.get("sha256"):
                issues.append(f"message {message.get('id')} attachment hash mismatch: {ref}")
                missing += 1
            else:
                checked += 1
    return {"checked": checked, "missing_or_invalid": missing}


def grade_pine_world(world_path: str | Path, *, expected_source_hashes: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Grade one saved ``world-{arm}.json`` without reading/guessing prose meaning."""
    # The executed study defaults to its immutable archived bytes. A separately
    # generated source (e.g. a different SQLite build) must explicitly supply
    # its own pre-recorded manifest; never recompute expected hashes here.
    hashes = SOURCE_SHA256 if expected_source_hashes is None else expected_source_hashes
    if (len(hashes) != 3 or any(not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value) for value in hashes)):
        raise ValueError("Declare exactly three lowercase SHA-256 source hashes")
    world_path = Path(world_path)
    world = json.loads(world_path.read_text(encoding="utf-8"))
    root = world_path.parent.resolve()
    issues: list[str] = []
    sources = []
    for i in range(3):
        try:
            sources.append(_source(root / f"snapshot-{i}.sqlite3", i, expected_sha256=hashes[i]))
        except Exception as exc:
            issues.append(f"snapshot-{i} source check failed: {exc}")
    source_by_cutoff = {s["clock"]["as_of_utc"]: s for s in sources}

    messages = world.get("messages", [])
    if not isinstance(messages, list):
        messages = []
        issues.append("messages is not an array")
    by_id = {}
    coverage = {cutoff: {DISPATCH: 0, DATA_OPS: 0} for cutoff in CUTOFFS}
    for message in messages:
        if not isinstance(message, dict):
            issues.append("message record is not an object")
            continue
        mid, cutoff, recipient = message.get("id"), message.get("source_cutoff"), message.get("to")
        if not isinstance(mid, str) or not mid or mid in by_id:
            issues.append("message IDs must be present and unique")
        else:
            by_id[mid] = message
        if cutoff not in source_by_cutoff:
            issues.append(f"message {mid} has no matching archived source cutoff")
        elif recipient in (DISPATCH, DATA_OPS):
            coverage[cutoff][recipient] += 1
        else:
            issues.append(f"message {mid} has an unknown simulated recipient")
        if not isinstance(message.get("body"), str) or not message["body"].strip():
            issues.append(f"message {mid} has no delivered body")
    for cutoff in CUTOFFS:
        if coverage[cutoff][DISPATCH] == 0:
            issues.append(f"no Dispatch delivery for {cutoff}")
    middle = source_by_cutoff.get(CUTOFFS[1])
    if middle and "cache_denominator_missing" in middle["quality_flags"] and coverage[CUTOFFS[1]][DATA_OPS] == 0:
        issues.append("known cached ALL denominator gap was not delivered to Data Operations")

    attachments = _attachment_check(world, root, issues)
    conversations = world.get("owner_conversations", [])
    if not isinstance(conversations, list):
        conversations = []
        issues.append("owner_conversations is not an array")
    owner_questions = sum(isinstance(c, dict) and bool(c.get("question")) and bool(c.get("answer"))
                          for c in conversations)
    confirmations = [c for c in conversations if isinstance(c, dict) and c.get("summary")
                     and c.get("answer") and c.get("source_cutoff") in CUTOFFS]
    if owner_questions == 0:
        issues.append("no recorded owner question/answer")
    if not confirmations:
        issues.append("no structural owner confirmation record")
    arm = world_path.stem.removeprefix("world-")
    saved_card_present = any(isinstance(c.get("saved_card"), dict) for c in confirmations)
    if arm == "signalweave" and not saved_card_present:
        issues.append("SignalWeave confirmation has no displayed saved-card artifact")

    actions = world.get("operator_actions", [])
    if not isinstance(actions, list):
        actions = []
        issues.append("operator_actions is not an array")
    failed_actions = [a for a in actions if isinstance(a, dict) and a.get("returncode") != 0]
    if failed_actions:
        issues.append("one or more recorded operator actions failed")

    feedback_reads = world.get("feedback_reads", [])
    replies_checked = 0
    if not isinstance(feedback_reads, list):
        feedback_reads = []
        issues.append("feedback_reads is not an array")
    read_cutoffs = set()
    for batch in feedback_reads:
        if not isinstance(batch, dict) or batch.get("source_cutoff") not in CUTOFFS:
            issues.append("feedback read has an invalid source cutoff")
            continue
        read_cutoffs.add(batch["source_cutoff"])
        for reply in batch.get("replies", []):
            original = by_id.get(reply.get("reply_to")) if isinstance(reply, dict) else None
            if (original is None or original.get("source_cutoff") != batch["source_cutoff"]
                    or original.get("to") != reply.get("from") or not reply.get("body")):
                issues.append("feedback reply is not linked to a delivered message/recipient")
            else:
                replies_checked += 1
    if read_cutoffs != set(CUTOFFS):
        issues.append("inbox feedback was not read at all three source cutoffs")
    if replies_checked == 0:
        issues.append("no linked human feedback reply was recorded")

    if world.get("complete") is not True or world.get("current_day") != 2:
        issues.append("world does not record completion of the final weekly cycle")

    return {
        "arm": arm,
        "structural_status": "pass" if not issues else "fail",
        "source_reference": [{
            "source_id": s["source_id"], "sha256": s["source_sha256"],
            "as_of_utc": s["clock"]["as_of_utc"],
            "prior_all": s["raw"]["prior"]["ALL"],
            "current_all": s["raw"]["current"]["ALL"],
            "delta_pp": s["delta_pp"], "raw_comparison_valid": s["raw_comparison_valid"],
            "cache_comparison_valid": s["cache_comparison_valid"],
            "cache_all_periods": s["cache"],
            "current_cache_all": s["cache"]["current"],
            "quality_flags": s["quality_flags"], "event_counts": s["event_counts"],
            "manifest_rows_checked": s["manifest_rows_checked"],
            "policy_reference": {
                "weekly_dispatch_digest_expected": True,
                "decline_notice_threshold_pp": -5.0,
                "decline_notice_expected": s["delta_pp"] <= -5.0,
                "data_operations_followup_expected": "cache_denominator_missing" in s["quality_flags"],
            },
        } for s in sources],
        "coverage": {"delivered_messages": len(messages), "by_cutoff_and_recipient": coverage,
                     "owner_questions_with_answers": owner_questions,
                     "confirmation_records": len(confirmations),
                     "saved_card_present": saved_card_present,
                     "operator_actions": len(actions), "feedback_replies_linked": replies_checked,
                     "attachment_access": attachments},
        "attachment_content": "path and SHA-256 checked; contents not semantically graded",
        "prose_numeric_accuracy": "not graded; no string matching or inference from message labels",
        "issues": issues,
    }
