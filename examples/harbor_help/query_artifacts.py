"""Write bounded, deterministic artifacts for a Harbor Help SQL result."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import stat
from io import StringIO
from pathlib import Path
from typing import Any

MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_ROW_LIMIT = 1_000
_ARTIFACT_NAMES = ("result.json", "rows.csv", "provenance.json")
_CSV_SEMANTICS = (
    "CSV nulls and empty strings both encode as empty fields; result.json preserves their "
    "distinction. String cells whose first non-whitespace character is =, +, -, or @, and cells "
    "beginning with a tab, carriage return, or newline, are prefixed with an apostrophe for "
    "spreadsheet formula safety."
)


def write_query_artifacts(result: dict, output_dir: Path) -> dict:
    """Write a complete query result under a content-addressed, private directory.

    ``result.json`` is the canonical record of values. CSV cannot distinguish ``None`` from an
    empty string, so callers should use the JSON file when that distinction matters.
    """
    _validate_result(result)

    try:
        result_bytes = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("query result is not canonical JSON") from error
    if len(result_bytes) > MAX_RESULT_BYTES:
        raise ValueError("query result exceeds the 2 MB limit")

    csv_bytes = _csv_bytes(result["columns"], result["rows"])
    result_digest = hashlib.sha256(result_bytes).hexdigest()
    csv_digest = hashlib.sha256(csv_bytes).hexdigest()
    provenance = {
        "assets_read": result["assets_read"],
        "columns": result["columns"],
        "files": {
            "result.json": {"sha256": result_digest, "size_bytes": len(result_bytes)},
            "rows.csv": {"sha256": csv_digest, "size_bytes": len(csv_bytes)},
        },
        "format": "harbor_help.query_artifacts.v1",
        "row_count": len(result["rows"]),
        "source": result["source"],
        "sql": result["query"],
    }
    provenance_bytes = json.dumps(
        provenance,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    file_contents = {
        "result.json": result_bytes,
        "rows.csv": csv_bytes,
        "provenance.json": provenance_bytes,
    }
    digests = {
        "json": hashlib.sha256(result_bytes).hexdigest(),
        "csv": hashlib.sha256(csv_bytes).hexdigest(),
        "provenance": hashlib.sha256(provenance_bytes).hexdigest(),
    }

    root = _prepare_root(output_dir)
    folder_name = f"sha256-{result_digest}"
    root_descriptor = _open_directory(root)
    artifact_descriptor = -1
    created_directory = False
    created_files: list[str] = []
    try:
        try:
            os.mkdir(folder_name, 0o700, dir_fd=root_descriptor)
            created_directory = True
        except FileExistsError:
            pass

        artifact_descriptor = _open_directory_at(root_descriptor, folder_name)
        _check_private_directory(os.fstat(artifact_descriptor), "artifact directory")

        if created_directory:
            for name in _ARTIFACT_NAMES:
                _write_exclusive(artifact_descriptor, name, file_contents[name])
                created_files.append(name)
        else:
            _verify_existing(artifact_descriptor, file_contents)
    except BaseException:
        if created_directory:
            for name in reversed(created_files):
                try:
                    os.unlink(name, dir_fd=artifact_descriptor)
                except OSError:
                    pass
            if artifact_descriptor >= 0:
                try:
                    os.close(artifact_descriptor)
                except OSError:
                    pass
                artifact_descriptor = -1
            try:
                os.rmdir(folder_name, dir_fd=root_descriptor)
            except OSError:
                pass
        raise
    finally:
        if artifact_descriptor >= 0:
            os.close(artifact_descriptor)
        os.close(root_descriptor)

    artifact_directory = root / folder_name
    return {
        "paths": {
            "json": str(artifact_directory / "result.json"),
            "csv": str(artifact_directory / "rows.csv"),
            "provenance": str(artifact_directory / "provenance.json"),
        },
        "row_count": len(result["rows"]),
        "columns": list(result["columns"]),
        "sha256": digests,
        "csv_semantics": _CSV_SEMANTICS,
        "source": result["source"],
        "assets_read": list(result["assets_read"]),
    }


def _validate_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("query_readonly returned a malformed result")

    required = {
        "columns",
        "rows",
        "query",
        "source",
        "assets_read",
        "row_limit",
        "returned_row_count",
        "truncated",
        "truncation_reason",
    }
    if not required.issubset(result):
        raise ValueError("query_readonly result is missing required fields")
    if not _is_json_value(result):
        raise ValueError("query result contains unsupported or non-finite values")

    columns = result["columns"]
    if (
        not isinstance(columns, list)
        or not columns
        or any(not isinstance(column, str) or not column for column in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("query result columns must be non-empty and unique")

    rows = result["rows"]
    if not isinstance(rows, list):
        raise ValueError("query result rows are malformed")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("query result row does not match its columns")
        if any(not _is_scalar(value) for value in row):
            raise ValueError("query result rows must contain only scalar values")

    row_limit = result["row_limit"]
    if type(row_limit) is not int or not 1 <= row_limit <= MAX_ROW_LIMIT:
        raise ValueError("query result row limit is malformed")
    returned_count = result["returned_row_count"]
    if type(returned_count) is not int or returned_count != len(rows) or len(rows) > row_limit:
        raise ValueError("query result row count is inconsistent")

    if result["truncated"] is not False or result["truncation_reason"] is not None:
        raise ValueError("truncated query results cannot be written as complete artifacts")
    if not isinstance(result["query"], str) or not result["query"].strip():
        raise ValueError("query result SQL provenance is malformed")

    source = result["source"]
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("identifier"), str)
        or not source["identifier"]
        or not isinstance(source.get("retrieved_at_utc"), str)
        or not source["retrieved_at_utc"]
    ):
        raise ValueError("query result source provenance is malformed")

    assets = result["assets_read"]
    if (
        not isinstance(assets, list)
        or not assets
        or any(not isinstance(asset, str) or not asset for asset in assets)
        or len(set(assets)) != len(assets)
    ):
        raise ValueError("query result asset provenance is malformed")


def _is_json_value(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_is_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_json_value(item) for key, item in value.items())
    return False


def _is_scalar(value: Any) -> bool:
    return (
        value is None
        or type(value) in (str, bool, int)
        or (type(value) is float and math.isfinite(value))
    )


def _csv_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if value[:1] in ("\t", "\r", "\n") or stripped[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _csv_bytes(columns: list[str], rows: list[list[Any]]) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow([_csv_value(column) for column in columns])
    for row in rows:
        writer.writerow([_csv_value(value) for value in row])
    return stream.getvalue().encode("utf-8")


def _prepare_root(output_dir: Path) -> Path:
    try:
        root = Path(os.path.abspath(Path(output_dir).expanduser()))
    except (TypeError, OSError) as error:
        raise ValueError("output_dir must be a filesystem path") from error
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
    except OSError as error:
        raise PermissionError("query artifact root cannot be created") from error
    _check_private_directory(info, "query artifact root")
    return root


def _check_private_directory(info: os.stat_result, label: str) -> None:
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or (hasattr(os, "getuid") and info.st_uid != os.getuid())
    ):
        raise PermissionError(f"{label} must be an owner-only 0700 directory")


def _directory_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_directory(path: Path) -> int:
    descriptor = os.open(path, _directory_flags())
    try:
        _check_private_directory(os.fstat(descriptor), "query artifact root")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_directory_at(parent_descriptor: int, name: str) -> int:
    descriptor = os.open(name, _directory_flags(), dir_fd=parent_descriptor)
    try:
        _check_private_directory(os.fstat(descriptor), "artifact directory")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _write_exclusive(directory_descriptor: int, name: str, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_descriptor)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise PermissionError("query artifact files must be regular owner-only 0600 files")
        offset = 0
        while offset < len(content):
            try:
                written = os.write(descriptor, content[offset:])
            except InterruptedError:
                continue
            if written <= 0:
                raise OSError("short write while creating query artifact")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            os.unlink(name, dir_fd=directory_descriptor)
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)


def _verify_existing(directory_descriptor: int, expected: dict[str, bytes]) -> None:
    if set(os.listdir(directory_descriptor)) != set(expected):
        raise FileExistsError(
            "content-addressed query artifact directory is incomplete or inconsistent"
        )
    for name, expected_bytes in expected.items():
        actual_bytes = _read_private_file(directory_descriptor, name, len(expected_bytes))
        if actual_bytes != expected_bytes:
            raise FileExistsError(
                "content-addressed query artifact files do not match their address"
            )


def _read_private_file(directory_descriptor: int, name: str, max_bytes: int) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_descriptor,
    )
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
        ):
            raise PermissionError("query artifact files must be regular owner-only 0600 files")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > max_bytes:
            raise FileExistsError("existing query artifact exceeds its expected size")
        return content
    finally:
        os.close(descriptor)
