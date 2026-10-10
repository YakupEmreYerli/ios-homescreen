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
   address, which iOS randomises), and the record proves who we are. Bonjour answers
   are unreliable on many networks (none for a while, then fine), so the address and
   port of every successful connection are remembered per phone, and the next
   connection tries them directly while it browses (see :func:`locate`).
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
import ipaddress
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .events import Event, EventSink, ignore
from .paths import cache_dir

DEFAULT_DISCOVERY_TIMEOUT = 5.0
DEFAULT_CONNECT_TIMEOUT = 30.0
CLOSE_TIMEOUT = 10.0
DIRECT_TIMEOUT = 5.0
"""Time for one try at a remembered address (the browse runs alongside)."""
ADDRESS_FILE = "wifi-addresses.json"
MAX_ADDRESSES = 4

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
    marketing_name: str | None = None
    """``iPhone 15``, when the connection said so (the Wi-Fi handshake does)."""


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


# --------------------------------------------------------------------------- finding the phone


@dataclass(frozen=True)
class KnownAddress:
    """Where a phone answered RemotePairing last."""

    addresses: tuple[str, ...]
    port: int


def _valid_address(text: Any) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None
    return text


class AddressMemory:
    """The address and RemotePairing port each phone answered on last, per UDID, in
    ``CACHE/wifi-addresses.json``. Only addresses: no keys, nothing secret."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or cache_dir() / ADDRESS_FILE

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        phones = data.get("phones") if isinstance(data, dict) else None
        return phones if isinstance(phones, dict) else {}

    def get(self, udid: str) -> KnownAddress | None:
        entry = self._load().get(udid)
        if not isinstance(entry, dict):
            return None
        port = entry.get("port")
        addresses = tuple(
            a for a in (_valid_address(x) for x in entry.get("addresses", []) or []) if a
        )
        if not addresses or not isinstance(port, int) or not 0 < port < 65536:
            return None
        return KnownAddress(addresses[:MAX_ADDRESSES], port)

    def remember(self, udid: str, address: Any, port: Any) -> None:
        """Put ``address`` first for ``udid``; earlier ones stay behind it."""
        address = _valid_address(address)
        if address is None or not isinstance(port, int) or not 0 < port < 65536:
            return
        phones = self._load()
        known = self.get(udid)
        earlier = [a for a in (known.addresses if known else ()) if a != address]
        phones[udid] = {
            "addresses": [address, *earlier][:MAX_ADDRESSES],
            "port": port,
            "seen": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps({"version": 1, "phones": phones}, indent=2), encoding="utf-8")
        tmp.replace(path)


async def _close(service: Any) -> None:
    if service is not None and hasattr(service, "close"):
        await close_quietly(service.close)


async def locate(
    discovery_timeout: float,
    *,
    browse: Callable[[float], Awaitable[Any | None]],
    direct: Callable[[str, int], Awaitable[Any]],
    known: KnownAddress | None = None,
    direct_timeout: float = DIRECT_TIMEOUT,
) -> Any | None:
    """Find the phone's RemotePairing service; ``None`` when nothing answered.

    The remembered addresses are tried directly while Bonjour browses, and whichever
    answers first wins; the others are stopped and anything they opened is closed. The
    browse gets ``discovery_timeout`` seconds in two tries, because a fresh query often
    gets the answer the first one did not.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + discovery_timeout

    async def browsing() -> Any | None:
        for attempt in (1, 2):
            remaining = deadline - loop.time()
            if remaining <= 0.1:
                return None
            window = remaining / 2 if attempt == 1 else remaining
            try:
                found = await browse(window)
            except asyncio.CancelledError:
                raise
            except Exception:
                found = None
            if found is not None:
                return found
        return None

    async def trying(address: str, port: int) -> Any | None:
        try:
            return await asyncio.wait_for(direct(address, port), direct_timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    tasks = {asyncio.ensure_future(browsing())}
    if known is not None:
        for address in known.addresses:
            tasks.add(asyncio.ensure_future(trying(address, known.port)))
    winner = None
    try:
        while tasks and winner is None:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                found = task.result()
                if found is None:
                    continue
                if winner is None:
                    winner = found
                else:
                    await _close(found)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                late = await task
                if late is not None and late is not winner:
                    await _close(late)
    return winner


_tunnel_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _tunnel_lock
    if _tunnel_lock is None:
        _tunnel_lock = asyncio.Lock()
    return _tunnel_lock


class PymobiledeviceBackend:
    """The real connections, through pymobiledevice3."""

    def __init__(self, memory: AddressMemory | None = None) -> None:
        self.memory = memory or AddressMemory()

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

    async def _browse(self, udid: str, window: float) -> Any | None:
        from pymobiledevice3.remote.tunnel_service import get_remote_pairing_tunnel_services

        services = await get_remote_pairing_tunnel_services(bonjour_timeout=window, udid=udid)
        for extra in services[1:]:
            await extra.close()
        return services[0] if services else None

    async def _direct(self, udid: str, address: str, port: int) -> Any:
        """Pair-verify with the phone at a remembered address; never starts pairing.

        What ``create_core_device_tunnel_service_using_remotepairing`` does, except that a
        cancelled attempt (the browse won) closes its connection too.
        """
        from pymobiledevice3.remote.tunnel_service import RemotePairingTunnelService

        service = RemotePairingTunnelService(udid, address, port)
        try:
            await service.connect(autopair=False)
        except BaseException:
            await _close(service)
            raise
        return service

    async def _find(self, udid: str, discovery_timeout: float) -> Any | None:
        service = await locate(
            discovery_timeout,
            browse=lambda window: self._browse(udid, window),
            direct=lambda address, port: self._direct(udid, address, port),
            known=self.memory.get(udid),
            direct_timeout=max(DIRECT_TIMEOUT, discovery_timeout),
        )
        if service is not None:
            with contextlib.suppress(OSError):
                self.memory.remember(
                    udid, getattr(service, "hostname", None), getattr(service, "port", None)
                )
        return service

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
            known = self.memory.get(udid)
            service = await self._find(udid, discovery_timeout)
            if service is None:
                tried = f"; it did not answer at {known.addresses[0]} either" if known else ""
                raise TransportError(
                    f"the iPhone did not answer on the network (looked for "
                    f"{discovery_timeout:g} s{tried}). Keep it awake and unlocked on the same "
                    "network as this computer.",
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
        return Link(
            rsd,
            tunnel.aclose,
            kind="wifi",
            address=address or None,
            marketing_name=marketing_name(service, rsd),
        )


_MARKETING_KEYS = ("marketing-name", "MarketingName", "marketingName")


def marketing_name(*sources: Any) -> str | None:
    """The phone's marketing name (``iPhone 15``) from what the Wi-Fi handshake left behind.

    The RemotePairing handshake's ``peerDeviceInfo`` and its device key-value data carry
    ``marketing-name``; the RSD handshake's properties may too. Each source is a tunnel
    service or an RSD session; anything missing is skipped.
    """
    found: list[Any] = []
    for source in sources:
        info = getattr(source, "handshake_info", None)
        if isinstance(info, Mapping):
            found.append(info.get("peerDeviceInfo"))
        peer = getattr(source, "peer_info", None)
        if isinstance(peer, Mapping):
            found.append(peer.get("Properties"))
        try:
            metadata = getattr(source, "auxiliary_metadata", None)
        except Exception:
            metadata = None
        if isinstance(metadata, Mapping):
            found.append(metadata)
            found.extend(metadata.values())
    for table in found:
        if not isinstance(table, Mapping):
            continue
        for key in _MARKETING_KEYS:
            value = table.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


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
