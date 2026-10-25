import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from evaluations import cube_target
from evaluations.cube_fixture import CUBE_IMAGE, POSTGRES_IMAGE

PROJECT = "sw-cube-20261025-retail-v2"
PG_ID, CUBE_ID, NETWORK_ID = "a" * 64, "b" * 64, "c" * 64


def fixture_files(root):
    root.mkdir()
    (root / "model").mkdir()
    (root / "fixture.json").write_text(json.dumps({"port": 4407}))
    (root / "seed.sql").write_text("Identical synthetic seed\n")
    (root / "cube.js").write_text("module.exports = {};\n")
    return root


def target(fixture, project=PROJECT):
    def mount(source, destination):
        return {"Type": "bind", "Source": str(source), "Destination": destination, "RW": False}

    network_name = project + "_default"
    common = {"running": True, "project": project, "db_url_present": [False]}
    pg = {**copy.deepcopy(common), "id": PG_ID, "service": "postgres", "image": POSTGRES_IMAGE,
          "image_id": "sha256:" + "1" * 64, "db_env": [None], "ports": {"5432/tcp": None},
          "mounts": [mount(fixture / "seed.sql", "/docker-entrypoint-initdb.d/seed.sql")],
          "networks": {network_name: {"NetworkID": NETWORK_ID, "Aliases": ["postgres"]}}}
    cube = {**copy.deepcopy(common), "id": CUBE_ID, "service": "cube", "image": CUBE_IMAGE,
            "image_id": "sha256:" + "2" * 64,
            "db_env": [f"{key}={value}" for key, value in cube_target._DB.items()] + [None],
            "ports": {"4000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4407"}]},
            "mounts": [mount(fixture / "model", "/cube/conf/model"),
                       mount(fixture / "cube.js", "/cube/conf/cube.js")],
            "networks": {network_name: {"NetworkID": NETWORK_ID, "Aliases": ["cube"]}}}
    return {"containers": {PG_ID: pg, CUBE_ID: cube}, "ids": [PG_ID, CUBE_ID], "owners": [CUBE_ID],
            "network": {"id": NETWORK_ID, "name": network_name, "project": project, "network": "default"}}


def docker_reader(monkeypatch, state):
    calls = []

    def run(command, **options):
        calls.append(command)
        assert command[:3] == ["docker", "--context", "desktop-linux"]
        assert options == {"check": True, "capture_output": True, "text": True, "timeout": 30}
        args = command[3:]
        if args[:2] == ["context", "inspect"]:
            stdout = json.dumps("unix:///private/docker.sock")
        elif args[0] == "ps":
            stdout = "\n".join(state["owners"] if "publish=4407" in args else state["ids"])
        elif args[0] == "inspect":
            assert args[2] == cube_target._CONTAINER
            stdout = json.dumps(state["containers"][args[-1]])
        else:
            assert args[:2] == ["network", "inspect"]
            assert args[-1] == cube_target._NETWORK
            stdout = json.dumps(state["network"])
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(cube_target.subprocess, "run", run)
    return calls


def test_verified_identity_is_filtered_and_uses_only_read_only_docker_commands(tmp_path, monkeypatch, capsys):
    fixture = fixture_files(tmp_path / "fixture")
    state = target(fixture)
    state["containers"][CUBE_ID]["unrequested_secret"] = "never-return-this-private-value"
    calls = docker_reader(monkeypatch, state)
    identity = cube_target.verify_target("docker", fixture, PROJECT)
    assert identity["project"] == PROJECT
    assert identity["fixture"] == str(fixture)
    assert identity["cube_port"] == 4407
    assert identity["network"] == {"id": NETWORK_ID, "name": PROJECT + "_default"}
    assert identity["db_configuration_verified"] is True
    assert identity["services"]["cube"]["id"] == CUBE_ID
    assert identity["services"]["postgres"]["image"] == POSTGRES_IMAGE
    serialized = json.dumps(identity)
    assert "never-return-this-private-value" not in serialized
    assert "db_env" not in serialized and "CUBEJS_DB_" not in serialized
    assert "CUBEJS_DB_PASS" not in cube_target._CONTAINER
    assert all(command[3] in {"context", "ps", "inspect", "network"} for command in calls)
    assert not capsys.readouterr().out


def test_another_project_with_identical_seed_cannot_match_the_requested_fixture(tmp_path, monkeypatch):
    expected = fixture_files(tmp_path / "expected")
    other = fixture_files(tmp_path / "other")
    assert (expected / "seed.sql").read_bytes() == (other / "seed.sql").read_bytes()
    wrong_project = "sw-cube-other-identical-seed"
    docker_reader(monkeypatch, target(other, wrong_project))
    with pytest.raises(ValueError, match="mount"):
        cube_target.verify_target("docker", expected, wrong_project)


@pytest.mark.parametrize("case", [
    "wrong_project", "wrong_service", "not_running", "wrong_id", "duplicate_id", "missing_service",
    "wrong_image", "mutable_image", "missing_image_id", "wrong_model_mount", "wrong_cube_config_mount",
    "wrong_seed_mount", "writable_mount", "extra_mount", "wrong_host_port", "public_host_ip",
    "extra_cube_port", "published_postgres", "other_port_owner", "two_port_owners",
    "wrong_network_project", "wrong_network_name", "wrong_network_role", "wrong_network_id",
    "additional_network", "missing_database_alias", "wrong_db_host", "wrong_db_user", "wrong_db_name",
    "duplicate_db_setting", "db_url_override",
])
def test_mismatched_target_fails_closed_without_disclosing_configuration(tmp_path, monkeypatch, capsys, case):
    fixture = fixture_files(tmp_path / "fixture")
    state = target(fixture)
    cube, pg = state["containers"][CUBE_ID], state["containers"][PG_ID]
    network_name = PROJECT + "_default"
    if case == "wrong_project":
        pg["project"] = "sw-cube-other"
    elif case == "wrong_service":
        pg["service"] = "cube"
    elif case == "not_running":
        cube["running"] = False
    elif case == "wrong_id":
        cube["id"] = "d" * 64
    elif case == "duplicate_id":
        state["ids"] = [CUBE_ID, CUBE_ID]
    elif case == "missing_service":
        state["ids"] = [CUBE_ID]
    elif case in {"wrong_image", "mutable_image"}:
        cube["image"] = POSTGRES_IMAGE if case == "wrong_image" else "cubejs/cube:latest"
    elif case == "missing_image_id":
        pg.pop("image_id")
    elif case in {"wrong_model_mount", "wrong_cube_config_mount", "wrong_seed_mount", "writable_mount"}:
        mount = pg["mounts"][0] if case == "wrong_seed_mount" else cube["mounts"][1 if case == "wrong_cube_config_mount" else 0]
        if case == "writable_mount":
            mount["RW"] = True
        else:
            mount["Source"] = str(tmp_path / "another-fixture")
    elif case == "extra_mount":
        cube["mounts"].append({**cube["mounts"][0], "Destination": "/cube/conf/extra"})
    elif case in {"wrong_host_port", "public_host_ip"}:
        cube["ports"]["4000/tcp"][0]["HostPort" if case == "wrong_host_port" else "HostIp"] = "4408" if case == "wrong_host_port" else "0.0.0.0"
    elif case == "extra_cube_port":
        cube["ports"]["3000/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": "4408"}]
    elif case == "published_postgres":
        pg["ports"]["5432/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": "5432"}]
    elif case in {"other_port_owner", "two_port_owners"}:
        state["owners"] = [PG_ID] if case == "other_port_owner" else [CUBE_ID, PG_ID]
    elif case in {"wrong_network_project", "wrong_network_name", "wrong_network_role"}:
        field = {"wrong_network_project": "project", "wrong_network_name": "name", "wrong_network_role": "network"}[case]
        state["network"][field] = "other"
    elif case == "wrong_network_id":
        cube["networks"][network_name]["NetworkID"] = "d" * 64
    elif case == "additional_network":
        cube["networks"]["other_default"] = {"NetworkID": "d" * 64}
    elif case == "missing_database_alias":
        pg["networks"][network_name]["Aliases"] = []
    elif case.startswith("wrong_db_"):
        key = {"wrong_db_host": "CUBEJS_DB_HOST", "wrong_db_user": "CUBEJS_DB_USER", "wrong_db_name": "CUBEJS_DB_NAME"}[case]
        cube["db_env"] = [entry for entry in cube["db_env"] if entry is None or not entry.startswith(key + "=")]
        cube["db_env"].append(key + "=never-print-this-private-value")
    elif case == "duplicate_db_setting":
        cube["db_env"].append("CUBEJS_DB_HOST=postgres")
    else:
        cube["db_url_present"] = [True, False]
    docker_reader(monkeypatch, state)
    with pytest.raises(ValueError) as error:
        cube_target.verify_target("docker", fixture, PROJECT)
    assert "never-print-this-private-value" not in str(error.value)
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.parametrize("project", ["production", "sw-cube-", "sw-cube-../unsafe"])
def test_project_prefix_is_checked_before_any_docker_access(tmp_path, monkeypatch, project):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid project must not access Docker")

    monkeypatch.setattr(cube_target.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="sw-cube-"):
        cube_target.verify_target("docker", tmp_path, project)


def test_docker_failure_does_not_expose_captured_output(tmp_path, monkeypatch, capsys):
    fixture = fixture_files(tmp_path / "fixture")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output="private-output", stderr="private-error")

    monkeypatch.setattr(cube_target.subprocess, "run", fail)
    with pytest.raises(ValueError, match="could not be read") as error:
        cube_target.verify_target("docker", fixture, PROJECT)
    assert "private" not in str(error.value)
    assert not capsys.readouterr().out


def test_postgres_refuses_to_execute_even_read_sql_when_target_check_fails(tmp_path, monkeypatch):
    from evaluations import cube_fixture_control

    def reject(*args):
        raise ValueError("wrong target")

    def forbidden(*args, **kwargs):
        pytest.fail("No SQL command may execute before target verification")

    monkeypatch.setattr(cube_fixture_control, "verify_target", reject)
    monkeypatch.setattr(cube_fixture_control.subprocess, "run", forbidden)
    args = SimpleNamespace(docker="docker", fixture=tmp_path, project=PROJECT)
    with pytest.raises(ValueError, match="wrong target"):
        cube_fixture_control.postgres(args, "SELECT 1;")
