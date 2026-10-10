"""The data directory: pull snapshots, the link from a layout file, and backups."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import samples
from ios_homescreen.snapshots import make_backup
from ios_homescreen.state import StateError, save_plist
from ios_homescreen.storage import (
    find_backup,
    find_pull,
    list_backups,
    newest_pull,
    point_layout_at,
    save_pull,
)

LAYOUT = """\
# A note that mentions snapshot = "not-this.plist"
[pull]
snapshot = "pull-20261009-000000-000000.plist"  # keep me

[dock]
items = []
"""


def test_point_layout_at_changes_only_the_snapshot_line(tmp_path):
    path = tmp_path / "layout.toml"
    path.write_text(LAYOUT)

    assert point_layout_at(path, "pull-20261010-000000-000000.plist")

    assert path.read_text() == LAYOUT.replace("20261009", "20261010")


def test_point_layout_at_leaves_a_file_without_a_pull_table_alone(tmp_path):
    path = tmp_path / "layout.toml"
    text = '[dock]\nitems = []\n[other]\nsnapshot = "x.plist"\n'
    path.write_text(text)

    assert not point_layout_at(path, "pull-20261010-000000-000000.plist")
    assert path.read_text() == text


def test_point_layout_at_refuses_odd_names(tmp_path):
    path = tmp_path / "layout.toml"
    path.write_text(LAYOUT)

    with pytest.raises(StateError):
        point_layout_at(path, '../x.plist"\nmalicious = "1')
    assert path.read_text() == LAYOUT


def test_pulls_are_found_by_name_or_as_the_newest(tmp_path):
    with pytest.raises(StateError, match="nothing has been pulled yet"):
        newest_pull(tmp_path)
    first = save_pull(samples.read_snapshot(), tmp_path)
    second = save_pull(samples.read_snapshot(), tmp_path)

    assert newest_pull(tmp_path) == second
    assert find_pull({"pull": {"snapshot": first.name}}, tmp_path) == (first, True)
    assert find_pull({"dock": {}}, tmp_path) == (second, False)
    with pytest.raises(StateError, match="no pull snapshot named"):
        find_pull({"pull": {"snapshot": "pull-gone.plist"}}, tmp_path)


def test_a_pull_name_cannot_escape_the_pulls_directory(tmp_path):
    save_pull(samples.read_snapshot(), tmp_path)
    outside = save_plist(tmp_path / "secret.plist", samples.read_snapshot())
    (tmp_path / "pulls" / "link.plist").symlink_to(outside)

    for name in ("../secret.plist", str(outside), "link.plist"):
        with pytest.raises(StateError):
            find_pull({"pull": {"snapshot": name}}, tmp_path)


def _backup(directory: Path, stamp: str, **device) -> Path:
    data = make_backup(samples.home_screen(), device=device or None)
    return save_plist(directory / f"backup-{stamp}.plist", data)


def test_backups_are_listed_newest_first_with_their_iphone(tmp_path):
    old = _backup(tmp_path, "20261001-080000-000000", name="Old iPhone")
    new = _backup(tmp_path, "20261010-080000-000000", name="New iPhone", udid="U")
    legacy = save_plist(tmp_path / "backup-20260901-080000-000000.plist", [[], []])
    (tmp_path / "notes.txt").write_text("not a backup")

    found = list_backups(tmp_path)

    assert [b.path for b in found] == [new, old, legacy]
    assert found[0].device == {"name": "New iPhone", "udid": "U"}
    assert found[0].counts == {"dock": 4, "pages": 2, "items": 33}
    assert found[2].device == {}
    assert found[2].counts == {"dock": 0, "pages": 1, "items": 0}
    assert found[0].to_dict()["created"] == "2026-10-10T08:00:00"


def test_listing_reuses_what_it_already_read(tmp_path, monkeypatch):
    _backup(tmp_path, "20261010-080000-000000")
    cache: dict = {}
    list_backups(tmp_path, cache=cache)
    monkeypatch.setattr("ios_homescreen.storage.load_plist", lambda path: pytest.fail("re-read"))

    assert list_backups(tmp_path, cache=cache)[0].counts is not None


def test_an_unreadable_backup_is_still_listed(tmp_path):
    (tmp_path / "backup-20261010-080000-000000.plist").write_bytes(b"garbage")

    (found,) = list_backups(tmp_path)

    assert found.counts is None


def test_find_backup_takes_latest_a_name_or_a_path(tmp_path, monkeypatch):
    older = _backup(tmp_path, "20261001-080000-000000")
    newer = _backup(tmp_path, "20261010-080000-000000")
    elsewhere = _backup(tmp_path / "x", "20260101-000000-000000")
    monkeypatch.chdir(tmp_path)

    assert find_backup(tmp_path, "latest") == newer
    assert find_backup(tmp_path, older.stem) == older
    assert find_backup(tmp_path, older.name) == older
    assert find_backup(tmp_path, str(elsewhere)) == elsewhere
    assert find_backup(tmp_path, os.path.relpath(elsewhere)) == Path(os.path.relpath(elsewhere))
    with pytest.raises(StateError, match="ios-homescreen backups"):
        find_backup(tmp_path, "backup-nope")


@pytest.mark.parametrize("name", ["../x.plist", "/etc/passwd", "x/../../y.plist", ""])
def test_the_editor_can_only_name_backups_in_the_backup_directory(tmp_path, name):
    _backup(tmp_path / "backups", "20261010-080000-000000")
    save_plist(tmp_path / "x.plist", [[], []])

    with pytest.raises(StateError):
        find_backup(tmp_path / "backups", name, allow_paths=False)


def test_without_backups_latest_explains(tmp_path):
    with pytest.raises(StateError, match="there are no backups"):
        find_backup(tmp_path, "latest")
