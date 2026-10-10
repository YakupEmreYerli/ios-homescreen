"""Command line interface."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from . import __version__, api
from .events import Event
from .paths import (
    BACKUPS,
    DATA_DIR_ENV,
    PLANS,
    READS,
    data_dir,
)
from .report import diff_text, overview
from .snapshots import latest, state_from_file, timestamp
from .state import split_state
from .transport import DEFAULT_CONNECT_TIMEOUT, DEFAULT_DISCOVERY_TIMEOUT, Transport
from .workflow import APPLIED, ROLLBACK_FAILED, ROLLED_BACK, Timing

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_CONFIRMED = 2
EXIT_ROLLED_BACK = 3
EXIT_ROLLBACK_FAILED = 4

Opener = Callable[[Transport], Awaitable[Any]]


def say(message: str = "") -> None:
    print(message, flush=True)


def positive_number(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def non_negative_number(text: str) -> float:
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def port_number(text: str) -> int:
    value = int(text)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("must be between 0 and 65535")
    return value


def positive_integer(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


EPILOG = """\
Typical session:
  ios-homescreen read
  ios-homescreen export -o layout.toml
  ios-homescreen plan layout.toml -o plan.plist
  ios-homescreen apply plan.plist --yes

Exit codes: 0 done; 1 error (apply and restore stop before writing); 2 usage
error or --yes missing; 3 the new layout did not verify and the backup was
restored; 4 the restore did not verify either (the backup file is kept).

Data directory: {data_dir}
(override with --data-dir or ${env})
"""


def _writing_options(*, confirm: bool) -> argparse.ArgumentParser:
    """Write options; ``--yes`` only where the command line is the confirmation."""
    writing = argparse.ArgumentParser(add_help=False)
    defaults = Timing()
    group = writing.add_argument_group("writing")
    if confirm:
        group.add_argument(
            "--yes",
            action="store_true",
            help="confirm the write; without it the device is not contacted at all",
        )
    group.add_argument(
        "--backup-dir",
        type=Path,
        metavar="DIR",
        help="where the automatic backup is saved (default: DATA_DIR/backups)",
    )
    group.add_argument(
        "--verify-attempts",
        type=positive_integer,
        default=defaults.verify_attempts,
        metavar="N",
        help="re-reads used to verify a write before rolling back (default: %(default)s)",
    )
    group.add_argument(
        "--verify-interval",
        type=non_negative_number,
        default=defaults.verify_interval,
        metavar="SECONDS",
        help="pause between verification re-reads (default: %(default)g)",
    )
    group.add_argument(
        "--write-timeout",
        type=positive_number,
        default=defaults.write_timeout,
        metavar="SECONDS",
        help="time limit for sending the layout (default: %(default)g)",
    )
    group.add_argument(
        "--read-timeout",
        type=positive_number,
        default=defaults.read_timeout,
        metavar="SECONDS",
        help="time limit for each read (default: %(default)g)",
    )
    return writing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ios-homescreen",
        description=(
            "Read an iPhone home screen, plan a new layout offline from a TOML file, "
            "and write it back safely, over USB or Wi-Fi."
        ),
        epilog=EPILOG.format(data_dir=data_dir(), env=DATA_DIR_ENV),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    commands.required = True

    storage = argparse.ArgumentParser(add_help=False)
    storage.add_argument(
        "--data-dir",
        type=Path,
        metavar="DIR",
        help=f"where reads, backups and plans are kept (env ${DATA_DIR_ENV})",
    )

    connection = argparse.ArgumentParser(add_help=False)
    group = connection.add_argument_group("connection (USB unless --wifi)")
    group.add_argument(
        "--wifi",
        action="store_true",
        help=(
            "connect over the local network (iOS 17 or later; run 'wifi enable' over USB "
            "once first)"
        ),
    )
    group.add_argument(
        "--udid", metavar="UDID", help="choose the device when more than one is available"
    )
    group.add_argument(
        "--discovery-timeout",
        type=positive_number,
        default=DEFAULT_DISCOVERY_TIMEOUT,
        metavar="SECONDS",
        help="how long to look for the phone on the network (default: %(default)g)",
    )
    group.add_argument(
        "--connect-timeout",
        type=positive_number,
        default=DEFAULT_CONNECT_TIMEOUT,
        metavar="SECONDS",
        help="time limit for opening the connection (default: %(default)g)",
    )

    writing = _writing_options(confirm=True)
    ui_writing = _writing_options(confirm=False)

    read = commands.add_parser(
        "read",
        parents=[storage, connection],
        help="save the current layout and installed apps (read-only)",
        description=(
            "Save the home screen layout and the installed User and System apps as a read "
            "snapshot, plus a text summary. Never writes to the device."
        ),
    )
    read.add_argument(
        "-o", "--output", type=Path, metavar="DIR", help="directory (default: DATA_DIR/reads)"
    )

    export = commands.add_parser(
        "export",
        parents=[storage],
        help="turn a read into an editable TOML layout",
        description=(
            "Write the layout of a read snapshot as a TOML file that you can edit. "
            "Offline; does not contact the device."
        ),
    )
    export.add_argument(
        "read", nargs="?", type=Path, metavar="READ", help="read snapshot (default: newest read)"
    )
    export.add_argument(
        "-o", "--output", type=Path, metavar="FILE", help="layout file (default: print it)"
    )

    plan = commands.add_parser(
        "plan",
        parents=[storage],
        help="check a TOML layout and build a plan (offline)",
        description=(
            "Resolve a TOML layout against a read snapshot, check it, show what will change "
            "and save a plan for 'apply'. Offline; does not contact the device."
        ),
    )
    plan.add_argument("layout", type=Path, metavar="LAYOUT", help="TOML layout file")
    plan.add_argument(
        "--read", type=Path, metavar="READ", help="read snapshot (default: newest read)"
    )
    plan.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="plan file (default: DATA_DIR/plans/plan-TIMESTAMP.plist)",
    )
    plan.add_argument(
        "--allow-removal",
        action="store_true",
        help=(
            "allow removing widgets that the layout leaves out (web clips and web apps "
            "cannot be removed this way; delete them on the phone)"
        ),
    )

    apply = commands.add_parser(
        "apply",
        parents=[storage, connection, writing],
        help="write a plan to the device, verified, with automatic rollback",
        description=(
            "Back up the current layout, refuse if it changed since the plan's read, write "
            "the plan, re-read to verify it, and restore the backup if verification fails."
        ),
    )
    apply.add_argument("plan", type=Path, metavar="PLAN", help="plan file made by 'plan'")
    apply.add_argument(
        "--force",
        action="store_true",
        help="write even if the device layout changed since the plan's read",
    )

    restore = commands.add_parser(
        "restore",
        parents=[storage, connection, writing],
        help="write a backup or read back to the device, verified",
        description=(
            "Restore a backup, read snapshot or saved layout plist. The list of apps kept "
            "off the home screen is recomputed from the apps installed now. Same safety "
            "steps as 'apply'."
        ),
    )
    restore.add_argument(
        "backup", type=Path, metavar="BACKUP", help="backup or read snapshot (.plist)"
    )

    diff = commands.add_parser(
        "diff",
        help="compare two saved layouts (offline)",
        description=(
            "Show items that moved, appeared or disappeared between two saved layouts "
            "(reads, backups, plans, or plist/JSON state dumps). Offline."
        ),
    )
    diff.add_argument("before", type=Path, metavar="BEFORE")
    diff.add_argument("after", type=Path, metavar="AFTER")

    wifi = commands.add_parser(
        "wifi",
        parents=[connection],
        help="set up, check or turn off Wi-Fi access to the phone",
        description=(
            "enable (over USB, once): turn on the phone's Wi-Fi connections setting and "
            "pair this computer for Wi-Fi (RemotePairing; no prompt on the phone, no root, "
            "no Developer Mode). status: show the setting, the pairing, and whether the "
            "phone answers on the network now. disable: turn the setting off; with "
            "--forget also delete this computer's Wi-Fi pairing. Afterwards use --wifi "
            "while the phone is on the same network, awake and unlocked (iOS 17 or later)."
        ),
    )
    wifi.add_argument(
        "action",
        choices=["status", "enable", "disable"],
        metavar="ACTION",
        help="status, enable or disable",
    )
    wifi.add_argument(
        "--forget",
        action="store_true",
        help="with disable: also delete this computer's Wi-Fi pairing with the phone",
    )

    ui = commands.add_parser(
        "ui",
        parents=[storage, connection, ui_writing],
        help="edit the home screen in your browser",
        description=(
            "Start a local editor on 127.0.0.1 and open it in the browser: drag apps, "
            "folders and widgets around, see what will change, and apply it with the same "
            "backup, verification and rollback as 'apply'. The address printed at start "
            "contains a key that changes on every run. Needs the 'ui' extra."
        ),
    )
    group = ui.add_argument_group("browser UI")
    group.add_argument(
        "--port",
        type=port_number,
        default=0,
        metavar="PORT",
        help="port on 127.0.0.1 (default: any free port)",
    )
    group.add_argument(
        "--no-browser",
        action="store_true",
        help="only print the address; do not open a browser",
    )
    group.add_argument(
        "--demo",
        action="store_true",
        help="try the editor on a pretend iPhone; nothing connects to a phone",
    )
    return parser


# --------------------------------------------------------------------------- helpers


def _data_dir(args: argparse.Namespace) -> Path:
    return args.data_dir.expanduser() if getattr(args, "data_dir", None) else data_dir()


def _transport(args: argparse.Namespace) -> Transport:
    return Transport(
        wifi=bool(args.wifi),
        udid=args.udid,
        discovery_timeout=args.discovery_timeout,
        connect_timeout=args.connect_timeout,
    )


def _timing(args: argparse.Namespace) -> Timing:
    return Timing(
        read_timeout=args.read_timeout,
        write_timeout=args.write_timeout,
        verify_attempts=args.verify_attempts,
        verify_interval=args.verify_interval,
    )


def _describe(info: Mapping[str, Any]) -> str:
    version = f"iOS {info['ios_version']}" if info.get("ios_version") else None
    details = ", ".join(str(x) for x in (info.get("model"), version) if x)
    name = info.get("name") or "device"
    return f"{name} ({details})" if details else str(name)


def _show(event: Event) -> None:
    prefix = f"[{event.step}/{event.total}] " if event.step and event.total else ""
    say(prefix + event.message)


def _read_path(args: argparse.Namespace, given: Path | None) -> Path:
    if given is not None:
        return given
    path = latest(_data_dir(args) / READS, "read-*.plist")
    print(f"Using read: {path}", file=sys.stderr, flush=True)
    return path


def _default_opener(transport: Transport) -> Awaitable[Any]:
    return api.connect(transport, on_event=_show)


# --------------------------------------------------------------------------- commands


async def _read(args: argparse.Namespace, opener: Opener) -> int:
    device = await opener(_transport(args))
    try:
        say(f"Connected: {_describe(device.info)}")
        say("Reading the home screen (read-only)...")
        snapshot = await api.read_device(device)
    finally:
        await device.close()
    saved = api.save_read(snapshot, args.output or _data_dir(args) / READS)
    say(f"Read saved: {saved.path}")
    say(f"Summary: {saved.summary_path}")
    say(f"Found {overview(snapshot['state'], snapshot['apps'])}.")
    return EXIT_OK


def _export(args: argparse.Namespace) -> int:
    path = _read_path(args, args.read)
    text = api.export_layout(api.load_read(path), source=path.name)
    if args.output is None:
        sys.stdout.write(text)
        return EXIT_OK
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    say(f"Layout written: {args.output}")
    return EXIT_OK


def _plan(args: argparse.Namespace) -> int:
    read = api.load_read(_read_path(args, args.read))
    plan = api.plan_layout(args.layout, read, allow_removal=args.allow_removal)
    out = api.save_plan(plan, args.output or _data_dir(args) / PLANS / f"plan-{timestamp()}.plist")
    say(plan.changes)
    say(f"\nPlan written: {out}")
    say(f"Apply it with: ios-homescreen apply {out} --yes")
    return EXIT_OK


def _not_confirmed(target: Mapping[str, Any], what: str) -> int:
    dock, pages = split_state(dict(target))
    if what == "plan":
        kept = f", {len(target.get('ignored', []))} apps kept off the home screen"
    else:
        kept = "; installed apps that are not in it will stay in the App Library"
    say(f"The {what} is valid: {len(dock)} dock items, {len(pages)} pages{kept}.")
    say("Nothing was written and the device was not contacted. Add --yes to write it.")
    return EXIT_NOT_CONFIRMED


_EXIT_FOR_STATUS = {
    APPLIED: EXIT_OK,
    ROLLED_BACK: EXIT_ROLLED_BACK,
    ROLLBACK_FAILED: EXIT_ROLLBACK_FAILED,
}


async def _apply(args: argparse.Namespace, opener: Opener, plan: dict[str, Any]) -> int:
    device = await opener(_transport(args))
    try:
        say(f"Connected: {_describe(device.info)}")
        result = await api.apply_plan(
            device,
            plan,
            backup_dir=args.backup_dir or _data_dir(args) / BACKUPS,
            force=args.force,
            timing=_timing(args),
            on_event=_show,
        )
    finally:
        await device.close()
    return _EXIT_FOR_STATUS[result.status]


async def _restore(args: argparse.Namespace, opener: Opener, target: dict[str, Any]) -> int:
    device = await opener(_transport(args))
    try:
        say(f"Connected: {_describe(device.info)}")
        result = await api.restore(
            device,
            target,
            backup_dir=args.backup_dir or _data_dir(args) / BACKUPS,
            timing=_timing(args),
            on_event=_show,
        )
    finally:
        await device.close()
    return _EXIT_FOR_STATUS[result.status]


def _diff(args: argparse.Namespace) -> int:
    sys.stdout.write(diff_text(state_from_file(args.before), state_from_file(args.after)))
    return EXIT_OK


async def _wifi(args: argparse.Namespace, opener: Opener, backend: Any) -> int:
    if args.forget and args.action != "disable":
        print("error: --forget only goes with disable", file=sys.stderr, flush=True)
        return EXIT_NOT_CONFIRMED
    transport = _transport(args)
    device = await opener(transport)
    try:
        if args.action == "status":
            say("Checking whether the phone answers on the network...")
            status = await api.wifi_status(
                device, backend=backend, discovery_timeout=transport.discovery_timeout
            )
        else:
            if args.action == "enable":
                say("Turning Wi-Fi access on and pairing this computer for Wi-Fi...")
            status = await api.set_wifi(
                device,
                args.action == "enable",
                backend=backend,
                forget=args.forget,
                discovery_timeout=transport.discovery_timeout,
            )
    finally:
        await device.close()
    info = status.device
    say(f"Device: {_describe(info)}")
    if info.get("udid"):
        say(f"UDID: {info['udid']}")
    say(f"Wi-Fi connections setting: {'on' if status.enabled else 'off'}")
    say(f"Wi-Fi pairing: {status.pair_record or status.pair_record_problem}")
    if status.reachable is True:
        where = f" at {status.address}" if status.address else ""
        say(f"On the network: answering{where}")
    elif status.reachable is False:
        say(
            "On the network: not answering right now. Keep the phone awake and unlocked, "
            "on the same network as this computer."
        )
    if status.enabled and args.action == "enable":
        say("Use --wifi from now on while the phone is on the same network, awake and unlocked.")
    return EXIT_OK


def _ui(args: argparse.Namespace) -> int:
    from .ui import Options, UIUnavailable, serve

    options = Options(
        transport=_transport(args),
        data_dir=_data_dir(args),
        backup_dir=args.backup_dir or _data_dir(args) / BACKUPS,
        timing=_timing(args),
        port=args.port,
        open_browser=not args.no_browser,
        demo=args.demo,
    )
    try:
        return serve(options, say=say)
    except UIUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return EXIT_ERROR


def _run(args: argparse.Namespace, opener: Opener, backend: Any = None) -> int:
    if args.command == "read":
        return asyncio.run(_read(args, opener))
    if args.command == "export":
        return _export(args)
    if args.command == "plan":
        return _plan(args)
    if args.command == "apply":
        # Validated before --yes is checked, so a bad file is reported either way.
        plan = api.load_plan(args.plan)
        if not args.yes:
            return _not_confirmed(plan, "plan")
        return asyncio.run(_apply(args, opener, plan))
    if args.command == "restore":
        target = api.load_backup(args.backup)
        if not args.yes:
            return _not_confirmed(target, "backup")
        return asyncio.run(_restore(args, opener, target))
    if args.command == "diff":
        return _diff(args)
    if args.command == "wifi":
        return asyncio.run(_wifi(args, opener, backend))
    if args.command == "ui":
        return _ui(args)
    raise AssertionError(f"unhandled command {args.command!r}")


def main(
    argv: list[str] | None = None,
    *,
    open_device: Opener | None = None,
    wifi_backend: Any = None,
) -> int:
    """Entry point. ``open_device`` replaces the real connection and ``wifi_backend`` the
    Wi-Fi pairing helpers (tests use fakes)."""
    args = build_parser().parse_args(argv)
    try:
        return _run(args, open_device or _default_opener, wifi_backend)
    except (
        api.StateError,
        api.LayoutError,
        api.WorkflowError,
        api.DeviceError,
        api.TransportError,
        OSError,
        TimeoutError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print(
            "\ninterrupted. If a write was running, check the phone with 'read' and use "
            "'restore' with the newest file in the backups directory.",
            file=sys.stderr,
            flush=True,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
