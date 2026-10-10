"""A pretend iPhone for ``ios-homescreen editor --demo``.

Every app, widget and web clip here is invented, with ``com.example.*`` ids and the
generated icons from :mod:`.demo_icons`. :class:`DemoDevice` answers like the real
:class:`~ios_homescreen.device.Device` (reads, writes, icons), with a short delay so
progress can be seen, and keeps the layout in memory: nothing touches a phone.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime
from typing import Any

from ..state import split_state, validate_write_payload
from .demo_icons import icon_svg

_MODIFIED = datetime(2026, 9, 1, 9, 41, 0)

# bundle id suffix -> (name, glyph, palette, application type, glyph colour)
_APPS: dict[str, tuple[str, str, str, str, str]] = {
    # dock
    "callo": ("Callo", "phone", "green", "System", "#FFFFFF"),
    "parley": ("Parley", "chat", "blue", "System", "#FFFFFF"),
    "wayfare": ("Wayfare", "compass", "sky", "System", "#FFFFFF"),
    "melodia": ("Melodia", "music", "rose", "System", "#FFFFFF"),
    # page 1
    "skycast": ("Skycast", "weather", "sky", "System", "#FFFFFF"),
    "agenda": ("Agenda", "calendar", "white", "System", "#E5483B"),
    "lumina": ("Lumina", "photo", "orange", "System", "#FFFFFF"),
    "shutter": ("Shutter", "camera", "slate", "System", "#FFFFFF"),
    "postal": ("Postal", "mail", "blue", "System", "#FFFFFF"),
    "waypoint": ("Waypoint", "pin", "mint", "System", "#FFFFFF"),
    "chrono": ("Chrono", "clock", "graphite", "System", "#FFFFFF"),
    "jotter": ("Jotter", "notes", "amber", "System", "#FFFFFF"),
    "ticklist": ("Ticklist", "checklist", "indigo", "System", "#FFFFFF"),
    "inkwell": ("Inkwell", "pen", "violet", "User", "#FFFFFF"),
    "palette": ("Palette", "palette", "sand", "User", "#FFFFFF"),
    "cutroom": ("Cutroom", "clapper", "graphite", "User", "#FFFFFF"),
    "mixdown": ("Mixdown", "wave", "pink", "User", "#FFFFFF"),
    "vitals": ("Vitals", "heart", "rose", "System", "#FFFFFF"),
    "purse": ("Purse", "card", "teal", "System", "#FFFFFF"),
    "settings": ("Settings", "gear", "slate", "System", "#FFFFFF"),
    "sums": ("Sums", "calculator", "orange", "System", "#FFFFFF"),
    "recorder": ("Recorder", "mic", "coral", "System", "#FFFFFF"),
    "loupe": ("Loupe", "loupe", "graphite", "System", "#FFFFFF"),
    "level": ("Level", "ruler", "amber", "System", "#FFFFFF"),
    "bookshelf": ("Bookshelf", "book", "orange", "System", "#FFFFFF"),
    "airwaves": ("Airwaves", "headphones", "violet", "System", "#FFFFFF"),
    "market": ("Market", "bag", "blue", "System", "#FFFFFF"),
    # page 2
    "stride": ("Stride", "trend", "lime", "User", "#FFFFFF"),
    "mealtime": ("Mealtime", "dining", "coral", "User", "#FFFFFF"),
    "greenhouse": ("Greenhouse", "leaf", "green", "User", "#FFFFFF"),
    "courier": ("Courier", "box", "amber", "User", "#FFFFFF"),
    "margin": ("Margin", "bars", "navy", "User", "#FFFFFF"),
    "spendwise": ("Spendwise", "pie", "teal", "User", "#FFFFFF"),
    "jetset": ("Jetset", "plane", "sky", "User", "#FFFFFF"),
    "voyage": ("Voyage", "suitcase", "sand", "User", "#FFFFFF"),
    "babel": ("Babel", "translate", "blue", "System", "#FFFFFF"),
    "gather": ("Gather", "people", "purple", "User", "#FFFFFF"),
    "murmur": ("Murmur", "typing", "mint", "User", "#FFFFFF"),
    "hearth": ("Hearth", "house", "orange", "System", "#FFFFFF"),
    "lull": ("Lull", "moon", "navy", "User", "#FFFFFF"),
    "lockbox": ("Lockbox", "key", "graphite", "System", "#FFFFFF"),
    # page 3
    "tetrad": ("Tetrad", "gamepad", "purple", "User", "#FFFFFF"),
    "scanline": ("Scanline", "scan", "cyan", "User", "#FFFFFF"),
    "metro": ("Metro", "train", "indigo", "User", "#FFFFFF"),
    "atelier": ("Atelier", "mosaic", "pink", "User", "#FFFFFF"),
    # App Library only
    "aurora": ("Aurora", "arcs", "violet", "User", "#FFFFFF"),
    "breeze": ("Breeze", "waves", "sky", "User", "#FFFFFF"),
    "circuit": ("Circuit", "nodes", "green", "User", "#FFFFFF"),
    "ember": ("Ember", "flame", "orange", "User", "#FFFFFF"),
    "fern": ("Fern", "leaf", "mint", "User", "#FFFFFF"),
    "glyph": ("Glyph", "hexagon", "amber", "User", "#FFFFFF"),
    "harbor": ("Harbor", "anchor", "navy", "User", "#FFFFFF"),
    "horizon": ("Horizon", "mountain", "blue", "User", "#FFFFFF"),
    "kite": ("Kite", "kite", "coral", "User", "#FFFFFF"),
    "nimbus": ("Nimbus", "cloud", "sky", "User", "#FFFFFF"),
    "orbit": ("Orbit", "planet", "teal", "User", "#FFFFFF"),
    "prism": ("Prism", "prism", "purple", "User", "#FFFFFF"),
    "quill": ("Quill", "quill", "slate", "User", "#FFFFFF"),
    "ripple": ("Ripple", "ripple", "cyan", "User", "#FFFFFF"),
    "sprout": ("Sprout", "sprout", "lime", "User", "#FFFFFF"),
    "tide": ("Tide", "drop", "blue", "User", "#FFFFFF"),
    "zenith": ("Zenith", "star", "amber", "User", "#FFFFFF"),
    "beacon": ("Beacon", "broadcast", "rose", "User", "#FFFFFF"),
    "cobalt": ("Cobalt", "cube", "indigo", "User", "#FFFFFF"),
    "drift": ("Drift", "paperplane", "teal", "User", "#FFFFFF"),
}

PREFIX = "com.example."

FORECAST = "D3E0A1C2-5B7F-4E21-9A10-000000000001"
UP_NEXT = "D3E0A1C2-5B7F-4E21-9A10-000000000002"
ACTIVITY = "D3E0A1C2-5B7F-4E21-9A10-000000000003"
MEMORIES = "D3E0A1C2-5B7F-4E21-9A10-000000000004"
HANDBOOK = "4F1C2D3E4A5B46C7D8E9F0A1B2C3D4E5"
PLANNER = "B7C8D9E0-1A2B-4C3D-8E4F-000000000005"

_SPECIAL_ICONS = {HANDBOOK: ("document", "slate"), PLANNER: ("kanban", "teal")}


def _id(key: str) -> str:
    return PREFIX + key


def _app(key: str) -> dict[str, Any]:
    ident = _id(key)
    return {
        "bundleIdentifier": ident,
        "displayIdentifier": ident,
        "displayName": _APPS[key][0],
        "bundleVersion": "1.0",
        "iconModDate": _MODIFIED,
    }


def _widget(ident: str, key: str, size: str, kind: str) -> dict[str, Any]:
    return {
        "elementType": "widget",
        "iconType": "custom",
        "bundleIdentifier": f"{_id(key)}.widgets",
        "containerBundleIdentifier": _id(key),
        "widgetIdentifier": kind,
        "displayIdentifier": ident,
        "gridSize": size,
    }


def _folder(name: str, *keys: str) -> dict[str, Any]:
    return {"listType": "folder", "displayName": name, "iconLists": [[_app(k) for k in keys]]}


def home_screen() -> list[list[Any]]:
    """The demo layout as SpringBoard reports it: ``[dock, page 1, page 2, page 3]``."""
    dock = [_app(k) for k in ("callo", "parley", "wayfare", "melodia")]
    page1 = [
        _widget(FORECAST, "skycast", "medium", "forecast"),
        *(_app(k) for k in ("agenda", "lumina", "shutter", "postal")),
        *(_app(k) for k in ("waypoint", "chrono", "jotter", "ticklist")),
        _folder("Creativity", "inkwell", "palette", "cutroom", "mixdown"),
        *(_app(k) for k in ("vitals", "purse", "settings")),
        _folder("Utilities", "sums", "recorder", "loupe", "level"),
        *(_app(k) for k in ("bookshelf", "airwaves", "market")),
    ]
    up_next = {
        "iconType": "custom",
        "displayIdentifier": UP_NEXT,
        "gridSize": "small",
        "elements": [
            {
                "uniqueIdentifier": "agenda-up-next",
                "bundleIdentifier": f"{_id('agenda')}.widgets",
                "containerBundleIdentifier": _id("agenda"),
                "widgetIdentifier": "up-next",
            },
            {
                "uniqueIdentifier": "ticklist-today",
                "bundleIdentifier": f"{_id('ticklist')}.widgets",
                "containerBundleIdentifier": _id("ticklist"),
                "widgetIdentifier": "today",
            },
        ],
        "userSelectedElementIdentifier": "agenda-up-next",
    }
    page2 = [
        up_next,
        _widget(ACTIVITY, "stride", "small", "activity"),
        *(_app(k) for k in ("stride", "mealtime", "greenhouse", "courier")),
        _folder("Finance", "margin", "spendwise"),
        _folder("Travel", "jetset", "voyage", "babel"),
        _folder("Social", "gather", "murmur"),
        _app("hearth"),
        {
            "displayIdentifier": HANDBOOK,
            "displayName": "Handbook",
            "webClipURL": "https://handbook.example.com/",
            "iconModDate": _MODIFIED,
        },
        {
            "bundleIdentifier": _id("wayfare"),
            "displayIdentifier": PLANNER,
            "displayName": "Planner",
            "iconType": "app",
        },
        *(_app(k) for k in ("lull", "lockbox")),
    ]
    page3 = [
        _widget(MEMORIES, "lumina", "large", "memories"),
        # Offloaded: SpringBoard keeps only the display id.
        {"displayIdentifier": _id("tetrad"), "displayName": "Tetrad"},
        *(_app(k) for k in ("scanline", "metro", "atelier")),
    ]
    return [dock, page1, page2, page3]


def installed_apps() -> dict[str, dict[str, str]]:
    """What Installation Proxy would report: name and User/System type."""
    return {_id(key): {"name": name, "type": kind} for key, (name, _, _, kind, _) in _APPS.items()}


def icon(identifier: str) -> bytes | None:
    """The generated SVG for a demo id, or ``None``."""
    if identifier in _SPECIAL_ICONS:
        glyph, palette = _SPECIAL_ICONS[identifier]
        return icon_svg(glyph, palette)
    if not identifier.startswith(PREFIX):
        return None
    entry = _APPS.get(identifier.removeprefix(PREFIX))
    if entry is None:
        return None
    _, glyph, palette, _, fg = entry
    return icon_svg(glyph, palette, fg=fg)


class DemoDevice:
    """Behaves like :class:`~ios_homescreen.device.Device`, in memory."""

    def __init__(self, *, delay: float = 0.4) -> None:
        dock, pages = split_state(home_screen())
        self._state: list[list[Any]] = [dock, *pages]
        self._installed = installed_apps()
        self.delay = delay
        self.writes = 0

    @property
    def info(self) -> dict[str, Any]:
        return {
            "name": "Demo iPhone",
            "model": "iPhone (demo)",
            "ios_version": "26.0",
            "udid": "demo",
        }

    async def _pause(self, factor: float = 1.0) -> None:
        if self.delay:
            await asyncio.sleep(self.delay * factor)

    async def read_state(self) -> Any:
        await self._pause()
        return deepcopy(self._state)

    async def read_raw_state(self) -> Any:
        return None

    async def installed_apps(self) -> dict[str, dict[str, str]]:
        await self._pause(0.5)
        return deepcopy(self._installed)

    async def write_state(self, payload: Any) -> None:
        validate_write_payload(payload)
        await self._pause(1.5)
        dock, pages = split_state(payload)
        self._state = [deepcopy(dock), *deepcopy(pages)]
        self.writes += 1

    async def icons(self, identifiers: Iterable[str]) -> dict[str, bytes | None]:
        return {ident: icon(ident) for ident in identifiers}

    async def wifi_connections_enabled(self) -> bool:
        return True

    async def set_wifi_connections(self, enabled: bool) -> None:
        return None

    async def close(self) -> None:
        return None
