"""Scoped loading of local Preset deployment environment files."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values


@contextmanager
def preset_environment_file(filename: str | None = None) -> Iterator[str | None]:
    """Temporarily overlay a Preset env file without mutating the caller."""

    resolved_name = (
        filename if filename is not None else os.getenv("PRESET_ENV_FILE", "")
    ).strip()
    if not resolved_name:
        yield None
        return
    path = Path(resolved_name)
    if not path.is_file():
        raise ValueError(f"PRESET_ENV_FILE does not exist: {path}")
    injected: list[str] = []
    for key, value in dotenv_values(path).items():
        if key and value is not None and key not in os.environ:
            os.environ[key] = value
            injected.append(key)
    try:
        yield str(path)
    finally:
        for key in injected:
            os.environ.pop(key, None)
