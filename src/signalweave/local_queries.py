"""Install reviewed query artifacts without another runtime or credential store."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pydantic import ValidationError

from .local_setup import (
    SetupError,
    _config_text,
    _private_path,
    _publish_config,
    _write_new,
    read_config,
)
from .query_source import MAX_CATALOG_BYTES, QueryCatalog, load_query_catalog


def _active_catalog(root, config, prefix):
    selected = config.get(prefix + "_QUERY_SOURCES_FILE")
    if not selected:
        return None
    path = Path(selected)
    try:
        return load_query_catalog(path if path.is_absolute() else root/path)
    except (OSError, ValueError):
        raise SetupError("Existing query catalog is invalid; inspect it before importing") from None


def _merge_catalog(existing, incoming):
    # Replacements keep their position; new keys append in incoming order.
    queries = {query.key: query for query in existing.queries} if existing else {}
    queries.update((query.key, query) for query in incoming.queries)
    try:
        merged = QueryCatalog(version=2, queries=list(queries.values()))
    except ValidationError:
        raise SetupError("Merged query catalog must contain at most 1000 queries") from None
    text = json.dumps(merged.model_dump(mode="json", by_alias=True), sort_keys=True, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_CATALOG_BYTES:
        raise SetupError("Merged query catalog exceeds its 2 MB serialized byte limit")
    return merged, text


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
    except ValidationError as error:
        fields = list(dict.fromkeys(".".join(map(str, item["loc"]))
                                   for item in error.errors(include_input=False, include_context=False)))[:8]
        raise SetupError("Invalid query catalog fields " + json.dumps(fields) +
                         "; use `signalweave queries schema` for the current format") from None
    except (OSError, ValueError):
        raise SetupError("Invalid query catalog: use `signalweave queries schema` for the exact format") from None
    tenant = config.get(prefix + "_TENANT_ID") or config.get("SIGNALWEAVE_TENANT_ID")
    if not tenant:
        raise SetupError("Query sources require the connection's configured tenant; finish `signalweave setup` first")
    reviewed_url = config[prefix + "_URL"]
    reviewed_config = dict(config)
    existing = _active_catalog(root, config, prefix)
    merged, text = _merge_catalog(existing, catalog)
    previous = {query.key: query for query in existing.queries} if existing else {}
    retained = len(previous.keys() - {query.key for query in catalog.queries})
    print(f"Reviewed queries for {source}: {reviewed_url}")
    for query in catalog.queries:
        print(f"  {query.title}: database {query.database_id}; {query.resource}")
        print(f"    {query.definition}")
        if query.key in previous and query.resource != previous[query.key].resource:
            print(f"    Changed definition for {query.key}: new source identity; review affected cards before continuing.")
    print(f"{len(catalog.queries)} incoming; {len(merged.queries)} active after import; {retained} unmentioned queries retained.")
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
        if _active_catalog(root, config, prefix) != existing:
            raise SetupError("Query catalog changed during review; inspect it before importing")
        # Immutable files avoid changing a running process's reviewed catalog.
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
    return merged


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
