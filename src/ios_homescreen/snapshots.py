"""On-disk formats: read snapshots, backups and plans.

Everything is stored as a binary plist because icon state carries ``datetime`` and
``bytes`` values that JSON cannot round-trip.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .state import StateError, load_any, load_plist

READ_FORMAT = "ios-homescreen.read"
READ_FORMAT_VERSION = 1


def timestamp() -> str:
    """Local time stamp for file names; sorts chronologically."""
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def utc_now() -> datetime:
    """Naive UTC ``datetime``: plistlib reads it back the same on every Python version."""
    return datetime.now(UTC).replace(tzinfo=None)


def make_read(
    state: Any,
    apps: Mapping[str, Any],
    *,
    device: Mapping[str, Any] | None = None,
    raw_v3: Any = None,
    raw_v3_error: str | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "format": READ_FORMAT,
        "version": READ_FORMAT_VERSION,
        "created": utc_now(),
        "device": {k: v for k, v in (device or {}).items() if v is not None},
        "state": state,
        "apps": dict(apps),
    }
    if raw_v3_error is not None:
        snapshot["raw_state_v3_error"] = raw_v3_error
    elif raw_v3 is not None:
        snapshot["raw_state_v3"] = raw_v3
    return snapshot


def load_read(path: Path) -> dict[str, Any]:
    """Load a read snapshot; planning needs both the layout and the installed apps."""
    data = load_plist(path)
    if not isinstance(data, dict) or "state" not in data or "apps" not in data:
        raise StateError(f"{path}: not a read snapshot (expected 'state' and 'apps')")
    return data


def state_from_file(path: Path) -> Any:
    """Icon state from a read snapshot, a backup, a plan or a raw state dump."""
    data = load_any(path)
    if isinstance(data, dict) and "state" in data:
        return data["state"]
    return data


def latest(directory: Path, pattern: str) -> Path:
    candidates = sorted(directory.glob(pattern)) if directory.is_dir() else []
    if not candidates:
        raise StateError(f"no {pattern} file in {directory}")
    return candidates[-1]
