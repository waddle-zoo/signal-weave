"""Evaluation-only local simulation of caller-owned evidence files.

Recipient keys model intended access only. This is not recipient delivery or
proof that an ordinary workspace can access files in another environment.
CSV fields use Python's standard CSV rendering; values are not spreadsheet-
sanitized, so this is not a production spreadsheet export implementation.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

MAX_ROW_LIMIT = 500
MAX_ARTIFACT_BYTES = 1_000_000
DEFAULT_ROW_LIMIT = 200
SCOPE_NOTE = (
    "Evaluation-only local caller-file simulation using the delegate's query source; this is not "
    "actual recipient delivery or proof of ordinary-workspace compatibility."
)
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.csv\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_TOOLS = frozenset({"export_query_csv", "read_evidence_file"})


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _csv_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if (
        isinstance(value, dict)
        and set(value) == {"blob_hex"}
        and isinstance(value["blob_hex"], str)
    ):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise ValueError("query result contains an unsupported cell value")


class EvidenceFileActor:
    """Add bounded local file tools; retained manifests come from a trusted coordinator."""

    def __init__(
        self,
        delegate: Any,
        directory: str | os.PathLike[str],
        audience: Sequence[str],
        audit: Any,
        retained_manifest: Mapping[str, Mapping[str, str]] | None = None,
    ):
        if isinstance(audience, (str, bytes)) or not isinstance(audience, Sequence):
            raise ValueError("audience must be an explicit finite sequence of recipient keys")
        if (
            not audience
            or any(not isinstance(key, str) or not key or key.strip() != key for key in audience)
            or len(set(audience)) != len(audience)
        ):
            raise ValueError("audience must contain unique, non-empty recipient keys")
        if not callable(getattr(audit, "emit", None)):
            raise ValueError("audit must provide emit")

        requested_root = Path(directory).expanduser().absolute()
        manifest = self._validate_manifest(retained_manifest)
        exists = requested_root.exists() or requested_root.is_symlink()
        if retained_manifest is None:
            if exists:
                raise FileExistsError("evidence output directory must be new and exclusively owned")
            requested_root.mkdir(mode=0o700)
        elif not exists:
            raise FileNotFoundError("retained evidence directory does not exist")
        root_stat = requested_root.lstat()
        if (
            stat.S_ISLNK(root_stat.st_mode)
            or not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_IMODE(root_stat.st_mode) & 0o077
            or stat.S_IMODE(root_stat.st_mode) & 0o700 != 0o700
            or root_stat.st_uid != os.geteuid()
        ):
            raise ValueError("evidence directory must be owned, private, and non-symlink")

        self.delegate = delegate
        self.directory = requested_root.resolve(strict=True)
        self.audience = tuple(audience)
        self.audit = audit
        self._root_identity = (root_stat.st_dev, root_stat.st_ino, root_stat.st_uid)
        self._artifacts = manifest
        if retained_manifest is not None:
            try:
                for filename in manifest:
                    self._load_artifact(filename)
            except Exception:
                self._audit("caller_evidence_file.resume_failed")
                raise
            self._audit("caller_evidence_file.resume_verified", artifact_count=len(manifest))

    @staticmethod
    def _validate_manifest(
        retained_manifest: Mapping[str, Mapping[str, str]] | None,
    ) -> dict[str, tuple[str, str]]:
        if retained_manifest is None:
            return {}
        if not isinstance(retained_manifest, Mapping):
            raise ValueError("retained_manifest must be a filename-to-hashes mapping")
        normalized: dict[str, tuple[str, str]] = {}
        for raw_filename, hashes in retained_manifest.items():
            filename = raw_filename
            if not isinstance(filename, str) or not _FILENAME.fullmatch(filename):
                raise ValueError("retained manifest contains an invalid filename")
            if not isinstance(hashes, Mapping) or set(hashes) != {
                "csv_sha256", "provenance_sha256"
            }:
                raise ValueError("retained manifest entry must contain both SHA-256 hashes")
            csv_hash, provenance_hash = hashes["csv_sha256"], hashes["provenance_sha256"]
            if (
                not isinstance(csv_hash, str)
                or not _SHA256.fullmatch(csv_hash)
                or not isinstance(provenance_hash, str)
                or not _SHA256.fullmatch(provenance_hash)
            ):
                raise ValueError("retained manifest contains an invalid SHA-256 hash")
            normalized[filename] = (csv_hash, provenance_hash)
        return normalized

    @property
    def artifact_manifest(self) -> dict[str, dict[str, str]]:
        """Return a JSON-safe copy suitable for a trusted coordinator report."""
        return {
            filename: {"csv_sha256": hashes[0], "provenance_sha256": hashes[1]}
            for filename, hashes in self._artifacts.items()
        }

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def _audit(self, event: str, **fields: Any) -> None:
        # Deliberately omit filenames, SQL, source metadata, cell values, and recipient keys.
        self.audit.emit(event, **fields)

    def _check_root(self) -> None:
        info = self.directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o077
            or stat.S_IMODE(info.st_mode) & 0o700 != 0o700
            or (info.st_dev, info.st_ino, info.st_uid) != self._root_identity
        ):
            raise PermissionError("private evidence directory is no longer available")

    def _filename(self, filename: str) -> str:
        if not isinstance(filename, str) or not _FILENAME.fullmatch(filename):
            raise ValueError("filename must be a simple .csv basename")
        return filename

    def _recipients(self, recipients: Sequence[str] | None) -> list[str]:
        if recipients is None:
            return []
        if isinstance(recipients, (str, bytes)) or not isinstance(recipients, Sequence):
            raise ValueError("recipients must be a list of audience keys")
        chosen = list(recipients)
        if (
            any(not isinstance(key, str) or key not in self.audience for key in chosen)
            or len(set(chosen)) != len(chosen)
        ):
            raise ValueError("recipients must be unique keys from the declared audience")
        return chosen

    async def specs(self) -> list[dict[str, Any]]:
        existing = list(await _await(self.delegate.specs()))
        names = {tool.get("name") for tool in existing if isinstance(tool, dict)}
        if names & _TOOLS:
            raise ValueError("delegate already defines a caller evidence-file tool")
        existing.extend(
            [
                {
                    "name": "export_query_csv",
                    "description": (
                        "Run a bounded read-only query and save its unmodified rows and source "
                        "provenance as a local CSV. Evaluation-only simulation; recipients are "
                        "intended audience keys, not actual delivery. Does not prove ordinary-"
                        "workspace compatibility."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string"},
                            "filename": {"type": "string"},
                            "recipients": {
                                "type": "array",
                                "items": {"type": "string", "enum": list(self.audience)},
                                "uniqueItems": True,
                            },
                            "row_limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_ROW_LIMIT,
                            },
                        },
                        "required": ["sql", "filename"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "read_evidence_file",
                    "description": (
                        "Read back one locally saved evidence file as a declared simulated "
                        "audience key. This is not remote delivery or production authorization."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "artifact_ref": {"type": "string"},
                            "recipient_key": {
                                "type": "string",
                                "enum": list(self.audience),
                            },
                        },
                        "required": ["artifact_ref", "recipient_key"],
                        "additionalProperties": False,
                    },
                },
            ]
        )
        return existing

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "export_query_csv":
            return await self.export_query_csv(**arguments)
        if name == "read_evidence_file":
            return self.read_evidence_file(**arguments)
        return await _await(self.delegate.call(name, arguments))

    async def export_query_csv(
        self,
        sql: str,
        filename: str,
        recipients: Sequence[str] | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
    ) -> dict[str, Any]:
        stage = "query_or_validation"
        try:
            if not isinstance(sql, str) or not sql.strip():
                raise ValueError("sql must be a non-empty string")
            filename = self._filename(filename)
            chosen = self._recipients(recipients)
            if type(row_limit) is not int or not 1 <= row_limit <= MAX_ROW_LIMIT:
                raise ValueError(f"row_limit must be an integer from 1 to {MAX_ROW_LIMIT}")
            self._check_root()
            csv_path = self.directory / filename
            metadata_path = self.directory / f"{filename}.provenance.json"
            if any(path.exists() or path.is_symlink() for path in (csv_path, metadata_path)):
                raise FileExistsError("evidence artifact path already exists")

            result = await _await(
                self.delegate.call("query_readonly", {"sql": sql, "row_limit": row_limit})
            )
            columns, rows, source, assets_read = self._validate_result(result, sql, row_limit)
            stream = StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            for row in rows:
                writer.writerow([_csv_value(value) for value in row])
            csv_bytes = stream.getvalue().encode("utf-8")
            digest = hashlib.sha256(csv_bytes).hexdigest()
            metadata = {
                "artifact_ref": filename,
                "format": "csv",
                "sql": sql,
                "source": source,
                "assets_read": assets_read,
                "row_count": len(rows),
                "columns": columns,
                "truncated": False,
                "sha256": digest,
                "access_audience": chosen,
                "scope_note": SCOPE_NOTE,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            metadata_bytes = json.dumps(
                metadata, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            if len(csv_bytes) + len(metadata_bytes) > MAX_ARTIFACT_BYTES:
                raise ValueError("CSV and provenance exceed the 1 MB artifact limit")

            stage = "file_write"
            created: list[Path] = []
            try:
                self._write_exclusive(csv_path, csv_bytes)
                created.append(csv_path)
                self._write_exclusive(metadata_path, metadata_bytes)
                created.append(metadata_path)
            except BaseException:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
            metadata_digest = hashlib.sha256(metadata_bytes).hexdigest()
            self._artifacts[filename] = (digest, metadata_digest)
            self._audit(
                "caller_evidence_file.exported",
                row_count=len(rows),
                column_count=len(columns),
                byte_count=len(csv_bytes),
                recipient_count=len(chosen),
            )
            return {
                "row_count": len(rows),
                "columns": columns,
                "sample": rows[:3],
                "artifact_ref": filename,
                "path": str(csv_path),
                "sha256": digest,
                "access_audience": chosen,
                "source": source,
                "assets_read": assets_read,
                "scope_note": SCOPE_NOTE,
            }
        except Exception:
            self._audit("caller_evidence_file.export_failed", stage=stage)
            raise

    @staticmethod
    def _validate_result(
        result: Any, sql: str, row_limit: int
    ) -> tuple[list[str], list[list[Any]], dict[str, Any], list[str]]:
        if not isinstance(result, dict):
            raise ValueError("query_readonly returned a malformed result")
        columns = result.get("columns")
        rows = result.get("rows")
        source = result.get("source")
        assets_read = result.get("assets_read")
        if result.get("truncated") is not False:
            raise ValueError("truncated query results cannot be exported as complete evidence")
        if (
            "truncation_reason" not in result
            or result["truncation_reason"] is not None
            or result.get("query") != sql
        ):
            raise ValueError("query_readonly returned inconsistent provenance")
        if type(result.get("row_limit")) is not int or result["row_limit"] != row_limit:
            raise ValueError("query_readonly returned an inconsistent row limit")
        if (
            not isinstance(columns, list)
            or not columns
            or any(not isinstance(column, str) or not column for column in columns)
            or len(set(columns)) != len(columns)
        ):
            raise ValueError("query result columns must be non-empty and unique")
        if not isinstance(rows, list) or len(rows) > row_limit:
            raise ValueError("query result rows are malformed")
        if type(result.get("returned_row_count")) is not int or result["returned_row_count"] != len(rows):
            raise ValueError("query result row count is inconsistent")
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("identifier"), str)
            or not source["identifier"]
            or not isinstance(source.get("retrieved_at_utc"), str)
            or not source["retrieved_at_utc"]
        ):
            raise ValueError("query result source provenance is malformed")
        if not isinstance(assets_read, list) or not assets_read or any(
            not isinstance(asset, str) or not asset for asset in assets_read
        ):
            raise ValueError("query result asset provenance is malformed")
        try:
            source = json.loads(json.dumps(source, ensure_ascii=False, allow_nan=False))
            assets_read = json.loads(json.dumps(assets_read, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise ValueError("query result provenance is not JSON-compatible") from error

        normalized_rows: list[list[Any]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("query result row does not match its columns")
            for value in row:
                _csv_value(value)
            normalized_rows.append(row)
        return list(columns), normalized_rows, source, assets_read

    @staticmethod
    def _write_exclusive(path: Path, content: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _read_regular(path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise PermissionError("evidence artifact must be a regular local file")
            with os.fdopen(descriptor, "rb") as stream:
                content = stream.read(MAX_ARTIFACT_BYTES + 1)
            if len(content) > MAX_ARTIFACT_BYTES:
                raise ValueError("evidence artifact exceeds the 1 MB limit")
            return content
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise

    def _load_artifact(
        self, artifact_ref: str, recipient_key: str | None = None
    ) -> tuple[bytes, str, dict[str, Any]]:
        filename = self._filename(artifact_ref)
        if recipient_key is not None and (
            not isinstance(recipient_key, str) or recipient_key not in self.audience
        ):
            raise PermissionError("recipient is not in the declared simulated audience")
        expected = self._artifacts.get(filename)
        if expected is None:
            raise FileNotFoundError("unknown local evidence artifact")
        self._check_root()
        try:
            content = self._read_regular(self.directory / filename)
            metadata_bytes = self._read_regular(self.directory / f"{filename}.provenance.json")
        except FileNotFoundError as error:
            raise FileNotFoundError("unknown local evidence artifact") from error
        if len(content) + len(metadata_bytes) > MAX_ARTIFACT_BYTES:
            raise ValueError("evidence artifact exceeds the 1 MB limit")
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected[0] or hashlib.sha256(metadata_bytes).hexdigest() != expected[1]:
            raise ValueError("evidence artifact integrity check failed")
        provenance = json.loads(metadata_bytes)
        access_audience = provenance.get("access_audience") if isinstance(provenance, dict) else None
        if (
            not isinstance(provenance, dict)
            or provenance.get("artifact_ref") != filename
            or provenance.get("sha256") != digest
            or not isinstance(access_audience, list)
            or any(not isinstance(key, str) or key not in self.audience for key in access_audience)
            or len(set(access_audience)) != len(access_audience)
            or recipient_key is not None and recipient_key not in access_audience
        ):
            raise PermissionError("recipient is not authorized for this simulated artifact")
        return content, digest, provenance

    def read_evidence_file(self, artifact_ref: str, recipient_key: str) -> dict[str, Any]:
        try:
            content, digest, provenance = self._load_artifact(artifact_ref, recipient_key)
            decoded = content.decode("utf-8")
            self._audit("caller_evidence_file.read", byte_count=len(content))
            return {
                "artifact_ref": artifact_ref,
                "content": decoded,
                "sha256": digest,
                "provenance": provenance,
                "recipient_key": recipient_key,
                "scope_note": SCOPE_NOTE,
            }
        except Exception:
            self._audit("caller_evidence_file.read_denied")
            raise
