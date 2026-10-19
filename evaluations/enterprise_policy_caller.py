"""Evaluation-only one-shot caller for the Harbor enterprise policy study.

This module records actual source/helper or native-card calls. It is not a
product scheduler, policy implementation, or business-outcome grader.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from evaluations.codex_workspace import sandbox_command, validate_workspace

HELPER_TIMEOUT_SECONDS = 15
HELPER_OUTPUT_LIMIT_BYTES = 256 * 1024
SUPPORTED_OUTCOMES = frozenset({"ignore", "investigate", "notify", "escalate", "insufficient_data"})


@dataclass(frozen=True)
class Monitor:
    """One caller-frozen observation for one approved native card or B query."""

    monitor_id: str
    cutoff: str
    card_id: str | None = None
    sql: str | None = None
    helper_path: str | os.PathLike[str] | None = None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _helper_file(value: str | os.PathLike[str], workspace: Path) -> Path:
    supplied = Path(value)
    if not supplied.is_absolute():
        supplied = workspace / supplied
    if supplied.is_symlink():
        raise ValueError("helper_path must not be a symlink")
    resolved = supplied.resolve(strict=True)
    if not _within(resolved, workspace) or not resolved.is_file():
        raise ValueError("helper_path must be an existing file inside the retained workspace")
    if any(parent.is_symlink() for parent in (supplied, *supplied.parents) if parent != workspace):
        raise ValueError("helper_path must not pass through symlinked directories")
    return resolved


def _public_read_paths(
    paths: Sequence[str | os.PathLike[str]], workspace: Path
) -> tuple[Path, ...]:
    if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence):
        raise ValueError("public_dependency_paths must be an explicit sequence")
    resolved_paths = []
    for value in paths:
        supplied = Path(value)
        if not supplied.is_absolute() or supplied.is_symlink():
            raise ValueError(
                "public dependency read grants must be absolute, existing, non-symlink paths"
            )
        resolved = supplied.resolve(strict=True)
        if _within(resolved, workspace) or _within(workspace, resolved):
            raise ValueError(
                "public dependency read grants must not overlap the retained workspace"
            )
        if any(parent.is_symlink() for parent in supplied.parents):
            raise ValueError(
                "public dependency read grants must not pass through symlinked directories"
            )
        resolved_paths.append(resolved)
    return tuple(resolved_paths)


async def _call_tool(facade: Any, name: str, arguments: dict[str, Any]) -> Any:
    response = await facade.call_tool(name, arguments)
    # InstalledServer and the Harbor evaluation facade return (content, result).
    if isinstance(response, tuple) and len(response) == 2:
        return response[1]
    return response


async def _run_helper(
    *,
    codex_executable: str | os.PathLike[str],
    python_executable: str | os.PathLike[str],
    workspace: Path,
    helper: Path,
    input_path: Path,
    output_path: Path,
    readonly_paths: tuple[Path, ...],
) -> tuple[bytes, list[str]]:
    codex = os.fspath(codex_executable)
    if not codex or Path(codex).name.lower() != "codex":
        raise ValueError("codex_executable must name the Codex CLI")
    python = os.fspath(python_executable)
    if not python or not Path(python).name.lower().startswith("python"):
        raise ValueError("python_executable must name a Python interpreter")
    command = sandbox_command(
        codex_executable,
        workspace,
        [python, str(helper), "--input", str(input_path), "--output", str(output_path)],
        readonly_paths=readonly_paths,
    )
    kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
        "cwd": str(workspace),
        "env": {
            "HOME": str(output_path.parent / "sandbox-home"),
            "TMPDIR": str(output_path.parent / "sandbox-tmp"),
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(*command, **kwargs)
    deadline = time.monotonic() + HELPER_TIMEOUT_SECONDS
    wait_task = asyncio.create_task(process.wait())

    def stop_process() -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            process.kill()

    try:
        while True:
            try:
                info = output_path.lstat()
            except FileNotFoundError:
                info = None
            if info is not None:
                if not output_path.is_file() or output_path.is_symlink():
                    stop_process()
                    await wait_task
                    raise ValueError("sandboxed helper output must be a regular file")
                if info.st_size > HELPER_OUTPUT_LIMIT_BYTES:
                    stop_process()
                    await wait_task
                    raise ValueError(
                        f"sandboxed helper output exceeded {HELPER_OUTPUT_LIMIT_BYTES} bytes"
                    )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stop_process()
                await wait_task
                raise TimeoutError(f"sandboxed helper exceeded {HELPER_TIMEOUT_SECONDS} seconds")
            try:
                return_code = await asyncio.wait_for(
                    asyncio.shield(wait_task), timeout=min(0.01, remaining)
                )
                break
            except TimeoutError:
                continue
    except asyncio.CancelledError:
        stop_process()
        await wait_task
        raise
    if return_code != 0:
        raise RuntimeError(f"sandboxed helper exited with status {return_code}")
    try:
        info = output_path.lstat()
    except FileNotFoundError as error:
        raise ValueError("sandboxed helper did not create decision.json") from error
    if not output_path.is_file() or output_path.is_symlink():
        raise ValueError("sandboxed helper output must be a regular file")
    if info.st_size > HELPER_OUTPUT_LIMIT_BYTES:
        raise ValueError(f"sandboxed helper output exceeded {HELPER_OUTPUT_LIMIT_BYTES} bytes")
    return output_path.read_bytes(), command


def _validate_monitors(arm: str, monitors: Sequence[Monitor]) -> tuple[Monitor, ...]:
    if arm not in {"B", "T"}:
        raise ValueError("arm must be 'B' (agent-authored helper) or 'T' (native approved card)")
    if isinstance(monitors, (str, bytes)) or not isinstance(monitors, Sequence) or not monitors:
        raise ValueError("monitors must be a nonempty, ordered sequence")
    frozen = tuple(monitors)
    seen = set()
    for monitor in frozen:
        if not isinstance(monitor, Monitor):
            raise ValueError("each monitor must be a Monitor")
        if not isinstance(monitor.monitor_id, str) or not monitor.monitor_id.strip():
            raise ValueError("monitor_id must be a nonempty string")
        if monitor.monitor_id in seen:
            raise ValueError("monitor_id values must be unique within one check")
        seen.add(monitor.monitor_id)
        if not isinstance(monitor.cutoff, str) or not monitor.cutoff.strip():
            raise ValueError("cutoff must be a nonempty caller-frozen string")
        if arm == "T":
            if not isinstance(monitor.card_id, str) or not monitor.card_id.strip():
                raise ValueError("T monitors require an approved card_id")
            if monitor.sql is not None or monitor.helper_path is not None:
                raise ValueError("T monitors accept a card_id only")
        else:
            if monitor.card_id is not None:
                raise ValueError("B monitors cannot contain a native card_id")
            if not isinstance(monitor.sql, str) or not monitor.sql.strip():
                raise ValueError("B monitors require agent-authored SQL")
            if monitor.helper_path is None:
                raise ValueError("B monitors require their retained-workspace helper_path")
    return frozen


async def check_once(
    arm: Literal["B", "T"],
    monitors: Sequence[Monitor],
    *,
    workspace: str | os.PathLike[str],
    source: Any = None,
    native: Any = None,
    run_id: str | None = None,
    codex_executable: str | os.PathLike[str] = "codex",
    python_executable: str | os.PathLike[str] = sys.executable,
    public_dependency_paths: Sequence[str | os.PathLike[str]] = (),
) -> dict[str, Any]:
    """Run one ordered check against actual injected company/native facades.

    B reads each monitor's own SQL, writes the actual structured source result
    as JSON, then executes that monitor's retained agent helper only through
    ``codex sandbox``. T evaluates each approved card with a distinct key.
    Errors are retained per monitor so later observations still run.
    """
    frozen = _validate_monitors(arm, monitors)
    if arm == "B" and source is None:
        raise ValueError("B requires an actual company source facade")
    if arm == "T" and native is None:
        raise ValueError("T requires an actual native facade")
    if run_id is None:
        run_id = uuid.uuid4().hex
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a nonempty string")

    root = validate_workspace(workspace)
    readonly_paths = _public_read_paths(public_dependency_paths, root)
    run_dir = root / f"enterprise-policy-{uuid.uuid4().hex}"
    run_dir.mkdir(mode=0o700)
    if arm == "B":
        (run_dir / "sandbox-home").mkdir(mode=0o700)
        (run_dir / "sandbox-tmp").mkdir(mode=0o700)
    ledger: list[dict[str, Any]] = []
    known_errors: list[dict[str, str]] = []

    for index, monitor in enumerate(frozen):
        started = time.perf_counter()
        key_material = f"{run_id}\0{monitor.monitor_id}\0{monitor.cutoff}".encode()
        run_key = "enterprise-evaluation:" + hashlib.sha256(key_material).hexdigest()
        entry: dict[str, Any] = {
            "sequence": index,
            "monitor_id": monitor.monitor_id,
            "cutoff": monitor.cutoff,
            "run_key": run_key,
            "status": "error",
        }
        try:
            if arm == "T":
                raw = await _call_tool(
                    native,
                    "evaluate_insight_card",
                    {
                        "card_id": monitor.card_id,
                        "idempotency_key": run_key,
                        "actor": "enterprise-policy-evaluation-caller",
                        "response_mode": "full",
                    },
                )
                entry["native_result"] = raw
                result_bytes = _canonical_json(raw)
                result_path = run_dir / f"{index:03d}-native-result.json"
                _write_exclusive(result_path, result_bytes)
                entry.update(
                    status="completed",
                    result_ref=str(result_path.relative_to(root)),
                    result_bytes=len(result_bytes),
                    result_sha256=hashlib.sha256(result_bytes).hexdigest(),
                )
            else:
                raw_source = await _call_tool(source, "query_readonly", {"sql": monitor.sql})
                source_bytes = _canonical_json(raw_source)
                input_value = {
                    "monitor_id": monitor.monitor_id,
                    "cutoff": monitor.cutoff,
                    "sql": monitor.sql,
                    "source_result": raw_source,
                }
                input_bytes = _canonical_json(input_value)
                input_path = run_dir / f"{index:03d}-actual.json"
                output_path = run_dir / f"{index:03d}-decision.json"
                _write_exclusive(input_path, input_bytes)
                entry.update(
                    source_result=raw_source,
                    source_ref=str(input_path.relative_to(root)),
                    source_result_bytes=len(source_bytes),
                    source_result_sha256=hashlib.sha256(source_bytes).hexdigest(),
                    input_bytes=len(input_bytes),
                    input_sha256=hashlib.sha256(input_bytes).hexdigest(),
                )
                helper = _helper_file(monitor.helper_path, root)
                entry["helper_path"] = str(helper.relative_to(root))
                decision_bytes, command = await _run_helper(
                    codex_executable=codex_executable,
                    python_executable=python_executable,
                    workspace=root,
                    helper=helper,
                    input_path=input_path,
                    output_path=output_path,
                    readonly_paths=readonly_paths,
                )
                entry.update(
                    sandbox_argv=command,
                    result_ref=str(output_path.relative_to(root)),
                    result_bytes=len(decision_bytes),
                    result_sha256=hashlib.sha256(decision_bytes).hexdigest(),
                )
                try:
                    decision = json.loads(decision_bytes)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(
                        "sandboxed helper decision.json must contain valid UTF-8 JSON"
                    ) from error
                if not isinstance(decision, dict):
                    raise ValueError("sandboxed helper decision.json must contain a JSON object")
                outcome = decision.get("outcome")
                entry.update(
                    decision=decision,
                )
                if not isinstance(outcome, str) or outcome not in SUPPORTED_OUTCOMES:
                    shown = repr(outcome)[:120]
                    raise ValueError(
                        f"unsupported helper outcome {shown}; no all-clear is inferred"
                    )
                entry.update(status="completed", outcome=outcome)
        except Exception as error:  # Keep a complete ordered attempt ledger.
            if arm == "B":
                partial_output = run_dir / f"{index:03d}-decision.json"
                try:
                    output_info = partial_output.lstat()
                except FileNotFoundError:
                    output_info = None
                if (
                    output_info is not None
                    and partial_output.is_file()
                    and not partial_output.is_symlink()
                ):
                    entry.setdefault("result_ref", str(partial_output.relative_to(root)))
                    entry.setdefault("result_bytes", output_info.st_size)
                    if output_info.st_size <= HELPER_OUTPUT_LIMIT_BYTES:
                        entry.setdefault(
                            "result_sha256",
                            hashlib.sha256(partial_output.read_bytes()).hexdigest(),
                        )
            detail = f"{type(error).__name__}: {str(error)[:1000]}"
            entry["error"] = detail
            known_errors.append({"monitor_id": monitor.monitor_id, "error": detail})
        entry["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        ledger.append(entry)

    return {
        "arm": arm,
        "run_id": run_id,
        "workspace": str(root),
        "run_directory": str(run_dir.relative_to(root)),
        "ledger": ledger,
        "known_errors": known_errors,
        "business_grade": None,
    }
