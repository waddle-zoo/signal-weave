"""Expose one operator-selected publication as a fixed, read-only MCP tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

MAX_PUBLICATION_BYTES = 900_000
MAX_RESPONSE_BYTES = 1_000_000
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _read_publication(path: Path) -> dict[str, Any]:
    """Read bounded JSON without following a final-component symlink; preserve it."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or opened.st_size > MAX_PUBLICATION_BYTES
            ):
                raise ValueError("file identity or size rejected")
            raw = stream.read(MAX_PUBLICATION_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
                raise ValueError("publication changed during read")
        if len(raw) > MAX_PUBLICATION_BYTES:
            raise ValueError("publication too large")
        publication = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")),
        )
        if not isinstance(publication, dict):
            raise ValueError("publication must be an object")
        json.dumps(publication, allow_nan=False)  # Also reject numeric overflow such as 1e999.
        metadata = publication.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("publication metadata is required")
        if (
            type(metadata.get("publication_schema_version")) is not int
            or metadata["publication_schema_version"] != 1
            or not isinstance(metadata.get("publication_id"), str)
            or not metadata["publication_id"].strip()
            or len(metadata["publication_id"]) > 200
            or type(metadata.get("revision")) is not int
            or metadata["revision"] < 1
            or not isinstance(metadata.get("publication_authority"), str)
            or not metadata["publication_authority"].strip()
            or not isinstance(metadata.get("source_scope"), str)
            or not metadata["source_scope"].strip()
            or not _aware_timestamp(metadata.get("published_at"))
            or not _aware_timestamp(publication.get("source_captured_at"))
        ):
            raise ValueError("publication identity, authority, scope, or timestamps are invalid")
        captured = datetime.fromisoformat(publication["source_captured_at"].replace("Z", "+00:00"))
        published = datetime.fromisoformat(metadata["published_at"].replace("Z", "+00:00"))
        if captured > published or published > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("publication timestamp order or clock bound is invalid")
        evidence = publication.setdefault("evidence", [])
        if not isinstance(evidence, list) or not isinstance(publication.get("source_key"), str):
            raise ValueError("invalid evidence envelope")
        # Preserve the supplied claims and add a transport audit fact. Metadata
        # alone is not otherwise guaranteed to survive in a decision receipt.
        evidence.append({
            "source_key": publication["source_key"], "subject_id": "publication-record",
            "statement": "Publication identity and byte hash; not verification of the analyst's claims.",
            "values": {"claim_kind": "publication_record", "publication_id": metadata["publication_id"],
                       "revision": metadata["revision"], "publication_sha256": hashlib.sha256(raw).hexdigest()},
            "origin": "source", "provenance": ["analysis-publication-reader"],
        })
        return publication
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("published analysis is unavailable or invalid") from None


def create_server(publication_file: Path) -> FastMCP:
    server = FastMCP("Published analytical evidence")

    @server.tool(structured_output=False)
    def get_published_analysis() -> CallToolResult:
        """Read the one operator-configured publication; accepts no caller inputs."""
        result = CallToolResult(content=[], structuredContent=_read_publication(publication_file))
        # The bridge consumes structuredContent; do not duplicate large reports
        # as pretty-printed text. Apply its configured wire budget too.
        encoded = json.dumps(result.model_dump(mode="json", by_alias=True), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("published analysis exceeds the response budget")
        return result

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication_file", type=Path, help="operator-configured JSON file")
    args = parser.parse_args()
    create_server(args.publication_file).run(transport="stdio")


if __name__ == "__main__":
    main()
