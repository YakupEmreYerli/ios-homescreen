"""App icons and the home screen wallpaper from the device, cached on disk.

The cache lives under the XDG cache directory: icons in one folder per device, the
wallpaper as one file per device. Icons change rarely (app updates); :meth:`IconCache.clear`
or deleting the folder refreshes them. The browser editor fetches the wallpaper again on
every read and shows the cached one until then.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from .paths import ICONS, WALLPAPERS, cache_dir

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class IconSource(Protocol):
    async def icons(self, identifiers: Iterable[str]) -> dict[str, bytes | None]: ...


def _file_name(identifier: str) -> str | None:
    """Bundle ids and display ids are plain names; anything else is not cached."""
    if not _SAFE_NAME.match(identifier) or ".." in identifier:
        return None
    return f"{identifier}.png"


class IconCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @classmethod
    def for_device(cls, udid: str | None, root: Path | None = None) -> IconCache:
        base = (root or cache_dir()) / ICONS
        name = _file_name(udid or "") and udid
        return cls(base / (name or "unknown-device"))

    def path(self, identifier: str) -> Path | None:
        name = _file_name(identifier)
        return self.directory / name if name else None

    def get(self, identifier: str) -> bytes | None:
        path = self.path(identifier)
        if path is None or not path.is_file():
            return None
        return path.read_bytes()

    def put(self, identifier: str, data: bytes) -> Path | None:
        path = self.path(identifier)
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path

    def clear(self) -> None:
        if self.directory.is_dir():
            for file in self.directory.glob("*.png"):
                file.unlink()


class WallpaperCache:
    """One wallpaper image per device: ``CACHE/wallpapers/UDID.png``."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def for_device(cls, udid: str | None, root: Path | None = None) -> WallpaperCache:
        name = _file_name(udid or "") or "unknown-device.png"
        return cls((root or cache_dir()) / WALLPAPERS / name)

    def get(self) -> bytes | None:
        return self.path.read_bytes() if self.path.is_file() else None

    def put(self, data: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_bytes(data)
        tmp.replace(self.path)


async def load_icons(
    source: IconSource, identifiers: Iterable[str], cache: IconCache | None = None
) -> dict[str, bytes | None]:
    """PNG bytes per id: from the cache when present, otherwise from the device.

    Ids the device has no icon for map to ``None`` and are asked again next time.
    """
    wanted = list(dict.fromkeys(identifiers))
    found: dict[str, bytes | None] = {}
    missing = []
    for ident in wanted:
        cached = cache.get(ident) if cache else None
        if cached is not None:
            found[ident] = cached
        else:
            missing.append(ident)
    if missing:
        fetched: dict[str, Any] = await source.icons(missing)
        for ident in missing:
            data = fetched.get(ident)
            found[ident] = data if isinstance(data, bytes) and data else None
            if cache and found[ident] is not None:
                cache.put(ident, found[ident])
    return {ident: found[ident] for ident in wanted}
