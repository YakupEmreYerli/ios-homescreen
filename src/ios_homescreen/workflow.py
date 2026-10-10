"""Backup, drift check, timed write, verification by re-read, automatic rollback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .events import ERROR, WARNING, Event, EventSink, ignore
from .snapshots import make_backup, timestamp
from .state import PLAN_META_KEY, fingerprint, safe_payload, same_layout, save_plist

APPLIED = "applied"
ROLLED_BACK = "rolled-back"
ROLLBACK_FAILED = "rollback-failed"

STEPS = 5


class WorkflowError(RuntimeError):
    """A precondition for a safe write was not met; nothing was written."""

    def __init__(self, message: str, *, code: str = "workflow_error") -> None:
        super().__init__(message)
        self.code = code


class HomeScreen(Protocol):
    async def read_state(self) -> Any: ...

    async def installed_apps(self) -> dict[str, Any]: ...

    async def write_state(self, payload: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class Timing:
    read_timeout: float = 30.0
    write_timeout: float = 10.0
    verify_attempts: int = 6
    verify_interval: float = 3.0


@dataclass(frozen=True)
class ApplyResult:
    status: str
    """``applied``, ``rolled-back`` or ``rollback-failed``."""
    backup: Path
    write_unconfirmed: bool
    rollback_verified: bool
    events: tuple[Event, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.status == APPLIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "backup": str(self.backup),
            "write_unconfirmed": self.write_unconfirmed,
            "rollback_verified": self.rollback_verified,
            "events": [event.to_dict() for event in self.events],
        }


async def _timed(awaitable: Awaitable[Any], seconds: float, what: str) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except TimeoutError as exc:
        raise WorkflowError(f"{what} did not finish within {seconds:g} s", code="timeout") from exc


async def _verify(device: HomeScreen, target: Any, timing: Timing) -> bool:
    attempts = max(1, timing.verify_attempts)
    for attempt in range(attempts):
        if attempt > 0 and timing.verify_interval:
            await asyncio.sleep(timing.verify_interval)
        try:
            current = await _timed(device.read_state(), timing.read_timeout, "Re-read")
        except Exception:
            # After a write, a failed read proves nothing either way. Keep trying;
            # without proof the caller rolls back.
            continue
        if same_layout(current, target):
            return True
    return False


async def _write(device: HomeScreen, payload: dict[str, Any], seconds: float) -> bool:
    """Send ``payload``; return True when the device did not confirm the write.

    An unconfirmed write is not a failure by itself: SpringBoard often never replies
    to setIconState. The re-read decides.
    """
    try:
        await asyncio.wait_for(device.write_state(payload), timeout=seconds)
        return False
    except Exception:
        return True


async def apply_state(
    device: HomeScreen,
    target: Mapping[str, Any],
    *,
    backup_dir: Path,
    force: bool = False,
    timing: Timing | None = None,
    on_event: EventSink = ignore,
) -> ApplyResult:
    """Back up, write ``target`` safely, prove it by re-reading, roll back if needed.

    ``target`` is a plan payload (with a source fingerprint) or a plain state to restore.
    The backup records the layout as read and the device's ``info`` when it has one.
    Raises :class:`WorkflowError` before anything is written if a precondition fails.
    """
    timing = timing or Timing()
    events: list[Event] = []

    def emit(code: str, message: str, step: int | None = None, **data: Any) -> None:
        level = data.pop("level", "info")
        event = Event(code, message, step, STEPS if step else None, level, data)
        events.append(event)
        on_event(event)

    emit("reading", "Reading the current layout and saving a backup...", 1)
    current = await _timed(device.read_state(), timing.read_timeout, "Reading the layout")
    installed = await _timed(
        device.installed_apps(), timing.read_timeout, "Reading the installed apps"
    )
    backup = save_plist(
        Path(backup_dir) / f"backup-{timestamp()}.plist",
        make_backup(current, device=getattr(device, "info", None)),
    )
    emit("backup_saved", f"Backup: {backup}", path=backup)

    meta = target.get(PLAN_META_KEY)
    source = meta.get("source_fingerprint") if isinstance(meta, Mapping) else None
    if source and source != fingerprint(current) and not force:
        raise WorkflowError(
            "the phone's layout changed since the pull this layout was made from; nothing "
            "was written. Pull again, or push with --force to write anyway.",
            code="layout_changed",
        )

    emit("building", "Building the payload from the installed User and System apps...", 2)
    payload = safe_payload(dict(target), installed)
    ignored = len(payload["ignored"])
    emit(
        "writing",
        f"Sending the new layout ({ignored} apps kept off the home screen)...",
        3,
        ignored=ignored,
    )
    unconfirmed = await _write(device, payload, timing.write_timeout)
    if unconfirmed:
        emit(
            "write_unconfirmed",
            "The device did not confirm the write. That alone is not an error; checking.",
            level=WARNING,
        )

    emit("verifying", "Re-reading the layout to verify it...", 4)
    if await _verify(device, payload, timing):
        emit("verified", "Layout verified.", 5)
        return ApplyResult(APPLIED, backup, unconfirmed, False, tuple(events))

    emit(
        "rolling_back",
        "The new layout could not be verified. Rolling back to the backup...",
        level=WARNING,
    )
    rollback = safe_payload(current, installed)
    rollback_unconfirmed = await _write(device, rollback, timing.write_timeout)
    if await _verify(device, rollback, timing):
        emit(
            "rolled_back",
            "Rollback written and verified. The device is back to its previous layout.",
            level=WARNING,
        )
        return ApplyResult(
            ROLLED_BACK, backup, unconfirmed or rollback_unconfirmed, True, tuple(events)
        )
    emit(
        "rollback_failed",
        f"CRITICAL: the rollback could not be verified either. Backup kept at {backup}.",
        level=ERROR,
        path=backup,
    )
    return ApplyResult(
        ROLLBACK_FAILED, backup, unconfirmed or rollback_unconfirmed, False, tuple(events)
    )
