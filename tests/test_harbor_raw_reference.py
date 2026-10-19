from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evaluations.harbor_enterprise_fixture import build_fixture, default_cutoffs
from evaluations.harbor_raw_reference import build_reference, classify_coverage

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "evaluations" / "harbor_raw_reference.py"


def test_cli_reads_fresh_immutable_fixture_and_writes_raw_facts(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    build_fixture(fixture, default_cutoffs()[:2])
    output = tmp_path / "reference.json"

    subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(fixture), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )

    reference = json.loads(output.read_text(encoding="utf-8"))
    assert reference["cutoff_count"] == 2
    assert reference["fixture_name"] == "fixture"
    assert "source_root" not in reference
    assert reference["method"]["outcome_thresholds_applied"] is False
    assert reference["method"]["source_writes"] is False
    for cutoff in reference["cutoffs"]:
        assert cutoff["snapshot"]["mode_octal"] == "0400"
        assert cutoff["snapshot"]["embedded_as_of_utc"] == cutoff["source_cutoff_utc"]
        assert cutoff["weekly_raw_facts"]["priority_1_visible_resolved_denominator"] > 0
        assert cutoff["weekly_raw_facts"]["by_support_tier_and_region"]
        assert cutoff["daily_raw_sets"]["priority_1_open_unanswered_over_first_response_clock"][
            "count"
        ] >= 0


def test_no_completed_week_keeps_zero_denominator_rate_null(tmp_path: Path) -> None:
    fixture = tmp_path / "early-fixture"
    early_cutoff = datetime(2026, 1, 5, 6, tzinfo=timezone.utc)
    build_fixture(fixture, [early_cutoff])

    cutoff, = build_reference(fixture)["cutoffs"]

    assert cutoff["weekly_raw_facts"]["latest_fully_ended_creation_week_start_utc"] is None
    assert cutoff["weekly_raw_facts"]["priority_1_visible_resolved_denominator"] == 0
    assert cutoff["weekly_raw_facts"]["priority_1_resolution_clock_miss_count"] == 0
    assert cutoff["weekly_raw_facts"]["descriptive_miss_rate"] is None


def test_coverage_does_not_turn_unknown_manifest_into_missing_partition() -> None:
    assert classify_coverage(None, 0) == "unknown"
    assert classify_coverage(3, 0) == "missing"
    assert classify_coverage(3, 2) == "partial"


def test_cli_rejects_report_output_inside_fixture_root(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    build_fixture(fixture, default_cutoffs()[:1])
    output = fixture / "report.json"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(fixture), "--output", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--output must be outside" in result.stderr
    assert not output.exists()


def test_public_checker_has_only_standard_library_imports_and_no_personal_paths() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = {
        (alias.name if isinstance(node, ast.Import) else node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name="", asname=None)])
    }

    assert not {"evaluations", "signalweave", "src"} & roots
    assert "/Users/" not in source
    assert "DEFAULT_SOURCE_ROOT" not in source
