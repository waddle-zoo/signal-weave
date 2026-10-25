"""Targeted CA incident regression, including the actual public affected root.

The fixture is a public certificate from certifi 2026.7.22, not a private key.
It must never be loaded as trust by a test client.
"""
from __future__ import annotations

import hashlib
import ssl
from pathlib import Path

import certifi
import pytest
import tomllib

from scripts.check_ca_bundle import FORBIDDEN_ROOT_SHA256, check_bundle, check_installed_certifi

ROOT = Path(__file__).parents[1]
BAD_ROOT = ROOT / "tests/fixtures/emsign-g3-public-root.pem"


def test_actual_affected_public_root_is_rejected():
    der = ssl.PEM_cert_to_DER_cert(BAD_ROOT.read_text())
    assert hashlib.sha256(der).hexdigest() == FORBIDDEN_ROOT_SHA256
    with pytest.raises(ValueError, match="Affected emSign"):
        check_bundle(BAD_ROOT)


def test_affected_root_hidden_in_otherwise_safe_bundle_is_rejected(tmp_path):
    bundle = tmp_path / "cacert.pem"
    bundle.write_bytes(Path(certifi.where()).read_bytes() + BAD_ROOT.read_bytes())
    with pytest.raises(ValueError, match="Affected emSign"):
        check_bundle(bundle)


def test_installed_fixed_bundle_passes_and_has_recorded_identity():
    result = check_installed_certifi()
    assert result["certifi_version"] == certifi.__version__
    assert result["certificates"] > 0
    assert result["bundle_sha256"] == hashlib.sha256(Path(certifi.where()).read_bytes()).hexdigest()
    assert check_bundle(Path(certifi.where()), expected_sha256=result["bundle_sha256"])


def test_frozen_bundle_must_match_build_environment():
    with pytest.raises(ValueError, match="differs"):
        check_bundle(Path(certifi.where()), expected_sha256="0" * 64)


@pytest.mark.parametrize("version", ["2026.7.22", "2026.10.18", "2026.10.19rc1", "unknown"])
def test_old_or_unrecognized_build_dependency_is_rejected(monkeypatch, version):
    monkeypatch.setattr(certifi, "__version__", version)
    with pytest.raises(ValueError, match="requires certifi"):
        check_installed_certifi()


@pytest.mark.parametrize("data", [b"", b"not a CA bundle", b"-----BEGIN CERTIFICATE-----\nbad\n-----END CERTIFICATE-----"])
def test_empty_or_malformed_bundle_is_rejected(tmp_path, data):
    path = tmp_path / "cacert.pem"
    path.write_bytes(data)
    with pytest.raises((ValueError, ssl.SSLError)):
        check_bundle(path)


def test_source_lock_container_and_workflow_require_patched_trust():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "certifi>=2026.10.19" in project["project"]["dependencies"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = next(p for p in lock["package"] if p["name"] == "certifi")
    assert tuple(map(int, locked["version"].split("."))) >= (2026, 10, 19)
    docker = (ROOT / "Dockerfile").read_text()
    assert "pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70" in docker
    assert docker.index("pip-26.2.2") < docker.index("pip install --no-cache-dir .")
    for name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text()
        uv_steps = workflow.split("uses: astral-sh/setup-uv@")[1:]
        assert uv_steps
        assert all("version: '0.13.4'" in step.split("\n      - ", 1)[0] for step in uv_steps)
    assert "Check installed container certificate trust bundle" in (ROOT / ".github/workflows/ci.yml").read_text()


@pytest.mark.parametrize("packaged", ["safe", "affected", "missing"])
def test_native_builder_checks_actual_packaged_ca_file(tmp_path, monkeypatch, packaged):
    from importlib.metadata import version

    from scripts import build_binary

    skill = tmp_path / "skills/signalweave/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("Canonical workflow instructions\n")
    metadata = {"version": version("signal-weave"), "source_sha256": "f" * 64}
    monkeypatch.setattr(build_binary, "ROOT", tmp_path)
    monkeypatch.setattr(build_binary, "build_metadata", lambda: metadata.copy())
    monkeypatch.setattr(build_binary, "source_fingerprint", lambda: "f" * 64)

    def fake_pyinstaller(*args, **kwargs):
        if packaged != "missing":
            output = tmp_path / "dist/signalweave/_internal/certifi/cacert.pem"
            output.parent.mkdir(parents=True)
            output.write_bytes((BAD_ROOT if packaged == "affected" else Path(certifi.where())).read_bytes())

    monkeypatch.setattr(build_binary.subprocess, "run", fake_pyinstaller)
    if packaged == "safe":
        build_binary.main()
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            build_binary.main()
