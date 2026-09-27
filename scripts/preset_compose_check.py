"""Validate the rendered Preset Compose deployment without contacting a provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = ("docker-compose.preset.yml", "docker-compose.preset.secrets.yml")


def _fail(message: str) -> int:
    print(f"Preset Compose preflight failed: {message}", file=sys.stderr)
    return 1


def main() -> int:
    required_environment = (
        "TYPESAFE_API_KEY_FILE",
        "PRESET_API_TOKEN_NAME_HOST_FILE",
        "PRESET_API_TOKEN_SECRET_HOST_FILE",
        "SIGNALWEAVE_API_TOKEN_HOST_FILE",
        "PUSH_WEBHOOK_TOKEN_HOST_FILE",
    )
    missing = [name for name in required_environment if not os.getenv(name)]
    if missing:
        return _fail("missing required host input(s): " + ", ".join(missing))
    if not (ROOT / ".env.preset").is_file():
        return _fail(".env.preset is missing; copy examples/preset/.env.preset.example first")

    command = ["docker", "compose"]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", compose_file))
    command.extend(("config", "--format", "json"))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return _fail(f"could not run Docker Compose: {type(error).__name__}")
    if completed.returncode != 0:
        return _fail("Docker Compose could not render the Preset deployment")
    try:
        config: dict[str, Any] = json.loads(completed.stdout)
        service = config["services"]["signal-weave"]
        environment = service["environment"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return _fail("rendered Compose output did not contain the signal-weave service model")

    expected_environment = {
        "TYPESAFE_API_KEY_FILE": "/run/secrets/typesafe_api_key",
        "PRESET_API_TOKEN_NAME": "",
        "PRESET_API_TOKEN_SECRET": "",
        "PRESET_API_TOKEN_NAME_FILE": "/run/secrets/preset_api_token_name",
        "PRESET_API_TOKEN_SECRET_FILE": "/run/secrets/preset_api_token_secret",
        "SIGNALWEAVE_API_TOKEN": "",
        "SIGNALWEAVE_API_TOKEN_FILE": "/run/secrets/signalweave_api_token",
        "PUSH_WEBHOOK_TOKEN": "",
        "PUSH_WEBHOOK_TOKEN_FILE": "/run/secrets/push_webhook_token",
    }
    for name, expected in expected_environment.items():
        if environment.get(name) != expected:
            return _fail(f"rendered environment invariant failed for {name}")

    secret_names = {
        item.get("source")
        for item in service.get("secrets", [])
        if isinstance(item, dict)
    }
    if secret_names != {
        "preset_api_token_name",
        "preset_api_token_secret",
        "signalweave_api_token",
        "push_webhook_token",
    }:
        return _fail("the required Preset and SignalWeave Docker secrets are not mounted")

    volume_text = json.dumps(service.get("volumes", []), sort_keys=True)
    if "/run/secrets/typesafe_api_key" not in volume_text:
        return _fail("the TypeSafe key is not mounted into the container")

    print("Preset Compose preflight passed: secret mounts and redaction invariants are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
