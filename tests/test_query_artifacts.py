from __future__ import annotations

import csv
import hashlib
import json
import stat
from pathlib import Path

import pytest

from examples.harbor_help.query_artifacts import write_query_artifacts


def _result(rows: list[list[object]] | None = None) -> dict:
    actual_rows = rows if rows is not None else [[None, 0, "", "zero"], ["text", 2, "", "two"]]
    return {
        "columns": ["maybe_null", "count", "empty", "label"],
        "rows": actual_rows,
        "query": "SELECT value, count, note, label FROM sample ORDER BY value",
        "source": {
            "identifier": "harbor_help_raw_sqlite",
            "retrieved_at_utc": "2026-10-18T12:00:00+00:00",
            "description": "Original source metadata",
        },
        "assets_read": ["harbor_help_raw_sqlite:sample"],
        "row_limit": 10,
        "returned_row_count": len(actual_rows),
        "truncated": False,
        "truncation_reason": None,
    }


def test_writes_canonical_json_actual_rows_and_hash_backed_provenance(tmp_path: Path) -> None:
    result = _result()
    output = write_query_artifacts(result, tmp_path / "artifacts")

    paths = output["paths"]
    root = Path(paths["json"]).parent
    json_bytes = Path(paths["json"]).read_bytes()
    csv_bytes = Path(paths["csv"]).read_bytes()
    provenance_bytes = Path(paths["provenance"]).read_bytes()
    assert set(paths) == {"json", "csv", "provenance"}
    assert all(Path(path).is_absolute() for path in paths.values())
    assert stat.S_IMODE(root.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE((root / name).stat().st_mode) == 0o600
        for name in ("result.json", "rows.csv", "provenance.json")
    )
    assert json.loads(json_bytes) == result
    assert json_bytes == json.dumps(
        result, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert list(csv.reader(csv_bytes.decode("utf-8").splitlines())) == [
        result["columns"],
        ["", "0", "", "zero"],
        ["text", "2", "", "two"],
    ]

    provenance = json.loads(provenance_bytes)
    assert provenance["sql"] == result["query"]
    assert provenance["source"] == result["source"]
    assert provenance["assets_read"] == result["assets_read"]
    assert provenance["columns"] == result["columns"]
    assert provenance["row_count"] == 2
    assert provenance["files"]["result.json"] == {
        "sha256": hashlib.sha256(json_bytes).hexdigest(),
        "size_bytes": len(json_bytes),
    }
    assert provenance["files"]["rows.csv"] == {
        "sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "size_bytes": len(csv_bytes),
    }
    assert output["row_count"] == 2
    assert output["sha256"] == {
        "json": hashlib.sha256(json_bytes).hexdigest(),
        "csv": hashlib.sha256(csv_bytes).hexdigest(),
        "provenance": hashlib.sha256(provenance_bytes).hexdigest(),
    }
    assert output["source"] == result["source"]
    assert output["assets_read"] == result["assets_read"]
    assert "nulls and empty strings" in output["csv_semantics"]


def test_csv_formula_protection_applies_to_headers_and_string_cells(tmp_path: Path) -> None:
    result = _result([["=1+1", "  +SUM(A1:A2)", "@formula", "-12"]])
    result["columns"] = ["=header", "  +header", "normal", "label"]
    output = write_query_artifacts(result, tmp_path / "artifacts")

    with Path(output["paths"]["csv"]).open(encoding="utf-8", newline="") as stream:
        parsed = list(csv.reader(stream))
    assert parsed == [
        ["'=header", "'  +header", "normal", "label"],
        ["'=1+1", "'  +SUM(A1:A2)", "'@formula", "'-12"],
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.pop("source"),
        lambda result: result.update(columns=["same", "same", "empty", "label"]),
        lambda result: result.update(truncated=True, truncation_reason="row_limit"),
        lambda result: result.update(truncation_reason="unexpected"),
        lambda result: result.update(returned_row_count=1),
        lambda result: result.update(source={"identifier": "missing-timestamp"}),
        lambda result: result.update(assets_read=[]),
        lambda result: result.update(rows=[[None, 0, "", {"nested": "unsupported"}]]),
        lambda result: result.update(rows=[[None, 0, "", float("inf")]]),
        lambda result: result.update(rows=[[None, 0, ""]]),
    ],
)
def test_rejects_malformed_or_inconsistent_results(tmp_path: Path, mutate) -> None:
    result = _result()
    mutate(result)
    output_dir = tmp_path / "artifacts"

    with pytest.raises(ValueError):
        write_query_artifacts(result, output_dir)
    assert not output_dir.exists()


def test_rejects_result_larger_than_two_megabytes(tmp_path: Path) -> None:
    result = _result([[None, 0, "x" * (2 * 1024 * 1024), "large"]])
    output_dir = tmp_path / "artifacts"

    with pytest.raises(ValueError, match="2 MB"):
        write_query_artifacts(result, output_dir)
    assert not output_dir.exists()


def test_repeat_is_idempotent_and_modified_existing_files_are_not_overwritten(
    tmp_path: Path,
) -> None:
    result = _result()
    output_dir = tmp_path / "artifacts"
    first = write_query_artifacts(result, output_dir)
    second = write_query_artifacts(result, output_dir)
    assert second == first

    csv_path = Path(first["paths"]["csv"])
    csv_path.write_bytes(b"modified")
    with pytest.raises(FileExistsError, match="do not match"):
        write_query_artifacts(result, output_dir)
    assert csv_path.read_bytes() == b"modified"


def test_rejects_symlink_and_nonprivate_roots(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    symlink = tmp_path / "linked"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        write_query_artifacts(_result(), symlink)

    broad = tmp_path / "broad"
    broad.mkdir(mode=0o700)
    broad.chmod(0o750)
    with pytest.raises(PermissionError):
        write_query_artifacts(_result(), broad)


def test_rejects_symlink_at_content_addressed_directory(tmp_path: Path) -> None:
    result = _result()
    target_root = tmp_path / "target-root"
    target_output = write_query_artifacts(result, target_root)
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    artifact_link = root / Path(target_output["paths"]["json"]).parent.name
    artifact_link.symlink_to(Path(target_output["paths"]["json"]).parent, target_is_directory=True)

    with pytest.raises(OSError):
        write_query_artifacts(result, root)
    assert Path(target_output["paths"]["json"]).exists()


def test_failed_file_write_removes_only_new_partial_artifacts(tmp_path, monkeypatch):
    import errno

    from examples.harbor_help import query_artifacts

    output = tmp_path / "exports"
    retained = write_query_artifacts(_result(), output)
    retained_bytes = {kind: Path(path).read_bytes() for kind, path in retained["paths"].items()}
    original_write = query_artifacts.os.write
    writes = 0

    def out_of_space(descriptor, content):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError(errno.ENOSPC, "synthetic full filesystem")
        return original_write(descriptor, content)

    monkeypatch.setattr(query_artifacts.os, "write", out_of_space)
    changed = _result([["another", 10, "", "row"]])
    with pytest.raises(OSError, match="full filesystem"):
        write_query_artifacts(changed, output)
    assert list(output.iterdir()) == [Path(retained["paths"]["json"]).parent]
    assert {kind: Path(path).read_bytes() for kind, path in retained["paths"].items()} == retained_bytes
