"""Turn a pull snapshot into an editable TOML layout file."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .report import library_apps
from .state import (
    PAGE_CELLS,
    StateError,
    cell_count,
    folder_pages,
    item_id,
    item_kind,
    page_usage,
    split_state,
)

HEADER = """\
# ios-homescreen layout. Edit it, then run `ios-homescreen check` to see what would
# change and `ios-homescreen push` to write it to the iPhone.
#
# Items are in home screen order: left to right, top to bottom.
# Apps: "bundle.id" or the app's name. Apps you leave out go to the App Library; the
# end of this file lists the apps that are only there now.
# Widgets, web clips and Safari web apps keep the id they have on the phone. They can
# be moved, not created. Widgets can also be removed (check and push --allow-removal);
# web clips and web apps only on the phone.
# Folders: { type = "folder", name = "...", items = [...] }, or pages = [[...], [...]]
# for a folder with several pages. Folders hold apps, web clips and web apps.
# Limits: dock 4 items. A page has 24 cells: an app, folder, web clip or web app
# takes 1, a widget takes 4 (small), 8 (medium) or 16 (large).
"""


def _quote(value: str) -> str:
    # A JSON string is a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def _comment(text: str) -> str:
    return " ".join(str(text).split())


class _Names:
    def __init__(self, apps: Mapping[str, Any]):
        self.apps = apps

    def of_bundle(self, ident: str) -> str:
        meta = self.apps.get(ident)
        if isinstance(meta, Mapping) and meta.get("name"):
            return str(meta["name"])
        return ident

    def app(self, item: Any) -> str:
        if isinstance(item, Mapping) and item.get("displayName"):
            return str(item["displayName"])
        return self.of_bundle(item_id(item))


def _widget_comment(item: Mapping[str, Any], names: _Names) -> str:
    size = str(item.get("gridSize", "small"))
    cells = cell_count(item)
    elements = [e for e in item.get("elements", []) or [] if isinstance(e, Mapping)]
    if item.get("iconType") == "custom" and elements:
        sources = [
            names.of_bundle(str(e.get("containerBundleIdentifier") or e.get("bundleIdentifier")))
            for e in elements
        ]
        return f"widget stack ({size}, {cells} cells): " + ", ".join(sources)
    source = item.get("displayName") or names.of_bundle(
        str(item.get("containerBundleIdentifier") or item.get("bundleIdentifier") or "?")
    )
    return f"widget ({size}, {cells} cells): {source}"


def _entry(item: Any, names: _Names) -> tuple[str, str]:
    """Inline TOML value and trailing comment for a non-folder item."""
    kind = item_kind(item)
    ident = item_id(item)
    if kind == "app":
        offloaded = isinstance(item, Mapping) and not item.get("bundleIdentifier")
        return _quote(ident), names.app(item) + (" (offloaded)" if offloaded else "")
    if kind == "widget":
        return f'{{ type = "widget", id = {_quote(ident)} }}', _widget_comment(item, names)
    if kind == "webapp":
        owner = names.of_bundle(str(item.get("bundleIdentifier")))
        label = f"web app ({owner})"
        if item.get("displayName"):
            label += f": {item['displayName']}"
        return f'{{ type = "webapp", id = {_quote(ident)} }}', label
    url = item.get("webClipURL", "")
    name = item.get("displayName") or "web clip"
    return f'{{ type = "webclip", id = {_quote(ident)} }}', f"web clip: {name} {url}".strip()


def _line(indent: str, value: str, comment: str) -> str:
    return f"{indent}{value},  # {_comment(comment)}"


def _folder_lines(item: Mapping[str, Any], names: _Names, indent: str) -> list[str]:
    pages = folder_pages(item)
    head = f'{indent}{{ type = "folder", name = {_quote(str(item.get("displayName", "")))}, '

    def inner_lines(page: list[Any], inner_indent: str) -> list[str]:
        lines = []
        for inner in page:
            if item_kind(inner) == "folder":
                raise StateError("folders inside folders cannot be exported")
            lines.append(_line(inner_indent, *_entry(inner, names)))
        return lines

    if len(pages) <= 1:
        return [
            head + "items = [",
            *inner_lines(pages[0] if pages else [], indent + "  "),
            f"{indent}] }},",
        ]
    lines = [head + "pages = ["]
    for page in pages:
        lines.append(f"{indent}  [")
        lines.extend(inner_lines(page, indent + "    "))
        lines.append(f"{indent}  ],")
    lines.append(f"{indent}] }},")
    return lines


def _items_block(items: list[Any], names: _Names) -> list[str]:
    if not items:
        return ["items = []"]
    lines = ["items = ["]
    for item in items:
        if item_kind(item) == "folder":
            lines.extend(_folder_lines(item, names, "  "))
        else:
            lines.append(_line("  ", *_entry(item, names)))
    lines.append("]")
    return lines


def pull_source(read: Mapping[str, Any]) -> str:
    """``Ada's iPhone (iPhone 15, iOS 26.0) on 2026-10-10 14:44``: where and when."""
    device = read.get("device") or {}
    version = f"iOS {device['ios_version']}" if device.get("ios_version") else None
    details = ", ".join(str(x) for x in (device.get("model"), version) if x)
    name = str(device.get("name") or "the iPhone")
    text = f"{name} ({details})" if details else name
    created = read.get("created")
    if isinstance(created, datetime):
        local = created.replace(tzinfo=UTC).astimezone() if created.tzinfo is None else created
        text += f" on {local:%Y-%m-%d %H:%M}"
    return text


def pull_note(read: Mapping[str, Any]) -> str:
    """``Pulled from Ada's iPhone (iPhone 15, iOS 26.0) on 2026-10-10 14:44.``"""
    return f"Pulled from {pull_source(read)}."


def _library_block(read: Mapping[str, Any], names: _Names) -> list[str]:
    apps = read.get("apps", {}) or {}
    only = sorted(
        library_apps(read["state"], apps), key=lambda i: (names.of_bundle(i).casefold(), i)
    )
    if not only:
        return []
    lines = [
        "",
        f"# Only in the App Library ({len(only)}). To put one on the home screen, copy it",
        "# into a page above:",
    ]
    lines.extend(f"#   {_quote(ident)},  # {_comment(names.of_bundle(ident))}" for ident in only)
    return lines


def export_layout(
    read: Mapping[str, Any], *, pull: str | None = None, note: str | None = None
) -> str:
    """A complete layout file that plans back to the exact same layout.

    ``pull`` names the snapshot in a ``[pull]`` table so check and push can find it;
    ``note`` is a comment under the header, such as :func:`pull_note`.
    """
    dock, pages = split_state(read["state"])
    names = _Names(read.get("apps", {}) or {})
    lines = [HEADER.rstrip("\n")]
    if note:
        lines.append(f"#\n# {_comment(note)}")
    if pull:
        lines += [
            "",
            "# check and push compare this file with the phone layout it was pulled from.",
            "# Leave this table as it is.",
            "[pull]",
            f"snapshot = {_quote(pull)}",
        ]
    lines += ["", "[dock]", *_items_block(dock, names)]
    for page_no, page in enumerate(pages, 1):
        lines += [
            "",
            f"# Page {page_no} ({page_usage(page)}/{PAGE_CELLS} cells)",
            "[[pages]]",
            *_items_block(page, names),
        ]
    lines += _library_block(read, names)
    return "\n".join(lines) + "\n"
