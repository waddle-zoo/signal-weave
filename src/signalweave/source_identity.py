"""Opaque connector identity for context dependencies, never authentication data."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


def namespace_fingerprint(value: dict) -> str:
    """Hash a connector's stable identity projection, not its credentials or rows."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def namespace_uri(url: str) -> str:
    """Normalize a service locator without userinfo, query strings or fragments."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("connector identity requires an absolute HTTP(S) URL")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    authority = host if port is None or (scheme, port) in {("http", 80), ("https", 443)} else f"{host}:{port}"
    return urlunsplit((scheme, authority, parsed.path.rstrip("/"), "", ""))
