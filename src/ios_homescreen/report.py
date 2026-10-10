"""Plain-text summaries: what a layout holds and what a write would change."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .state import (
    app_type,
    counts_for_home_screen,
    folder_pages,
    is_folder,
    is_hidden_app,
    item_id,
    item_kind,
    split_state,
    visible_apps,
)


def library_apps(state: Any, apps: Mapping[str, Any]) -> list[str]:
    """Installed User/System apps that are not on the home screen (App Library only).

    Hidden system services are left out: iOS shows them nowhere.
    """
    shown = visible_apps(state)
    return sorted(
        ident
        for ident, meta in apps.items()
        if ident not in shown and counts_for_home_screen(meta) and not is_hidden_app(meta)
    )


def overview(state: Any, apps: Mapping[str, Any]) -> str:
    dock, pages = split_state(state)
    return (
        f"dock {len(dock)} items, {len(pages)} pages, "
        f"{len(library_apps(state, apps))} apps only in the App Library"
    )


def app_places(read: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every app a person can see, by name, and where it is.

    ``where`` is ``{"section": "dock" | "page" | "library"}`` plus ``page`` and ``index``
    (1-based, counting every item on the page in order, widgets included) and, inside a
    folder, ``folder``, ``folder_page`` and ``folder_index``.
    """
    state = read["state"]
    apps: Mapping[str, Any] = read.get("apps", {}) or {}
    found: dict[str, dict[str, Any]] = {}

    def add(item: Any, where: dict[str, Any]) -> None:
        if item_kind(item) != "app":
            return
        ident = item_id(item)
        meta = apps.get(ident)
        name = (
            (isinstance(item, Mapping) and item.get("displayName"))
            or (isinstance(meta, Mapping) and meta.get("name"))
            or ident
        )
        found.setdefault(
            ident,
            {
                "name": str(name),
                "id": ident,
                "type": app_type(meta) or "",
                "offloaded": isinstance(item, Mapping) and not item.get("bundleIdentifier"),
                "where": where,
            },
        )

    def place(item: Any, where: dict[str, Any]) -> None:
        if not is_folder(item):
            add(item, where)
            return
        for folder_page, page in enumerate(folder_pages(item), 1):
            for position, inner in enumerate(page, 1):
                add(
                    inner,
                    {
                        **where,
                        "folder": str(item.get("displayName", "")),
                        "folder_page": folder_page,
                        "folder_index": position,
                    },
                )

    dock, pages = split_state(state)
    for position, item in enumerate(dock, 1):
        place(item, {"section": "dock", "index": position})
    for page_no, page in enumerate(pages, 1):
        for position, item in enumerate(page, 1):
            place(item, {"section": "page", "page": page_no, "index": position})
    for ident in library_apps(state, apps):
        meta = apps[ident]
        found.setdefault(
            ident,
            {
                "name": str(meta.get("name", ident)),
                "id": ident,
                "type": app_type(meta) or "",
                "offloaded": False,
                "where": {"section": "library"},
            },
        )
    return sorted(found.values(), key=lambda app: (app["name"].casefold(), app["id"]))


# --------------------------------------------------------------------------- changes

_SUBJECT_WIDTH = 30


def _subject(change: Mapping[str, Any]) -> str:
    name = str(change.get("name") or change.get("id") or "?")
    kind = change.get("type")
    if kind == "folder":
        return f'Folder "{name}"'
    if kind == "widget" and not name.lower().endswith("widget"):
        return f"{name} widget"
    return name


def _container(where: Mapping[str, Any]) -> str:
    if where.get("folder") is not None:
        return f'the "{where["folder"]}" folder'
    if where.get("section") == "dock":
        return "the dock"
    return f"page {where.get('page', '?')}"


def _place(where: Mapping[str, Any] | None) -> str:
    if not where:
        return "?"
    text = _container(where)
    return f"{text}, position {where['index']}" if where.get("index") else text


def _what(change: Mapping[str, Any]) -> str:
    kind = change["kind"]
    to, was = change.get("to"), change.get("from")
    if kind == "added" and change.get("type", "app") == "app":
        return f"comes from the App Library to {_place(to)}"
    if kind == "added":
        return f"comes back on {_place(to)}"
    if kind == "moved":
        return f"moves from {_container(was or {})} to {_place(to)}"
    if kind == "reordered":
        return f"moves to position {(to or {}).get('index', '?')} in {_container(to or {})}"
    if kind == "to_library":
        return "goes to the App Library (stays installed)"
    if kind == "removed":
        return "is removed; add it again on the iPhone to get it back"
    if kind == "folder_created":
        return f"is a new folder on {_place(to)}"
    if kind == "folder_renamed":
        return f'was "{change.get("old_name", "")}"'
    if kind == "folder_deleted":
        return "is removed (its apps are listed on their own)"
    return kind


def change_lines(changes: Iterable[Mapping[str, Any]]) -> list[str]:
    """One aligned line per change from :func:`ios_homescreen.model.describe_changes`."""
    rows: list[tuple[str, str]] = []
    for change in changes:
        if change["kind"] == "pages":
            rows.append(("Pages", f"{change['before']} become {change['after']}"))
        else:
            rows.append((_subject(change), _what(change)))
    width = min(_SUBJECT_WIDTH, max((len(subject) for subject, _ in rows), default=0))
    lines = []
    for subject, what in rows:
        if len(subject) > width:
            subject = subject[: width - 1] + "…"
        lines.append(f"  {subject.ljust(width)}  {what}")
    return lines


def change_summary(changes: Iterable[Mapping[str, Any]]) -> str:
    """``3 moved, 1 added and 1 to the App Library.`` or ``No changes.``"""
    changes = list(changes)

    def count(*kinds: str) -> int:
        return sum(1 for change in changes if change["kind"] in kinds)

    parts = []
    for number, label in (
        (count("moved", "reordered"), "moved"),
        (count("added", "folder_created"), "added"),
        (count("to_library"), "to the App Library"),
        (count("removed"), "removed"),
        (count("folder_renamed"), "renamed"),
        (count("folder_deleted"), "folders removed"),
    ):
        if number:
            parts.append(f"{number} {label}")
    if not parts:
        return "No changes." if not changes else "Pages change."
    text = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    return text[0].upper() + text[1:] + "."
