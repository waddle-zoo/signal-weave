"""Small terminal conveniences; no formatting in pipes, JSON or MCP traffic."""
from __future__ import annotations

import os
import sys
from typing import TextIO


def interactive(stream: TextIO) -> bool:
    return stream.isatty() and os.environ.get("TERM") != "dumb"


def emphasis(text: str, *, stream: TextIO | None = None) -> str:
    target = stream if stream is not None else sys.stdout
    if interactive(target) and not os.environ.get("NO_COLOR"):
        return f"\033[1m{text}\033[0m"
    return text


def progress(message: str) -> None:
    """Human-only activity on stderr; never contaminate machine-readable stdout."""
    if interactive(sys.stderr):
        print(message, file=sys.stderr, flush=True)
