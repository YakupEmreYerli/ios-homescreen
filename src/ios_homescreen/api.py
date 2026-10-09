"""Python API: everything the CLI does, with no printing and no argument parsing.

Typical use::

    from ios_homescreen import api

    device = await api.connect(api.Transport())          # USB; Transport(wifi=True) for Wi-Fi
    try:
        snapshot = await api.read_device(device)
        plan = api.plan_layout(layout_toml_or_document, snapshot)
        result = await api.apply_plan(device, plan.payload, backup_dir=api.data_dir() / "backups",
                                      on_event=lambda event: print(event.message))
    finally:
        await device.close()

Long operations report progress through ``on_event`` callbacks (:class:`Event`) and
return dataclasses with ``to_dict()`` for JSON. Errors carry a machine-readable ``code``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .device import Device, DeviceError, open_device
from .events import Event, EventSink, ignore
from .export import export_layout
from .icons import IconCache, load_icons
from .model import describe, to_document
from .paths import cache_dir, data_dir
from .planner import LayoutError, LayoutIssue, Plan, load_layout, plan_layout
from .report import read_summary
from .snapshots import load_read, make_read, state_from_file, timestamp
from .state import (
    PLAN_META_KEY,
    StateError,
    load_plist,
    save_plist,
    to_payload,
    validate_backup,
    validate_plan,
)
from .transport import (
    DEFAULT_DISCOVERY_TIMEOUT,
    Backend,
    PymobiledeviceBackend,
    RemoteRecord,
    Transport,
    TransportError,
    pick_record,
)
from .workflow import ApplyResult, Timing, WorkflowError, apply_state

__all__ = [
    "ApplyResult",
    "Device",
    "DeviceError",
    "Event",
    "EventSink",
    "IconCache",
    "LayoutError",
    "LayoutIssue",
    "Plan",
    "SavedRead",
    "StateError",
    "Timing",
    "Transport",
    "TransportError",
    "WifiStatus",
    "WorkflowError",
    "apply_plan",
    "cache_dir",
    "connect",
    "data_dir",
    "describe",
    "export_layout",
    "fetch_icons",
    "load_backup",
    "load_layout",
    "load_plan",
    "load_read",
    "plan_layout",
    "read_device",
    "restore",
    "save_plan",
    "save_read",
    "set_wifi",
    "to_document",
    "wifi_status",
]


async def connect(
    transport: Transport | None = None,
    *,
    on_event: EventSink = ignore,
    backend: Backend | None = None,
) -> Device:
    """Open the device over USB (default) or the network. Close it when done.

    ``backend`` replaces pymobiledevice3 (tests pass a fake).
    """
    return await open_device(transport or Transport(), on_event=on_event, backend=backend)


async def read_device(device: Any) -> dict[str, Any]:
    """Read-only snapshot: layout, installed User/System apps, raw format 3 state."""
    info = {k: v for k, v in dict(device.info).items() if k != "wifi_mac"}
    state = await device.read_state()
    apps = await device.installed_apps()
    raw_v3, raw_v3_error = None, None
    try:
        raw_v3 = await device.read_raw_state()
    except Exception as exc:
        # The format 3 answer is only kept for reference; its failure is recorded.
        raw_v3_error = str(exc)
    return make_read(state, apps, device=info, raw_v3=raw_v3, raw_v3_error=raw_v3_error)


@dataclass(frozen=True)
class SavedRead:
    path: Path
    summary_path: Path


def save_read(snapshot: Mapping[str, Any], directory: Path) -> SavedRead:
    """Write ``read-TIMESTAMP.plist`` and a text summary next to it."""
    stamp = timestamp()
    path = save_plist(Path(directory) / f"read-{stamp}.plist", dict(snapshot))
    summary = path.with_suffix(".txt")
    summary.write_text(
        read_summary(
            snapshot["state"],
            snapshot["apps"],
            device=snapshot.get("device"),
            raw_v3_error=snapshot.get("raw_state_v3_error"),
        ),
        encoding="utf-8",
    )
    return SavedRead(path, summary)


def save_plan(plan: Plan, path: Path) -> Path:
    return save_plist(path, plan.payload)


def load_plan(path: Path) -> dict[str, Any]:
    """Load and validate a plan file made by :func:`plan_layout` / :func:`save_plan`."""
    plan = load_plist(path)
    validate_plan(plan)
    return plan


def load_backup(path: Path) -> dict[str, Any]:
    """Load a backup, read snapshot or state plist and return it as a restore target."""
    if Path(path).suffix.lower() == ".json":
        raise StateError("restore needs a plist; JSON dumps lose dates and binary data")
    state = state_from_file(path)
    if isinstance(state, dict) and PLAN_META_KEY in state:
        raise StateError(f"{path} is a plan; use apply for plans")
    validate_backup(state)
    return to_payload(state)


async def apply_plan(
    device: Any,
    plan: Mapping[str, Any],
    *,
    backup_dir: Path,
    force: bool = False,
    timing: Timing | None = None,
    on_event: EventSink = ignore,
) -> ApplyResult:
    """Back up, refuse on drift (unless ``force``), write, verify, roll back on failure."""
    validate_plan(plan)
    return await apply_state(
        device, plan, backup_dir=backup_dir, force=force, timing=timing, on_event=on_event
    )


async def restore(
    device: Any,
    target: Any,
    *,
    backup_dir: Path,
    timing: Timing | None = None,
    on_event: EventSink = ignore,
) -> ApplyResult:
    """Write a backup (list or dictionary form, see :func:`load_backup`) like apply does."""
    validate_backup(target)
    # A backup has no source fingerprint: restoring is meant to overwrite.
    return await apply_state(
        device,
        to_payload(target),
        backup_dir=backup_dir,
        force=True,
        timing=timing,
        on_event=on_event,
    )


@dataclass(frozen=True)
class WifiStatus:
    enabled: bool
    """The phone's ``EnableWifiConnections`` setting."""
    device: dict[str, Any]
    pair_record: Path | None
    """This computer's RemotePairing record for the phone (what Wi-Fi uses)."""
    pair_record_problem: str | None
    reachable: bool | None = None
    """Whether the phone answered on the network with that pairing; ``None``: not checked."""
    address: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "device": dict(self.device),
            "pair_record": str(self.pair_record) if self.pair_record else None,
            "pair_record_problem": self.pair_record_problem,
            "reachable": self.reachable,
            "address": self.address,
        }


def _records_for(backend: Backend, udid: Any) -> list[RemoteRecord]:
    if not udid:
        return []
    wanted = str(udid).strip().lower()
    return [r for r in backend.remote_records() if r.udid.strip().lower() == wanted]


def _remote_record(backend: Backend, udid: Any) -> tuple[Path | None, str | None]:
    if not udid:
        return None, "the device did not report its UDID"
    try:
        record = pick_record(backend.remote_records(), str(udid))
    except TransportError as exc:
        return None, str(exc)
    return record.path, None


async def wifi_status(
    device: Any,
    *,
    backend: Backend | None = None,
    check_network: bool = True,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> WifiStatus:
    """The Wi-Fi setting, this computer's Wi-Fi pairing, and whether the phone answers
    on the network right now (``check_network``, over USB only)."""
    backend = backend or PymobiledeviceBackend()
    info = dict(device.info)
    enabled = await device.wifi_connections_enabled()
    record, problem = _remote_record(backend, info.get("udid"))
    reachable, address = None, None
    if getattr(device, "transport", "usb") == "wifi":
        reachable = True
    elif check_network and record is not None:
        try:
            address = await backend.reachable(str(info["udid"]), discovery_timeout)
        except Exception:
            address = None
        reachable = address is not None
    return WifiStatus(enabled, info, record, problem, reachable, address)


async def set_wifi(
    device: Any,
    enabled: bool,
    *,
    backend: Backend | None = None,
    forget: bool = False,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> WifiStatus:
    """Turn Wi-Fi access on or off.

    Enabling sets the phone's ``EnableWifiConnections`` and, over USB, creates this
    computer's RemotePairing record when it is missing (no prompt on the phone: the
    computer is already trusted). Disabling turns the setting off; ``forget`` also
    deletes the pairing record.
    """
    backend = backend or PymobiledeviceBackend()
    await device.set_wifi_connections(enabled)
    records = _records_for(backend, device.info.get("udid"))
    if enabled and not any(r.usable for r in records):
        if getattr(device, "transport", "usb") != "usb":
            raise DeviceError("the Wi-Fi pairing can only be made over USB", code="needs_usb")
        for record in records:
            # Made by an older pymobiledevice3; it would be reused as it is.
            record.path.unlink(missing_ok=True)
        try:
            await backend.pair_remote(getattr(device, "lockdown", device))
        except Exception as exc:
            raise DeviceError(
                f"creating the Wi-Fi pairing failed: {exc}", code="pairing_failed"
            ) from exc
    if not enabled and forget:
        for record in records:
            record.path.unlink(missing_ok=True)
    status = await wifi_status(
        device, backend=backend, check_network=enabled, discovery_timeout=discovery_timeout
    )
    if status.enabled != enabled:
        raise DeviceError("the phone did not keep the new Wi-Fi setting", code="setting_not_kept")
    if enabled and status.pair_record is None:
        raise DeviceError(
            f"the Wi-Fi pairing was not created: {status.pair_record_problem}",
            code="pairing_failed",
        )
    return status


async def fetch_icons(
    device: Any, identifiers: Iterable[str], cache: IconCache | None = None
) -> dict[str, bytes | None]:
    """App icon PNGs by bundle id; ``None`` where the device has none."""
    return await load_icons(device, identifiers, cache)
