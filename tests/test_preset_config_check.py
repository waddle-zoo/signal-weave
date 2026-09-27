from __future__ import annotations

import json

import pytest

import scripts.preset_config_check as config_check


def _clear_config(monkeypatch):
    for name in (
        "PRESET_URL",
        "PRESET_WORKSPACE",
        "PRESET_TENANT_ID",
        "PRESET_ACCESS_TOKEN",
        "PRESET_ACCESS_TOKEN_FILE",
        "PRESET_API_TOKEN_NAME",
        "PRESET_API_TOKEN_NAME_FILE",
        "PRESET_API_TOKEN_SECRET",
        "PRESET_API_TOKEN_SECRET_FILE",
        "PRESET_API_BASE_URL",
        "SIGNALWEAVE_TENANT_ID",
        "SIGNALWEAVE_PRINCIPAL_ID",
        "SIGNALWEAVE_AUTH_MODE",
        "SIGNALWEAVE_OIDC_ISSUER_URL",
        "SIGNALWEAVE_OIDC_AUDIENCE",
        "SIGNALWEAVE_OIDC_JWKS_URL",
        "TYPESAFE_MODE",
        "TYPESAFE_API_KEY",
        "TYPESAFE_API_KEY_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_valid_token_config(monkeypatch):
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_WORKSPACE", "northstar")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME", "preset-name")
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET", "preset-secret")
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "signalweave-agent")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")


def test_config_check_is_zero_network_and_redacts_credentials(monkeypatch, tmp_path):
    _clear_config(monkeypatch)
    _set_valid_token_config(monkeypatch)

    report = config_check.run(output=tmp_path / "config.json")

    assert report["passed"] is True
    assert report["checks"]["network_requests"] == 0
    assert report["checks"]["jev_requests"] == 0
    assert report["configuration"]["preset_credential_source"] == "environment"
    serialized = json.dumps(report)
    assert "preset-secret" not in serialized
    assert "test-key" not in serialized
    assert json.loads((tmp_path / "config.json").read_text()) == report


def test_config_check_accepts_oidc_and_mounted_secrets_without_static_principal(
    monkeypatch, tmp_path
):
    _clear_config(monkeypatch)
    name_file = tmp_path / "preset-name"
    secret_file = tmp_path / "preset-secret"
    typesafe_file = tmp_path / "typesafe"
    name_file.write_text("preset-name\n", encoding="utf-8")
    secret_file.write_text("preset-secret\n", encoding="utf-8")
    typesafe_file.write_text("typesafe-key\n", encoding="utf-8")
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME_FILE", str(name_file))
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "oidc")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_AUDIENCE", "signalweave")
    monkeypatch.setenv("TYPESAFE_API_KEY_FILE", str(typesafe_file))

    report = config_check.run()

    assert report["passed"] is True
    assert report["configuration"]["auth_mode"] == "oidc"
    assert report["configuration"]["principal_mode"] == "request_scoped"
    assert report["configuration"]["preset_credential_source"] == "mounted_file"
    assert report["typesafe_key_source"] == "mounted_file"


def test_config_check_accepts_mounted_bearer_preset_token(monkeypatch, tmp_path):
    _clear_config(monkeypatch)
    access_file = tmp_path / "preset-access-token"
    typesafe_file = tmp_path / "typesafe"
    access_file.write_text("preset-access-token\n", encoding="utf-8")
    typesafe_file.write_text("typesafe-key\n", encoding="utf-8")
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "signalweave-agent")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN_FILE", str(access_file))
    monkeypatch.setenv("TYPESAFE_API_KEY_FILE", str(typesafe_file))

    report = config_check.run()

    assert report["passed"] is True
    assert report["configuration"]["auth_mode"] == "token"
    assert report["configuration"]["preset_credential_source"] == "mounted_file"
    serialized = json.dumps(report)
    assert "preset-access-token" not in serialized
    assert "typesafe-key" not in serialized


def test_config_check_rejects_malformed_oidc_identity_claim(monkeypatch):
    _clear_config(monkeypatch)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "preset-token")
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "oidc")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_AUDIENCE", "signalweave")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_TENANT_CLAIM", "claims..tenant")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    report = config_check.run()

    assert report["passed"] is False
    assert any("dotted claim path" in error for error in report["errors"])
    assert report["checks"]["network_requests"] == 0
    assert report["checks"]["jev_requests"] == 0


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("typesafe", "typesafe:"),
        ("principal", "SIGNALWEAVE_TENANT_ID and SIGNALWEAVE_PRINCIPAL_ID"),
    ],
)
def test_config_check_reports_actionable_missing_inputs(monkeypatch, missing, expected):
    _clear_config(monkeypatch)
    _set_valid_token_config(monkeypatch)
    if missing == "typesafe":
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)

    report = config_check.run()

    assert report["passed"] is False
    assert any(expected in error for error in report["errors"])
    assert report["checks"]["network_requests"] == 0
    assert report["checks"]["jev_requests"] == 0


def test_config_check_rejects_insecure_provider_before_any_network(monkeypatch):
    _clear_config(monkeypatch)
    _set_valid_token_config(monkeypatch)
    monkeypatch.setenv("PRESET_URL", "http://workspace.local")
    monkeypatch.setenv("SIGNALWEAVE_ALLOW_INSECURE_PROVIDER", "1")

    report = config_check.run()

    assert report["passed"] is False
    assert any("PRESET_URL must use https" in error for error in report["errors"])
    assert report["checks"]["network_requests"] == 0
    assert report["checks"]["jev_requests"] == 0
