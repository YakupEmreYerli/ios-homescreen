"""Where pull snapshots, backups and cached images live.

Nothing is written to the working directory unless asked: the default is the XDG data
directory, ``$XDG_DATA_HOME/ios-homescreen`` or ``~/.local/share/ios-homescreen``. Only
the layout file that ``pull`` writes goes where the user says (``layout.toml`` in the
current directory by default).
"""

from __future__ import annotations

import os
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
    """``$XDG_CACHE_HOME/ios-homescreen`` or ``~/.cache/ios-homescreen`` (icons, wallpaper)."""
    env = os.environ if env is None else env
    override = env.get(CACHE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    xdg = env.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    return (home or Path.home()) / ".cache" / APP_NAME
