from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ios_homescreen.icons import IconCache, load_icons
from ios_homescreen.paths import cache_dir, data_dir

HOME = Path("/home/someone")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, HOME / ".local/share/ios-homescreen"),
        ({"XDG_DATA_HOME": "/data"}, Path("/data/ios-homescreen")),
        ({"XDG_DATA_HOME": "relative/dir"}, HOME / ".local/share/ios-homescreen"),
        ({"XDG_DATA_HOME": ""}, HOME / ".local/share/ios-homescreen"),
        ({"XDG_DATA_HOME": "/data", "IOS_HOMESCREEN_DATA_DIR": "/elsewhere"}, Path("/elsewhere")),
    ],
)
def test_data_dir_follows_xdg(env, expected):
    assert data_dir(env, home=HOME) == expected


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, HOME / ".cache/ios-homescreen"),
        ({"XDG_CACHE_HOME": "/cache"}, Path("/cache/ios-homescreen")),
        ({"XDG_CACHE_HOME": "cache"}, HOME / ".cache/ios-homescreen"),
        ({"IOS_HOMESCREEN_CACHE_DIR": "/icons"}, Path("/icons")),
    ],
)
def test_cache_dir_follows_xdg(env, expected):
    assert cache_dir(env, home=HOME) == expected


def test_icon_cache_stores_by_identifier_and_refuses_unsafe_names(tmp_path):
    cache = IconCache.for_device("00008120-000A1B2C3D4E5F60", root=tmp_path)

    cache.put("com.apple.Maps", b"png")

    assert cache.get("com.apple.Maps") == b"png"
    assert cache.directory == tmp_path / "icons" / "00008120-000A1B2C3D4E5F60"
    assert cache.path("../escape") is None
    assert cache.put("../escape", b"x") is None
    assert cache.get("missing") is None
    assert IconCache.for_device("../x", root=tmp_path).directory.name == "unknown-device"
    cache.clear()
    assert cache.get("com.apple.Maps") is None


class FakeIcons:
    def __init__(self, icons):
        self.data = icons
        self.asked: list[list[str]] = []

    async def icons(self, identifiers):
        wanted = list(identifiers)
        self.asked.append(wanted)
        return {ident: self.data.get(ident) for ident in wanted}


def test_load_icons_uses_the_cache_and_only_asks_for_the_rest(tmp_path):
    cache = IconCache(tmp_path)
    cache.put("com.apple.Maps", b"cached maps")
    source = FakeIcons({"com.apple.Music": b"music"})

    first = asyncio.run(load_icons(source, ["com.apple.Maps", "com.apple.Music", "W-1"], cache))
    second = asyncio.run(load_icons(source, ["com.apple.Music"], cache))

    assert first == {"com.apple.Maps": b"cached maps", "com.apple.Music": b"music", "W-1": None}
    assert second == {"com.apple.Music": b"music"}
    assert source.asked == [["com.apple.Music", "W-1"]]
    assert cache.get("W-1") is None
