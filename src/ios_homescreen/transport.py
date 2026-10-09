"""Pick and open the lockdown connection: USB through usbmuxd, or the network.

Over the network the phone is reached on its lockdown port (62078). Its address comes
from ``--host`` or from Bonjour: paired iPhones with Wi-Fi connections enabled answer
``_apple-mobdev2._tcp`` with an instance name that starts with their Wi-Fi MAC address,
and usbmuxd's pair records carry the same address as ``WiFiMACAddress``. The pair
record is what lets us start a session without the USB cable.

pymobiledevice3 is imported lazily so that ``--help`` and the tests never load it.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import plistlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .events import Event, EventSink, ignore
from .paths import default_pair_records_dir

DEFAULT_DISCOVERY_TIMEOUT = 5.0
DEFAULT_CONNECT_TIMEOUT = 30.0


class TransportError(RuntimeError):
    """The device could not be reached over the chosen transport."""

    def __init__(self, message: str, *, code: str = "transport_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Transport:
    """How to reach the device. The default is USB."""

    wifi: bool = False
    host: str | None = None
    udid: str | None = None
    pair_records: Path = field(default_factory=default_pair_records_dir)
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT

    @property
    def network(self) -> bool:
        return self.wifi or bool(self.host)

    def describe(self) -> str:
        if self.host:
            return f"network ({self.host})"
        if self.wifi:
            return "network (Bonjour discovery)"
        return "USB"


@dataclass(frozen=True)
class PairRecord:
    udid: str
    path: Path
    wifi_mac: str | None
    data: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class Candidate:
    record: PairRecord
    addresses: tuple[str, ...]


def normalize_mac(value: Any) -> str | None:
    """``"A0:B:0C:..."`` -> ``"a0:0b:0c:..."``; ``None`` if it is not a MAC address."""
    if not isinstance(value, str):
        return None
    parts = value.strip().lower().replace("-", ":").split(":")
    if len(parts) != 6:
        return None
    try:
        octets = [int(part, 16) for part in parts]
    except ValueError:
        return None
    if any(not 0 <= octet <= 255 for octet in octets):
        return None
    return ":".join(f"{octet:02x}" for octet in octets)


def mac_from_instance(instance: str) -> str | None:
    """Wi-Fi MAC from a mobdev2 instance name such as ``aa:bb:...@fe80::1._apple-mobdev2...``."""
    if "@" not in instance:
        return None
    return normalize_mac(instance.split("@", 1)[0])


def _same_udid(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def load_pair_records(directory: Path, udid: str | None = None) -> list[PairRecord]:
    """Device pair records in usbmuxd's store, optionally only the one for ``udid``.

    Files that are not device pair records (``SystemConfiguration.plist``, for one)
    are skipped.
    """
    directory = Path(directory)
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError as exc:
        raise TransportError(
            f"pair record directory {directory} does not exist; pair the phone over USB "
            "first, or point --pair-records at the right directory",
            code="pair_records_missing",
        ) from exc
    except PermissionError as exc:
        raise TransportError(
            f"cannot list {directory} (permission denied); give your user read access "
            "or pass --pair-records with a readable copy",
            code="pair_records_unreadable",
        ) from exc
    records = []
    for name in names:
        path = directory / name
        if not name.endswith(".plist") or name.startswith("remote_"):
            continue
        stem = name.removesuffix(".plist")
        if udid is not None and not _same_udid(stem, udid):
            continue
        try:
            data = plistlib.loads(path.read_bytes())
        except PermissionError as exc:
            raise TransportError(
                f"cannot read {path} (permission denied); give your user read access "
                "or pass --pair-records with a readable copy",
                code="pair_records_unreadable",
            ) from exc
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        if not isinstance(data, dict) or not {"HostID", "HostCertificate"} <= data.keys():
            continue
        records.append(PairRecord(stem, path, normalize_mac(data.get("WiFiMACAddress")), data))
    return records


def _address_order(address: str) -> tuple[int, str]:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return (3, address)
    if ip.version == 4:
        return (0, address)
    return (2 if ip.is_link_local else 1, address)


def _full_ip(address: Any) -> str | None:
    value = getattr(address, "full_ip", address)
    return value if isinstance(value, str) and value else None


def match_discovered(answers: Iterable[Any], records: Iterable[PairRecord]) -> list[Candidate]:
    """Pair Bonjour answers with pair records through the Wi-Fi MAC address.

    ``answers`` are pymobiledevice3 ``ServiceInstance`` objects (``instance`` and
    ``addresses``). Several answers for one phone (one per interface) are merged.
    IPv4 addresses come first, link-local IPv6 last.
    """
    by_mac = {record.wifi_mac: record for record in records if record.wifi_mac}
    found: dict[str, tuple[PairRecord, list[str]]] = {}
    for answer in answers:
        record = by_mac.get(mac_from_instance(str(getattr(answer, "instance", ""))))
        if record is None:
            continue
        _, addresses = found.setdefault(record.udid, (record, []))
        for address in getattr(answer, "addresses", []) or []:
            ip = _full_ip(address)
            if ip and ip not in addresses:
                addresses.append(ip)
    return [
        Candidate(record, tuple(sorted(addresses, key=_address_order)))
        for _, (record, addresses) in sorted(found.items())
    ]


def pick_candidate(candidates: list[Candidate], answered: int, transport: Transport) -> Candidate:
    if not candidates:
        if answered:
            raise TransportError(
                f"{answered} device(s) answered on the network, but none matches a pair "
                f"record in {transport.pair_records}"
                + (f" for UDID {transport.udid}" if transport.udid else "")
                + ". Check --udid and --pair-records, or use --host.",
                code="no_matching_device",
            )
        raise TransportError(
            "no paired device answered on the network. The phone must be on the same "
            "network, awake and unlocked, with Wi-Fi connections enabled "
            "('ios-homescreen wifi enable' over USB once). Or pass --host.",
            code="no_device_found",
        )
    if len(candidates) > 1:
        udids = ", ".join(c.record.udid for c in candidates)
        raise TransportError(
            f"several paired devices answered ({udids}); pick one with --udid",
            code="several_devices",
        )
    candidate = candidates[0]
    if not candidate.addresses:
        raise TransportError(
            f"device {candidate.record.udid} answered without a usable address; try --host",
            code="no_address",
        )
    return candidate


def record_for_host(records: list[PairRecord], transport: Transport) -> PairRecord:
    if not records:
        which = f" for UDID {transport.udid}" if transport.udid else ""
        raise TransportError(
            f"no pair record{which} in {transport.pair_records}; pair over USB first "
            "or point --pair-records at the right directory",
            code="no_pair_record",
        )
    if len(records) > 1:
        udids = ", ".join(record.udid for record in records)
        raise TransportError(
            f"several pair records in {transport.pair_records} ({udids}); pick one with --udid",
            code="several_pair_records",
        )
    return records[0]


class Backend(Protocol):
    async def usb(self, udid: str | None, pair_timeout: float) -> Any: ...

    async def tcp(self, host: str, pair_record: dict[str, Any]) -> Any: ...

    async def browse(self, timeout: float) -> list[Any]: ...


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

    async def tcp(self, host: str, pair_record: dict[str, Any]) -> Any:
        from pymobiledevice3.lockdown import create_using_tcp

        # The pair record must be passed in: over TCP pymobiledevice3 would look it up
        # by host name and find nothing. autopair=False: never start pairing over Wi-Fi.
        return await create_using_tcp(
            hostname=host, autopair=False, pair_record=pair_record, keep_alive=True
        )

    async def browse(self, timeout: float) -> list[Any]:
        from pymobiledevice3.bonjour import browse_mobdev2

        return await browse_mobdev2(timeout=timeout)


async def close_quietly(lockdown: Any, timeout: float = 3.0) -> None:
    close = getattr(lockdown, "close", None)
    if close is None:
        return
    # Nothing useful can be done about a failed close; the socket goes away anyway.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(close(), timeout=timeout)


async def _tcp(backend: Backend, host: str, record: PairRecord, timeout: float) -> Any:
    try:
        lockdown = await asyncio.wait_for(backend.tcp(host, record.data), timeout=timeout)
    except TimeoutError as exc:
        raise TransportError(
            f"connecting to {host} timed out after {timeout:g} s", code="timeout"
        ) from exc
    except TransportError:
        raise
    except Exception as exc:
        raise TransportError(
            f"could not connect to {host}: {exc}", code="connection_failed"
        ) from exc
    if not getattr(lockdown, "paired", False):
        await close_quietly(lockdown)
        raise TransportError(
            f"{host} did not accept the pair record of {record.udid}. Connect over USB "
            "and trust this computer again.",
            code="not_paired",
        )
    return lockdown


async def connect(
    transport: Transport,
    *,
    backend: Backend | None = None,
    on_event: EventSink = ignore,
) -> Any:
    """Open a lockdown client over the transport ``transport`` describes."""
    backend = backend or PymobiledeviceBackend()
    timeout = transport.connect_timeout
    if not transport.network:
        on_event(Event("connecting", "Connecting over USB...", data={"transport": "usb"}))
        try:
            return await asyncio.wait_for(backend.usb(transport.udid, timeout), timeout=timeout)
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

    records = load_pair_records(transport.pair_records, transport.udid)
    if transport.host:
        record = record_for_host(records, transport)
        on_event(
            Event(
                "connecting",
                f"Connecting to {transport.host} over the network...",
                data={"transport": "network", "host": transport.host},
            )
        )
        return await _tcp(backend, transport.host, record, timeout)

    if not any(record.wifi_mac for record in records):
        which = f" for UDID {transport.udid}" if transport.udid else ""
        raise TransportError(
            f"no pair record{which} with a Wi-Fi MAC address in {transport.pair_records}; "
            "pair over USB first, or use --host",
            code="no_pair_record",
        )
    on_event(
        Event(
            "discovering",
            f"Looking for paired devices on the network ({transport.discovery_timeout:g} s)...",
            data={"timeout": transport.discovery_timeout},
        )
    )
    try:
        answers = await asyncio.wait_for(
            backend.browse(transport.discovery_timeout),
            timeout=transport.discovery_timeout + 10,
        )
    except TimeoutError as exc:
        raise TransportError("Bonjour discovery did not finish", code="discovery_failed") from exc
    except OSError as exc:
        raise TransportError(f"Bonjour discovery failed: {exc}", code="discovery_failed") from exc
    candidate = pick_candidate(match_discovered(answers, records), len(answers), transport)
    errors: list[TransportError] = []
    for address in candidate.addresses:
        on_event(
            Event(
                "connecting",
                f"Found {candidate.record.udid} at {address}, connecting...",
                data={"transport": "network", "host": address, "udid": candidate.record.udid},
            )
        )
        try:
            return await _tcp(backend, address, candidate.record, timeout)
        except TransportError as exc:
            errors.append(exc)
    raise TransportError("; ".join(map(str, errors)), code=errors[-1].code)
