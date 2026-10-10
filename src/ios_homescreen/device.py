"""The only module that talks to a real device. Every call has a time limit.

Importing it connects to nothing; :func:`open_device` does, when called.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from .events import EventSink, ignore
from .state import StateError, validate_write_payload
from .transport import CLOSE_TIMEOUT, Backend, Transport, close_quietly, connect

READ_TIMEOUT = 30.0

# What Installation Proxy is asked for. SBAppTags marks system services that never show
# on the home screen or in the App Library ("hidden"), such as AirDropUI.
APP_ATTRIBUTES = [
    "CFBundleIdentifier",
    "CFBundleDisplayName",
    "CFBundleName",
    "ApplicationType",
    "SBAppTags",
]
SEND_TIMEOUT = 10.0
REPLY_TIMEOUT = 3.0
ICON_TIMEOUT = 10.0
# Short on purpose: on iOS 27 over Wi-Fi the phone drops this request, and the wallpaper
# is only decoration.
WALLPAPER_TIMEOUT = 5.0

# Marketing names for recent iPhones, used when the connection does not say (pymobiledevice3's
# own table covers USB; over Wi-Fi the handshake usually carries the name).
IPHONE_NAMES = {
    "iPhone12,1": "iPhone 11",
    "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max",
    "iPhone12,8": "iPhone SE (2nd generation)",
    "iPhone13,1": "iPhone 12 mini",
    "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro",
    "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,4": "iPhone 13 mini",
    "iPhone14,5": "iPhone 13",
    "iPhone14,6": "iPhone SE (3rd generation)",
    "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus",
    "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15",
    "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max",
    "iPhone17,1": "iPhone 16 Pro",
    "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,5": "iPhone 16e",
    "iPhone18,1": "iPhone 17 Pro",
    "iPhone18,2": "iPhone 17 Pro Max",
    "iPhone18,3": "iPhone 17",
    "iPhone18,4": "iPhone Air",
}

# pymobiledevice3 calls that write the list form of the layout back, which is how the
# accident this tool exists to avoid happened. device.py never calls them, and the
# SpringBoard service it creates refuses them (see _springboard).
FORBIDDEN_SPRINGBOARD_CALLS = ("set_icon_state", "reload_icon_state")


def model_name(product_type: Any) -> str | None:
    """``iPhone 15`` for ``iPhone15,4``; the identifier itself when it is not known."""
    if not isinstance(product_type, str) or not product_type:
        return None
    return IPHONE_NAMES.get(product_type, product_type)


class DeviceError(RuntimeError):
    """A device operation failed or did not finish in time."""

    def __init__(self, message: str, *, code: str = "device_error") -> None:
        super().__init__(message)
        self.code = code


class Device:
    """Home screen and Wi-Fi setting access on top of a lockdown client.

    ``lockdown`` is a lockdown client (USB) or a RemoteServiceDiscovery session through
    the Wi-Fi tunnel; the services work the same on both. ``close`` ends the connection
    (the tunnel, for Wi-Fi); by default it closes ``lockdown``.
    """

    def __init__(
        self,
        lockdown: Any,
        *,
        close: Callable[[], Awaitable[Any]] | None = None,
        transport: str = "usb",
        springboard_factory: Callable[[Any], Any] | None = None,
        installer_factory: Callable[[Any], Any] | None = None,
        marketing_name: str | None = None,
        read_timeout: float = READ_TIMEOUT,
        send_timeout: float = SEND_TIMEOUT,
        reply_timeout: float = REPLY_TIMEOUT,
    ) -> None:
        self.lockdown = lockdown
        self.transport = transport
        self.marketing_name = marketing_name
        self._close = close
        self._springboard_factory = springboard_factory or _springboard
        self._installer_factory = installer_factory or _installer
        self.read_timeout = read_timeout
        self.send_timeout = send_timeout
        self.reply_timeout = reply_timeout

    @property
    def info(self) -> dict[str, Any]:
        values = getattr(self.lockdown, "all_values", None) or {}
        try:
            # pymobiledevice3's own table, on a USB lockdown client.
            known = getattr(self.lockdown, "display_name", None)
        except Exception:
            known = None
        product = values.get("ProductType") or getattr(self.lockdown, "product_type", None)
        return {
            "name": values.get("DeviceName"),
            "model": self.marketing_name or known or model_name(product),
            "ios_version": values.get("ProductVersion"),
            "udid": values.get("UniqueDeviceID") or getattr(self.lockdown, "udid", None),
            "wifi_mac": values.get("WiFiAddress"),
        }

    async def _timed(self, awaitable: Awaitable[Any], seconds: float, what: str) -> Any:
        try:
            return await asyncio.wait_for(awaitable, timeout=seconds)
        except TimeoutError as exc:
            raise DeviceError(f"{what} timed out after {seconds:g} s", code="timeout") from exc
        except DeviceError:
            raise
        except Exception as exc:
            raise DeviceError(f"{what} failed: {exc}") from exc

    async def _read(self, format_version: str) -> Any:
        service = self._springboard_factory(self.lockdown)

        async def run() -> Any:
            await service.connect()
            try:
                return await service.get_icon_state(format_version=format_version)
            finally:
                await service.close()

        return await self._timed(run(), self.read_timeout, "Reading the home screen")

    async def read_state(self) -> Any:
        """Format version 2: ``[dock, page1, page2, ...]``."""
        return await self._read("2")

    async def read_raw_state(self) -> Any:
        """Format version 3, kept for reference in read snapshots only."""
        return await self._read("3")

    async def installed_apps(self) -> dict[str, dict[str, Any]]:
        """Installed apps that can sit on the home screen: ``ApplicationType`` User or System.

        Each is ``{"name", "type"}``, plus ``"hidden": True`` for system services that
        iOS never shows (``SBAppTags`` contains ``hidden``). Hidden apps still have to be
        listed in a write's ``ignored`` list, but they are not App Library apps.
        """
        service = self._installer_factory(self.lockdown)

        async def run() -> Mapping[str, Mapping[str, Any]] | None:
            await service.connect()
            try:
                return await service.lookup(
                    {"ApplicationType": "Any", "ReturnAttributes": APP_ATTRIBUTES}
                )
            finally:
                await service.close()

        found = await self._timed(run(), self.read_timeout, "Reading the installed apps")
        if not isinstance(found, Mapping):
            raise DeviceError("Installation Proxy returned no app list", code="no_app_list")
        apps: dict[str, dict[str, Any]] = {}
        for ident, meta in found.items():
            kind = meta.get("ApplicationType")
            if kind not in {"User", "System"}:
                continue
            name = meta.get("CFBundleDisplayName") or meta.get("CFBundleName") or ident
            apps[ident] = {"name": str(name), "type": str(kind)}
            tags = meta.get("SBAppTags")
            if isinstance(tags, list | tuple) and "hidden" in tags:
                apps[ident]["hidden"] = True
        return apps

    async def write_state(self, payload: Any) -> Any | None:
        """Send ``setIconState`` with the safe dictionary payload.

        pymobiledevice3's ``set_icon_state`` waits for a reply forever, and SpringBoard
        often never sends one. So the plist is sent on the raw service connection, the
        reply gets ``reply_timeout`` seconds, and no reply returns ``None``. Callers
        prove the result by re-reading on a fresh connection.
        """
        try:
            validate_write_payload(payload)
        except StateError as exc:
            raise DeviceError(
                f"refusing to send an unsafe payload: {exc}", code="unsafe_payload"
            ) from exc
        service = self._springboard_factory(self.lockdown)

        async def send() -> None:
            await service.connect()
            await service.service.send_plist({"command": "setIconState", "iconState": payload})

        try:
            try:
                await asyncio.wait_for(send(), timeout=self.send_timeout)
            except TimeoutError as exc:
                raise DeviceError(
                    f"sending the layout timed out after {self.send_timeout:g} s"
                ) from exc
            except Exception as exc:
                raise DeviceError(f"sending the layout failed: {exc}") from exc
            try:
                return await asyncio.wait_for(
                    service.service.recv_plist(), timeout=self.reply_timeout
                )
            except Exception:
                # No reply or a closed connection: expected on many iOS versions.
                return None
        finally:
            # A failed close does not matter: the next read opens a new service connection.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(service.close(), timeout=self.reply_timeout)

    async def icons(self, identifiers: Iterable[str]) -> dict[str, bytes | None]:
        """Home screen icons as PNG bytes, over one SpringBoard connection.

        ``None`` when SpringBoard has no icon for an id (web clips, web apps and widgets
        often do not). Raises :class:`DeviceError` if the connection fails or times out.
        """
        wanted = list(dict.fromkeys(identifiers))
        service = self._springboard_factory(self.lockdown)

        async def run() -> dict[str, bytes | None]:
            await service.connect()
            try:
                found: dict[str, bytes | None] = {}
                for ident in wanted:
                    try:
                        data = await asyncio.wait_for(
                            service.get_icon_pngdata(ident), timeout=ICON_TIMEOUT
                        )
                    except TimeoutError:
                        raise
                    except Exception:
                        data = None
                    found[ident] = data if isinstance(data, bytes) and data else None
                return found
            finally:
                await service.close()

        return await self._timed(run(), ICON_TIMEOUT * max(1, len(wanted)), "Reading app icons")

    async def wallpaper(self) -> bytes | None:
        """The home screen wallpaper as PNG bytes (SpringBoard's
        ``getHomeScreenWallpaperPNGData``), or ``None`` when SpringBoard sends none."""
        service = self._springboard_factory(self.lockdown)

        async def run() -> bytes | None:
            await service.connect()
            try:
                data = await service.get_wallpaper_pngdata()
            finally:
                await service.close()
            return data if isinstance(data, bytes) and data else None

        return await self._timed(run(), WALLPAPER_TIMEOUT, "Reading the wallpaper")

    async def wifi_connections_enabled(self) -> bool:
        value = await self._timed(
            self.lockdown.get_enable_wifi_connections(),
            self.read_timeout,
            "Reading the Wi-Fi connection setting",
        )
        return bool(value)

    async def set_wifi_connections(self, enabled: bool) -> None:
        await self._timed(
            self.lockdown.set_enable_wifi_connections(enabled),
            self.read_timeout,
            "Changing the Wi-Fi connection setting",
        )

    async def close(self) -> None:
        if self._close is not None:
            # Tearing a tunnel down takes longer than closing a socket.
            await close_quietly(self._close, CLOSE_TIMEOUT)
        elif hasattr(self.lockdown, "close"):
            await close_quietly(self.lockdown.close, self.reply_timeout)


def _refuse(name: str) -> Callable[..., Any]:
    async def refused(*args: Any, **kwargs: Any) -> None:
        raise DeviceError(
            f"{name} writes the list form of the layout and is never used; "
            "writes go through Device.write_state",
            code="unsafe_payload",
        )

    return refused


def _springboard(lockdown: Any) -> Any:
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    service = SpringBoardServicesService(lockdown=lockdown)
    for name in FORBIDDEN_SPRINGBOARD_CALLS:
        setattr(service, name, _refuse(name))
    return service


def _installer(lockdown: Any) -> Any:
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    return InstallationProxyService(lockdown=lockdown)


async def open_device(
    transport: Transport, *, on_event: EventSink = ignore, backend: Backend | None = None
) -> Device:
    """Connect over ``transport`` and return a :class:`Device`. Close it when done."""
    link = await connect(transport, backend=backend, on_event=on_event)
    return Device(
        link.provider, close=link.close, transport=link.kind, marketing_name=link.marketing_name
    )
