"""Resolve a layout document against a read snapshot into a safe write payload.

A layout document is the parsed TOML file (or the same structure built from JSON):
``{"dock": {"items": [...]}, "pages": [{"items": [...]}, ...]}``. Planning is offline:
it never talks to a device.

Problems are collected rather than raised one by one, each with a stable ``code`` and
a location, so the CLI can list them all and a UI can point at the item.
"""

from __future__ import annotations

import tomllib
from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .report import diff_text
from .snapshots import utc_now
from .state import (
    DOCK_SLOTS,
    PAGE_CELLS,
    PLAN_FORMAT_VERSION,
    PLAN_META_KEY,
    StateError,
    fingerprint,
    folder_pages,
    is_folder,
    item_id,
    item_kind,
    iter_items,
    page_usage,
    safe_payload,
    visible_apps,
)

ITEM_TYPES = ("app", "folder", "widget", "webclip", "webapp")

# Opaque items SpringBoard made; a layout can move them but not create them.
UNRECREATABLE = frozenset({"widget", "webclip", "webapp"})

_ITEM_KEYS = {
    "app": {"type", "id"},
    "widget": {"type", "id"},
    "webclip": {"type", "id"},
    "webapp": {"type", "id"},
    "folder": {"type", "name", "items", "pages"},
}
_TOP_LEVEL_KEYS = {"dock", "pages"}


@dataclass(frozen=True)
class Location:
    """Where an issue is. Page, item and folder numbers count from 1."""

    section: str = "layout"
    """``layout``, ``dock`` or ``page``."""
    page: int | None = None
    item: int | None = None
    folder: str | None = None
    folder_page: int | None = None
    folder_item: int | None = None

    def inside_folder(self, name: str, page: int, item: int) -> Location:
        return Location(self.section, self.page, self.item, name, page, item)

    def __str__(self) -> str:
        if self.section == "layout":
            return "layout"
        text = "dock" if self.section == "dock" else f"page {self.page}"
        if self.item is not None:
            text += f", item {self.item}"
        if self.folder is not None:
            text += f" (folder {self.folder!r}"
            if self.folder_item is not None:
                text += f", page {self.folder_page}, item {self.folder_item}"
            text += ")"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class LayoutIssue:
    code: str
    message: str
    location: Location = field(default_factory=Location)
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.location.section == "layout":
            return self.message
        return f"{self.location}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "location": self.location.to_dict(),
            "details": dict(self.details),
        }


class LayoutError(ValueError):
    """The layout cannot become a safe payload. ``issues`` lists every problem found."""

    def __init__(self, issues: list[LayoutIssue] | tuple[LayoutIssue, ...]):
        self.issues = tuple(issues)
        if len(self.issues) == 1:
            text = str(self.issues[0])
        else:
            text = f"{len(self.issues)} problems in the layout:\n" + "\n".join(
                f"  - {issue}" for issue in self.issues
            )
        super().__init__(text)

    @property
    def code(self) -> str:
        return self.issues[0].code

    def to_dict(self) -> dict[str, Any]:
        return {"issues": [issue.to_dict() for issue in self.issues]}


def _fail(code: str, message: str, where: Location | None = None, **details: Any) -> LayoutError:
    return LayoutError([LayoutIssue(code, message, where or Location(), details)])


@dataclass(frozen=True)
class Plan:
    payload: dict[str, Any]
    changes: str
    to_library: tuple[str, ...]
    to_home_screen: tuple[str, ...]
    removed: tuple[str, ...]
    ignored_count: int

    def summary(self) -> dict[str, Any]:
        """JSON-friendly facts about the plan (the payload itself is binary-plist data)."""
        return {
            "to_library": list(self.to_library),
            "to_home_screen": list(self.to_home_screen),
            "removed": list(self.removed),
            "ignored_count": self.ignored_count,
            "changes": self.changes,
        }


def _app_name(meta: Any) -> str | None:
    if not isinstance(meta, Mapping):
        return None
    name = meta.get("name") or meta.get("CFBundleDisplayName") or meta.get("CFBundleName")
    return str(name) if name else None


class _Resolver:
    """Look up layout references in the read: raw items, installed apps and names."""

    def __init__(self, read: Mapping[str, Any]):
        self.installed: Mapping[str, Any] = read.get("apps", {}) or {}
        self.raw: dict[str, Any] = {}
        self.names: dict[str, set[str]] = defaultdict(set)
        for item in iter_items(read["state"]):
            if is_folder(item):
                continue
            try:
                ident = item_id(item)
            except StateError as exc:
                raise _fail("read_item_without_id", f"the read is unusable: {exc}") from exc
            self.raw[ident] = deepcopy(item)
            if isinstance(item, Mapping) and item.get("displayName") and item_kind(item) == "app":
                self.names[str(item["displayName"])].add(ident)
        for ident, meta in self.installed.items():
            name = _app_name(meta)
            if name:
                self.names[name].add(ident)

    def _is_app_id(self, ident: str) -> bool:
        return ident in self.installed or (
            ident in self.raw and item_kind(self.raw[ident]) == "app"
        )

    def _app_item(self, ident: str) -> Any:
        # Reuse the dictionary SpringBoard gave us; a new app gets the minimal form.
        raw = self.raw.get(ident)
        if raw is not None and item_kind(raw) == "app":
            return deepcopy(raw)
        return {"bundleIdentifier": ident, "displayIdentifier": ident}

    def app_by_id(self, ident: Any, where: Location) -> Any:
        if not isinstance(ident, str) or not ident:
            raise _fail("missing_id", "an app needs a non-empty id", where)
        if not self._is_app_id(ident):
            raise _fail("unknown_app", f"unknown app id {ident!r}", where, id=ident)
        return self._app_item(ident)

    def app_by_ref(self, ref: str, where: Location) -> Any:
        """A bare string: a bundle id first, otherwise an app name."""
        if not ref:
            raise _fail("missing_id", "empty app reference", where)
        if self._is_app_id(ref):
            return self._app_item(ref)
        matches = {i for i in self.names.get(ref, set()) if self._is_app_id(i)}
        if not matches and ref in self.raw:
            kind = item_kind(self.raw[ref])
            raise _fail(
                "wrong_kind",
                f'{ref!r} is a {kind}, not an app; write {{ type = "{kind}", id = "{ref}" }}',
                where,
                id=ref,
                kind=kind,
            )
        if not matches:
            raise _fail("unknown_app", f"unknown app {ref!r}", where, id=ref)
        if len(matches) > 1:
            listed = sorted(matches)
            raise _fail(
                "ambiguous_name",
                f"{ref!r} matches several apps ({', '.join(listed)}); use the bundle id",
                where,
                name=ref,
                candidates=listed,
            )
        return self._app_item(next(iter(matches)))

    def existing(self, ident: Any, kind: str, where: Location) -> Any:
        if not isinstance(ident, str) or not ident:
            raise _fail("missing_id", f"a {kind} needs a non-empty id", where)
        item = self.raw.get(ident)
        if item is None:
            raise _fail(
                "unknown_item", f"unknown {kind} id {ident!r} (not in the read)", where, id=ident
            )
        if item_kind(item) != kind:
            raise _fail(
                "wrong_kind",
                f"{ident!r} is a {item_kind(item)}, not a {kind}",
                where,
                id=ident,
                kind=item_kind(item),
            )
        return deepcopy(item)


def load_layout(source: str | bytes | Path | Mapping[str, Any]) -> Mapping[str, Any]:
    """Parse TOML text or a file; a mapping (already parsed, or from JSON) passes through."""
    if isinstance(source, Mapping):
        return source
    try:
        if isinstance(source, Path):
            return tomllib.loads(source.read_text(encoding="utf-8"))
        if isinstance(source, bytes):
            source = source.decode("utf-8")
        return tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise _fail("invalid_toml", f"invalid TOML: {exc}") from exc


def _items_list(table: Any, where: Location) -> list[Any]:
    if not isinstance(table, Mapping):
        raise _fail("bad_structure", "must be a table", where)
    unknown = sorted(set(table) - {"items"})
    if unknown:
        raise _fail("unknown_key", f"unknown key(s) {', '.join(unknown)}", where, keys=unknown)
    items = table.get("items", [])
    if not isinstance(items, list):
        raise _fail("bad_structure", "items must be an array", where)
    return items


class _Planner:
    def __init__(self, read: Mapping[str, Any]):
        self.resolver = _Resolver(read)
        self.issues: list[LayoutIssue] = []

    def collect(self, error: LayoutError) -> None:
        self.issues.extend(error.issues)

    def resolve(
        self, entry: Any, where: Location, *, in_folder: bool = False, in_dock: bool = False
    ) -> Any:
        if isinstance(entry, str):
            return self.resolver.app_by_ref(entry, where)
        if not isinstance(entry, Mapping):
            raise _fail("bad_item", "an item must be an app string or an inline table", where)
        kind = entry.get("type")
        if kind not in _ITEM_KEYS:
            raise _fail(
                "bad_type",
                f"type must be one of {', '.join(ITEM_TYPES)} (got {kind!r})",
                where,
                type=kind,
            )
        unknown = sorted(set(entry) - _ITEM_KEYS[kind])
        if unknown:
            raise _fail(
                "unknown_key",
                f"unknown key(s) for a {kind}: {', '.join(unknown)}",
                where,
                keys=unknown,
            )
        if kind == "app":
            return self.resolver.app_by_id(entry.get("id"), where)
        if kind == "widget":
            if in_folder:
                raise _fail("widget_in_folder", "folders cannot contain widgets", where)
            if in_dock:
                raise _fail("widget_in_dock", "the dock cannot hold widgets", where)
        if kind in UNRECREATABLE:
            return self.resolver.existing(entry.get("id"), kind, where)
        return self.folder(entry, where, in_folder=in_folder)

    def folder(self, entry: Mapping[str, Any], where: Location, *, in_folder: bool) -> Any:
        if in_folder:
            raise _fail("nested_folder", "folders cannot contain folders", where)
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _fail("folder_name_missing", "a folder needs a non-empty name", where)
        name = name.strip()
        here = Location(where.section, where.page, where.item, name)
        if ("items" in entry) == ("pages" in entry):
            raise _fail(
                "folder_shape", "give a folder either items or pages, not both or neither", here
            )
        if "items" in entry:
            raw_pages = [entry["items"]]
            if not isinstance(raw_pages[0], list):
                raise _fail("bad_structure", "items must be an array", here)
        else:
            raw_pages = entry["pages"]
            if not isinstance(raw_pages, list) or any(not isinstance(p, list) for p in raw_pages):
                raise _fail("bad_structure", "pages must be an array of arrays", here)
        if not raw_pages or not any(raw_pages):
            raise _fail("empty_folder", "empty folders are not allowed", here)
        pages: list[list[Any]] = []
        for page_no, raw_page in enumerate(raw_pages, 1):
            if not raw_page:
                self.collect(_fail("empty_folder_page", f"folder page {page_no} is empty", here))
                continue
            page = []
            for pos, inner in enumerate(raw_page, 1):
                try:
                    page.append(
                        self.resolve(inner, where.inside_folder(name, page_no, pos), in_folder=True)
                    )
                except LayoutError as error:
                    self.collect(error)
            pages.append(page)
        # listType, not iconType: SpringBoard drops iconType folders without a word.
        return {"listType": "folder", "displayName": name, "iconLists": pages}

    def section(self, entries: list[Any], where: Location, *, in_dock: bool = False) -> list[Any]:
        items = []
        for pos, entry in enumerate(entries, 1):
            try:
                items.append(
                    self.resolve(entry, Location(where.section, where.page, pos), in_dock=in_dock)
                )
            except LayoutError as error:
                self.collect(error)
        return items


def _check_duplicates(dock: list[Any], pages: list[list[Any]]) -> list[LayoutIssue]:
    seen: dict[str, list[str]] = defaultdict(list)

    def add(item: Any, where: str) -> None:
        if is_folder(item):
            for folder_page in folder_pages(item):
                for inner in folder_page:
                    seen[item_id(inner)].append(f"{where} / folder {item['displayName']!r}")
        else:
            seen[item_id(item)].append(where)

    for item in dock:
        add(item, "dock")
    for page_no, page in enumerate(pages, 1):
        for item in page:
            add(item, f"page {page_no}")
    return [
        LayoutIssue(
            "duplicate_item",
            f"{ident} is used more than once ({', '.join(places)})",
            details={"id": ident, "places": places},
        )
        for ident, places in sorted(seen.items())
        if len(places) > 1
    ]


def _specials(state: Any) -> set[str]:
    return {item_id(item) for item in iter_items(state) if item_kind(item) in UNRECREATABLE}


def plan_layout(
    source: str | bytes | Path | Mapping[str, Any],
    read: Mapping[str, Any],
    *,
    allow_removal: bool = False,
) -> Plan:
    """Validate a layout and turn it into a plan payload for ``apply``.

    Raises :class:`LayoutError` listing every problem found.
    """
    document = load_layout(source)
    unknown = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown:
        raise _fail(
            "unknown_key",
            f"unknown top-level key(s): {', '.join(unknown)} (expected dock, pages)",
            keys=unknown,
        )
    planner = _Planner(read)

    dock_where = Location("dock")
    dock_entries = _items_list(document.get("dock", {}), dock_where)
    if len(dock_entries) > DOCK_SLOTS:
        planner.collect(
            _fail(
                "dock_full",
                f"the dock holds at most {DOCK_SLOTS} items, got {len(dock_entries)}",
                dock_where,
                count=len(dock_entries),
                capacity=DOCK_SLOTS,
            )
        )
    dock = planner.section(dock_entries, dock_where, in_dock=True)

    page_tables = document.get("pages", [])
    if not isinstance(page_tables, list):
        raise _fail("bad_structure", "pages must be an array of tables ([[pages]])")
    pages: list[list[Any]] = []
    for page_no, table in enumerate(page_tables, 1):
        where = Location("page", page_no)
        page = planner.section(_items_list(table, where), where)
        used = page_usage(page)
        if used > PAGE_CELLS:
            planner.collect(
                _fail(
                    "page_full",
                    f"over capacity: {used}/{PAGE_CELLS} cells",
                    where,
                    cells=used,
                    capacity=PAGE_CELLS,
                )
            )
        pages.append(page)
    planner.issues.extend(_check_duplicates(dock, pages))

    draft = {"buttonBar": dock, "iconLists": pages, "ignored": []}
    source_state = read["state"]
    removed = tuple(sorted(_specials(source_state) - _specials(draft)))
    if removed and not allow_removal and not planner.issues:
        planner.issues.append(
            LayoutIssue(
                "removal_not_allowed",
                "the layout leaves out widgets, web clips or web apps that are on the "
                "device: " + ", ".join(removed) + ". They cannot be recreated from a "
                "layout file; pass --allow-removal to remove them anyway",
                details={"ids": list(removed)},
            )
        )
    if planner.issues:
        raise LayoutError(planner.issues)

    before, after = visible_apps(source_state), visible_apps(draft)
    to_library = tuple(sorted(before - after))
    to_home = tuple(sorted(after - before))
    payload = safe_payload(draft, read.get("apps", {}))
    payload[PLAN_META_KEY] = {
        "version": PLAN_FORMAT_VERSION,
        "source_fingerprint": fingerprint(source_state),
        "created": utc_now(),
    }
    changes = "\n".join(
        [
            "Changes:",
            diff_text(source_state, draft).rstrip(),
            f"To the App Library ({len(to_library)}): {', '.join(to_library) or 'none'}",
            f"To the home screen ({len(to_home)}): {', '.join(to_home) or 'none'}",
            f"Removed widgets/web clips/web apps ({len(removed)}): {', '.join(removed) or 'none'}",
            f"Apps kept off the home screen (ignored): {len(payload['ignored'])}",
        ]
    )
    return Plan(
        payload=payload,
        changes=changes,
        to_library=to_library,
        to_home_screen=to_home,
        removed=removed,
        ignored_count=len(payload["ignored"]),
    )
