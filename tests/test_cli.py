import sys
from types import SimpleNamespace

import pytest

import signalweave.cli as cli


def test_token_preset_server_fails_closed_without_static_principal(monkeypatch):
    monkeypatch.setenv("PRESET_URL", "https://workspace.app.preset.io")
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "token")
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setattr(cli, "build_runtime", lambda: SimpleNamespace(principal=None))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--transport", "streamable-http"])

    with pytest.raises(RuntimeError, match="token-authenticated Preset deployments"):
        cli.main()
