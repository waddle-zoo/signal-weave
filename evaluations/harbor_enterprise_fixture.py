"""Prepare private, immutable Harbor as-of sources for a later workflow study.

Only a selected SQLite snapshot belongs in an analyst's MCP directory. The full
history and reviewer inventory stay under the private output root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluations.harbor_history import make_history, materialize_snapshot

UTC = timezone.utc
DEFAULT_CUTOFF_START = datetime(2026, 2, 23, 6, tzinfo=UTC)
DEFAULT_CUTOFF_COUNT = 28
MAX_CUTOFFS = 40
GENERATOR_SEED = 20261018
_HISTORY_START = datetime(2026, 1, 5, tzinfo=UTC)
_MAX_HISTORY_WEEKS = 54


def default_cutoffs() -> list[datetime]:
    """Formative candidate sequence; not a holdout or selected success window."""
    return [DEFAULT_CUTOFF_START + timedelta(days=day) for day in range(DEFAULT_CUTOFF_COUNT)]


def parse_cutoffs(values: Iterable[datetime | str] | None = None) -> list[datetime]:
    """Normalize caller-frozen cutoffs to sorted, unique UTC whole-second instants."""
    raw = default_cutoffs() if values is None else list(values)
    if not raw or len(raw) > MAX_CUTOFFS:
        raise ValueError(f"Provide 1..{MAX_CUTOFFS} cutoffs")
    cutoffs = []
    for value in raw:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("Cutoffs must be ISO-8601 timestamps") from exc
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Cutoffs must be timezone-aware datetimes")
        if value.microsecond:
            raise ValueError("Cutoffs must have whole-second precision")
        cutoffs.append(value.astimezone(UTC))
    if any(value < _HISTORY_START for value in cutoffs):
        raise ValueError("Cutoffs precede the available Harbor history")
    if cutoffs != sorted(set(cutoffs)):
        raise ValueError("Cutoffs must be strictly increasing and unique")
    return cutoffs


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_history(history: dict) -> bytes:
    private = {
        "first_week": _stamp(history["first_week"]),
        "clock_definitions": history["clock_definitions"],
        "regions": history["regions"],
        "events": [
            {
                **row,
                "effective_at": _stamp(row["effective_at"]),
                "available_at": _stamp(row["available_at"]),
            }
            for row in history["events"]
        ],
    }
    return (json.dumps(private, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), 0o600)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _review_inventory(path: Path) -> dict:
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        objects = connection.execute(
            "SELECT name,type FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        row_counts, source_fields = {}, {}
        for name, _kind in objects:
            quoted = _quote(name)
            row_counts[name] = connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            source_fields[name] = [
                {"name": row[1], "type": row[2]}
                for row in connection.execute(f"PRAGMA table_info({quoted})")
            ]
        coverage = connection.execute(
            "SELECT coverage_status,COUNT(*) FROM weekly_source_coverage "
            "GROUP BY coverage_status ORDER BY coverage_status"
        ).fetchall()
        gaps = connection.execute(
            "SELECT week_start_utc,support_tier,region,expected_ticket_count,"
            "observed_ticket_count,missing_ticket_count,coverage_status,"
            "manifest_available_at_utc FROM weekly_source_coverage "
            "WHERE coverage_status!='complete' "
            "ORDER BY week_start_utc,support_tier,region"
        ).fetchall()
    return {
        "row_counts": row_counts,
        "source_fields": source_fields,
        "coverage_status_counts": {status: count for status, count in coverage},
        "known_coverage_gaps": [
            dict(
                zip(
                    (
                        "week_start_utc",
                        "support_tier",
                        "region",
                        "expected_ticket_count",
                        "observed_ticket_count",
                        "missing_ticket_count",
                        "coverage_status",
                        "manifest_available_at_utc",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in gaps
        ],
    }


def build_fixture(output_root: str | Path, cutoffs: Iterable[datetime | str] | None = None) -> dict:
    """Create an exclusive private root of as-of SQLite snapshots and reviewer metadata."""
    frozen = parse_cutoffs(cutoffs)
    weeks = max(18, (frozen[-1] - _HISTORY_START).days // 7 + 6)
    if weeks > _MAX_HISTORY_WEEKS:
        raise ValueError("Latest cutoff is outside the bounded Harbor history horizon")

    root = Path(output_root).expanduser().absolute()
    if root.name in {"", ".", ".."} or os.path.lexists(root):
        raise FileExistsError(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    snapshots_dir, private_dir = root / "snapshots", root / "private"
    snapshots_dir.mkdir(mode=0o700)
    private_dir.mkdir(mode=0o700)

    history = make_history(seed=GENERATOR_SEED, weeks=weeks)
    history_bytes = _encode_history(history)
    history_path = private_dir / "full-history.json"
    _write_private(history_path, history_bytes)
    snapshot_records = []
    for cutoff in frozen:
        filename = f"snapshot-{cutoff.strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        path = snapshots_dir / filename
        materialize_snapshot(history, cutoff, path)
        os.chmod(path, 0o400)
        snapshot_records.append(
            {
                "as_of_utc": _stamp(cutoff),
                "path": f"snapshots/{filename}",
                "sha256": _sha256(path),
                **_review_inventory(path),
            }
        )
    os.chmod(snapshots_dir, 0o500)

    manifest = {
        "schema_version": 1,
        "reviewer_only": True,
        "fixture": "Harbor operational-history source snapshots",
        "window_note": "Formative candidate dates, not a holdout or a selected-success window.",
        "generator": {
            "function": "evaluations.harbor_history.make_history",
            "seed": GENERATOR_SEED,
            "weeks": weeks,
        },
        "history": {
            "path": "private/full-history.json",
            "sha256": hashlib.sha256(history_bytes).hexdigest(),
            "event_count": len(history["events"]),
            "first_week_utc": _stamp(history["first_week"]),
        },
        "snapshots": snapshot_records,
    }
    identity_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_id"] = hashlib.sha256(identity_payload).hexdigest()
    manifest_path = private_dir / "reviewer-manifest.json"
    _write_private(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "manifest_id": manifest["manifest_id"],
        "snapshot_paths": [str(root / row["path"]) for row in snapshot_records],
    }


def copy_active_snapshot(
    output_root: str | Path, cutoff: datetime | str, destination: str | Path
) -> dict[str, str]:
    """Copy exactly one verified snapshot outside the private root for an MCP run."""
    supplied_root = Path(output_root).expanduser().absolute()
    if supplied_root.is_symlink():
        raise ValueError("Private history root must not be a symlink")
    root = supplied_root.resolve(strict=True)
    cutoff_stamp = _stamp(parse_cutoffs([cutoff])[0])
    if any(
        (root / name).is_symlink() or not (root / name).is_dir()
        for name in ("private", "snapshots")
    ):
        raise ValueError("Private history directories must be regular directories")
    manifest_path = root / "private" / "reviewer-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Reviewer manifest must be a regular private file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    claimed_id = manifest.pop("manifest_id", None)
    actual_id = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed_id != actual_id:
        raise ValueError("Reviewer manifest identity check failed")
    record = next((row for row in manifest["snapshots"] if row["as_of_utc"] == cutoff_stamp), None)
    if record is None:
        raise KeyError(f"No frozen snapshot for {cutoff_stamp}")
    source_path = root / record["path"]
    if source_path.is_symlink():
        raise ValueError("Snapshot files must not be symlinks")
    source = source_path.resolve(strict=True)
    if source.parent != (root / "snapshots").resolve():
        raise ValueError("Snapshot path escaped its private snapshot directory")
    if _sha256(source) != record["sha256"]:
        raise ValueError("Snapshot hash does not match the private manifest")

    target = Path(destination).expanduser().absolute()
    if target.parent.resolve() == root or root in target.parent.resolve().parents:
        raise ValueError("Active MCP copy must be outside the private history root")
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o400)
        if _sha256(target) != record["sha256"]:
            raise OSError("Copied active snapshot failed its hash check")
    except BaseException:
        try:
            current = target.lstat()
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                target.unlink()
        raise
    return {"path": str(target), "as_of_utc": cutoff_stamp, "sha256": record["sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_root", help="New private directory; it must not already exist")
    parser.add_argument(
        "--cutoff", action="append", help="Frozen ISO-8601 as-of timestamp; repeat up to 40 times"
    )
    args = parser.parse_args()
    result = build_fixture(args.output_root, args.cutoff)
    print(json.dumps({key: result[key] for key in ("root", "manifest", "manifest_id")}, indent=2))


if __name__ == "__main__":
    main()
