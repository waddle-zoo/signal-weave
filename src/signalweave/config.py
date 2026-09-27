"""Small helpers for rejecting copied example configuration."""

from __future__ import annotations


def is_obvious_placeholder(value: str | None) -> bool:
    """Return whether *value* is an unmistakable documentation sentinel.

    This intentionally does not validate credential entropy or guess whether a
    real secret is usable. It only catches values plainly copied from an
    example file, so preflight can fail before any provider or Jev request.
    Test values such as ``test-key`` remain valid for offline verification.
    """

    normalized = (value or "").strip().lower()
    if not normalized:
        return False
    markers = (
        "replace-me",
        "replace_me",
        "change-me",
        "change_me",
        "changeme",
        "placeholder",
    )
    if any(marker in normalized for marker in markers):
        return True
    if "<" in normalized or ">" in normalized:
        return True
    return "your-" in normalized or "your_" in normalized or normalized.startswith("your ")
