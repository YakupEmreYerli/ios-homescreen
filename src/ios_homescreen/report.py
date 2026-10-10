"""Human-readable summaries and offline layout diffs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .state import (
    PAGE_CELLS,
    counts_for_home_screen,
    folder_pages,
    is_folder,
    is_hidden_app,
    item_id,
    item_kind,
    item_name,
    page_usage,
    same_layout,
    split_state,
    visible_apps,
)


def _app_meta(meta: Any, key: str, fallback: str) -> str:
    return str(meta.get(key, fallback)) if isinstance(meta, Mapping) else fallback


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


def read_summary(
    state: Any,
    apps: Mapping[str, Any],
    *,
    device: Mapping[str, Any] | None = None,
    raw_v3_error: str | None = None,
) -> str:
    dock, pages = split_state(state)
    lines = ["Home screen summary"]
    if device:
        described = ", ".join(
            str(device[key]) for key in ("name", "model", "ios_version") if device.get(key)
        )
        if described:
            lines.append(f"Device: {described}")
    lines += ["", "Dock: " + (", ".join(item_name(x) for x in dock) or "empty")]
    for page_no, page in enumerate(pages, 1):
        lines.append(f"\nPage {page_no}: {page_usage(page)}/{PAGE_CELLS} cells")
        for item in page:
            kind = item_kind(item)
            if kind == "folder":
                lines.append(f"  Folder: {item_name(item)}")
                for folder_page_no, folder_page in enumerate(folder_pages(item), 1):
                    names = ", ".join(item_name(x) for x in folder_page)
                    lines.append(f"    page {folder_page_no}: {names}")
            elif kind == "widget":
                lines.append(f"  Widget: {item_name(item)} [{item.get('gridSize', 'small')}]")
            elif kind == "webclip":
                lines.append(f"  Web clip: {item_name(item)} ({item_id(item)})")
            elif kind == "webapp":
                lines.append(f"  Web app of {item.get('bundleIdentifier')}: {item_id(item)}")
            else:
                lines.append(f"  App: {item_name(item)} ({item_id(item)})")
    hidden = library_apps(state, apps)
    lines.append(f"\nOnly in the App Library ({len(hidden)}):")
    for ident in hidden:
        meta = apps[ident]
        name = _app_meta(meta, "name", ident)
        kind = _app_meta(meta, "type", "?")
        lines.append(f"  {name} - {ident} [{kind}]")
    if raw_v3_error is not None:
        lines.append(f"\nRaw format version 3 read failed: {raw_v3_error}")
    return "\n".join(lines) + "\n"


def overview(state: Any, apps: Mapping[str, Any]) -> str:
    dock, pages = split_state(state)
    return (
        f"dock {len(dock)} items, {len(pages)} pages, "
        f"{len(library_apps(state, apps))} apps only in the App Library"
    )


def _locations(state: Any) -> dict[str, str]:
    dock, pages = split_state(state)
    found: dict[str, str] = {}

    def add(item: Any, where: str) -> None:
        if is_folder(item):
            for folder_page in folder_pages(item):
                for inner in folder_page:
                    found[item_id(inner)] = f"{where} / folder {item_name(item)!r}"
            return
        found[item_id(item)] = where

    for item in dock:
        add(item, "dock")
    for page_no, page in enumerate(pages, 1):
        for item in page:
            add(item, f"page {page_no}")
    return found


def _label(item: Any) -> str:
    if is_folder(item):
        inner = ",".join(item_id(x) for folder_page in folder_pages(item) for x in folder_page)
        return f"folder:{item_name(item)}[{inner}]"
    if item_kind(item) == "widget":
        return f"{item_id(item)}/{item.get('gridSize', 'small')}"
    return item_id(item)


def diff_text(before: Any, after: Any) -> str:
    """Explain moves, additions, removals and order changes between two layouts."""
    old, new = _locations(before), _locations(after)
    lines: list[str] = []
    for ident in sorted(old.keys() & new.keys()):
        if old[ident] != new[ident]:
            lines.append(f"Moved: {ident}: {old[ident]} -> {new[ident]}")
    lines.extend(f"Added: {ident}: {new[ident]}" for ident in sorted(new.keys() - old.keys()))
    lines.extend(f"Removed: {ident}: {old[ident]}" for ident in sorted(old.keys() - new.keys()))
    if not same_layout(before, after):
        old_dock, old_pages = split_state(before)
        new_dock, new_pages = split_state(after)
        old_sections = {"dock": old_dock} | {f"page {n}": p for n, p in enumerate(old_pages, 1)}
        new_sections = {"dock": new_dock} | {f"page {n}": p for n, p in enumerate(new_pages, 1)}
        lines.append("Order or structure changed:")
        for name in [*dict.fromkeys([*old_sections, *new_sections])]:
            was = [_label(x) for x in old_sections.get(name, [])]
            now = [_label(x) for x in new_sections.get(name, [])]
            if (name in old_sections) != (name in new_sections) or was != now:
                lines.append(f"  {name}:")
                lines.append("    before: " + (", ".join(was) if name in old_sections else "-"))
                lines.append("    after:  " + (", ".join(now) if name in new_sections else "-"))
    return "\n".join(lines or ["No layout differences."]) + "\n"
