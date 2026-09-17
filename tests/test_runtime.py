import pytest

from semantic_monitor.runtime import build_runtime


def test_runtime_requires_jev_credentials_by_default(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)

    with pytest.raises(RuntimeError, match="requires TYPESAFE_API_KEY"):
        build_runtime()


def test_runtime_rejects_non_jev_mode():
    with pytest.raises(ValueError, match="only supports TYPESAFE_MODE=jev"):
        build_runtime(mode="other")


def test_runtime_requires_superset_url_after_jev_credentials(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)

    with pytest.raises(RuntimeError, match="requires SUPERSET_URL"):
        build_runtime()
