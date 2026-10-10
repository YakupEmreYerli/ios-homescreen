"""Open the connection to the phone: USB through usbmuxd, or Wi-Fi through RemotePairing.

USB is a lockdown session through usbmuxd.

Wi-Fi needs iOS 17 or later and works like Xcode's wireless connection. The classic
network lockdown (port 62078, found through ``_apple-mobdev2._tcp``) still answers on
current iOS versions, but the phone closes every service on the first request, so it
is not used. Instead:

1. ``ios-homescreen wifi setup``, over USB once, creates a RemotePairing record on
   this computer. The computer is already trusted over USB, so the phone shows no prompt.
2. The phone then advertises ``_remotepairing._tcp`` on the local network. Its
   advertisement is matched to the record by an authentication tag (not by MAC
   address, which iOS randomises), and the record proves who we are.
3. pymobiledevice3's userspace tunnel carries the session: a TCP/IP stack in this
   process, so no root, no ``utun`` device and no Developer Mode. The springboard and
   installation proxy services are reached through it as ``*.shim.remote``.

Only one userspace tunnel can exist per process (pymobiledevice3's stack is global);
callers close the connection before opening the next one.

pymobiledevice3 is imported lazily so that ``--help`` and the tests never load it.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .events import Event, EventSink, ignore

DEFAULT_DISCOVERY_TIMEOUT = 5.0
DEFAULT_CONNECT_TIMEOUT = 30.0
CLOSE_TIMEOUT = 10.0

# The key pymobiledevice3 stores the phone's alternate IRK under; without it the
# phone's advertisement cannot be recognised (records made by old versions lack it).
ALT_IRK_KEY = "peer_alt_irk"


class TransportError(RuntimeError):
    """The device could not be reached over the chosen transport."""

    def __init__(self, message: str, *, code: str = "transport_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Transport:
    """How to reach the device. The default is USB."""

    wifi: bool = False
    udid: str | None = None
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT

    @property
    def network(self) -> bool:
        return self.wifi

    def describe(self) -> str:
        return "Wi-Fi" if self.wifi else "USB"


@dataclass(frozen=True)
class Link:
    """An open connection. Services start on ``provider``; ``close`` ends the session."""

    provider: Any
    close: Callable[[], Awaitable[Any]]
    kind: str = "usb"
    """``usb`` or ``wifi``."""
    address: str | None = None


@dataclass(frozen=True)
class RemoteRecord:
    """A RemotePairing record on this computer (the Wi-Fi pairing with one phone)."""

    udid: str
    path: Path
    usable: bool
    """False for records without the phone's alternate IRK (made by older versions)."""


class Backend(Protocol):
    async def usb(self, udid: str | None, pair_timeout: float) -> Any: ...

    async def wifi(self, udid: str, discovery_timeout: float) -> Link: ...

    def remote_records(self) -> list[RemoteRecord]: ...

    async def pair_remote(self, lockdown: Any) -> None: ...

    async def reachable(self, udid: str, discovery_timeout: float) -> str | None: ...


_tunnel_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _tunnel_lock
    if _tunnel_lock is None:
        _tunnel_lock = asyncio.Lock()
    return _tunnel_lock


class PymobiledeviceBackend:
    """The real connections, through pymobiledevice3."""

    async def usb(self, udid: str | None, pair_timeout: float) -> Any:
        from pymobiledevice3.exceptions import (
            ConnectionFailedToUsbmuxdError,
            DeviceNotFoundError,
            NoDeviceConnectedError,
        )
        from pymobiledevice3.lockdown import create_using_usbmux

        try:
            return await create_using_usbmux(
                serial=udid, connection_type="USB", pair_timeout=pair_timeout
            )
        except (NoDeviceConnectedError, DeviceNotFoundError) as exc:
            which = f" with UDID {udid}" if udid else ""
            raise TransportError(
                f"no iPhone{which} found over USB. Plug it in, unlock it and tap "
                "'Trust This Computer' if asked.",
                code="no_usb_device",
            ) from exc
        except (ConnectionFailedToUsbmuxdError, FileNotFoundError, ConnectionRefusedError) as exc:
            raise TransportError(
                "cannot reach usbmuxd. Is it installed and running? (sudo systemctl start usbmuxd)",
                code="usbmuxd_unreachable",
            ) from exc

    def remote_records(self) -> list[RemoteRecord]:
        from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

        return [
            RemoteRecord(identifier, path, bool(record.get(ALT_IRK_KEY)))
            for identifier, path, record in iter_remote_pair_records_by_identifier()
        ]

    async def pair_remote(self, lockdown: Any) -> None:
        """Create the RemotePairing record over an already trusted USB lockdown session."""
        from pymobiledevice3.exceptions import RemotePairingCompletedError
        from pymobiledevice3.remote.tunnel_service import RemotePairingLockdownService

        service = await RemotePairingLockdownService.create(lockdown)
        try:
            await service.connect(autopair=True)
        except RemotePairingCompletedError:
            # The phone closes the channel once pairing is done; the record is saved.
            pass
        finally:
            await service.close()

    async def _find(self, udid: str, discovery_timeout: float) -> Any | None:
        from pymobiledevice3.remote.tunnel_service import get_remote_pairing_tunnel_services

        services = await get_remote_pairing_tunnel_services(
            bonjour_timeout=discovery_timeout, udid=udid
        )
        for extra in services[1:]:
            await extra.close()
        return services[0] if services else None

    async def reachable(self, udid: str, discovery_timeout: float) -> str | None:
        """The phone's address if it advertises RemotePairing and accepts our record."""
        service = await self._find(udid, discovery_timeout)
        if service is None:
            return None
        await service.close()
        return str(getattr(service, "hostname", "") or "") or "?"

    async def wifi(self, udid: str, discovery_timeout: float) -> Link:
        from pymobiledevice3.remote import userspace_tunnel

        # One userspace tunnel per process: open them one at a time.
        async with _lock():
            service = await self._find(udid, discovery_timeout)
            if service is None:
                raise TransportError(
                    "the iPhone did not answer on the network. Keep it awake and unlocked "
                    "on the same network as this computer.",
                    code="not_advertising",
                )
            address = str(getattr(service, "hostname", "") or "")

            async def provider(serial: Any, autopair: Any, remotepairing_fallback: Any = True):
                return service, None

            # UserspaceRsdTunnel asks this module function for its tunnel provider; hand it
            # the service found above for the length of the call, then put it back.
            tunnel = userspace_tunnel.UserspaceRsdTunnel(serial=udid, autopair=False)
            original = userspace_tunnel._create_no_root_tunnel_provider
            userspace_tunnel._create_no_root_tunnel_provider = provider
            try:
                rsd = await tunnel.aopen()
            except BaseException:
                await service.close()
                raise
            finally:
                userspace_tunnel._create_no_root_tunnel_provider = original
        return Link(rsd, tunnel.aclose, kind="wifi", address=address or None)


async def close_quietly(close: Callable[[], Awaitable[Any]], timeout: float = 3.0) -> None:
    """Run ``close()`` with a time limit; never raises."""
    # Nothing useful can be done about a failed close; the socket goes away anyway.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(close(), timeout=timeout)


def pick_record(records: list[RemoteRecord], udid: str | None) -> RemoteRecord:
    """The Wi-Fi pairing to use: the one for ``udid``, or the only one there is."""
    if udid is not None:
        records = [r for r in records if r.udid.strip().lower() == udid.strip().lower()]
    if not records:
        which = f" with {udid}" if udid else ""
        raise TransportError(
            f"this computer has no Wi-Fi pairing{which} yet. Connect the iPhone with a cable "
            "once and run 'ios-homescreen wifi setup'.",
            code="no_pair_record",
        )
    if len(records) > 1:
        udids = ", ".join(sorted(r.udid for r in records))
        raise TransportError(
            f"this computer has Wi-Fi pairings with several devices ({udids}); "
            "pick one with --udid",
            code="several_pair_records",
        )
    record = records[0]
    if not record.usable:
        raise TransportError(
            f"the Wi-Fi pairing in {record.path} was made by an older pymobiledevice3 and "
            "cannot be used. Connect the iPhone with a cable and run "
            "'ios-homescreen wifi setup' again.",
            code="stale_pair_record",
        )
    return record


async def connect(
    transport: Transport,
    *,
    backend: Backend | None = None,
    on_event: EventSink = ignore,
) -> Link:
    """Open the connection ``transport`` describes."""
    backend = backend or PymobiledeviceBackend()
    timeout = transport.connect_timeout
    if not transport.wifi:
        on_event(Event("connecting", "Connecting over USB...", data={"transport": "usb"}))
        try:
            lockdown = await asyncio.wait_for(backend.usb(transport.udid, timeout), timeout=timeout)
        except TimeoutError as exc:
            raise TransportError(
                f"USB connection timed out after {timeout:g} s. If the phone shows "
                "'Trust This Computer', tap Trust and try again; otherwise restart usbmuxd.",
                code="timeout",
            ) from exc
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(
                f"could not connect over USB: {exc}", code="connection_failed"
            ) from exc
        return Link(lockdown, lockdown.close, kind="usb")

    record = pick_record(backend.remote_records(), transport.udid)
    on_event(
        Event(
            "discovering",
            f"Looking for the iPhone on the network ({transport.discovery_timeout:g} s)...",
            data={"transport": "wifi", "udid": record.udid},
        )
    )
    try:
        link = await asyncio.wait_for(
            backend.wifi(record.udid, transport.discovery_timeout),
            timeout=transport.discovery_timeout + timeout,
        )
    except TimeoutError as exc:
        raise TransportError(
            f"the Wi-Fi connection did not open within {transport.discovery_timeout + timeout:g} s",
            code="timeout",
        ) from exc
    except TransportError:
        raise
    except Exception as exc:
        raise TransportError(
            f"could not connect over Wi-Fi: {exc}", code="connection_failed"
        ) from exc
    on_event(
        Event(
            "connected",
            "Connected over Wi-Fi.",
            data={"transport": "wifi", "udid": record.udid},
        )
    )
    return link
