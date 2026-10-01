"""Private, cwd-independent setup for the installed Python CLI.

This module performs no network requests and never builds a runtime. The local
configuration is an explicit overlay on the existing environment contract.
"""

from __future__ import annotations

import getpass
import json
import os
import stat
import sys
import tempfile
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import tomllib

from .config import is_obvious_placeholder


class SetupError(ValueError):
    """A setup failure whose message is safe to show without secret values."""


_SECRET_NAMES = (
    "TYPESAFE_API_KEY", "PRESET_ACCESS_TOKEN", "PRESET_API_TOKEN_NAME",
    "PRESET_API_TOKEN_SECRET", "SIGNALWEAVE_API_TOKEN", "PUSH_WEBHOOK_TOKEN",
)
_STORE_PATHS = {
    "SIGNALWEAVE_STORE_PATH": "signalweave.db",
    "INSIGHT_CARD_STORE": "insight-cards.json",
    "METRIC_QUERY_CARD_STORE": "metric-query-cards.json",
    "DECISION_RECEIPT_STORE": "decision-receipts.json",
    "DECISION_FEEDBACK_STORE": "decision-feedback.json",
    "CERTIFICATION_REPORT_STORE": "certification-reports.json",
}
_PATH_NAMES = {
    *_STORE_PATHS, "TRINO_CATALOG_FILE", "SIGNALWEAVE_MCP_SOURCES_FILE",
    *(f"{n}_FILE" for n in _SECRET_NAMES),
}
_ENV_NAMES = {
    *_PATH_NAMES, *_SECRET_NAMES,
    "TYPESAFE_MODE", "SIGNALWEAVE_STORE_BACKEND", "SIGNALWEAVE_TENANT_ID",
    "TYPESAFE_TIMEOUT_SECONDS", "TYPESAFE_MAX_RETRIES", "TYPESAFE_RETRY_BACKOFF_SECONDS",
    "SIGNALWEAVE_ALLOW_EMPTY_SOURCES",
    "SIGNALWEAVE_PRINCIPAL_ID", "SIGNALWEAVE_MAX_JEV_PAYLOAD_BYTES",
    "SIGNALWEAVE_MAX_SNAPSHOT_BYTES", "SUPERSET_URL", "SUPERSET_USERNAME",
    "SUPERSET_PASSWORD", "SUPERSET_TENANT_ID", "TRINO_URL", "TRINO_USER",
    "TRINO_CATALOG", "TRINO_SCHEMA", "TRINO_MAX_ROWS", "PRESET_URL",
    "PRESET_WORKSPACE", "PRESET_CONNECTION_ID", "PRESET_TENANT_ID",
    "PRESET_DATA_MODE", "PRESET_ALLOW_LIVE_QUERIES", "PRESET_ALLOW_REFRESH",
    "PRESET_MAX_RESULT_ROWS", "PRESET_MAX_SNAPSHOT_BYTES", "PRESET_API_BASE_URL",
    "PRESET_RETAIN_RAW_RESULTS", "PRESET_RETENTION_HOURS", "SIGNALWEAVE_AUTH_MODE",
    "SIGNALWEAVE_ALLOW_INSECURE_HTTP", "SIGNALWEAVE_ALLOW_INSECURE_OIDC",
    "SIGNALWEAVE_OIDC_ISSUER_URL", "SIGNALWEAVE_OIDC_AUDIENCE",
    "SIGNALWEAVE_OIDC_TENANT_CLAIM", "SIGNALWEAVE_OIDC_REQUIRED_SCOPES",
    "SIGNALWEAVE_OIDC_JWKS_URL", "SIGNALWEAVE_OIDC_ALGORITHMS",
    "SIGNALWEAVE_OIDC_JWKS_TTL_SECONDS", "SIGNALWEAVE_OIDC_PRINCIPAL_CLAIM",
    "SIGNALWEAVE_OIDC_SCOPE_CLAIM",
    "SIGNALWEAVE_RESOURCE_SERVER_URL", "MCP_HOST", "MCP_PORT",
}


def resolve_home(home: str | Path | None = None) -> Path:
    value = home if home is not None else os.environ.get("SIGNALWEAVE_HOME")
    if value is not None and not str(value).strip():
        raise SetupError("SignalWeave home must not be empty")
    path = Path(value).expanduser() if value is not None else Path.home() / ".signalweave"
    # Do not resolve symlinks: the private-path checks must see them.
    return Path(os.path.abspath(path))


def _private_path(path: Path, *, directory: bool = False) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise SetupError("A required local file or directory is missing or unreadable") from None
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_type:
        raise SetupError("Local files and directories must not be symlinks or special files")
    if os.name == "posix":
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            mode = "0700" if directory else "0600"
            raise SetupError(f"Local files must be owned by the current user; use chmod {mode}")


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_path(path, directory=True)


def _read_private(path: Path) -> str:
    _private_path(path)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise SetupError("Could not read a local UTF-8 file") from None


def _write_new(path: Path, content: str) -> None:
    """Publish a complete 0600 file without replacing an existing destination."""
    fd, temporary = tempfile.mkstemp(prefix=".setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        os.unlink(temporary)


def _validate_key(value: str) -> str:
    value = value.strip()
    if not value or any(character.isspace() for character in value) or "\x00" in value:
        raise SetupError("The TypeSafe key must be one non-empty token")
    if is_obvious_placeholder(value):
        raise SetupError("Replace the example TypeSafe key with a real key")
    return value


def _prompt_key() -> str:
    # getpass otherwise falls back to echoed stdin when no terminal is present.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return _validate_key(getpass.getpass("TypeSafe API key (hidden): "))
        except (getpass.GetPassWarning, EOFError):
            raise SetupError("A secure terminal is required; use --key-file for unattended setup") from None


def initialize(home: str | Path | None = None, *, key_file: str | Path | None = None) -> Path:
    """Create private local files; repeating init never replaces configuration or keys."""
    root = resolve_home(home)
    _private_directory(root)
    config = root / "config.toml"
    key_path = root / "typesafe.key"
    if config.exists() or config.is_symlink():
        read_config(root)
        if key_file is not None and (
            _validate_key(_read_private(Path(key_file).expanduser())) !=
            _validate_key(_read_private(key_path))
        ):
            raise SetupError("Already initialized; --key-file cannot replace an existing key")
        return root
    _private_directory(root / "state")
    if key_path.exists() or key_path.is_symlink():
        existing = _validate_key(_read_private(key_path))
        if key_file is not None and _validate_key(_read_private(Path(key_file).expanduser())) != existing:
            raise SetupError("An existing local key will not be replaced")
    else:
        key = _validate_key(_read_private(Path(key_file).expanduser())) if key_file else _prompt_key()
        _write_new(key_path, key + "\n")
    _write_new(config, '''# SignalWeave local setup. All relative paths are relative to this home.
# Existing process environment settings override this file.
version = 1

[environment]
TYPESAFE_MODE = "jev"
TYPESAFE_API_KEY_FILE = "typesafe.key"
SIGNALWEAVE_STORE_BACKEND = "sqlite"
SIGNALWEAVE_STORE_PATH = "state/signalweave.db"
SIGNALWEAVE_ALLOW_EMPTY_SOURCES = "1"

# Configure an existing source before serving. For example:
# SUPERSET_URL = "http://127.0.0.1:8088"
# SUPERSET_USERNAME = "your-username"
# SUPERSET_PASSWORD = "your-password"
# For Preset or an approved Trino catalog, see docs/local-install.md.
''')
    return root


def read_config(home: str | Path | None = None) -> tuple[Path, dict[str, str]]:
    root = resolve_home(home)
    _private_path(root, directory=True)
    _private_path(root / "state", directory=True)
    try:
        config = tomllib.loads(_read_private(root / "config.toml"))
    except tomllib.TOMLDecodeError:
        raise SetupError("Invalid config.toml; expected TOML with version = 1 and [environment]") from None
    if type(config.get("version")) is not int or config["version"] != 1:
        raise SetupError("Unsupported local config version; expected version = 1")
    environment = config.get("environment")
    if set(config) != {"version", "environment"} or not isinstance(environment, dict):
        raise SetupError("Local config must contain only version and [environment]")
    for name, value in environment.items():
        if name not in _ENV_NAMES or not isinstance(value, str) or "\x00" in value:
            raise SetupError("Local config contains an unsupported setting or a non-string value")
    return root, environment


@contextmanager
def local_environment(home: str | Path | None = None) -> Iterator[Path]:
    """Apply local defaults for the server lifetime, restoring the caller afterward."""
    root, configured = read_config(home)
    values = {"SIGNALWEAVE_STORE_BACKEND": "sqlite", **configured}
    for name, filename in _STORE_PATHS.items():
        values.setdefault(name, str(root / "state" / filename))
    # A deployment value OR file wins over the entire local credential pair.
    for name in _SECRET_NAMES:
        if name in os.environ or f"{name}_FILE" in os.environ:
            values.pop(name, None)
            values.pop(f"{name}_FILE", None)
    values.update({name: value for name, value in os.environ.items() if name in _ENV_NAMES})
    for name in _STORE_PATHS:
        if not values[name].strip():
            raise SetupError(f"{name} must be a non-empty durable storage path")
    for name in _PATH_NAMES:
        if values.get(name):
            path = Path(values[name]).expanduser()
            values[name] = str(root / path) if not path.is_absolute() else str(path)
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield root
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def agent_config(home: str | Path | None, agent: str) -> str:
    """Return copyable stdio configuration, without editing the agent's files."""
    root = resolve_home(home)
    # sys.executable retains the venv path; resolving its symlink would lose it.
    command = os.path.abspath(sys.executable)
    args = ([] if getattr(sys, "frozen", False) else ["-m", "signalweave.cli"]) + [
        "serve", "--transport", "stdio", "--home", str(root),
    ]
    if agent == "codex":
        return (
            "[mcp_servers.signalweave]\n"
            f"command = {json.dumps(command, ensure_ascii=False)}\n"
            f"args = {json.dumps(args, ensure_ascii=False)}\n"
        )
    if agent == "claude":
        return json.dumps({"mcpServers": {"signalweave": {
            "type": "stdio", "command": command, "args": args,
        }}}, indent=2, ensure_ascii=False) + "\n"
    raise SetupError("Unknown agent; choose codex or claude")


def _valid_source_url(name: str) -> None:
    value = os.environ[name]
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"} and parsed.hostname and
            parsed.port != 0 and not parsed.username and not parsed.password and
            not parsed.query and not parsed.fragment and not is_obvious_placeholder(value) and
            not any(ord(character) <= 32 for character in value)
        )
    except ValueError:
        valid = False
    if not valid:
        raise SetupError(f"{name} must be an http(s) URL without credentials, query, or fragment")


def validate_key_configuration() -> str:
    """Validate only local key availability/permissions, never its live acceptance."""
    key_file = os.getenv("TYPESAFE_API_KEY_FILE", "").strip()
    key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if key and key_file:
        raise SetupError("Set only one of TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
    if key_file:
        _validate_key(_read_private(Path(key_file)))
        return "readable private file"
    if key:
        _validate_key(key)
        return "environment"
    raise SetupError("TypeSafe key is missing; configure TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")


def doctor() -> tuple[bool, list[str]]:
    """Check the effective environment offline, returning only fixed/safe messages."""
    messages = ["Offline configuration check only; no provider or Jev requests were made."]
    errors: list[str] = []
    try:
        source = validate_key_configuration()
        messages.append(f"TypeSafe key: {source} (acceptance not tested).")
    except SetupError as error:
        errors.append(str(error))
    if os.getenv("TYPESAFE_MODE", "jev").lower() != "jev":
        errors.append("TYPESAFE_MODE must be jev")
    tenant = os.getenv("SIGNALWEAVE_TENANT_ID", "").strip()
    principal = os.getenv("SIGNALWEAVE_PRINCIPAL_ID", "").strip()
    if bool(tenant) != bool(principal):
        errors.append("SIGNALWEAVE_TENANT_ID and SIGNALWEAVE_PRINCIPAL_ID must be configured together")
    sources = 0
    if os.getenv("SUPERSET_URL"):
        sources += 1
        try:
            _valid_source_url("SUPERSET_URL")
            username = os.getenv("SUPERSET_USERNAME", "")
            password = os.getenv("SUPERSET_PASSWORD", "")
            if bool(username) != bool(password) or any(
                is_obvious_placeholder(value) for value in (username, password)
            ):
                raise SetupError("Configure SUPERSET_USERNAME and SUPERSET_PASSWORD together with real values")
            if tenant and os.getenv("SUPERSET_TENANT_ID", tenant).strip() != tenant:
                raise SetupError("SUPERSET_TENANT_ID must match SIGNALWEAVE_TENANT_ID")
            messages.append("Superset: configuration present (connectivity and access not tested).")
            if not username:
                messages.append("Superset: no login credentials configured; anonymous access assumed.")
        except SetupError as error:
            errors.append(str(error))
    if os.getenv("PRESET_URL"):
        sources += 1
        from .runtime import validate_preset_environment

        try:
            validate_preset_environment()
            messages.append("Preset: configuration valid (connectivity and access not tested).")
        except (OSError, ValueError, RuntimeError):
            # Runtime/Pydantic errors can contain raw values, URLs, or file contents.
            errors.append("Preset configuration invalid; check credential mode/files, HTTPS origin, tenant/principal, and data policy")
    if os.getenv("TRINO_URL") or os.getenv("TRINO_CATALOG_FILE"):
        sources += 1
        try:
            if not os.getenv("TRINO_URL") or not os.getenv("TRINO_CATALOG_FILE"):
                raise SetupError("Trino requires TRINO_URL and TRINO_CATALOG_FILE together")
            _valid_source_url("TRINO_URL")
            from .models import ResourceDescriptor

            payload = json.loads(Path(os.environ["TRINO_CATALOG_FILE"]).read_text())
            if not isinstance(payload, list) or not payload:
                raise ValueError("empty catalog")
            resources = [ResourceDescriptor.model_validate(item) for item in payload]
            if any(resource.adapter != "trino" for resource in resources):
                raise ValueError("wrong adapter")
            if int(os.getenv("TRINO_MAX_ROWS", "1000")) < 1 or not os.getenv("TRINO_USER", "signal-weave").strip():
                raise ValueError("invalid Trino bounds/user")
            messages.append("Trino: approved catalog parses (connectivity and access not tested).")
        except SetupError as error:
            errors.append(str(error))
        except (OSError, ValueError):
            errors.append("Trino configuration invalid; check catalog descriptors, TRINO_USER, and TRINO_MAX_ROWS")
    if os.getenv("SIGNALWEAVE_MCP_SOURCES_FILE"):
        from .mcp_source import build_mcp_sources

        try:
            adapters = build_mcp_sources(os.environ["SIGNALWEAVE_MCP_SOURCES_FILE"])
            sources += len(adapters)
            messages.append("MCP sources: manifest schema valid; referenced credentials and live access remain unverified.")
        except (OSError, ValueError):
            errors.append("SIGNALWEAVE_MCP_SOURCES_FILE must name a valid MCP source manifest")
    if not sources:
        if os.getenv("SIGNALWEAVE_ALLOW_EMPTY_SOURCES") == "1":
            messages.append("No source configured: onboarding only; evaluation requires approved sources.")
        else:
            errors.append("No source configured; set SUPERSET_URL, PRESET_URL, TRINO_URL with TRINO_CATALOG_FILE, or SIGNALWEAVE_MCP_SOURCES_FILE")
    if os.getenv("SIGNALWEAVE_STORE_BACKEND", "sqlite").lower() not in {"sqlite", "json"}:
        errors.append("SIGNALWEAVE_STORE_BACKEND must be sqlite or json")
    messages.extend(f"ERROR: {error}" for error in errors)
    if not errors:
        messages.append("Offline checks passed. Live credentials, source access, and Jev behavior remain unverified.")
    return not errors, messages
