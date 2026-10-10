"""The data directory: pull snapshots, backups, and the link from a layout file to its pull.

::

    DATA_DIR/pulls/pull-TIMESTAMP.plist      what pull (and the editor) read from the phone
    DATA_DIR/backups/backup-TIMESTAMP.plist  the layout before every write

A layout file names its pull in a ``[pull]`` table (``snapshot = "pull-....plist"``), so
``check`` and ``push`` compare it with the phone state it was made from, and ``push`` can
tell whether the phone changed since. A file without that table uses the newest pull.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import PULLS
from .snapshots import device_details, timestamp
from .state import StateError, folder_pages, is_folder, load_plist, save_plist, split_state

LATEST = "latest"

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.plist$")
_STAMP = re.compile(r"(\d{8}-\d{6})")
_TABLE = re.compile(r"^\s*\[")
_PULL_TABLE = re.compile(r"^\s*\[\s*pull\s*\]\s*(#.*)?$")
_SNAPSHOT_LINE = re.compile(r'^(\s*snapshot\s*=\s*)"[^"\n]*"(.*)$')


# --------------------------------------------------------------------------- pulls


def save_pull(snapshot: Mapping[str, Any], data_dir: Path) -> Path:
    """Write ``DATA_DIR/pulls/pull-TIMESTAMP.plist`` and return its path."""
    return save_plist(Path(data_dir) / PULLS / f"pull-{timestamp()}.plist", dict(snapshot))


def _named(directory: Path, name: Any, what: str) -> Path:
    """A plain file name inside ``directory``; anything that could point elsewhere fails."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise StateError(f"{name!r} is not a {what} file name", code="bad_name")
    path = directory / name
    if not path.is_file() or path.resolve().parent != directory.resolve():
        raise StateError(f"there is no {what} named {name} in {directory}", code="not_found")
    return path


def _newest(directory: Path, prefix: str) -> Path | None:
    if not directory.is_dir():
        return None
    found = [p for p in directory.glob(f"{prefix}-*.plist") if _NAME.match(p.name)]
    return max(found, key=lambda p: (p.name, p.stat().st_mtime), default=None)


def newest_pull(data_dir: Path) -> Path:
    found = _newest(Path(data_dir) / PULLS, "pull")
    if found is None:
        raise StateError(
            f"nothing has been pulled yet (no snapshot in {Path(data_dir) / PULLS}); "
            "run 'ios-homescreen pull' first",
            code="no_pull",
        )
    return found


def pull_reference(document: Mapping[str, Any]) -> str | None:
    """The snapshot a layout document names in its ``[pull]`` table, if any."""
    table = document.get("pull")
    if isinstance(table, Mapping) and isinstance(table.get("snapshot"), str):
        return table["snapshot"]
    return None


def find_pull(document: Mapping[str, Any], data_dir: Path) -> tuple[Path, bool]:
    """``(snapshot path, named_by_the_file)``: the file's own pull, else the newest one."""
    name = pull_reference(document)
    if name is None:
        return newest_pull(data_dir), False
    try:
        return _named(Path(data_dir) / PULLS, name, "pull snapshot"), True
    except StateError as exc:
        raise StateError(
            f"{exc}. The layout file was pulled on another computer or with another "
            "--data-dir, or the snapshot was deleted; pull into a new file and carry "
            "your edits over",
            code="pull_missing",
        ) from exc


def point_layout_at(path: Path, snapshot: str) -> bool:
    """Make the ``[pull]`` table of the layout file at ``path`` name ``snapshot``.

    Only that one line changes; comments and formatting stay. Returns False (and leaves
    the file alone) when the file has no ``snapshot = "..."`` line in a ``[pull]`` table.
    """
    if not _NAME.match(snapshot):
        raise StateError(f"{snapshot!r} is not a pull snapshot file name")
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    inside = False
    for number, line in enumerate(lines):
        if _TABLE.match(line):
            inside = bool(_PULL_TABLE.match(line.rstrip("\r\n")))
            continue
        match = _SNAPSHOT_LINE.match(line.rstrip("\r\n")) if inside else None
        if match:
            ending = line[len(line.rstrip("\r\n")) :]
            lines[number] = f'{match.group(1)}"{snapshot}"{match.group(2)}{ending}'
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text("".join(lines), encoding="utf-8")
            tmp.replace(path)
            return True
    return False


# --------------------------------------------------------------------------- backups


def layout_counts(state: Any) -> dict[str, int]:
    """Dock items, pages, and items in all (folder contents counted one by one)."""
    dock, pages = split_state(state)
    items = 0
    for section in [dock, *pages]:
        for item in section:
            if is_folder(item):
                items += sum(len(page) for page in folder_pages(item))
            else:
                items += 1
    return {"dock": len(dock), "pages": len(pages), "items": items}


@dataclass(frozen=True)
class Backup:
    path: Path
    created: datetime
    """Local time the backup was made."""
    device: dict[str, str]
    """Name, model, iOS version and UDID; empty for backups made by older versions."""
    counts: dict[str, int] | None
    """:func:`layout_counts`, or ``None`` when the file cannot be read."""

    @property
    def name(self) -> str:
        return self.path.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created": self.created.isoformat(timespec="seconds"),
            "device": dict(self.device),
            "summary": dict(self.counts) if self.counts is not None else None,
        }


def _created(path: Path) -> datetime:
    match = _STAMP.search(path.name)
    if match:
        with contextlib.suppress(ValueError):
            return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)


def _details(path: Path) -> tuple[dict[str, str], dict[str, int] | None]:
    try:
        data = load_plist(path)
        device = data.get("device") if isinstance(data, dict) else None
        state = data["state"] if isinstance(data, dict) and "state" in data else data
        return device_details(device if isinstance(device, Mapping) else None), layout_counts(state)
    except Exception:
        return {}, None


def _backup_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [p for p in directory.glob("*.plist") if _NAME.match(p.name) and p.is_file()]
    return sorted(files, key=lambda p: (_created(p), p.name), reverse=True)


def list_backups(
    directory: Path,
    *,
    limit: int | None = None,
    cache: MutableMapping[tuple[str, int, int], Any] | None = None,
) -> list[Backup]:
    """Backups in ``directory``, newest first. ``cache`` skips re-reading unchanged files."""
    found = []
    for path in _backup_files(Path(directory))[:limit]:
        stat = path.stat()
        key = (path.name, stat.st_mtime_ns, stat.st_size)
        if cache is not None and key in cache:
            details = cache[key]
        else:
            details = _details(path)
            if cache is not None:
                cache[key] = details
        found.append(Backup(path, _created(path), *details))
    return found


def find_backup(directory: Path, ref: str, *, allow_paths: bool = True) -> Path:
    """``latest``, a backup's name (``.plist`` optional) in ``directory``, or a file path."""
    directory = Path(directory)
    if ref == LATEST:
        files = _backup_files(directory)
        if not files:
            raise StateError(f"there are no backups in {directory} yet", code="no_backup")
        return files[0]
    name = ref if ref.endswith(".plist") else f"{ref}.plist"
    if _NAME.match(name) and (directory / name).is_file():
        return _named(directory, name, "backup")
    if allow_paths:
        path = Path(ref).expanduser()
        if path.is_file():
            return path
    raise StateError(
        f"there is no backup named {ref} in {directory} (list them with 'ios-homescreen backups')",
        code="no_backup",
    )
