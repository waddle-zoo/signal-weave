"""Run a zero-network Preset deployment configuration preflight.

This command validates the same Preset environment parser used by the
production runtime and checks that the Jev credential is present, without
instantiating a TypeSafe client or contacting Preset. It is safe to run before
the no-credit provider bootstrap check and before any Jev call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from signalweave.runtime import validate_preset_environment
from signalweave.typesafe_adapter import load_api_key


def run(*, output: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    configuration: dict[str, Any] | None = None
    try:
        configuration = validate_preset_environment()
    except (OSError, RuntimeError, ValueError) as error:
        errors.append(f"preset: {error}")

    typesafe_key_source = "none"
    mode = os.getenv("TYPESAFE_MODE", "jev").strip().lower()
    if mode != "jev":
        errors.append("typesafe: production runtime only supports TYPESAFE_MODE=jev")
    else:
        key_file = os.getenv("TYPESAFE_API_KEY_FILE", "").strip()
        try:
            key = load_api_key()
        except (OSError, ValueError) as error:
            errors.append(f"typesafe: {error}")
        else:
            if not key:
                errors.append(
                    "typesafe: set TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE to a non-empty key"
                )
            else:
                typesafe_key_source = "mounted_file" if key_file else "environment"

    report = {
        "trial": "preset-config-check",
        "configuration": configuration,
        "checks": {
            "preset_environment_valid": configuration is not None,
            "jev_mode_configured": mode == "jev",
            "jev_credential_present": typesafe_key_source != "none",
            "network_requests": 0,
            "jev_requests": 0,
        },
        "typesafe_key_source": typesafe_key_source,
        "errors": errors,
        "passed": not errors,
        "not_proven": [
            "Preset credentials are accepted by the provider",
            "dashboard/chart permissions and result-shape quality",
            "a human-approved card or Jev judgment",
            "managed SignalWeave hosting",
        ],
    }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    return report


def main() -> int:
    output_name = os.getenv("PRESET_CONFIG_CHECK_OUTPUT", "").strip()
    report = run(output=Path(output_name) if output_name else None)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
