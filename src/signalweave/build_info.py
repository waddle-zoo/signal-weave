"""Public non-secret metadata embedded by the native build."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__


def build_info() -> dict:
    if not getattr(sys, "frozen", False):
        return {"version": __version__, "frozen": False}
    path = Path(sys._MEIPASS) / "signalweave-build.json"
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"version": __version__, "frozen": True, "error": "build_metadata_unavailable"}
    return value
