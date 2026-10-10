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


def _folders(view: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = [*view.get("dock", []), *(i for p in view.get("pages", []) for i in _page_items(p))]
    return [item for item in items if isinstance(item, dict) and item.get("type") == "folder"]


def _contents(folder: Mapping[str, Any]) -> set[str]:
    return {x["id"] for page in folder.get("pages", []) for x in page if isinstance(x, Mapping)}


def match_folders(before: Mapping[str, Any], after: dict[str, Any], prefix: str = "new") -> None:
    """Give the folders of ``after`` the ids of the matching folders of ``before``.

    Folders have no id on the phone, so two views made separately number them on their
    own. A folder keeps its id when it keeps its name, or else when it shares the most
    items with a folder that was renamed; other folders get ``PREFIX-...`` ids.
    """
    old = _folders(before)
    new = _folders(after)
    taken: set[str] = set()
    matched: dict[int, str] = {}
    for index, folder in enumerate(new):
        for candidate in old:
            if candidate["id"] not in taken and candidate.get("name") == folder.get("name"):
                matched[index] = candidate["id"]
                taken.add(candidate["id"])
                break
    for index, folder in enumerate(new):
        if index in matched:
            continue
        inside = _contents(folder)
        best, overlap = None, 0
        for candidate in old:
            shared = len(inside & _contents(candidate))
            if candidate["id"] not in taken and shared > overlap:
                best, overlap = candidate, shared
        if best is not None:
            matched[index] = best["id"]
            taken.add(best["id"])
    for index, folder in enumerate(new):
        folder["id"] = matched.get(index) or f"{prefix}-{folder['id']}"


# --------------------------------------------------------------------------- changes

_SPECIAL_KINDS = frozenset({"widget", "webclip", "webapp"})


def _view_pages(layout: Mapping[str, Any]) -> list[list[Any]]:
    pages = layout.get("pages", [])
    if not isinstance(pages, list):
        return []
    return [list(_page_items(page) or []) for page in pages]


def _placements(layout: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list]]:
    """Where every item of a view is: ``{id: placement}`` and ``{container: [ids]}``.

    A container is the dock, one page, or one folder (all of its pages in order).
    Empty pages are skipped, so page numbers match what gets written.
    """
    places: dict[str, dict[str, Any]] = {}
    containers: dict[str, list[str]] = {}

    def walk(items: list[Any], where: dict[str, Any], key: str) -> None:
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                continue
            ident = item["id"]
            containers.setdefault(key, []).append(ident)
            places[ident] = {
                "item": item,
                "where": {**where, "index": len(containers[key])},
                "container": key,
            }
            if item.get("type") == "folder":
                inner = {**where, "folder": str(item.get("name", "")), "folder_id": ident}
                for folder_page in item.get("pages", []) or []:
                    walk(list(folder_page or []), inner, f"folder:{ident}")

    walk(list(layout.get("dock", []) or []), {"section": "dock"}, "dock")
    page_no = 0
    for page in _view_pages(layout):
        if not page:
            continue
        page_no += 1
        walk(page, {"section": "page", "page": page_no}, f"page:{page_no}")
    return places, containers


def _kept_in_order(before: list[str], after: list[str]) -> set[str]:
    """Ids that keep their relative order (a longest common subsequence)."""
    if not before or not after:
        return set()
    rows, cols = len(before), len(after)
    table = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            table[i][j] = (
                table[i + 1][j + 1] + 1
                if before[i] == after[j]
                else max(table[i + 1][j], table[i][j + 1])
            )
    kept, i, j = set(), 0, 0
    while i < rows and j < cols:
        if before[i] == after[j]:
            kept.add(before[i])
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return kept


def _subject(item: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "type": item.get("type", "app"), "name": str(item.get("name", ""))}


def describe_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What changes between two :func:`describe` views (``after`` is usually edited).

    Each change is a dict with a ``kind`` and the item's ``id``, ``type`` and ``name``:
    ``added`` (from the App Library), ``moved`` (to another place), ``reordered``
    (same place, new order), ``to_library``, ``removed`` (a widget, web clip or web app
    that will be gone), ``folder_created``, ``folder_renamed``, ``folder_deleted``, and
    ``pages`` when the number of pages changes. ``from`` and ``to`` say where, with
    1-based ``page`` and ``index`` and the folder's ``name`` when inside one. Folders
    are matched by ``id``; folders a client creates need ids of their own.
    """
    old, old_containers = _placements(before)
    new, new_containers = _placements(after)
    in_order = {
        key: _kept_in_order(
            [i for i in old_containers.get(key, []) if new.get(i, {}).get("container") == key],
            [i for i in ids if old.get(i, {}).get("container") == key],
        )
        for key, ids in new_containers.items()
    }
    placed: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for ident, now in new.items():
        item = now["item"]
        was = old.get(ident)
        is_folder = item.get("type") == "folder"
        if was is None:
            kind = "folder_created" if is_folder else "added"
            placed.append({"kind": kind, **_subject(item), "to": now["where"]})
            continue
        if was["container"] != now["container"]:
            placed.append(
                {"kind": "moved", **_subject(item), "from": was["where"], "to": now["where"]}
            )
        elif ident not in in_order.get(now["container"], set()):
            placed.append(
                {"kind": "reordered", **_subject(item), "from": was["where"], "to": now["where"]}
            )
        if is_folder and str(was["item"].get("name", "")) != str(item.get("name", "")):
            later.append(
                {
                    "kind": "folder_renamed",
                    **_subject(item),
                    "old_name": str(was["item"].get("name", "")),
                }
            )
    for ident, was in old.items():
        if ident in new:
            continue
        item = was["item"]
        kind = item.get("type", "app")
        if kind == "folder":
            later.append({"kind": "folder_deleted", **_subject(item), "from": was["where"]})
        elif kind in _SPECIAL_KINDS:
            later.append({"kind": "removed", **_subject(item), "from": was["where"]})
        else:
            later.append({"kind": "to_library", **_subject(item), "from": was["where"]})
    pages_before = sum(1 for page in _view_pages(before) if page)
    pages_after = sum(1 for page in _view_pages(after) if page)
    if pages_before != pages_after:
        later.append({"kind": "pages", "before": pages_before, "after": pages_after})
    return placed + later
