"""Where reads, backups and plans live.

Nothing is written to the working directory unless asked: the default is the XDG data
directory, ``$XDG_DATA_HOME/ios-homescreen`` or ``~/.local/share/ios-homescreen``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

APP_NAME = "ios-homescreen"
DATA_DIR_ENV = "IOS_HOMESCREEN_DATA_DIR"
CACHE_DIR_ENV = "IOS_HOMESCREEN_CACHE_DIR"
PAIR_RECORDS_ENV = "IOS_HOMESCREEN_PAIR_RECORDS"

READS = "reads"
BACKUPS = "backups"
PLANS = "plans"
ICONS = "icons"


def data_dir(env: Mapping[str, str] | None = None, *, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    xdg = env.get("XDG_DATA_HOME")
    # The XDG spec says relative paths are invalid and must be ignored.
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    return (home or Path.home()) / ".local" / "share" / APP_NAME


def cache_dir(env: Mapping[str, str] | None = None, *, home: Path | None = None) -> Path:
    """``$XDG_CACHE_HOME/ios-homescreen`` or ``~/.cache/ios-homescreen`` (app icons)."""
    env = os.environ if env is None else env
    override = env.get(CACHE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    xdg = env.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    return (home or Path.home()) / ".cache" / APP_NAME


def default_pair_records_dir(
    env: Mapping[str, str] | None = None, *, platform: str | None = None
) -> Path:
    """usbmuxd's pair record store (``/var/lib/lockdown`` on Linux)."""
    env = os.environ if env is None else env
    override = env.get(PAIR_RECORDS_ENV)
    if override:
        return Path(override).expanduser()
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return Path("/var/db/lockdown")
    return Path("/var/lib/lockdown")
