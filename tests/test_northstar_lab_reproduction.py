from __future__ import annotations

import csv
import hashlib
import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = REPO_ROOT / "examples" / "northstar-enterprise-lab"
HASH_MANIFEST = LAB_ROOT / "docs" / "seeded-input-sha256.json"


@pytest.fixture(scope="module")
def generated_init(tmp_path_factory: pytest.TempPathFactory) -> Path:
    generated_root = tmp_path_factory.mktemp("northstar-reproduction")
    scripts_dir = generated_root / "scripts"
    (generated_root / "docs").mkdir()
    (generated_root / "warehouse" / "init").mkdir(parents=True)
    scripts_dir.mkdir()
    generator = scripts_dir / "generate_enterprise.py"
    shutil.copy2(LAB_ROOT / "scripts" / "generate_enterprise.py", generator)

    env = os.environ.copy()
    env["NORTHSTAR_SEED"] = "90219"
    subprocess.run(
        [sys.executable, str(generator)],
        cwd=generated_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return generated_root / "warehouse" / "init"


def test_generator_matches_all_original_seeded_csv_hashes(generated_init: Path) -> None:
    expected = json.loads(HASH_MANIFEST.read_text(encoding="utf-8"))["files"]
    generated = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(generated_init.glob("*.csv"))
    }
    generated_manifest = generated_init.parents[1] / "docs" / "generated_manifest.json"

    assert len(expected) == 16
    assert generated == expected
    assert json.loads(generated_manifest.read_text(encoding="utf-8")) == json.loads(
        (LAB_ROOT / "docs" / "generated_manifest.json").read_text(encoding="utf-8")
    )


def test_generated_delivery_select_facts_match_original_seed(generated_init: Path) -> None:
    csv_path = generated_init / "fct_delivery.csv"
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        columns = reader.fieldnames
        assert columns is not None
        records = list(reader)

    database = sqlite3.connect(":memory:")
    quoted_columns = ", ".join(f'"{column}" TEXT' for column in columns)
    database.execute(f"CREATE TABLE delivery ({quoted_columns})")
    placeholders = ", ".join("?" for _ in columns)
    database.executemany(
        f"INSERT INTO delivery VALUES ({placeholders})",
        [tuple(record[column] for column in columns) for record in records],
    )

    overall = database.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN lower(late_flag) = 'true' THEN 1 ELSE 0 END),
               SUM(CASE WHEN lower(damage_flag) = 'true' THEN 1 ELSE 0 END)
        FROM delivery
        """
    ).fetchone()
    august = database.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN lower(late_flag) = 'true' THEN 1 ELSE 0 END),
               SUM(CASE WHEN lower(damage_flag) = 'true' THEN 1 ELSE 0 END)
        FROM delivery
        WHERE promised_date >= '2026-08-01' AND promised_date < '2026-09-01'
        """
    ).fetchone()

    assert overall == (70_000, 30_331, 579)
    assert august == (2_273, 970, 28)


def test_compose_is_local_project_scoped_and_secret_free() -> None:
    compose = (LAB_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (LAB_ROOT / "Dockerfile").read_text(encoding="utf-8")
    bootstrap = (LAB_ROOT / "superset" / "bootstrap.py").read_text(encoding="utf-8")

    assert "name: northstar-enterprise-lab" in compose
    assert '"127.0.0.1:${NORTHSTAR_SUPERSET_PORT:-18090}:8088"' in compose
    assert "northstar-bi_net" not in compose
    assert "subnet:" not in compose
    assert "./agents" not in compose
    assert "northstar-bi_" not in compose
    assert "${NORTHSTAR_WAREHOUSE_PASSWORD:?" in compose
    assert "${NORTHSTAR_SUPERSET_DB_PASSWORD:?" in compose
    assert "${NORTHSTAR_SUPERSET_ADMIN_PASSWORD:?" in compose
    assert "${NORTHSTAR_SUPERSET_SECRET_KEY:?" in compose
    init_service = compose.split("  superset-init:\n", 1)[1].split("\n  superset:\n", 1)[0]
    seed_service = compose.split("  superset-seed:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    assert "    healthcheck:\n      disable: true" in init_service
    assert "    healthcheck:\n      disable: true" in seed_service
    assert "northstar-local-only-change-me" not in compose
    assert "signalweave-northstar-lab:local" in compose
    assert "northstar-superset:local" not in compose
    assert "enterprise:enterprise@" not in (LAB_ROOT / "superset" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "apache/superset:4.1.3@sha256:31d965435b462361d2b8207595eff28f54492778d0afd53768da5e763cc16ce7" in dockerfile
    assert "apache/superset:latest" not in dockerfile
    assert "quote_plus(os.environ['NORTHSTAR_WAREHOUSE_PASSWORD'])" in bootstrap


def test_superset_config_url_encodes_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERSET_SECRET_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("SUPERSET_DB_PASSWORD", "p@:/ +%")

    config = runpy.run_path(str(LAB_ROOT / "superset" / "superset_config.py"))

    assert config["SQLALCHEMY_DATABASE_URI"] == (
        "postgresql+psycopg2://superset:p%40%3A%2F+%2B%25@superset-db:5432/superset"
    )


def test_seed_reauthenticates_once_after_expired_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    seeder = runpy.run_path(str(LAB_ROOT / "superset" / "bootstrap.py"))
    session = seeder["SESSION"]
    session.headers["Authorization"] = "Bearer expired-token"
    calls: list[tuple[str, str]] = []
    protected_reads = 0

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload
            self.content = json.dumps(payload).encode()
            self.text = json.dumps(payload)

        def json(self) -> dict[str, object]:
            return self._payload

    def request(method: str, url: str, **_kwargs: object) -> Response:
        nonlocal protected_reads
        calls.append((method, url))
        if url.endswith("/api/v1/security/login"):
            return Response(200, {"access_token": "fresh-token"})
        if url.endswith("/api/v1/security/csrf_token/"):
            return Response(200, {"result": "fresh-csrf"})
        protected_reads += 1
        if protected_reads == 1:
            return Response(401, {"msg": "Token has expired"})
        return Response(200, {"result": "ok"})

    monkeypatch.setattr(session, "request", request)

    result = seeder["api"]("GET", "/api/v1/test")

    assert result == {"result": "ok"}
    assert [url.rsplit("/api/v1", 1)[-1] for _, url in calls] == [
        "/test",
        "/security/login",
        "/security/csrf_token/",
        "/test",
    ]
    assert session.headers["Authorization"] == "Bearer fresh-token"
    assert session.headers["X-CSRFToken"] == "fresh-csrf"
