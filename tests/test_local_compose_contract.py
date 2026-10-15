"""The local Jev service must retain its explicit mounted credential path."""

from pathlib import Path


def test_local_compose_wires_the_required_jev_provider_and_private_key_mount():
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text()
    service = compose.split("  signal-weave:", 1)[1].split("\nvolumes:", 1)[0]
    assert "SIGNALWEAVE_MCP_PROFILE: agent" in service
    assert "TYPESAFE_MODE: jev" in service
    assert "TYPESAFE_API_KEY_FILE: /run/secrets/typesafe_api_key" in service
    assert "${TYPESAFE_API_KEY_FILE:-./secrets/typesafe_api_key}:/run/secrets/typesafe_api_key:ro" in service
    assert "TYPESAFE_API_KEY:" not in service


def test_server_image_contains_the_package_skill_and_excludes_private_build_inputs():
    root = Path(__file__).parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    ignored = set((root / ".dockerignore").read_text().splitlines())
    assert "COPY pyproject.toml README.md LICENSE ./" in dockerfile
    assert "COPY skills ./skills" in dockerfile
    assert "COPY tests" not in dockerfile
    assert {".env.*", "*.key", "secrets", "artifacts", "build", "dist", ".agents", ".codex"} <= ignored
