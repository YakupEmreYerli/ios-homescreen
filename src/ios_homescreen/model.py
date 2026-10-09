"""A JSON-friendly view of a home screen, and the way back to a layout document.

:func:`describe` turns a read snapshot into plain dicts and lists (names, kinds, sizes,
cell counts, App Library contents) that ``json.dumps`` accepts. A client edits the
``dock`` and ``pages`` lists and sends them back; :func:`to_document` turns that into
the layout document :func:`ios_homescreen.planner.plan_layout` takes. Item ``id`` values
are the same ones the TOML layout uses, so they stay stable between the two.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .report import library_apps
from .state import (
    DOCK_SLOTS,
    PAGE_CELLS,
    WIDGET_CELLS,
    cell_count,
    fingerprint,
    folder_pages,
    item_id,
    item_kind,
    page_usage,
    split_state,
)


def _app_name(apps: Mapping[str, Any], ident: str) -> str:
    meta = apps.get(ident)
    if isinstance(meta, Mapping) and meta.get("name"):
        return str(meta["name"])
    return ident


def _view(item: Any, apps: Mapping[str, Any], folder_no: list[int]) -> dict[str, Any]:
    kind = item_kind(item)
    data = item if isinstance(item, Mapping) else {}
    name = data.get("displayName")
    if kind == "folder":
        folder_no[0] += 1
        return {
            "type": "folder",
            # Folders have no identifier on the device; this one is stable per read.
            "id": f"folder-{folder_no[0]}",
            "name": str(item.get("displayName", "")),
            "cells": 1,
            "pages": [[_view(x, apps, folder_no) for x in page] for page in folder_pages(item)],
        }
    ident = item_id(item)
    view: dict[str, Any] = {"type": kind, "id": ident, "cells": cell_count(item)}
    if kind == "app":
        view["name"] = str(name or _app_name(apps, ident))
        view["offloaded"] = isinstance(item, Mapping) and not item.get("bundleIdentifier")
    elif kind == "widget":
        elements = [e for e in data.get("elements", []) or [] if isinstance(e, Mapping)]
        sources = [
            str(e.get("containerBundleIdentifier") or e.get("bundleIdentifier"))
            for e in elements
            if e.get("containerBundleIdentifier") or e.get("bundleIdentifier")
        ]
        container = data.get("containerBundleIdentifier")
        view["size"] = str(data.get("gridSize", "small"))
        view["stack"] = bool(elements)
        view["apps"] = sources or ([str(container)] if container else [])
        view["name"] = str(name or ", ".join(_app_name(apps, a) for a in view["apps"]) or "Widget")
    elif kind == "webclip":
        view["name"] = str(name or "Web clip")
        view["url"] = str(data.get("webClipURL", ""))
    else:  # webapp
        owner = str(data.get("bundleIdentifier"))
        view["app"] = owner
        view["name"] = str(name or f"{_app_name(apps, owner)} web app")
    return view


def describe(read: Mapping[str, Any]) -> dict[str, Any]:
    """JSON-ready view of a read snapshot."""
    state = read["state"]
    apps: Mapping[str, Any] = read.get("apps", {}) or {}
    dock, pages = split_state(state)
    folder_no = [0]
    return {
        "device": {k: v for k, v in (read.get("device") or {}).items() if isinstance(v, str)},
        "fingerprint": fingerprint(state),
        "limits": {
            "dock_items": DOCK_SLOTS,
            "page_cells": PAGE_CELLS,
            "widget_cells": dict(WIDGET_CELLS),
        },
        "dock": [_view(item, apps, folder_no) for item in dock],
        "pages": [
            {"cells": page_usage(page), "items": [_view(item, apps, folder_no) for item in page]}
            for page in pages
        ],
        "library": [
            {
                "type": "app",
                "id": ident,
                "name": _app_name(apps, ident),
                "app_type": str(apps[ident].get("type", "")),
            }
            for ident in library_apps(state, apps)
        ],
    }


def _entry(item: Any) -> Any:
    if isinstance(item, str):
        return item
    if not isinstance(item, Mapping):
        return item  # the planner reports it with a location
    kind = item.get("type")
    if kind == "folder":
        pages = item.get("pages")
        if pages is None and "items" in item:
            pages = [item["items"]]
        return {
            "type": "folder",
            "name": item.get("name"),
            "pages": [[_entry(x) for x in page] for page in pages]
            if isinstance(pages, list) and all(isinstance(p, list) for p in pages)
            else pages,
        }
    if kind == "app":
        return item.get("id")
    return {"type": kind, "id": item.get("id")}


def _page_items(page: Any) -> Any:
    if isinstance(page, Mapping):
        return page.get("items", [])
    return page


def to_document(layout: Mapping[str, Any]) -> dict[str, Any]:
    """Layout document for the planner from a (possibly edited) :func:`describe` view.

    Accepts ``{"dock": [...], "pages": [{"items": [...]}, ...]}`` or pages given as plain
    lists. Display-only keys (``name``, ``cells``, ``size``...) are dropped.
    """
    pages = layout.get("pages", [])
    return {
        "dock": {"items": [_entry(x) for x in layout.get("dock", []) or []]},
        "pages": [
            {"items": [_entry(x) for x in _page_items(page) or []]}
            for page in (pages if isinstance(pages, list) else [])
        ],
    }
