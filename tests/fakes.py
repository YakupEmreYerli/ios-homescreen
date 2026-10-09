"""In-memory stand-ins for a phone. No test ever talks to a real device."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ios_homescreen.state import PAGE_CELLS, cell_count, split_state, visible_apps


class FakeSpringBoard:
    """Simulates the SpringBoard behaviours that make home screen writes dangerous.

    * A list-form write appends every installed User/System app that is not listed to
      the end of the home screen (the real accident).
    * A dictionary write with ``ignored`` leaves those apps in the App Library.
    * Folders written with ``iconType: folder`` instead of ``listType: folder`` vanish.
    * Items beyond 24 cells spill onto a new page.
    * Optionally the write never gets a reply, or is silently ignored.
    """

    def __init__(
        self,
        state: Any,
        installed: Mapping[str, Any],
        *,
        no_reply: bool = False,
        ignore_writes: bool = False,
        info: Mapping[str, Any] | None = None,
        wifi_enabled: bool = False,
    ) -> None:
        dock, pages = split_state(state)
        self._state = [deepcopy(dock), *deepcopy(pages)]
        self._installed = deepcopy(dict(installed))
        self.no_reply = no_reply
        self.ignore_writes = ignore_writes
        self.writes: list[Any] = []
        self.reads = 0
        self.closed = False
        self.wifi_enabled = wifi_enabled
        self.info = dict(
            info
            or {
                "name": "Test iPhone",
                "model": "iPhone 15",
                "ios_version": "26.0",
                "udid": "00008120-000A1B2C3D4E5F60",
                "wifi_mac": "a0:b1:c2:d3:e4:f5",
            }
        )

    async def read_state(self) -> Any:
        self.reads += 1
        return deepcopy(self._state)

    async def read_raw_state(self) -> Any:
        return {"formatVersion": 3, "iconState": deepcopy(self._state)}

    async def installed_apps(self) -> dict[str, Any]:
        return deepcopy(self._installed)

    @staticmethod
    def _kept(items: list[Any]) -> list[Any]:
        return [
            deepcopy(item)
            for item in items
            if not (
                isinstance(item, dict)
                and item.get("iconType") == "folder"
                and item.get("listType") != "folder"
            )
        ]

    @classmethod
    def _reflow(cls, pages: list[list[Any]]) -> list[list[Any]]:
        result: list[list[Any]] = []
        for source in pages:
            remaining = cls._kept(source)
            page: list[Any] = []
            used = 0
            for item in remaining:
                cells = cell_count(item)
                if page and used + cells > PAGE_CELLS:
                    result.append(page)
                    page, used = [], 0
                page.append(item)
                used += cells
            result.append(page)
        return result

    async def write_state(self, payload: Any) -> None:
        self.writes.append(deepcopy(payload))
        if not self.ignore_writes:
            if isinstance(payload, list):
                dock = deepcopy(payload[0] if payload else [])
                pages = deepcopy(payload[1:])
                ignored: set[str] = set()
            else:
                dock = deepcopy(payload.get("buttonBar", []))
                pages = deepcopy(payload.get("iconLists", []))
                ignored = set(payload.get("ignored", []) or [])
            shown = visible_apps([dock, *pages])
            missing = [
                ident
                for ident, meta in self._installed.items()
                if meta.get("type") in {None, "User", "System"}
                and ident not in shown
                and ident not in ignored
            ]
            if missing:
                if not pages:
                    pages = [[]]
                pages[-1].extend(
                    {"bundleIdentifier": ident, "displayIdentifier": ident} for ident in missing
                )
            self._state = [self._kept(dock), *self._reflow(pages)]
        if self.no_reply:
            await asyncio.Event().wait()

    async def icons(self, identifiers) -> dict[str, bytes | None]:
        """Installed apps have an icon; widgets, web clips and web apps do not."""
        return {
            ident: (b"\x89PNG" + ident.encode() if ident in self._installed else None)
            for ident in identifiers
        }

    async def wifi_connections_enabled(self) -> bool:
        return self.wifi_enabled

    async def set_wifi_connections(self, enabled: bool) -> None:
        self.wifi_enabled = enabled

    async def close(self) -> None:
        self.closed = True


def opener_for(device: Any, seen: list[Any] | None = None):
    """A CLI ``open_device`` that hands out ``device`` and records the transport."""

    async def open_device(transport: Any) -> Any:
        if seen is not None:
            seen.append(transport)
        return device

    return open_device


async def must_not_connect(transport: Any) -> Any:
    raise AssertionError("the device must not be contacted")
