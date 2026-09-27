from __future__ import annotations

import json
import subprocess

import scripts.preset_compose_check as compose_check

REQUIRED_HOST_ENV = {
    "TYPESAFE_API_KEY_FILE": "/tmp/typesafe-key",
    "PRESET_API_TOKEN_NAME_HOST_FILE": "/tmp/preset-name",
    "PRESET_API_TOKEN_SECRET_HOST_FILE": "/tmp/preset-secret",
}


def _rendered_config() -> dict:
    return {
        "services": {
            "signal-weave": {
                "environment": {
                    "TYPESAFE_API_KEY_FILE": "/run/secrets/typesafe_api_key",
                    "PRESET_API_TOKEN_NAME": "",
                    "PRESET_API_TOKEN_SECRET": "",
                    "PRESET_API_TOKEN_NAME_FILE": "/run/secrets/preset_api_token_name",
                    "PRESET_API_TOKEN_SECRET_FILE": "/run/secrets/preset_api_token_secret",
                },
                "secrets": [
                    {"source": "preset_api_token_name"},
                    {"source": "preset_api_token_secret"},
                ],
                "volumes": [
                    "/tmp/typesafe-key:/run/secrets/typesafe_api_key:ro",
                ],
            }
        }
    }


def _set_inputs(monkeypatch, tmp_path):
    for name, value in REQUIRED_HOST_ENV.items():
        monkeypatch.setenv(name, value)
    (tmp_path / ".env.preset").write_text("PRESET_URL=https://preset.example\n", encoding="utf-8")
    monkeypatch.setattr(compose_check, "ROOT", tmp_path)


def test_compose_preflight_accepts_redacted_secret_overlay(monkeypatch, tmp_path):
    _set_inputs(monkeypatch, tmp_path)
    completed = subprocess.CompletedProcess(
        args=["docker", "compose"],
        returncode=0,
        stdout=json.dumps(_rendered_config()),
        stderr="",
    )
    monkeypatch.setattr(compose_check.subprocess, "run", lambda *args, **kwargs: completed)

    assert compose_check.main() == 0


def test_compose_preflight_rejects_missing_host_input_before_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(compose_check, "ROOT", tmp_path)
    for name in REQUIRED_HOST_ENV:
        monkeypatch.delenv(name, raising=False)
    called = False

    def run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Docker must not run with missing host inputs")

    monkeypatch.setattr(compose_check.subprocess, "run", run)

    assert compose_check.main() == 1
    assert called is False


def test_compose_preflight_rejects_direct_token_rendering(monkeypatch, tmp_path):
    _set_inputs(monkeypatch, tmp_path)
    config = _rendered_config()
    config["services"]["signal-weave"]["environment"]["PRESET_API_TOKEN_SECRET"] = "leaked"
    completed = subprocess.CompletedProcess(
        args=["docker", "compose"],
        returncode=0,
        stdout=json.dumps(config),
        stderr="",
    )
    monkeypatch.setattr(compose_check.subprocess, "run", lambda *args, **kwargs: completed)

    assert compose_check.main() == 1


def test_compose_preflight_rejects_missing_preset_secret_mount(monkeypatch, tmp_path):
    _set_inputs(monkeypatch, tmp_path)
    config = _rendered_config()
    config["services"]["signal-weave"]["secrets"] = [
        {"source": "preset_api_token_name"},
    ]
    completed = subprocess.CompletedProcess(
        args=["docker", "compose"],
        returncode=0,
        stdout=json.dumps(config),
        stderr="",
    )
    monkeypatch.setattr(compose_check.subprocess, "run", lambda *args, **kwargs: completed)

    assert compose_check.main() == 1
