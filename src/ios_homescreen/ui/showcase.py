"""Showcase mode (``editor --showcase LAYOUT``): screenshots of the editor on a real phone.

The phone is read as usual, for its icons and widget data, but what the editor shows is
the layout file, and only that: the App Library lists only the apps named in the file's
optional ``[showcase]`` table, the device is called by its model instead of its name, and
the phone's own layout never reaches the page. The table can also name a ``wallpaper``
image and a ``before`` layout that the change list is computed from (paths relative to
the file).

Nothing is written: the session refuses Apply and Restore (the page shows a notice), and
the device is wrapped so that a write fails even if something asked for one.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..device import DeviceError
from ..model import describe, match_folders
from ..planner import LayoutError, check_tables, load_layout, plan_layout, resolve_apps
from ..snapshots import device_details
from ..state import StateError, is_folder, item_id, item_kind, iter_items, split_state

SHOWCASE_CODE = "showcase"


class ReadOnlyDevice:
    """A device that reads like the one it wraps and refuses every write."""

    def __init__(self, device: Any) -> None:
        self._device = device

    def __getattr__(self, name: str) -> Any:
        return getattr(self._device, name)

    @property
    def info(self) -> dict[str, Any]:
        return masked(self._device.info)

    async def write_state(self, payload: Any) -> None:
        raise DeviceError("showcase mode never writes to the phone", code=SHOWCASE_CODE)

    async def set_wifi_connections(self, enabled: bool) -> None:
        raise DeviceError("showcase mode never changes the phone", code=SHOWCASE_CODE)

    async def close(self) -> None:
        await self._device.close()


def masked(info: Mapping[str, Any]) -> dict[str, Any]:
    """Device details with the phone's name replaced by its model."""
    found = dict(info)
    found["name"] = found.get("model") or "iPhone"
    return found


@dataclass(frozen=True)
class Showcase:
    """A loaded showcase file: the layout to show, and its optional extras."""

    path: Path
    document: Mapping[str, Any]
    before: Mapping[str, Any] | None = None
    """The layout the change list is computed from (``[showcase] before``)."""
    wallpaper: bytes | None = None
    """The phone background (``[showcase] wallpaper``), PNG or JPEG."""


def _layout(path: Path) -> Mapping[str, Any]:
    document = load_layout(path)
    check_tables(document)
    return document


def load(path: Path) -> Showcase:
    """Read and check the layout file and what its table names, before anything connects."""
    path = Path(path)
    document = _layout(path)
    table = document.get("showcase")
    table = table if isinstance(table, Mapping) else {}
    before = None
    if "before" in table:
        other = path.parent / table["before"]
        try:
            before = _layout(other)
        except (LayoutError, StateError) as exc:
            raise StateError(f"[showcase] before = {table['before']!r}: {exc}") from exc
    wallpaper = None
    if "wallpaper" in table:
        wallpaper = (path.parent / table["wallpaper"]).read_bytes()
        if not wallpaper.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            raise StateError(f"[showcase] wallpaper = {table['wallpaper']!r} is not a PNG or JPEG")
    return Showcase(path, document, before, wallpaper)


def _state(document: Mapping[str, Any], read: Mapping[str, Any]) -> list[list[Any]]:
    plan = plan_layout(document, read, allow_removal=True, display_only=True)
    dock, pages = split_state(plan.payload)
    return [deepcopy(dock), *deepcopy(pages)]


def _specials(state: Any) -> dict[str, Any]:
    return {
        item_id(item): item
        for item in iter_items(state)
        if not is_folder(item) and item_kind(item) != "app"
    }


def _uses(view: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """Apps on a view's home screen, and apps that only own a widget or web app on it."""
    shown: set[str] = set()
    owners: set[str] = set()

    def walk(items: list[Any]) -> None:
        for item in items:
            kind = item.get("type")
            if kind == "folder":
                for page in item.get("pages", []):
                    walk(page)
            elif kind == "app":
                shown.add(item["id"])
            elif kind == "widget":
                owners.update(w["app"] for w in item.get("widgets", []) if w.get("app"))
            elif kind == "webapp":
                owners.add(item.get("app", ""))

    walk(view["dock"])
    for page in view["pages"]:
        walk(page["items"])
    return shown, owners


def snapshot(read: Mapping[str, Any], shown: Showcase) -> dict[str, Any]:
    """What the editor works on: the ``before`` layout (or the shown one) as the read,
    the shown layout as the starting edit, and only the apps they and the table name."""
    installed: Mapping[str, Any] = read.get("apps", {}) or {}
    after = _state(shown.document, read)
    before = _state(shown.before, read) if shown.before is not None else after
    table = shown.document.get("showcase")
    refs = table.get("library", []) if isinstance(table, Mapping) else []
    library = resolve_apps(refs, read)

    on_screen: set[str] = set()
    owners: set[str] = set()
    for state in (after, before):
        found, owned = _uses(describe({"state": state, "apps": installed}))
        on_screen |= found
        owners |= owned
    apps: dict[str, Any] = {}
    for ident in [*sorted(on_screen), *library]:
        if ident in installed:
            apps[ident] = {k: v for k, v in dict(installed[ident]).items() if k != "hidden"}
    for ident in sorted(owners - set(apps)):
        if ident in installed:
            # Needed for the widget's or web app's name and icon, but not part of the
            # App Library list: hidden apps are left out of it.
            apps[ident] = {**dict(installed[ident]), "hidden": True}
    found = {
        "created": read.get("created"),
        "device": masked(device_details(read.get("device"))),
        "state": before,
        "apps": apps,
    }
    if shown.before is not None:
        found["draft_state"] = after
        # Widgets, web clips and web apps of the shown layout that ``before`` lacks: the
        # planner needs their data to check the edited layout.
        known = _specials(before)
        found["extra_items"] = [deepcopy(x) for i, x in _specials(after).items() if i not in known]
    return found


def draft_view(snapshot: Mapping[str, Any], view: Mapping[str, Any]) -> dict[str, Any] | None:
    """The shown layout as an editor view whose folders keep the ids they have in ``view``."""
    state = snapshot.get("draft_state")
    if state is None:
        return None
    draft = describe({"state": state, "apps": snapshot.get("apps", {})})
    match_folders(view, draft, prefix="showcase")
    return {"dock": draft["dock"], "pages": draft["pages"]}
