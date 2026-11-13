"""Where pull snapshots, backups and cached images live.

Nothing is written to the working directory unless asked. The default is the system's
place for application data: ``$XDG_DATA_HOME/ios-homescreen`` or
``~/.local/share/ios-homescreen`` on Linux, ``~/Library/Application Support/ios-homescreen``
on macOS and ``%LOCALAPPDATA%\\ios-homescreen`` on Windows. Only the layout file that
``pull`` writes goes where the user says (``layout.toml`` in the current directory by
default).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

APP_NAME = "ios-homescreen"
DATA_DIR_ENV = "IOS_HOMESCREEN_DATA_DIR"
CACHE_DIR_ENV = "IOS_HOMESCREEN_CACHE_DIR"

PULLS = "pulls"
BACKUPS = "backups"
ICONS = "icons"
WALLPAPERS = "wallpapers"

DEFAULT_LAYOUT = "layout.toml"


def _system_dir(env: Mapping[str, str], home: Path, platform: str, *, cache: bool) -> Path | None:
    """macOS and Windows locations; ``None`` on Linux and other XDG systems."""
    if platform == "darwin":
        return home / "Library" / ("Caches" if cache else "Application Support") / APP_NAME
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / APP_NAME / "Cache" if cache else base / APP_NAME
    return None


def data_dir(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    platform: str = sys.platform,
) -> Path:
    env = os.environ if env is None else env
    override = env.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    system = _system_dir(env, home or Path.home(), platform, cache=False)
    if system is not None:
        return system
    xdg = env.get("XDG_DATA_HOME")
    # The XDG spec says relative paths are invalid and must be ignored.
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    return (home or Path.home()) / ".local" / "share" / APP_NAME


def cache_dir(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    platform: str = sys.platform,
) -> Path:
    """Icons and wallpapers: ``~/.cache/ios-homescreen`` on Linux (or XDG), the system's
    cache folder on macOS and Windows."""
    env = os.environ if env is None else env
    override = env.get(CACHE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    system = _system_dir(env, home or Path.home(), platform, cache=True)
    if system is not None:
        return system
    xdg = env.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    return (home or Path.home()) / ".cache" / APP_NAME
