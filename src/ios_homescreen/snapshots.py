"""On-disk formats: pull snapshots and backups.

Everything is stored as a binary plist because icon state carries ``datetime`` and
``bytes`` values that JSON cannot round-trip.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .state import StateError, load_plist

PULL_FORMAT = "ios-homescreen.pull"
BACKUP_FORMAT = "ios-homescreen.backup"
FORMAT_VERSION = 1

# Device details worth keeping in a file: enough to tell phones apart, nothing more.
_DEVICE_KEYS = ("name", "model", "ios_version", "udid")


def timestamp() -> str:
    """Local time stamp for file names; sorts chronologically."""
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def utc_now() -> datetime:
    """Naive UTC ``datetime``: plistlib reads it back the same on every Python version."""
    return datetime.now(UTC).replace(tzinfo=None)


def device_details(info: Mapping[str, Any] | None) -> dict[str, str]:
    """Name, model, iOS version and UDID; the Wi-Fi MAC address and empty values are left out."""
    info = info or {}
    return {key: str(info[key]) for key in _DEVICE_KEYS if info.get(key)}


def make_read(
    state: Any,
    apps: Mapping[str, Any],
    *,
    device: Mapping[str, Any] | None = None,
    raw_v3: Any = None,
    raw_v3_error: str | None = None,
) -> dict[str, Any]:
    """A pull snapshot: the layout, the installed apps and the device it came from."""
    snapshot: dict[str, Any] = {
        "format": PULL_FORMAT,
        "version": FORMAT_VERSION,
        "created": utc_now(),
        "device": device_details(device),
        "state": state,
        "apps": dict(apps),
    }
    if raw_v3_error is not None:
        snapshot["raw_state_v3_error"] = raw_v3_error
    elif raw_v3 is not None:
        snapshot["raw_state_v3"] = raw_v3
    return snapshot


def make_backup(state: Any, *, device: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A backup: the layout exactly as the phone reported it, and which phone that was."""
    return {
        "format": BACKUP_FORMAT,
        "version": FORMAT_VERSION,
        "created": utc_now(),
        "device": device_details(device),
        "state": state,
    }


def load_pull(path: Path) -> dict[str, Any]:
    """Load a pull snapshot; planning needs both the layout and the installed apps."""
    data = load_plist(path)
    if not isinstance(data, dict) or "state" not in data or "apps" not in data:
        raise StateError(f"{path}: not a pull snapshot (expected 'state' and 'apps')")
    return data


def state_from_file(path: Path) -> Any:
    """Icon state from a backup, a pull snapshot or a raw state dump."""
    data = load_plist(path)
    if isinstance(data, dict) and "state" in data:
        return data["state"]
    return data


def device_of(path: Path) -> dict[str, str]:
    """The device recorded in a backup or pull snapshot (empty for raw state dumps)."""
    data = load_plist(path)
    if isinstance(data, dict) and isinstance(data.get("device"), Mapping):
        return device_details(data["device"])
    return {}
