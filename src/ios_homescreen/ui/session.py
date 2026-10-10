"""What the browser UI works on: the last read, device jobs, icons, planning.

One :class:`Session` lives as long as the server. It never keeps a connection open
between operations: every job (read, apply, restore) connects, works and closes, like
the CLI does. Only one job runs at a time. Icons are fetched after a read on the same
connection, in the background, and any job that needs the phone cancels that first.

Nothing here prints; progress goes into the job's event list as
:meth:`~ios_homescreen.events.Event.to_dict` dicts, which the server streams.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import api
from ..events import ERROR, WARNING, Event
from ..icons import IconCache
from ..model import describe, describe_changes, match_folders, to_document
from ..paths import cache_dir
from ..planner import LayoutError, Plan, load_layout, plan_layout
from ..state import (
    PAGE_CELLS,
    is_folder,
    is_hidden_app,
    item_kind,
    iter_items,
    same_layout,
)
from ..storage import find_backup, list_backups, save_pull
from ..transport import Backend, Transport, TransportError
from ..workflow import Timing
from .errors import friendly

log = logging.getLogger(__name__)

ICON_BATCH = 16
WIFI_RETRY_CODES = frozenset({"not_advertising", "timeout"})
WIFI_RETRY_DISCOVERY = 12.0
MAX_BACKUPS = 100

Opener = Callable[[Callable[[Event], None]], Awaitable[Any]]


class Busy(RuntimeError):
    """Another job is using the phone."""

    code = "busy"


class LayoutProblems(ValueError):
    """The layout cannot be planned; ``issues`` are planner issue dicts."""

    code = "layout_invalid"

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        super().__init__("; ".join(str(issue.get("message")) for issue in issues))
        self.issues = issues


class NoRead(RuntimeError):
    """Nothing has been read from the phone yet."""

    code = "no_read"


class MemoryIcons:
    """Icon store that only lives in memory (demo mode)."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def get(self, identifier: str) -> bytes | None:
        return self._data.get(identifier)

    def put(self, identifier: str, data: bytes) -> None:
        self._data[identifier] = data

    def ids(self) -> set[str]:
        return set(self._data)


class DiskIcons(IconCache):
    """:class:`IconCache` that can also list what it holds."""

    def ids(self) -> set[str]:
        if not self.directory.is_dir():
            return set()
        return {path.stem for path in self.directory.glob("*.png")}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Job:
    """One device operation and its progress events."""

    def __init__(self, kind: str) -> None:
        self.id = secrets.token_hex(6)
        self.kind = kind
        self.state = "running"
        self.events: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.started = _now()
        self.finished: str | None = None
        self.task: asyncio.Task[Any] | None = None
        self._wake = asyncio.Event()

    @property
    def running(self) -> bool:
        return self.state == "running"

    def emit(self, event: Event) -> None:
        self.events.append(event.to_dict())
        self._notify()

    def _notify(self) -> None:
        wake, self._wake = self._wake, asyncio.Event()
        wake.set()

    def finish(self, state: str) -> None:
        self.state = state
        self.finished = _now()
        self._notify()

    def waiter(self) -> asyncio.Event:
        """Set at the next event or at the end of the job. Take it before reading
        ``events``, then wait on it: nothing that happens in between is missed."""
        return self._wake

    def to_dict(self, since: int = 0) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "events": self.events[since:],
            "event_count": len(self.events),
            "result": self.result,
            "error": self.error,
            "started": self.started,
            "finished": self.finished,
        }


@dataclass
class Settings:
    data_dir: Path
    backup_dir: Path
    timing: Timing = field(default_factory=Timing)
    transport: Transport | None = None
    demo: bool = False
    cache_root: Path | None = None
    """Root of the icon cache; ``None`` uses the XDG cache directory."""


def _special_ids(state: Any, kinds: Iterable[str]) -> list[str]:
    wanted = set(kinds)
    found = []
    for item in iter_items(state):
        if is_folder(item) or item_kind(item) not in wanted:
            continue
        ident = item.get("displayIdentifier") if isinstance(item, Mapping) else None
        if isinstance(ident, str) and ident:
            found.append(ident)
    return found


def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    return None


def _strip_empty_pages(layout: Mapping[str, Any]) -> tuple[dict[str, Any], list[int]]:
    """Drop empty pages (SpringBoard does not keep them) and remember the numbering."""
    pages = layout.get("pages", [])
    pages = pages if isinstance(pages, list) else []
    kept, numbers = [], []
    for number, page in enumerate(pages, 1):
        items = page.get("items", []) if isinstance(page, Mapping) else page
        if items:
            kept.append(page)
            numbers.append(number)
    return {"dock": layout.get("dock", []) or [], "pages": kept}, numbers


class Session:
    def __init__(
        self,
        settings: Settings,
        *,
        opener: Opener | None = None,
        backend: Backend | None = None,
        icons: Any = None,
    ) -> None:
        self.settings = settings
        self._opener = opener
        self._backend = backend
        self._fixed_icons = icons
        self.icons: Any = icons or MemoryIcons()
        self.read: dict[str, Any] | None = None
        self.view: dict[str, Any] | None = None
        self.read_file: Path | None = None
        self.read_at: str | None = None
        self.device_info: dict[str, Any] | None = None
        self.last_error: dict[str, Any] | None = None
        self.job: Job | None = None
        self.icon_task: asyncio.Task[Any] | None = None
        self.icons_pending = False
        self._backup_details: dict[tuple[str, int, int], Any] = {}

    # ------------------------------------------------------------------ connection

    def connection(self) -> dict[str, Any]:
        transport = self.settings.transport
        if self.settings.demo or transport is None:
            return {"kind": "demo", "label": "Demo"}
        if transport.wifi:
            return {"kind": "wifi", "label": "Wi-Fi"}
        return {"kind": "usb", "label": "USB"}

    async def _connect(self, emit: Callable[[Event], None]) -> Any:
        if self._opener is not None:
            device = await self._opener(emit)
        else:
            device = await self._open(self.settings.transport or Transport(), emit)
        info = dict(device.info)
        self.device_info = {
            key: info.get(key) for key in ("name", "model", "ios_version") if info.get(key)
        }
        return device

    async def _open(self, transport: Transport, emit: Callable[[Event], None]) -> Any:
        try:
            return await api.connect(transport, on_event=emit, backend=self._backend)
        except TransportError as exc:
            if not transport.wifi or exc.code not in WIFI_RETRY_CODES:
                raise
        # A phone that was idle can take a while to answer Bonjour: look once more,
        # for longer, before giving up.
        emit(
            Event(
                "retrying",
                "The iPhone did not answer yet; looking a little longer...",
                level=WARNING,
            )
        )
        longer = replace(
            transport, discovery_timeout=max(WIFI_RETRY_DISCOVERY, transport.discovery_timeout * 2)
        )
        return await api.connect(longer, on_event=emit, backend=self._backend)

    async def _release_icons(self) -> None:
        """Stop a background icon fetch so a job can use the phone."""
        task = self.icon_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task

    # ------------------------------------------------------------------ jobs

    def _start(self, kind: str, work: Callable[[Job], Awaitable[dict[str, Any]]]) -> Job:
        if self.job is not None and self.job.running:
            raise Busy(f"the phone is busy ({self.job.kind} is running)")
        job = Job(kind)
        self.job = job
        job.task = asyncio.create_task(self._run(job, work))
        return job

    async def _run(self, job: Job, work: Callable[[Job], Awaitable[dict[str, Any]]]) -> None:
        try:
            job.result = await work(job)
        except asyncio.CancelledError:
            job.error = {
                "code": "cancelled",
                "title": "Stopped",
                "steps": ["The server stopped before the operation finished."],
                "detail": "",
            }
            job.finish("failed")
            raise
        except Exception as exc:
            if not isinstance(exc, api.DeviceError | TransportError | api.WorkflowError):
                log.exception("%s failed", job.kind)
            job.error = friendly(exc)
            if job.kind == "read":
                self.last_error = job.error
            code = job.error["code"]
            job.emit(Event("failed", job.error["title"], level=ERROR, data={"code": code}))
            job.finish("failed")
        else:
            job.finish("done")

    def start_read(self) -> Job:
        return self._start("read", self._read_job)

    async def _read_job(self, job: Job) -> dict[str, Any]:
        await self._release_icons()
        device = await self._connect(job.emit)
        handed_over = False
        try:
            job.emit(Event("reading", "Reading the home screen (read-only)...", 1, 2))
            snapshot = await api.read_device(device)
            saved = self._keep_read(snapshot)
            job.emit(Event("read_saved", f"Saved as {saved.name}.", 2, 2, data={"path": saved}))
            handed_over = self._fetch_icons(device)
        finally:
            if not handed_over:
                await device.close()
        return {"read": saved.name}

    def _keep_read(self, snapshot: dict[str, Any]) -> Path:
        saved = save_pull(snapshot, self.settings.data_dir)
        self.read = snapshot
        self.view = describe(snapshot)
        self.read_file = saved
        self.read_at = _now()
        self.last_error = None
        if self._fixed_icons is None:
            udid = (snapshot.get("device") or {}).get("udid")
            store = DiskIcons.for_device(udid, self.settings.cache_root or cache_dir())
            self.icons = DiskIcons(store.directory)
        return saved

    def _wanted_icons(self) -> list[str]:
        if self.read is None:
            return []
        have = self.icons.ids()
        state = self.read["state"]
        apps = self.read.get("apps", {}) or {}
        visible = sorted(ident for ident, meta in apps.items() if not is_hidden_app(meta))
        wanted = [*visible, *_special_ids(state, {"webapp", "webclip"})]
        return [ident for ident in dict.fromkeys(wanted) if ident not in have]

    def _fetch_icons(self, device: Any) -> bool:
        """Fetch missing icons in the background on ``device``; it is closed afterwards.

        Returns False (and leaves ``device`` to the caller) when nothing is missing.
        """
        wanted = self._wanted_icons()
        if not wanted or not hasattr(device, "icons"):
            return False
        self.icons_pending = True
        self.icon_task = asyncio.create_task(self._icons_job(device, wanted))
        return True

    async def _icons_job(self, device: Any, wanted: list[str]) -> None:
        try:
            for start in range(0, len(wanted), ICON_BATCH):
                await api.fetch_icons(device, wanted[start : start + ICON_BATCH], self.icons)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Icons are cosmetic: the UI draws a placeholder for the rest.
            log.info("fetching icons stopped: %s", exc)
        finally:
            self.icons_pending = False
            await device.close()

    def plan(
        self, layout: Mapping[str, Any], remove: Iterable[str] = ()
    ) -> tuple[Plan | None, list[dict[str, Any]]]:
        """Plan a UI layout. Removing widgets needs their ids in ``remove`` (the user
        confirmed it), like ``push --allow-removal``."""
        if self.read is None:
            raise NoRead("read the phone first")
        trimmed, numbers = _strip_empty_pages(layout)
        try:
            plan = plan_layout(to_document(trimmed), self.read, allow_removal=True)
        except LayoutError as error:
            issues = []
            for issue in error.issues:
                data = issue.to_dict()
                page = data["location"].get("page")
                if isinstance(page, int) and 0 < page <= len(numbers):
                    data["location"]["page"] = numbers[page - 1]
                issues.append(data)
            return None, issues
        unconfirmed = sorted(set(plan.removed) - set(remove))
        if unconfirmed:
            return None, [
                {
                    "code": "removal_not_allowed",
                    "message": "removing widgets, web clips or web apps needs confirmation: "
                    + ", ".join(unconfirmed),
                    "location": {"section": "layout"},
                    "details": {"ids": unconfirmed},
                }
            ]
        return plan, []

    def check(self, layout: Mapping[str, Any], remove: Iterable[str] = ()) -> dict[str, Any]:
        """Live validation for the editor: issues, changes and the plan summary."""
        plan, issues = self.plan(layout, remove)
        assert self.view is not None
        assert self.read is not None
        changes = describe_changes(self.view, layout)
        summary = None
        same = False
        if plan is not None:
            summary = {k: v for k, v in plan.summary().items() if k != "changes"}
            same = same_layout(plan.payload, self.read["state"])
        return {
            "ok": not issues,
            "issues": issues,
            "changes": changes,
            "summary": summary,
            "dirty": bool(changes) and not same,
        }

    def start_apply(
        self, layout: Mapping[str, Any], remove: Iterable[str] = (), *, force: bool = False
    ) -> Job:
        plan, issues = self.plan(layout, remove)
        if plan is None:
            raise LayoutProblems(issues)

        async def work(job: Job) -> dict[str, Any]:
            return await self._write_job(job, "apply", plan.payload, force=force)

        return self._start("apply", work)

    def start_restore(self, name: str) -> Job:
        path = self.backup_path(name)
        target = api.load_backup(path)

        async def work(job: Job) -> dict[str, Any]:
            return await self._write_job(job, "restore", target)

        return self._start("restore", work)

    async def _write_job(
        self, job: Job, kind: str, target: dict[str, Any], *, force: bool = False
    ) -> dict[str, Any]:
        await self._release_icons()
        device = await self._connect(job.emit)
        handed_over = False
        try:
            common = {
                "backup_dir": self.settings.backup_dir,
                "timing": self.settings.timing,
                "on_event": job.emit,
            }
            if kind == "apply":
                result = await api.push(device, target, force=force, **common)
            else:
                result = await api.restore(device, target, **common)
            outcome = {k: v for k, v in result.to_dict().items() if k != "events"}
            outcome["backup_name"] = result.backup.name
            job.emit(Event("rereading", "Reading the home screen again..."))
            try:
                snapshot = await api.read_device(device)
            except Exception as exc:
                outcome["reread_error"] = friendly(exc)
            else:
                self._keep_read(snapshot)
                handed_over = self._fetch_icons(device)
        finally:
            if not handed_over:
                await device.close()
        return outcome

    async def shutdown(self) -> None:
        """Let a running write finish; a half-done write is worse than a slow exit."""
        job = self.job
        if job is not None and job.running and job.kind in {"apply", "restore"} and job.task:
            log.warning("waiting for the running %s to finish", job.kind)
            with contextlib.suppress(BaseException):
                await asyncio.shield(job.task)
        await self._release_icons()
        if job is not None and job.running and job.task:
            job.task.cancel()
            with contextlib.suppress(BaseException):
                await job.task

    # ------------------------------------------------------------------ views

    def state(self) -> dict[str, Any]:
        read = None
        if self.read is not None and self.view is not None:
            apps = self.read.get("apps", {}) or {}
            read = {
                "file": self.read_file.name if self.read_file else None,
                "at": self.read_at,
                "view": self.view,
                "apps": sorted(
                    (
                        {
                            "id": ident,
                            "name": str(meta.get("name", ident)),
                            "type": str(meta.get("type", "")),
                        }
                        for ident, meta in apps.items()
                        if isinstance(meta, Mapping) and not is_hidden_app(meta)
                    ),
                    key=lambda app: (app["name"].casefold(), app["id"]),
                ),
            }
        return {
            "version": api_version(),
            "demo": self.settings.demo,
            "connection": self.connection(),
            "device": self.device_info,
            "read": read,
            "error": self.last_error,
            "job": self.job.to_dict() if self.job else None,
            "icons": self.icon_state(),
            "page_cells": PAGE_CELLS,
        }

    def icon_state(self) -> dict[str, Any]:
        available = set(self.icons.ids())
        if self.read is not None:
            for item in iter_items(self.read["state"]):
                if item_kind(item) == "webclip" and _image_type(item.get("iconData") or b""):
                    available.add(str(item.get("displayIdentifier")))
        return {"available": sorted(available), "pending": self.icons_pending}

    def icon(self, identifier: str) -> tuple[bytes, str] | None:
        data = self.icons.get(identifier)
        if data is None and self.read is not None:
            for item in iter_items(self.read["state"]):
                if item_kind(item) == "webclip" and item.get("displayIdentifier") == identifier:
                    data = item.get("iconData")
                    break
        if not isinstance(data, bytes):
            return None
        kind = _image_type(data)
        if kind is None or (kind == "image/svg+xml" and not self.settings.demo):
            return None
        return data, kind

    # ------------------------------------------------------------------ files

    def export(self, layout: Mapping[str, Any], remove: Iterable[str] = ()) -> str:
        plan, issues = self.plan(layout, remove)
        if plan is None:
            raise LayoutProblems(issues)
        assert self.read is not None
        state = {"buttonBar": plan.payload["buttonBar"], "iconLists": plan.payload["iconLists"]}
        return api.export_layout(
            {"state": state, "apps": self.read.get("apps", {})},
            pull=self.read_file.name if self.read_file else None,
            note=f"Edited in the ios-homescreen editor. {api.pull_note(self.read)}",
        )

    def import_layout(self, text: str) -> dict[str, Any]:
        """A layout file as an editor view, against the current read."""
        if self.read is None or self.view is None:
            raise NoRead("read the phone first")
        try:
            plan = plan_layout(load_layout(text), self.read, allow_removal=True)
        except LayoutError as error:
            raise LayoutProblems([issue.to_dict() for issue in error.issues]) from error
        state = {"buttonBar": plan.payload["buttonBar"], "iconLists": plan.payload["iconLists"]}
        view = describe({"state": state, "apps": self.read.get("apps", {})})
        # Folders have no ids on the phone; keep the current ids for the same folders.
        match_folders(self.view, view, prefix="imported")
        names = {}
        for item in iter_items(self.read["state"]):
            if not is_folder(item) and item_kind(item) in {"widget", "webclip", "webapp"}:
                names[item.get("displayIdentifier")] = item_label(item, self.read)
        return {
            "view": {"dock": view["dock"], "pages": view["pages"]},
            "removed": [{"id": ident, "name": names.get(ident, ident)} for ident in plan.removed],
        }

    def backup_path(self, name: str) -> Path:
        """A backup by its plain file name in the backup directory, nothing else."""
        return find_backup(self.settings.backup_dir, name, allow_paths=False)

    def backups(self) -> list[dict[str, Any]]:
        return [
            backup.to_dict()
            for backup in list_backups(
                self.settings.backup_dir, limit=MAX_BACKUPS, cache=self._backup_details
            )
        ]


def item_label(item: Mapping[str, Any], read: Mapping[str, Any]) -> str:
    """Display name of a widget, web clip or web app for confirmations."""
    name = item.get("displayName")
    if isinstance(name, str) and name:
        return name
    apps = read.get("apps", {}) or {}
    owner = item.get("containerBundleIdentifier") or item.get("bundleIdentifier")
    meta = apps.get(owner) if isinstance(owner, str) else None
    if isinstance(meta, Mapping) and meta.get("name"):
        label = str(meta["name"])
        return f"{label} widget" if item_kind(item) == "widget" else f"{label} web app"
    return str(item.get("displayIdentifier", "?"))


def api_version() -> str:
    from .. import __version__

    return __version__
