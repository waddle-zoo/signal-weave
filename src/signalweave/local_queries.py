"""Install reviewed query artifacts without another runtime or credential store."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .local_setup import (
    SetupError,
    _config_text,
    _private_path,
    _publish_config,
    _write_new,
    read_config,
)
from .query_source import load_query_catalog


def import_queries(home, source, file, *, yes=False, allow_live_queries=False):
    if source not in {"superset", "preset"}:
        raise SetupError("Choose a configured Superset or Preset source")
    root, config = read_config(home)
    prefix = source.upper()
    if not config.get(prefix + "_URL"):
        raise SetupError(f"Connect {source} first with `signalweave connections add`")
    if allow_live_queries and source != "preset":
        raise SetupError("--allow-live-queries applies only to Preset")
    path = Path(file).expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise SetupError("Choose an ordinary reviewed query JSON file")
    try:
        catalog = load_query_catalog(path)
    except (OSError, ValueError):
        raise SetupError("Invalid query catalog: use `signalweave queries schema` for the exact format") from None
    tenant = config.get(prefix + "_TENANT_ID") or config.get("SIGNALWEAVE_TENANT_ID")
    if not tenant or any(q.contract.tenant_id not in {"default", tenant} for q in catalog.queries):
        raise SetupError("Query definitions must match the configured source tenant")
    reviewed_url = config[prefix + "_URL"]
    reviewed_config = dict(config)
    print(f"Reviewed queries for {source}: {reviewed_url}")
    for query in catalog.queries:
        print(f"  {query.title}: database {query.database_id}; {query.resource}")
        print(f"    {query.definition}")
    if allow_live_queries:
        print("This also enables live reads and refresh on the configured Preset connection.")
    if not yes:
        try:
            confirmation = input("Trust these fixed queries under this source's read credentials? [y/N]: ")
        except EOFError:
            raise SetupError("Import cancelled; review the file and use --yes for non-interactive consent") from None
        if confirmation.strip().lower() not in {"y", "yes"}:
            raise SetupError("Import cancelled; configuration was not changed")
    lock = root / ".setup.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SetupError("Setup is already running; no query configuration changed") from None
    os.close(fd)
    try:
        _, config = read_config(root)
        if config != reviewed_config:
            raise SetupError("Connection changed during review; inspect it before importing")
        # Immutable files avoid changing a running process's reviewed catalog.
        text = json.dumps(catalog.model_dump(mode="json", by_alias=True), sort_keys=True, indent=2) + "\n"
        digest = hashlib.sha256(text.encode()).hexdigest()
        target = root / f"queries-{source}-{digest}.json"
        if target.exists():
            _private_path(target)
            if target.read_text() != text:
                raise SetupError("Existing versioned query artifact differs; configuration was not changed")
        else:
            _write_new(target, text)
        config[prefix + "_QUERY_SOURCES_FILE"] = target.name
        if allow_live_queries:
            config.update(PRESET_DATA_MODE="live_query", PRESET_ALLOW_LIVE_QUERIES="1", PRESET_ALLOW_REFRESH="1")
        _publish_config(root / "config.toml", _config_text(config))
    finally:
        lock.unlink(missing_ok=True)
    return catalog


def list_queries(home):
    root, config = read_config(home)
    result = []
    for source in ("superset", "preset"):
        selected = config.get(source.upper() + "_QUERY_SOURCES_FILE")
        if selected:
            path = Path(selected)
            catalog = load_query_catalog(path if path.is_absolute() else root/path)
            result.extend({"source": source, "title": query.title, "resource": query.resource}
                          for query in catalog.queries)
    return result
