"""Run a zero-network Preset deployment configuration preflight.

This command validates the same Preset environment parser used by the
production runtime and checks that the Jev credential is present, without
instantiating a TypeSafe client or contacting Preset. It is safe to run before
the no-credit provider bootstrap check and before any Jev call.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from signalweave.runtime import validate_preset_environment
from signalweave.typesafe_adapter import load_api_key


@contextmanager
def _environment_file() -> Iterator[str | None]:
    """Temporarily overlay an env file without mutating the caller's process."""

    filename = os.getenv("PRESET_ENV_FILE", "").strip()
    if not filename:
        yield None
        return
    path = Path(filename)
    if not path.is_file():
        raise ValueError(f"PRESET_ENV_FILE does not exist: {path}")
    values = dotenv_values(path)
    injected: list[str] = []
    for key, value in values.items():
        if key and value is not None and key not in os.environ:
            os.environ[key] = value
            injected.append(key)
    try:
        yield str(path)
    finally:
        for key in injected:
            os.environ.pop(key, None)


def run(*, output: Path | None = None) -> dict[str, Any]:
    try:
        with _environment_file() as environment_file:
            return _run_loaded(output=output, environment_file=environment_file)
    except (OSError, ValueError) as error:
        return _run_loaded(output=output, environment_file=None, environment_error=error)


def _run_loaded(
    *, output: Path | None = None, environment_file: str | None, environment_error: Exception | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    configuration: dict[str, Any] | None = None
    if environment_error is not None:
        errors.append(f"environment: {environment_error}")
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
        "environment_file": environment_file,
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
