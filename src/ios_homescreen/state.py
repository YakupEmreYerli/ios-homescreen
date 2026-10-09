"""Lossless storage and pure operations on SpringBoard icon state.

SpringBoard answers ``getIconState`` (format version 2) with a list: ``[0]`` is the dock
and ``[1:]`` are the home screen pages. The only form this tool ever writes back is the
dictionary ``{"buttonBar", "iconLists", "ignored"}``; see :func:`safe_payload`.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

PAGE_CELLS = 24
"""An iPhone home screen page is a 6x4 grid."""

DOCK_SLOTS = 4

WIDGET_CELLS = {"small": 4, "medium": 8, "large": 16, "extraLarge": 16}

PLAN_META_KEY = "_ios_homescreen"
PLAN_FORMAT_VERSION = 1

PAYLOAD_KEYS = frozenset({"buttonBar", "iconLists", "ignored"})

HOME_SCREEN_APP_TYPES = frozenset({"User", "System"})


class StateError(ValueError):
    """Raised when icon state cannot be handled safely."""


State = list[list[Any]] | dict[str, Any]


# --------------------------------------------------------------------------- storage


def load_plist(path: str | Path) -> Any:
    """Load a binary or XML property list."""
    try:
        return plistlib.loads(Path(path).read_bytes())
    except plistlib.InvalidFileException as exc:
        raise StateError(f"{path}: not a property list file") from exc


def save_plist(path: str | Path, data: Any) -> Path:
    """Write ``data`` atomically as a binary property list.

    Binary plists keep ``datetime`` and ``bytes`` values intact; JSON would not.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY, sort_keys=False))
    tmp.replace(target)
    return target


def load_any(path: str | Path) -> Any:
    """Load a plist, or a JSON file (read-only uses such as ``diff``)."""
    file = Path(path)
    if file.suffix.lower() == ".json":
        return json.loads(file.read_text(encoding="utf-8"))
    return load_plist(file)


# --------------------------------------------------------------------------- items


def is_folder(item: Any) -> bool:
    return isinstance(item, Mapping) and (
        item.get("listType") == "folder" or item.get("iconType") == "folder"
    )


def is_widget(item: Any) -> bool:
    """Single widgets (``elementType``) and widget stacks (``iconType: custom``)."""
    return isinstance(item, Mapping) and (
        item.get("elementType") == "widget" or item.get("iconType") == "custom"
    )


def is_webclip(item: Any) -> bool:
    return isinstance(item, Mapping) and "webClipURL" in item


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def is_webapp(item: Any) -> bool:
    """An app-like item with its own display id, such as a Safari web app.

    iOS 26+ stores "Add to Home Screen" web apps as
    ``{"bundleIdentifier": "com.apple.mobilesafari", "displayIdentifier": "<UUID>"}``.
    It is not the Safari app: it must not count as Safari on the home screen.
    """
    if not isinstance(item, Mapping) or is_folder(item) or is_widget(item) or is_webclip(item):
        return False
    bundle = _text(item.get("bundleIdentifier"))
    display = _text(item.get("displayIdentifier"))
    return bundle is not None and display is not None and display != bundle


def item_kind(item: Any) -> str:
    """Return ``"folder"``, ``"widget"``, ``"webclip"``, ``"webapp"`` or ``"app"``."""
    if is_folder(item):
        return "folder"
    if is_widget(item):
        return "widget"
    if is_webclip(item):
        return "webclip"
    if is_webapp(item):
        return "webapp"
    return "app"


def item_id(item: Any) -> str:
    """Stable identifier of a non-folder item.

    ``displayIdentifier`` wins: widgets carry their extension's bundle id (two widgets
    from one extension share it) and Safari web apps carry Safari's. For a normal app
    both ids are the same; offloaded apps and web clips only have ``displayIdentifier``.
    """
    if isinstance(item, str) and item:
        return item
    if isinstance(item, Mapping):
        ident = _text(item.get("displayIdentifier")) or _text(item.get("bundleIdentifier"))
        if ident:
            return ident
    raise StateError(f"home screen item has no identifier: {item!r}")


def item_name(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        if _text(item.get("displayName")):
            return str(item["displayName"])
        try:
            ident = item_id(item)
        except StateError:
            return "?"
        return f"web app {ident}" if is_webapp(item) else ident
    return repr(item)


def folder_pages(item: Mapping[str, Any]) -> list[list[Any]]:
    return list(item.get("iconLists", []) or [])


def cell_count(item: Any) -> int:
    """Grid cells an item occupies on a 6x4 page."""
    if not is_widget(item):
        return 1
    size = item.get("gridSize", "small")
    try:
        return WIDGET_CELLS[str(size)]
    except KeyError as exc:
        raise StateError(f"unknown widget size: {size!r}") from exc


# --------------------------------------------------------------------------- state shape


def split_state(state: State) -> tuple[list[Any], list[list[Any]]]:
    """Return ``(dock, pages)`` for the list or the dictionary form."""
    if isinstance(state, list):
        return (list(state[0]) if state else []), [list(page) for page in state[1:]]
    if isinstance(state, dict):
        return list(state.get("buttonBar", []) or []), list(state.get("iconLists", []) or [])
    raise StateError(f"unexpected icon state type: {type(state).__name__}")


def to_payload(state: State) -> dict[str, Any]:
    """Deep-copy any state into the ``{buttonBar, iconLists, ignored}`` skeleton."""
    if isinstance(state, list):
        dock, pages = split_state(state)
        return {"buttonBar": deepcopy(dock), "iconLists": deepcopy(pages), "ignored": []}
    if isinstance(state, dict):
        return {
            "buttonBar": deepcopy(state.get("buttonBar", [])),
            "iconLists": deepcopy(state.get("iconLists", [])),
            "ignored": deepcopy(state.get("ignored", [])),
        }
    raise StateError(f"unexpected icon state type: {type(state).__name__}")


def iter_items(state: State, *, into_folders: bool = True) -> Iterator[Any]:
    """Yield dock and page items, and folder contents when ``into_folders`` is set."""
    dock, pages = split_state(state)
    for section in [dock, *pages]:
        for item in section:
            yield item
            if into_folders and is_folder(item):
                for page in folder_pages(item):
                    yield from page


def _apps_in(item: Any) -> Iterator[str]:
    if isinstance(item, str):
        yield item
        return
    if not isinstance(item, Mapping):
        return
    if is_folder(item):
        for page in folder_pages(item):
            for inner in page:
                yield from _apps_in(inner)
        return
    if item_kind(item) != "app":
        # Widgets, web clips and web apps do not put their bundle id on the home screen.
        return
    ident = _text(item.get("displayIdentifier")) or _text(item.get("bundleIdentifier"))
    if ident:
        yield ident


def visible_apps(state: State) -> set[str]:
    """Bundle identifiers of apps in the dock, on pages and inside folders."""
    dock, pages = split_state(state)
    return {ident for section in [dock, *pages] for item in section for ident in _apps_in(item)}


def app_type(meta: Any) -> str | None:
    if not isinstance(meta, Mapping):
        return None
    value = meta.get("type") or meta.get("ApplicationType")
    return str(value) if value is not None else None


def counts_for_home_screen(meta: Any) -> bool:
    """User and System apps can appear on the home screen; extensions and the like cannot."""
    kind = app_type(meta)
    return kind is None or kind in HOME_SCREEN_APP_TYPES


def normalize_for_write(item: Any) -> Any:
    """Upgrade legacy ``iconType: folder`` folders to ``listType: folder``.

    SpringBoard silently drops folders written with ``iconType: folder``.
    """
    if not isinstance(item, Mapping):
        return deepcopy(item)
    result = deepcopy(dict(item))
    if is_folder(result):
        result.pop("iconType", None)
        result["listType"] = "folder"
        result["iconLists"] = [
            [normalize_for_write(inner) for inner in page] for page in folder_pages(result)
        ]
    return result


def safe_payload(state: State, installed: Mapping[str, Any]) -> dict[str, Any]:
    """Build the only payload shape that is safe to send to ``setIconState``.

    ``ignored`` lists every installed User and System app that is not on the home
    screen. Without it SpringBoard puts every unlisted app (archived ones included)
    back at the end of the home screen. User apps alone are not enough: stock apps
    come back too.
    """
    payload = to_payload(state)
    payload["buttonBar"] = [normalize_for_write(item) for item in payload["buttonBar"]]
    payload["iconLists"] = [
        [normalize_for_write(item) for item in page] for page in payload["iconLists"]
    ]
    shown = visible_apps(payload)
    payload["ignored"] = sorted(
        ident
        for ident, meta in installed.items()
        if ident not in shown and counts_for_home_screen(meta)
    )
    return payload


# --------------------------------------------------------------------------- comparison


def _widget_elements(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        (
            element.get("uniqueIdentifier"),
            element.get("bundleIdentifier"),
            element.get("displayIdentifier"),
            element.get("widgetIdentifier"),
            element.get("containerBundleIdentifier"),
        )
        for element in (item.get("elements", []) or [])
        if isinstance(element, Mapping)
    )


def _canonical_item(item: Any) -> Any:
    if is_folder(item):
        return (
            "folder",
            str(item.get("displayName", "")),
            tuple(tuple(_canonical_item(inner) for inner in page) for page in folder_pages(item)),
        )
    if is_widget(item):
        return (
            "widget",
            item_id(item),
            item.get("gridSize", "small"),
            item.get("uniqueIdentifier"),
            item.get("widgetIdentifier"),
            item.get("containerBundleIdentifier"),
            # userSelectedElementIdentifier is left out: SpringBoard drops it on
            # setIconState (seen on iOS 27.0.1), so a re-read never matches it.
            _widget_elements(item),
        )
    return (item_kind(item), item_id(item))


def canonical(state: State) -> Any:
    """Structural view of a layout: kinds, identifiers, order, folder contents.

    Volatile metadata (modification dates, versions) and ``ignored`` are left out.
    """
    dock, pages = split_state(state)
    return (
        tuple(_canonical_item(item) for item in dock),
        tuple(tuple(_canonical_item(item) for item in page) for page in pages),
    )


def same_layout(left: State, right: State) -> bool:
    return canonical(left) == canonical(right)


def fingerprint(state: State) -> str:
    """Deterministic SHA-256 of the structural layout."""
    text = json.dumps(canonical(state), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- validation


def _check_item(item: Any, where: str, *, in_folder: bool = False, for_write: bool = False) -> None:
    if isinstance(item, str):
        if not item:
            raise StateError(f"{where}: empty item identifier")
        return
    if not isinstance(item, Mapping):
        raise StateError(f"{where}: an item must be a dictionary or an identifier string")
    if is_folder(item):
        if in_folder:
            raise StateError(f"{where}: folders cannot contain folders")
        if for_write and item.get("listType") != "folder":
            raise StateError(f"{where}: folders must be written with listType=folder")
        pages = item.get("iconLists")
        if not isinstance(pages, list):
            raise StateError(f"{where}: folder iconLists must be a list")
        for page_no, page in enumerate(pages, 1):
            if not isinstance(page, list):
                raise StateError(f"{where}: folder page {page_no} must be a list")
            for pos, inner in enumerate(page, 1):
                _check_item(
                    inner,
                    f"{where}/folder page {page_no}/{pos}",
                    in_folder=True,
                    for_write=for_write,
                )
        return
    if in_folder and is_widget(item):
        raise StateError(f"{where}: folders cannot contain widgets")
    item_id(item)


def _check_sections(dock: Any, pages: Any, ignored: Any = None, *, for_write: bool = False) -> None:
    if not isinstance(dock, list) or not isinstance(pages, list):
        raise StateError("buttonBar and iconLists must be lists")
    if len(dock) > DOCK_SLOTS:
        raise StateError(f"the dock holds at most {DOCK_SLOTS} items, got {len(dock)}")
    for pos, item in enumerate(dock, 1):
        _check_item(item, f"dock/{pos}", for_write=for_write)
    for page_no, page in enumerate(pages, 1):
        if not isinstance(page, list):
            raise StateError(f"page {page_no} must be a list")
        used = 0
        for pos, item in enumerate(page, 1):
            _check_item(item, f"page {page_no}/{pos}", for_write=for_write)
            used += cell_count(item)
        if used > PAGE_CELLS:
            raise StateError(f"page {page_no} is over capacity: {used}/{PAGE_CELLS} cells")
    if ignored is not None:
        if not isinstance(ignored, list) or any(not isinstance(x, str) or not x for x in ignored):
            raise StateError("ignored must contain non-empty bundle identifier strings")
        if len(set(ignored)) != len(ignored):
            raise StateError("ignored contains duplicate bundle identifiers")


def _check_no_overlap(payload: Mapping[str, Any]) -> None:
    overlap = visible_apps(dict(payload)) & set(payload["ignored"])
    if overlap:
        raise StateError(
            "apps on the home screen cannot also be in ignored: " + ", ".join(sorted(overlap))
        )


def validate_plan(plan: Any) -> None:
    """Check that ``apply`` input is a planner-made, structurally sound payload."""
    if not isinstance(plan, dict):
        raise StateError("a plan must be a dictionary")
    if set(plan) != {*PAYLOAD_KEYS, PLAN_META_KEY}:
        raise StateError(
            f"a plan must contain exactly buttonBar, iconLists, ignored and {PLAN_META_KEY}"
        )
    meta = plan[PLAN_META_KEY]
    if not isinstance(meta, Mapping) or meta.get("version") != PLAN_FORMAT_VERSION:
        raise StateError(f"the plan's {PLAN_META_KEY} version is missing or unsupported")
    source = meta.get("source_fingerprint")
    if (
        not isinstance(source, str)
        or len(source) != 64
        or any(c not in "0123456789abcdef" for c in source)
    ):
        raise StateError("the plan's source fingerprint is missing or invalid")
    _check_sections(plan["buttonBar"], plan["iconLists"], plan["ignored"])
    _check_no_overlap(plan)


def validate_backup(state: Any) -> None:
    """Check that ``restore`` input is a list-form or dictionary-form icon state."""
    if isinstance(state, list):
        if not state:
            raise StateError("the list-form backup has no dock section ([0])")
        if any(not isinstance(section, list) for section in state):
            raise StateError("every section of a list-form backup must be a list of items")
        _check_sections(state[0], state[1:])
        return
    if isinstance(state, dict):
        if set(state) != PAYLOAD_KEYS:
            raise StateError(
                "a dictionary backup must contain exactly buttonBar, iconLists and ignored"
            )
        _check_sections(state["buttonBar"], state["iconLists"], state["ignored"])
        return
    raise StateError("a backup must be a list-form or dictionary-form icon state")


def validate_write_payload(payload: Any) -> None:
    """Gatekeeper for the device boundary: only the full safe dictionary may pass."""
    if not isinstance(payload, dict):
        raise StateError("the write payload must be the safe dictionary, not a list")
    if set(payload) != PAYLOAD_KEYS:
        raise StateError("the write payload must contain exactly buttonBar, iconLists and ignored")
    _check_sections(payload["buttonBar"], payload["iconLists"], payload["ignored"], for_write=True)
    _check_no_overlap(payload)


def page_usage(page: Iterable[Any]) -> int:
    return sum(cell_count(item) for item in page)
