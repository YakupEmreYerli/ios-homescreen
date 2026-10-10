"""Command line interface: pull, check, push, editor, backups, restore, apps, wifi.

With ``--json`` a command prints exactly one JSON object on stdout (the schema is in
``docs/agent-guide.md``); its progress and messages go to stderr, and the exit codes stay
the same.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from . import __version__, api
from .events import Event
from .export import pull_source
from .paths import BACKUPS, DATA_DIR_ENV, DEFAULT_LAYOUT, data_dir
from .planner import Plan
from .report import app_places, change_lines, change_summary, library_apps, overview
from .snapshots import device_details, device_of
from .state import fingerprint, same_layout
from .storage import (
    Backup,
    find_backup,
    find_pull,
    layout_counts,
    list_backups,
    newest_pull,
    point_layout_at,
)
from .transport import DEFAULT_CONNECT_TIMEOUT, DEFAULT_DISCOVERY_TIMEOUT, Transport
from .workflow import APPLIED, ROLLBACK_FAILED, ROLLED_BACK, Timing, WorkflowError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_CONFIRMED = 2
EXIT_ROLLED_BACK = 3
EXIT_ROLLBACK_FAILED = 4
EXIT_INTERRUPTED = 130

BACKUPS_SHOWN = 20

Opener = Callable[[Transport], Awaitable[Any]]


class _Output:
    """What one run prints: plain text, or (``--json``) one object on stdout at the end."""

    def __init__(self) -> None:
        self.json = False
        self.data: dict[str, Any] = {}


_out = _Output()


def say(message: str = "") -> None:
    print(message, file=sys.stderr if _out.json else sys.stdout, flush=True)


def report(**fields: Any) -> None:
    """Fields of the ``--json`` result."""
    _out.data.update(fields)


def failed(code: str, message: str, **extra: Any) -> None:
    """The ``--json`` error object for a run that ends with a non-zero exit code."""
    _out.data["error"] = {"code": code, "message": message, **extra}


class Refused(Exception):
    """The command refuses before doing anything; ``code`` goes into the JSON error."""

    def __init__(self, message: str, *, code: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


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
A session:
  ios-homescreen pull       read the phone into layout.toml
  $EDITOR layout.toml       move things around
  ios-homescreen check      see what would change (offline)
  ios-homescreen push       write it: asks first, backs up, verifies, rolls back

Exit codes: 0 done; 1 error, nothing was written; 2 usage error, or the write was
not confirmed; 3 the new layout did not verify and the backup was written back;
4 that did not verify either (the backup file is kept).

Data directory: {data_dir}
(change it with --data-dir or ${env})
"""


class _Formatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30)


def _storage_options(*, backups: bool) -> argparse.ArgumentParser:
    storage = argparse.ArgumentParser(add_help=False)
    group = storage.add_argument_group("files")
    group.add_argument(
        "--data-dir",
        type=Path,
        metavar="DIR",
        help=f"where pull snapshots and backups are kept (env ${DATA_DIR_ENV})",
    )
    if backups:
        group.add_argument(
            "--backup-dir",
            type=Path,
            metavar="DIR",
            help="where backups are kept (default: DATA_DIR/backups)",
        )
    return storage


def _connection_options() -> argparse.ArgumentParser:
    connection = argparse.ArgumentParser(add_help=False)
    group = connection.add_argument_group("connection (USB unless --wifi)")
    group.add_argument(
        "--wifi",
        action="store_true",
        help="connect over the local network (iOS 17 or later; run 'wifi setup' once first)",
    )
    group.add_argument(
        "--udid", metavar="UDID", help="choose the iPhone when more than one is available"
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
    return connection


def _write_options() -> argparse.ArgumentParser:
    writing = argparse.ArgumentParser(add_help=False)
    defaults = Timing()
    group = writing.add_argument_group("checking the write")
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


def _yes(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=f"{what} without asking (needed when there is no terminal to ask in)",
    )


def _layout_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "layout",
        nargs="?",
        type=Path,
        default=Path(DEFAULT_LAYOUT),
        metavar="LAYOUT",
        help=f"{help_text} (default: {DEFAULT_LAYOUT})",
    )


def _json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="print one JSON object on stdout (for scripts and AI agents); messages go to stderr",
    )


def _allow_removal(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-removal",
        action="store_true",
        help="let the layout remove widgets it leaves out (web clips and web apps can only "
        "be deleted on the phone)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ios-homescreen",
        description=(
            "Pull an iPhone home screen into a text file, edit it, and push it back\n"
            "safely, over USB or Wi-Fi. Or edit it in the browser."
        ),
        epilog=EPILOG.format(data_dir=data_dir(), env=DATA_DIR_ENV),
        formatter_class=_Formatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    commands.required = True

    files = _storage_options(backups=False)
    files_and_backups = _storage_options(backups=True)
    connection = _connection_options()
    writing = _write_options()

    pull = commands.add_parser(
        "pull",
        parents=[connection, files],
        usage="%(prog)s [LAYOUT] [--overwrite] [options]",
        formatter_class=_Formatter,
        help="read the phone into an editable layout file (read-only)",
        description=(
            "Read the iPhone's home screen and write it as a layout file you can edit.\n"
            "Nothing is written to the phone. The phone's state is also kept as a snapshot\n"
            "in the data directory: check and push compare the file with it."
        ),
    )
    _layout_argument(pull, "layout file to write")
    _json(pull)
    pull.add_argument(
        "--overwrite",
        action="store_true",
        help="replace LAYOUT even if it has edits that were not pushed",
    )

    check = commands.add_parser(
        "check",
        parents=[files],
        usage="%(prog)s [LAYOUT] [--allow-removal] [--data-dir DIR]",
        formatter_class=_Formatter,
        help="show what pushing a layout file would change (offline)",
        description=(
            "Check a layout file and list what push would change, compared with the\n"
            "phone as it was when the file was pulled. The phone is not contacted."
        ),
    )
    _layout_argument(check, "layout file to check")
    _allow_removal(check)
    _json(check)

    push = commands.add_parser(
        "push",
        parents=[connection, files_and_backups, writing],
        usage="%(prog)s [LAYOUT] [-y] [--force] [--allow-removal] [options]",
        formatter_class=_Formatter,
        help="write a layout file to the phone (asks first, backed up, verified)",
        description=(
            "Write a layout file to the iPhone. push checks the file, connects, and stops\n"
            "if the phone was changed since the pull. It shows the changes and asks. Then\n"
            "it saves a backup, writes, reads the phone back to verify, and writes the\n"
            "backup back if the phone does not show the new layout."
        ),
    )
    _layout_argument(push, "layout file to write to the phone")
    _yes(push, "write")
    push.add_argument(
        "--force",
        action="store_true",
        help="write even if the phone's layout changed since the pull",
    )
    _allow_removal(push)
    _json(push)

    editor = commands.add_parser(
        "editor",
        parents=[connection, files_and_backups, writing],
        usage="%(prog)s [--demo] [--port PORT] [--no-browser] [options]",
        formatter_class=_Formatter,
        help="edit the home screen in your browser",
        description=(
            "Open an editor in the browser: drag apps, folders and widgets, see what will\n"
            "change, and apply it with the same backup, check and rollback as push. It\n"
            "listens on 127.0.0.1; the address it prints holds a key that changes on\n"
            "every start."
        ),
    )
    group = editor.add_argument_group("editor")
    group.add_argument(
        "--demo",
        action="store_true",
        help="try the editor on a pretend iPhone; nothing connects to a phone",
    )
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
        "--showcase",
        type=Path,
        metavar="LAYOUT",
        help="for screenshots: show LAYOUT on the phone's wallpaper and icons, never write, "
        "and list only the apps in its [showcase] library table",
    )

    backups = commands.add_parser(
        "backups",
        parents=[files_and_backups],
        usage="%(prog)s [--all] [--data-dir DIR] [--backup-dir DIR]",
        formatter_class=_Formatter,
        help="list the backups saved before each write",
        description=(
            "List the backups that push, restore and the editor save before every write,\n"
            "newest first: when, which iPhone, and what the layout held. Offline."
        ),
    )
    backups.add_argument(
        "--all", action="store_true", help=f"list every backup, not only the {BACKUPS_SHOWN} newest"
    )
    _json(backups)

    restore = commands.add_parser(
        "restore",
        parents=[connection, files_and_backups, writing],
        usage="%(prog)s BACKUP [-y] [--force] [options]",
        formatter_class=_Formatter,
        help="write a backup back to the phone ('latest' for the newest)",
        description=(
            "Write a backup back to the iPhone, with the same steps as push: it shows the\n"
            "changes and asks, backs up the current layout, writes, verifies and rolls\n"
            "back. Apps installed since the backup stay in the App Library."
        ),
    )
    restore.add_argument(
        "backup",
        metavar="BACKUP",
        help="'latest', a name from 'ios-homescreen backups', or a backup file",
    )
    _yes(restore, "restore")
    restore.add_argument(
        "--force",
        action="store_true",
        help="restore a backup that was made on another iPhone",
    )
    _json(restore)

    apps = commands.add_parser(
        "apps",
        parents=[files],
        formatter_class=_Formatter,
        usage="%(prog)s [QUERY] [--json] [--data-dir DIR]",
        help="list the installed apps and where each one is (offline)",
        description=(
            "List the apps on the phone as of the newest pull, with their bundle ids and\n"
            "where each one is: the dock, a page, a folder, or only the App Library. Use the\n"
            "names or ids in a layout file. Offline: the phone is not contacted."
        ),
    )
    apps.add_argument(
        "query", nargs="?", metavar="QUERY", help="only apps whose name or bundle id contains this"
    )
    _json(apps)

    wifi = commands.add_parser(
        "wifi",
        parents=[connection],
        usage="%(prog)s {setup,status,off} [--forget] [options]",
        formatter_class=_Formatter,
        help="set up, check or turn off Wi-Fi access (setup, status, off)",
        description=(
            "setup   over USB, once: turn on the phone's Wi-Fi connections setting and\n"
            "        pair this computer for Wi-Fi (no prompt, no root, no Developer Mode)\n"
            "status  the setting, the pairing, and whether the phone answers on Wi-Fi\n"
            "off     turn the setting off; with --forget also delete the Wi-Fi pairing\n"
            "\n"
            "After setup, add --wifi to the other commands while the phone is on the same\n"
            "network, awake and unlocked (iOS 17 or later)."
        ),
    )
    wifi.add_argument(
        "action", choices=["setup", "status", "off"], metavar="ACTION", help="setup, status or off"
    )
    wifi.add_argument(
        "--forget",
        action="store_true",
        help="with off: also delete this computer's Wi-Fi pairing with the phone",
    )
    _json(wifi)
    return parser


# --------------------------------------------------------------------------- helpers


def _data_dir(args: argparse.Namespace) -> Path:
    return args.data_dir.expanduser() if getattr(args, "data_dir", None) else data_dir()


def _backup_dir(args: argparse.Namespace) -> Path:
    given = getattr(args, "backup_dir", None)
    return given.expanduser() if given else _data_dir(args) / BACKUPS


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
    name = info.get("name") or "the iPhone"
    return f"{name} ({details})" if details else str(name)


def _show(event: Event) -> None:
    prefix = f"[{event.step}/{event.total}] " if event.step and event.total else ""
    say(prefix + event.message)


def _default_opener(transport: Transport) -> Awaitable[Any]:
    return api.connect(transport, on_event=_show)


def _command(name: str, layout: Path) -> str:
    target = "" if layout == Path(DEFAULT_LAYOUT) else f" {layout}"
    return f"ios-homescreen {name}{target}"


def _interactive() -> bool:
    return bool(sys.stdin) and sys.stdin.isatty()


def _confirm(question: str) -> bool:
    print(f"{question} [y/N] ", end="", file=sys.stderr, flush=True)
    answer = sys.stdin.readline()
    if not answer:
        print(file=sys.stderr, flush=True)
    return answer.strip().lower() in {"y", "yes"}


def _no_terminal(what: str) -> int:
    if _out.json:
        message = (
            f"nothing was written and the phone was not contacted: {what} --json needs --yes, "
            "which only the user may give after seeing the changes"
        )
    else:
        message = (
            "nothing was written and the phone was not contacted: there is no terminal to "
            f"ask in. Run {what} in a terminal, or add --yes."
        )
    say(message[0].upper() + message[1:])
    failed("confirmation_needed", message)
    return EXIT_NOT_CONFIRMED


def _show_changes(changes: list[dict[str, Any]]) -> None:
    for line in change_lines(changes):
        say(line)
    say()
    say(change_summary(changes))


async def _timed(awaitable: Awaitable[Any], seconds: float, what: str) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except TimeoutError as exc:
        raise WorkflowError(f"{what} did not finish within {seconds:g} s", code="timeout") from exc


_EXIT_FOR_STATUS = {
    APPLIED: EXIT_OK,
    ROLLED_BACK: EXIT_ROLLED_BACK,
    ROLLBACK_FAILED: EXIT_ROLLBACK_FAILED,
}


# --------------------------------------------------------------------------- pull


def _unpushed_edits(layout: Path, data: Path) -> str | None:
    """Why ``layout`` must not be overwritten, or ``None`` when it holds nothing new."""
    try:
        document = api.load_layout(layout)
        snapshot, _ = find_pull(document, data)
        plan = api.plan_layout(document, api.load_pull(snapshot), allow_removal=True)
    except (api.LayoutError, api.StateError, OSError, UnicodeDecodeError):
        return "it cannot be compared with its pull, so it may hold edits"
    if plan.unchanged:
        return None
    count = len(plan.change_list)
    if count == 1:
        return "it has a change that was not pushed"
    return f"it has {count} changes that were not pushed"


async def _pull(args: argparse.Namespace, opener: Opener) -> int:
    layout: Path = args.layout
    data = _data_dir(args)
    if layout.exists() and not args.overwrite:
        reason = _unpushed_edits(layout, data)
        if reason:
            raise Refused(
                f"{layout} already exists and {reason}. Pull into another file "
                f"(ios-homescreen pull new.toml), or add --overwrite to replace it.",
                code="unpushed_edits",
            )
    device = await opener(_transport(args))
    try:
        say(f"Connected: {_describe(device.info)}")
        say("Reading the home screen (read-only)...")
        snapshot = await api.read_device(device)
    finally:
        await device.close()
    saved = api.save_pull(snapshot, data)
    text = api.export_layout(snapshot, pull=saved.name, note=api.pull_note(snapshot))
    layout.parent.mkdir(parents=True, exist_ok=True)
    tmp = layout.with_name(f".{layout.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(layout)
    say(f"Wrote {layout}: {overview(snapshot['state'], snapshot['apps'])}.")
    say(f"Snapshot: {saved}")
    counts = layout_counts(snapshot["state"])
    report(
        layout=str(layout),
        pull=saved.name,
        device=snapshot.get("device", {}),
        dock=counts["dock"],
        pages=counts["pages"],
        library=len(library_apps(snapshot["state"], snapshot["apps"])),
    )
    check, push = _command("check", layout), _command("push", layout)
    width = max(len(check), len(push))
    say(f"Next: edit {layout}, then run")
    say(f"  {check.ljust(width)}  to see what would change")
    say(f"  {push.ljust(width)}  to write it to the phone")
    return EXIT_OK


# --------------------------------------------------------------------------- check and push


def _plan(args: argparse.Namespace) -> tuple[Plan, dict[str, Any], Path, bool]:
    """Plan the layout file against its pull: ``(plan, snapshot, path, named_by_file)``."""
    document = api.load_layout(args.layout)
    path, named = find_pull(document, _data_dir(args))
    report(layout=str(args.layout), pull=path.name, pull_named_by_file=named)
    if not named:
        warn(f"{args.layout} names no pull; comparing it with the newest one, {path.name}.")
    read = api.load_pull(path)
    return api.plan_layout(document, read, allow_removal=args.allow_removal), read, path, named


def _check(args: argparse.Namespace) -> int:
    plan, read, _, _ = _plan(args)
    after = {"state": plan.payload, "apps": read.get("apps", {})}
    library = len(library_apps(after["state"], after["apps"]))
    source = f"the pull from {pull_source(read)}"
    report(
        valid=True,
        unchanged=plan.unchanged,
        changes=list(plan.change_list),
        summary=change_summary(plan.change_list),
        library=library,
    )
    if plan.unchanged:
        say(f"{args.layout} is valid and matches {source}: push would change nothing.")
        return EXIT_OK
    say(f"{args.layout} is valid.")
    say(f"Changes compared with {source}:")
    say()
    _show_changes(list(plan.change_list))
    say(f"{library} apps will be only in the App Library.")
    say(f"Write it with: {_command('push', args.layout)}")
    return EXIT_OK


def _drift_message(args: argparse.Namespace, path: Path) -> str:
    return (
        f"the iPhone's layout changed since {args.layout} was pulled ({path.name}), so nothing "
        "was written. Pull into a new file (ios-homescreen pull new.toml), carry your edits "
        f"over and push that, or add --force to write {args.layout} over the phone's changes."
    )


async def _push(
    args: argparse.Namespace,
    opener: Opener,
    plan: Plan,
    read: dict[str, Any],
    path: Path,
    named: bool,
) -> int:
    timing = _timing(args)
    device = await opener(_transport(args))
    try:
        info = dict(device.info)
        say(f"Connected: {_describe(info)}")
        current = await _timed(device.read_state(), timing.read_timeout, "Reading the layout")
        if same_layout(current, plan.payload):
            say("The iPhone already shows this layout. Nothing was written.")
            report(status="unchanged", changes=[])
            return EXIT_OK
        if fingerprint(current) != fingerprint(read["state"]):
            if not args.force:
                raise WorkflowError(_drift_message(args, path), code="layout_changed")
            say("The iPhone changed since the pull; writing anyway (--force).")
        say()
        say(f"Changes to {info.get('name') or 'the iPhone'}:")
        changes = api.changes_between({"state": current, "apps": read["apps"]}, plan.payload)
        report(changes=changes, summary=change_summary(changes))
        _show_changes(changes)
        say()
        if not args.yes and not _confirm("Write this layout? A backup is saved first."):
            say("Nothing was written.")
            failed("not_confirmed", "the write was not confirmed; nothing was written")
            return EXIT_NOT_CONFIRMED
        result = await api.push(
            device,
            plan,
            backup_dir=_backup_dir(args),
            force=args.force,
            timing=timing,
            on_event=_show,
        )
        _report_result(result)
        if result.ok:
            await _record_push(args, device, named)
    finally:
        await device.close()
    return _EXIT_FOR_STATUS[result.status]


def _report_result(result: Any) -> None:
    report(
        status=result.status,
        backup=str(result.backup),
        write_unconfirmed=result.write_unconfirmed,
    )
    if result.status == ROLLED_BACK:
        failed(
            "rolled_back",
            "the phone did not show the new layout in time; the backup was written back and "
            "verified",
        )
    elif result.status == ROLLBACK_FAILED:
        failed(
            "rollback_failed",
            f"the backup could not be verified after writing it back; it is kept at "
            f"{result.backup}",
        )


async def _record_push(args: argparse.Namespace, device: Any, named: bool) -> None:
    """Keep the phone's new state as the layout file's pull, so it is in step again."""
    try:
        snapshot = await api.read_device(device)
    except Exception as exc:
        say(f"Reading the phone afterwards failed ({exc}). Pull again before the next push.")
        report(new_pull=None, layout_updated=False)
        return
    saved = api.save_pull(snapshot, _data_dir(args))
    updated = named and point_layout_at(args.layout, saved.name)
    report(new_pull=saved.name, layout_updated=updated)
    if updated:
        say(f"{args.layout} is up to date with the phone again ({saved.name}).")
    else:
        say(f"Saved the phone's new layout as the newest pull: {saved.name}.")


def _run_push(args: argparse.Namespace, opener: Opener) -> int:
    # Everything that can be checked offline is checked before connecting.
    plan, read, path, named = _plan(args)
    if plan.unchanged and not args.force:
        say(f"{args.layout} matches its pull ({path.name}): nothing to push.")
        report(status="unchanged", changes=[])
        return EXIT_OK
    if not args.yes and (_out.json or not _interactive()):
        report(changes=list(plan.change_list), summary=change_summary(plan.change_list))
        say(f"{args.layout} is valid. Changes compared with its pull:")
        say()
        _show_changes(list(plan.change_list))
        say()
        return _no_terminal("push")
    return asyncio.run(_push(args, opener, plan, read, path, named))


# --------------------------------------------------------------------------- backups and restore


def _backup_line(backup: Backup) -> tuple[str, str, str, str]:
    counts = backup.counts
    summary = (
        f"dock {counts['dock']}, {counts['pages']} pages, {counts['items']} items"
        if counts
        else "unreadable"
    )
    device = backup.device.get("name") or "unknown iPhone"
    return f"{backup.created:%Y-%m-%d %H:%M:%S}", device, summary, backup.path.stem


def _backups(args: argparse.Namespace) -> int:
    directory = _backup_dir(args)
    found = list_backups(directory)
    report(directory=str(directory), backups=[backup.to_dict() for backup in found])
    if not found:
        say(f"No backups in {directory} yet. push, restore and the editor save one before writing.")
        return EXIT_OK
    shown = found if args.all else found[:BACKUPS_SHOWN]
    rows = [_backup_line(backup) for backup in shown]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    say(f"Backups in {directory}, newest first:")
    say()
    for number, row in enumerate(rows):
        mark = "latest" if number == 0 else ""
        cells = [cell.ljust(width) for cell, width in zip(row[:3], widths, strict=True)]
        say(f"  {mark:6}  {'  '.join(cells)}  {row[3]}")
    if len(found) > len(shown):
        say(f"  ...and {len(found) - len(shown)} older ones (--all lists them).")
    say()
    say("Restore one with: ios-homescreen restore latest   (or a name from the last column)")
    return EXIT_OK


async def _restore(
    args: argparse.Namespace, opener: Opener, path: Path, target: dict[str, Any]
) -> int:
    timing = _timing(args)
    recorded = device_of(path)
    device = await opener(_transport(args))
    try:
        info = dict(device.info)
        say(f"Connected: {_describe(info)}")
        wanted, actual = recorded.get("udid"), info.get("udid")
        if wanted and actual and wanted != actual and not args.force:
            raise Refused(
                f"{path.name} was made on another iPhone ({_describe(recorded)}), so nothing "
                "was written. Add --force to restore it to this one anyway.",
                code="other_device",
            )
        current = await _timed(device.read_state(), timing.read_timeout, "Reading the layout")
        if same_layout(current, target):
            say("The iPhone already shows this layout. Nothing was written.")
            report(status="unchanged", changes=[])
            return EXIT_OK
        apps = await _timed(device.installed_apps(), timing.read_timeout, "Reading the apps")
        say()
        say(f"Changes to {info.get('name') or 'the iPhone'}:")
        changes = api.changes_between({"state": current, "apps": apps}, target)
        report(changes=changes, summary=change_summary(changes))
        _show_changes(changes)
        say()
        if not args.yes and not _confirm("Restore this backup? The current layout is saved first."):
            say("Nothing was written.")
            failed("not_confirmed", "the restore was not confirmed; nothing was written")
            return EXIT_NOT_CONFIRMED
        result = await api.restore(
            device, target, backup_dir=_backup_dir(args), timing=timing, on_event=_show
        )
        _report_result(result)
    finally:
        await device.close()
    return _EXIT_FOR_STATUS[result.status]


def _run_restore(args: argparse.Namespace, opener: Opener) -> int:
    # The file is found and validated before anything connects.
    path = find_backup(_backup_dir(args), args.backup)
    target = api.load_backup(path)
    recorded = device_of(path)
    made_on = f", {recorded['name']}" if recorded.get("name") else ""
    say(f"Backup: {path.name}{made_on}")
    report(restoring=path.name, made_on=recorded)
    if not args.yes and (_out.json or not _interactive()):
        return _no_terminal("restore")
    return asyncio.run(_restore(args, opener, path, target))


# --------------------------------------------------------------------------- apps


def _place(where: Mapping[str, Any]) -> str:
    if where["section"] == "library":
        return "App Library"
    text = "dock" if where["section"] == "dock" else f"page {where['page']}"
    text += f", position {where['index']}"
    if where.get("folder") is not None:
        text += f', folder "{where["folder"]}"'
        if where.get("folder_page", 1) > 1:
            text += f" page {where['folder_page']}"
        text += f" (position {where['folder_index']})"
    return text


def _apps(args: argparse.Namespace) -> int:
    path = newest_pull(_data_dir(args))
    read = api.load_pull(path)
    found = app_places(read)
    query = (args.query or "").casefold()
    if query:
        found = [a for a in found if query in a["name"].casefold() or query in a["id"].casefold()]
    report(pull=path.name, pulled_from=pull_source(read), apps=found)
    say(f"Apps on {pull_source(read)} ({path.name}):")
    say()
    if not found:
        say(f"  No app matches {args.query!r}." if query else "  No apps.")
        return EXIT_OK
    name_width = min(28, max(len(a["name"]) for a in found))
    id_width = min(44, max(len(a["id"]) for a in found))
    for app in found:
        say(
            f"  {app['name'][:name_width].ljust(name_width)}  {app['id'].ljust(id_width)}  "
            f"{_place(app['where'])}"
        )
    shown = sum(1 for a in found if a["where"]["section"] != "library")
    say()
    say(
        f"{len(found)} apps: {shown} on the home screen, {len(found) - shown} only in the "
        "App Library."
    )
    return EXIT_OK


# --------------------------------------------------------------------------- wifi and editor


async def _wifi(args: argparse.Namespace, opener: Opener, backend: Any) -> int:
    if args.forget and args.action != "off":
        raise Refused("--forget only goes with off", code="usage", exit_code=EXIT_NOT_CONFIRMED)
    transport = _transport(args)
    device = await opener(transport)
    try:
        if args.action == "status":
            say("Checking whether the phone answers on the network...")
            status = await api.wifi_status(
                device, backend=backend, discovery_timeout=transport.discovery_timeout
            )
        else:
            if args.action == "setup":
                say("Turning Wi-Fi access on and pairing this computer for Wi-Fi...")
            status = await api.set_wifi(
                device,
                args.action == "setup",
                backend=backend,
                forget=args.forget,
                discovery_timeout=transport.discovery_timeout,
            )
    finally:
        await device.close()
    info = status.device
    report(action=args.action, **{**status.to_dict(), "device": device_details(info)})
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
    if status.enabled and args.action == "setup":
        say(
            "Add --wifi to other commands while the phone is on the same network, awake "
            "and unlocked."
        )
    return EXIT_OK


def _editor(args: argparse.Namespace) -> int:
    from .ui import Options, UIUnavailable, serve

    if args.showcase is not None:
        from .ui.showcase import load

        load(args.showcase)  # a missing or broken file stops here, before anything starts

    options = Options(
        transport=_transport(args),
        data_dir=_data_dir(args),
        backup_dir=_backup_dir(args),
        timing=_timing(args),
        port=args.port,
        open_browser=not args.no_browser,
        demo=args.demo,
        showcase=args.showcase,
    )
    try:
        return serve(options, say=say)
    except UIUnavailable as exc:
        warn(f"error: {exc}")
        return EXIT_ERROR


def _run(args: argparse.Namespace, opener: Opener, backend: Any = None) -> int:
    if args.command == "pull":
        return asyncio.run(_pull(args, opener))
    if args.command == "check":
        return _check(args)
    if args.command == "push":
        return _run_push(args, opener)
    if args.command == "editor":
        return _editor(args)
    if args.command == "backups":
        return _backups(args)
    if args.command == "restore":
        return _run_restore(args, opener)
    if args.command == "apps":
        return _apps(args)
    if args.command == "wifi":
        return asyncio.run(_wifi(args, opener, backend))
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
    _out.json = bool(getattr(args, "json", False))
    _out.data = {}
    try:
        code = _run(args, open_device or _default_opener, wifi_backend)
    except Refused as exc:
        code = exc.exit_code
        _error(exc, exc.code)
    except api.LayoutError as exc:
        code = EXIT_ERROR
        _error(exc, "layout_invalid", issues=exc.to_dict()["issues"])
    except (
        api.StateError,
        api.WorkflowError,
        api.DeviceError,
        api.TransportError,
        OSError,
        TimeoutError,
    ) as exc:
        code = EXIT_ERROR
        _error(exc, _error_code(exc))
    except KeyboardInterrupt:
        code = EXIT_INTERRUPTED
        message = (
            "interrupted. If a write was running, look at the phone; "
            "'ios-homescreen restore latest' writes back the backup made before it."
        )
        warn("\n" + message)
        failed("interrupted", message)
    if _out.json:
        result = {"ok": code == EXIT_OK, "command": args.command, "exit_code": code}
        print(json.dumps({**result, **_out.data}, ensure_ascii=False, default=str), flush=True)
    return code


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, api.StateError):
        return "invalid_file"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "os_error"


def _error(exc: BaseException, code: str, **extra: Any) -> None:
    if not _out.json:
        warn(f"error: {exc}")
    failed(code, str(exc), **extra)


if __name__ == "__main__":
    raise SystemExit(main())
