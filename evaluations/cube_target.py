"""Read-only identity guard for the disposable Cube/Postgres research target."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from evaluations.cube_fixture import CUBE_IMAGE, POSTGRES_IMAGE

CONTEXT = "desktop-linux"
_DB = {"CUBEJS_DB_HOST": "postgres", "CUBEJS_DB_USER": "cube_reader",
       "CUBEJS_DB_NAME": "semantic_trial", "CUBEJS_DB_TYPE": "postgres"}
_CONTAINER = (
    '{"id":{{json .Id}},"running":{{json .State.Running}},'
    '"image":{{json .Config.Image}},"image_id":{{json .Image}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"mounts":{{json .Mounts}},"ports":{{json .NetworkSettings.Ports}},'
    '"networks":{{json .NetworkSettings.Networks}},"db_env":['
    '{{range .Config.Env}}{{if or '
    '(eq (index (split . "=") 0) "CUBEJS_DB_HOST") '
    '(eq (index (split . "=") 0) "CUBEJS_DB_USER") '
    '(eq (index (split . "=") 0) "CUBEJS_DB_NAME") '
    '(eq (index (split . "=") 0) "CUBEJS_DB_TYPE")}}{{json .}},{{end}}{{end}}null],'
    '"db_url_present":[{{range .Config.Env}}{{if eq (index (split . "=") 0) '
    '"CUBEJS_DB_URL"}}true,{{end}}{{end}}false]}'
)
_NETWORK = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"project":{{json (index .Labels "com.docker.compose.project")}},'
    '"network":{{json (index .Labels "com.docker.compose.network")}}}'
)


def _read(docker, *arguments):
    try:
        return subprocess.run(
            [str(docker), "--context", CONTEXT, *arguments],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        # Do not include captured output or configuration values in exceptions.
        raise ValueError("Docker target identity could not be read") from None


def _inspect(docker, *arguments):
    try:
        return json.loads(_read(docker, *arguments))
    except (TypeError, json.JSONDecodeError):
        raise ValueError("Docker returned invalid target identity JSON") from None


def verify_target(docker: Path, fixture: Path, project: str) -> dict:
    """Return a filtered verified identity; never starts services or executes SQL.

    Docker projects with identical seed data remain distinct targets. Mounts,
    labels, image references, network IDs and host-port ownership must all agree.
    Credential environment values are never requested, returned or printed.
    """
    if not isinstance(project, str) or not re.fullmatch(r"sw-cube-[a-z0-9][a-z0-9_-]{0,55}", project):
        raise ValueError("An explicit disposable sw-cube- project is required")
    fixture = Path(fixture).resolve(strict=True)
    info = json.loads((fixture / "fixture.json").read_text())
    port = info.get("port")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Fixture must declare an unprivileged Cube port")
    expected_mounts = {
        "postgres": {"/docker-entrypoint-initdb.d/seed.sql": fixture / "seed.sql"},
        "cube": {"/cube/conf/model": fixture / "model", "/cube/conf/cube.js": fixture / "cube.js"},
    }
    if not all(path.exists() for mounts in expected_mounts.values() for path in mounts.values()):
        raise ValueError("Fixture source files are missing")
    endpoint = _inspect(docker, "context", "inspect", CONTEXT, "--format", "{{json .Endpoints.docker.Host}}")
    if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
        raise ValueError("The research Docker context must use a local Unix socket")
    ids = _read(docker, "ps", "--all", "--no-trunc", "--filter",
                "label=com.docker.compose.project=" + project, "--format", "{{.ID}}").split()
    if len(set(ids)) != 2 or len(ids) != 2 or any(not re.fullmatch(r"[0-9a-f]{64}", cid) for cid in ids):
        raise ValueError("Expected exactly two Compose service containers")
    services = {}
    for cid in ids:
        item = _inspect(docker, "inspect", "--format", _CONTAINER, cid)
        service = item.get("service")
        if (item.get("id") != cid or item.get("project") != project
                or service not in expected_mounts or service in services or item.get("running") is not True):
            raise ValueError("Docker service identity, project or running state does not match")
        expected_image = CUBE_IMAGE if service == "cube" else POSTGRES_IMAGE
        if (item.get("image") != expected_image
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("image_id", "")))):
            raise ValueError("Docker service does not use its pinned image configuration")
        mounts = item.get("mounts", [])
        binds = [mount for mount in mounts if mount.get("Type") == "bind"]
        if len(binds) != len(expected_mounts[service]):
            raise ValueError("Unexpected fixture bind mounts")
        for destination, source in expected_mounts[service].items():
            matches = [mount for mount in mounts if mount.get("Destination") == destination]
            if (len(matches) != 1 or matches[0].get("Type") != "bind"
                    or matches[0].get("RW") is not False or matches[0].get("Source") != str(source)):
                raise ValueError("Docker fixture mount does not match the exact source and read-only target")
        services[service] = item
    network_name = project + "_default"
    network = _inspect(docker, "network", "inspect", network_name, "--format", _NETWORK)
    if (network.get("name") != network_name or network.get("project") != project
            or network.get("network") != "default"
            or not re.fullmatch(r"[0-9a-f]{64}", str(network.get("id", "")))):
        raise ValueError("Docker default network is not owned by the selected project")
    for item in services.values():
        networks = item.get("networks", {})
        if set(networks) != {network_name} or networks[network_name].get("NetworkID") != network["id"]:
            raise ValueError("Docker services do not share the exact project default network")
    if "postgres" not in (services["postgres"]["networks"][network_name].get("Aliases") or []):
        raise ValueError("The database service is missing its expected network alias")
    cube = services["cube"]
    pairs = [entry.split("=", 1) for entry in cube.get("db_env", []) if entry is not None]
    if len(pairs) != len(_DB) or dict(pairs) != _DB or any(cube.get("db_url_present", [])):
        raise ValueError("Cube database connection configuration does not match the research reader")
    published = {key: value for key, value in (cube.get("ports") or {}).items() if value}
    if published != {"4000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}:
        raise ValueError("Cube host-port mapping does not match the loopback fixture endpoint")
    if any((services["postgres"].get("ports") or {}).values()):
        raise ValueError("The research database must not publish a host port")
    owners = _read(docker, "ps", "--no-trunc", "--filter", f"publish={port}", "--format", "{{.ID}}").split()
    if owners != [cube["id"]]:
        raise ValueError("The fixture port is not owned exclusively by the selected Cube container")
    return {
        "context": CONTEXT, "project": project, "fixture": str(fixture), "cube_port": port,
        "network": {"id": network["id"], "name": network_name}, "db_configuration_verified": True,
        "services": {name: {"id": item["id"], "image": item["image"], "image_id": item["image_id"],
                            "mounts": [{"source": str(source), "target": destination, "read_only": True}
                                       for destination, source in expected_mounts[name].items()]}
                     for name, item in services.items()},
    }
