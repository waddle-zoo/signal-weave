"""Run the no-credit Preset enterprise proof pack.

The proof pack runs the shipped hosted-connector and runtime-shadow trials, then
runs their independent reviewers against the serialized reports. It uses only
synthetic Preset and TypeSafe transports, so it does not spend Jev credits or
contact a customer workspace. A passing result proves the local integration
contract and safety boundaries; it does not prove live provider permissions,
live Jev semantic quality, or managed SignalWeave hosting.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ProofCase:
    name: str
    trial_args: tuple[str, ...]
    review_script: str
    report_name: str


CASES = (
    ProofCase(
        name="hosted_connector",
        trial_args=("evaluations/preset_hosted_trial.py",),
        review_script="evaluations/preset_hosted_review.py",
        report_name="preset-hosted-proof.json",
    ),
    ProofCase(
        name="credential_and_tenant_boundary",
        trial_args=("evaluations/preset_boundary_trial.py",),
        review_script="evaluations/preset_boundary_review.py",
        report_name="preset-boundary-proof.json",
    ),
    ProofCase(
        name="generated_generalization",
        trial_args=("evaluations/preset_generalization_trial.py",),
        review_script="evaluations/preset_generalization_review.py",
        report_name="preset-generalization-proof.json",
    ),
    ProofCase(
        name="jev_contract",
        trial_args=("-m", "evaluations.preset_jev_contract_trial"),
        review_script="evaluations/preset_jev_contract_review.py",
        report_name="preset-jev-contract-proof.json",
    ),
    ProofCase(
        name="runtime_shadow",
        trial_args=("-m", "evaluations.preset_runtime_shadow_trial"),
        review_script="evaluations/preset_runtime_shadow_review.py",
        report_name="preset-runtime-shadow-proof.json",
    ),
)


def _parse_json_output(output: str) -> dict[str, Any] | None:
    """Parse a reviewer JSON object even if a runner prefixes a log line."""

    stripped = output.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for offset in (index for index, char in enumerate(stripped) if char == "{"):
            try:
                value, end = decoder.raw_decode(stripped[offset:])
            except json.JSONDecodeError:
                continue
            if not stripped[offset + end :].strip():
                break
        else:
            return None
    return value if isinstance(value, dict) else None


def _run(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def _display_path(path: Path) -> str:
    """Keep reports readable whether output is in-repo or in a temp directory."""

    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run(*, output: Path) -> dict[str, Any]:
    component_dir = output.parent / f"{output.stem}-components"
    component_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    for case in CASES:
        report_path = component_dir / case.report_name
        trial_command = [sys.executable, *case.trial_args, "--output", str(report_path)]
        trial_run = _run(trial_command)
        trial_report: dict[str, Any] | None = None
        if report_path.is_file():
            try:
                loaded = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                trial_report = loaded

        review_run: dict[str, Any] | None = None
        review_report: dict[str, Any] | None = None
        if trial_run["exit_code"] == 0 and trial_report is not None:
            review_run = _run([sys.executable, case.review_script, str(report_path)])
            review_report = _parse_json_output(review_run["stdout"])

        cases.append(
            {
                "name": case.name,
                "report_path": _display_path(report_path),
                "producer": {
                    "passed": trial_run["exit_code"] == 0
                    and trial_report is not None
                    and trial_report.get("passed") is True,
                    "exit_code": trial_run["exit_code"],
                    "stderr": trial_run["stderr"],
                },
                "independent_review": {
                    "passed": review_run is not None
                    and review_run["exit_code"] == 0
                    and review_report is not None
                    and review_report.get("passed") is True,
                    "exit_code": review_run["exit_code"] if review_run else None,
                    "report": review_report,
                    "stderr": review_run["stderr"] if review_run else "",
                },
            }
        )

    report = {
        "trial": "preset-enterprise-proof-pack",
        "proof_scope": {
            "synthetic_preset_transport": True,
            "synthetic_typesafe_transport": True,
            "live_external_provider_requests": 0,
            "live_jev_requests": 0,
            "delivery_enabled": False,
        },
        "cases": cases,
        "producer_passed": all(case["producer"]["passed"] for case in cases),
        "independent_reviews_passed": all(
            case["independent_review"]["passed"] for case in cases
        ),
        "passed": all(
            case["producer"]["passed"] and case["independent_review"]["passed"]
            for case in cases
        ),
        "not_proven": [
            "real Preset plan, credentials, permissions, and rate limits",
            "live Jev semantic accuracy or business usefulness",
            "managed SignalWeave hosting",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/preset-enterprise-proof.json",
    )
    args = parser.parse_args()
    report = run(output=args.output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
