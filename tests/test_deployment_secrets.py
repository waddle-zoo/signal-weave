from pathlib import Path

from signalweave.runtime import load_deployment_secret


def test_deployment_secret_accepts_mounted_file(monkeypatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.delenv("TEST_DEPLOYMENT_SECRET", raising=False)
    monkeypatch.setenv("TEST_DEPLOYMENT_SECRET_FILE", str(secret_file))

    assert load_deployment_secret("TEST_DEPLOYMENT_SECRET") == "from-file"


def test_deployment_secret_rejects_value_and_file_together(monkeypatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("TEST_DEPLOYMENT_SECRET", "direct")
    monkeypatch.setenv("TEST_DEPLOYMENT_SECRET_FILE", str(secret_file))

    try:
        load_deployment_secret("TEST_DEPLOYMENT_SECRET")
    except RuntimeError as error:
        assert "set only one" in str(error)
    else:
        raise AssertionError("direct and mounted deployment secrets must be exclusive")
