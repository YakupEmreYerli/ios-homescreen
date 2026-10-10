from __future__ import annotations

import asyncio
import io
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import samples
from fakes import FakeSpringBoard, FakeWifiBackend, must_not_connect, opener_for
from ios_homescreen import __version__
from ios_homescreen.cli import main
from ios_homescreen.export import export_layout
from ios_homescreen.snapshots import make_backup
from ios_homescreen.state import load_plist, same_layout, save_plist
from ios_homescreen.transport import RemoteRecord, Transport

UDID = "00008120-000A1B2C3D4E5F60"
FAST = ["--verify-attempts", "2", "--verify-interval", "0", "--write-timeout", "1"]
COMMANDS = ["pull", "check", "push", "editor", "backups", "restore", "wifi"]


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """An isolated XDG data dir and an empty working directory. Without a terminal."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("IOS_HOMESCREEN_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return tmp_path / "xdg" / "ios-homescreen"


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def terminal(monkeypatch):
    """Answer the next questions as a person at a terminal would."""

    def answer(text: str) -> None:
        monkeypatch.setattr(sys, "stdin", Terminal(text))

    return answer


def phone(state=None, **kwargs) -> FakeSpringBoard:
    return FakeSpringBoard(state or samples.home_screen(), samples.installed_apps(), **kwargs)


def pull(home, device=None, *args) -> FakeSpringBoard:
    device = device or phone()
    assert main(["pull", *args], open_device=opener_for(device)) == 0
    return device


def newest_pull(home) -> str:
    return max(p.name for p in (home / "pulls").glob("pull-*.plist"))


def moved_camera() -> list:
    """The sample home screen with Camera moved from the dock to the start of page 2
    and Tips added from the App Library after it."""
    state = samples.home_screen()
    camera = state[0].pop()
    state[2][0:0] = [camera, "com.apple.tips"]
    return state


def write_layout(path: Path, state, pull_name: str | None) -> None:
    read = {"state": state, "apps": samples.installed_apps()}
    path.write_text(export_layout(read, pull=pull_name), encoding="utf-8")


# ------------------------------------------------------------------ the parser


@pytest.mark.parametrize("argv", [["--help"], *([c, "--help"] for c in COMMANDS)])
def test_every_help_page_works(argv, capsys):
    with pytest.raises(SystemExit) as exit_:
        main(argv)

    text = capsys.readouterr().out
    assert exit_.value.code == 0
    assert text.startswith("usage: ios-homescreen")


@pytest.mark.parametrize("command", ["pull", "push", "restore", "wifi", "editor"])
def test_device_commands_offer_usb_and_wifi_options(command, capsys):
    with pytest.raises(SystemExit):
        main([command, "--help"])

    text = capsys.readouterr().out
    for flag in ("--wifi", "--udid", "--discovery-timeout", "--connect-timeout"):
        assert flag in text


@pytest.mark.parametrize("old", ["read", "export", "plan", "apply", "diff", "ui"])
def test_the_old_command_names_are_gone(old, capsys):
    with pytest.raises(SystemExit) as exit_:
        main([old], open_device=must_not_connect)

    assert exit_.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.strip() == f"ios-homescreen {__version__}"


def test_help_does_not_load_the_device_stack():
    import subprocess

    code = (
        "import sys\n"
        "from ios_homescreen.cli import main\n"
        "try:\n"
        "    main(['push', '--help'])\n"
        "except SystemExit:\n"
        "    pass\n"
        "print('pymobiledevice3' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip().endswith("False")


# ------------------------------------------------------------------ pull


def test_pull_writes_the_layout_file_and_keeps_the_snapshot_in_the_data_dir(home, capsys):
    device = pull(home)

    (snapshot_file,) = (home / "pulls").glob("pull-*.plist")
    layout = Path("layout.toml").read_text()
    assert f'[pull]\nsnapshot = "{snapshot_file.name}"' in layout
    assert "# Pulled from Test iPhone (iPhone 15, iOS 26.0) on " in layout
    assert "# Only in the App Library (31)." in layout
    assert '#   "com.apple.tips",  # tips' in layout
    snapshot = load_plist(snapshot_file)
    assert snapshot["format"] == "ios-homescreen.pull"
    assert snapshot["state"] == samples.home_screen()
    assert snapshot["apps"] == samples.installed_apps()
    assert snapshot["device"]["udid"] == UDID
    assert "wifi_mac" not in snapshot["device"]
    assert "raw_state_v3" in snapshot
    assert device.closed
    assert not device.writes
    assert sorted(p.name for p in Path.cwd().iterdir()) == ["layout.toml"]
    out = capsys.readouterr().out
    assert "Wrote layout.toml: dock 4 items, 2 pages, 31 apps only in the App Library." in out
    assert "Next: edit layout.toml, then run\n  ios-homescreen check  to see what" in out
    assert "  ios-homescreen push   to write it to the phone" in out


def test_pull_records_a_failed_format_3_read(home):
    class NoRaw(FakeSpringBoard):
        async def read_raw_state(self):
            raise RuntimeError("format 3 not supported")

    pull(home, NoRaw(samples.home_screen(), samples.installed_apps()))

    snapshot = load_plist(next((home / "pulls").glob("pull-*.plist")))
    assert snapshot["raw_state_v3_error"] == "format 3 not supported"


def test_pull_into_a_named_file(home, capsys):
    pull(home, None, "phones/mine.toml")

    assert Path("phones/mine.toml").read_text().startswith("# ios-homescreen layout.")
    assert "  ios-homescreen check phones/mine.toml  to see" in capsys.readouterr().out


def test_data_dir_flag_and_env_override_the_default(home, tmp_path, monkeypatch):
    pull(home, None, "a.toml", "--data-dir", str(tmp_path / "flag"))
    monkeypatch.setenv("IOS_HOMESCREEN_DATA_DIR", str(tmp_path / "env"))
    pull(home, None, "b.toml")

    assert list((tmp_path / "flag" / "pulls").glob("pull-*.plist"))
    assert list((tmp_path / "env" / "pulls").glob("pull-*.plist"))
    assert not home.exists()


def test_pull_replaces_an_unedited_file_but_keeps_one_with_edits(home, capsys):
    pull(home)
    pull(home)  # nothing was edited: replacing the file loses nothing
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    edited = Path("layout.toml").read_text()
    capsys.readouterr()

    assert main(["pull"], open_device=must_not_connect) == 1

    err = capsys.readouterr().err
    assert "layout.toml already exists and it has 2 changes that were not pushed" in err
    assert "--overwrite" in err
    assert Path("layout.toml").read_text() == edited
    pull(home, None, "--overwrite")
    assert 'com.apple.tips",' not in Path("layout.toml").read_text().split("# Only in")[0]


def test_pull_keeps_a_file_it_cannot_compare(home, capsys):
    Path("layout.toml").write_text("my notes, not a layout [")

    assert main(["pull"], open_device=must_not_connect) == 1
    assert "it cannot be compared with its pull" in capsys.readouterr().err
    assert Path("layout.toml").read_text() == "my notes, not a layout ["


def test_transport_flags_reach_the_connection(home):
    seen: list[Transport] = []

    def run(*flags):
        assert main(["pull", *flags], open_device=opener_for(phone(), seen)) == 0

    run("--wifi")
    run("--wifi", "--udid", UDID)
    run("--wifi", "--discovery-timeout", "9", "--connect-timeout", "4")
    run()

    assert seen[0] == Transport(wifi=True)
    assert seen[1] == Transport(wifi=True, udid=UDID)
    assert (seen[2].discovery_timeout, seen[2].connect_timeout) == (9, 4)
    assert seen[3] == Transport()
    assert not seen[3].network


def test_connection_errors_are_reported_cleanly(home, capsys):
    from ios_homescreen.transport import TransportError

    async def unreachable(transport):
        raise TransportError("no iPhone found over USB", code="no_usb_device")

    assert main(["pull"], open_device=unreachable) == 1
    assert capsys.readouterr().err == "error: no iPhone found over USB\n"
    assert not Path("layout.toml").exists()


# ------------------------------------------------------------------ check


def test_check_lists_what_push_would_change(home, capsys):
    pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    capsys.readouterr()

    assert main(["check"]) == 0

    out = capsys.readouterr().out
    assert out.startswith(
        "layout.toml is valid.\nChanges compared with the pull from Test iPhone (iPhone 15, "
        "iOS 26.0) on "
    )
    assert "  Camera  moves from the dock to page 2, position 1\n" in out
    assert "  tips    comes from the App Library to page 2, position 2\n" in out
    assert "1 moved and 1 added.\n" in out
    assert "30 apps will be only in the App Library." in out
    assert "Write it with: ios-homescreen push" in out


def test_check_of_an_unedited_file(home, capsys):
    pull(home)
    capsys.readouterr()

    assert main(["check"]) == 0
    assert "push would change nothing" in capsys.readouterr().out


def test_check_reports_every_layout_problem(home, capsys):
    pull(home)
    Path("layout.toml").write_text(
        f'[pull]\nsnapshot = "{newest_pull(home)}"\n'
        '[[pages]]\nitems = ["Nope", "Calendar", "Calendar"]\n'
    )

    assert main(["check", "--allow-removal"]) == 1

    err = capsys.readouterr().err
    assert "error: 2 problems in the layout:" in err
    assert "page 1, item 1: unknown app 'Nope'" in err
    assert "com.apple.mobilecal is used more than once" in err


def test_removing_a_widget_needs_allow_removal(home, capsys):
    pull(home)
    state = samples.home_screen()
    state[2] = [x for x in state[2] if x.get("displayIdentifier") != samples.LIGHTS_A]
    write_layout(Path("layout.toml"), state, newest_pull(home))

    assert main(["check"]) == 1
    assert "--allow-removal" in capsys.readouterr().err
    assert main(["check", "--allow-removal"]) == 0
    assert "Lights widget  is removed; add it again on the iPhone" in capsys.readouterr().out


def test_check_uses_the_newest_pull_when_the_file_names_none(home, capsys):
    pull(home)
    write_layout(Path("other.toml"), moved_camera(), None)
    capsys.readouterr()

    assert main(["check", "other.toml"]) == 0

    captured = capsys.readouterr()
    assert f"other.toml names no pull; comparing it with the newest one, {newest_pull(home)}" in (
        captured.err
    )
    assert "Camera" in captured.out


def test_check_before_any_pull_explains(home, capsys):
    Path("layout.toml").write_text("[dock]\nitems = []\n")

    assert main(["check"]) == 1
    assert "nothing has been pulled yet" in capsys.readouterr().err


def test_check_with_a_missing_pull_explains(home, capsys):
    pull(home)
    Path("layout.toml").write_text('[pull]\nsnapshot = "pull-gone.plist"\n')

    assert main(["check"]) == 1
    assert "there is no pull snapshot named pull-gone.plist" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["../secret.plist", "/etc/passwd", "a/b.plist"])
def test_the_pull_table_cannot_point_outside_the_data_dir(home, capsys, name):
    pull(home)
    Path("layout.toml").write_text(f'[pull]\nsnapshot = "{name}"\n')

    assert main(["check"]) == 1
    assert "is not a pull snapshot file name" in capsys.readouterr().err


# ------------------------------------------------------------------ push


def test_push_writes_verifies_backs_up_and_brings_the_file_up_to_date(home, capsys):
    device = pull(home)
    first = newest_pull(home)
    write_layout(Path("layout.toml"), moved_camera(), first)
    capsys.readouterr()

    assert main(["push", "--yes", *FAST], open_device=opener_for(device)) == 0

    (backup,) = (home / "backups").glob("backup-*.plist")
    saved = load_plist(backup)
    assert saved["state"] == samples.home_screen()
    assert saved["device"] == {
        "name": "Test iPhone",
        "model": "iPhone 15",
        "ios_version": "26.0",
        "udid": UDID,
    }
    assert same_layout(asyncio.run(device.read_state()), moved_camera())
    assert device.writes[0]["ignored"]
    assert device.closed
    out = capsys.readouterr().out
    assert "Changes to Test iPhone:\n  Camera  moves from the dock to page 2, position 1" in out
    assert "[1/5] Reading the current layout" in out
    assert "[5/5] Layout verified." in out
    assert newest_pull(home) != first
    assert f'snapshot = "{newest_pull(home)}"' in Path("layout.toml").read_text()
    assert f"layout.toml is up to date with the phone again ({newest_pull(home)})." in out
    # The file and the phone agree again: a second push has nothing to do.
    assert main(["push", "--yes"], open_device=must_not_connect) == 0
    assert "nothing to push" in capsys.readouterr().out


def test_push_asks_at_a_terminal_and_writes_on_yes(home, terminal, capsys):
    device = pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    terminal("y\n")

    assert main(["push", *FAST], open_device=opener_for(device)) == 0

    assert len(device.writes) == 1
    assert "Write this layout? A backup is saved first. [y/N]" in capsys.readouterr().err


@pytest.mark.parametrize("answer", ["n\n", "\n", "", "maybe\n"])
def test_push_writes_nothing_unless_the_answer_is_yes(home, terminal, capsys, answer):
    device = pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    terminal(answer)

    assert main(["push", *FAST], open_device=opener_for(device)) == 2

    assert not device.writes
    assert not (home / "backups").exists()
    assert device.closed
    assert "Nothing was written." in capsys.readouterr().out


def test_push_without_a_terminal_needs_yes_and_never_connects(home, capsys):
    pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    capsys.readouterr()

    assert main(["push"], open_device=must_not_connect) == 2

    out = capsys.readouterr().out
    assert "Camera  moves from the dock to page 2" in out
    assert "the phone was not contacted: there is no terminal to ask in" in out
    assert "add --yes" in out


@pytest.mark.parametrize(
    "text",
    [
        "[dock\n",
        '[[pages]]\nitems = ["Nope"]\n',
        "[unknown]\n",
        "[pull]\nsnapshot = 3\n",
    ],
)
@pytest.mark.parametrize("yes", [[], ["--yes"]])
def test_push_checks_the_file_before_connecting(home, capsys, text, yes):
    pull(home)
    Path("layout.toml").write_text(text)

    assert main(["push", *yes], open_device=must_not_connect) == 1
    assert "error:" in capsys.readouterr().err


def test_push_of_an_unedited_file_does_not_connect(home, capsys):
    pull(home)

    assert main(["push", "--yes"], open_device=must_not_connect) == 0
    assert "matches its pull" in capsys.readouterr().out


def test_push_refuses_when_the_phone_changed_since_the_pull(home, capsys):
    pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    changed = samples.home_screen()
    changed[1].reverse()
    device = phone(changed)

    assert main(["push", "--yes", *FAST], open_device=opener_for(device)) == 1

    err = capsys.readouterr().err
    assert "changed since layout.toml was pulled" in err
    assert "--force" in err
    assert not device.writes
    assert not (home / "backups").exists()
    assert device.closed


def test_push_force_writes_over_a_changed_phone(home, capsys):
    pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    changed = samples.home_screen()
    changed[1].reverse()
    device = phone(changed)

    assert main(["push", "--yes", "--force", *FAST], open_device=opener_for(device)) == 0

    assert same_layout(asyncio.run(device.read_state()), moved_camera())
    assert load_plist(next((home / "backups").glob("backup-*.plist")))["state"] == changed
    assert "writing anyway (--force)" in capsys.readouterr().out


def test_push_when_the_phone_already_shows_the_layout(home, capsys):
    device = pull(home)
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))
    Path("copy.toml").write_text(Path("layout.toml").read_text())
    main(["push", "--yes", *FAST], open_device=opener_for(device))
    capsys.readouterr()

    assert main(["push", "copy.toml", "--yes", *FAST], open_device=opener_for(device)) == 0

    assert len(device.writes) == 1
    assert "already shows this layout. Nothing was written." in capsys.readouterr().out


def test_push_reports_a_rollback_with_exit_code_3(home):
    device = pull(home, phone(ignore_writes=True))
    pulled = newest_pull(home)
    write_layout(Path("layout.toml"), moved_camera(), pulled)

    assert main(["push", "--yes", *FAST], open_device=opener_for(device)) == 3

    assert len(device.writes) == 2
    assert f'snapshot = "{pulled}"' in Path("layout.toml").read_text()


def test_push_reports_a_failed_rollback_with_exit_code_4(home):
    class Dies(FakeSpringBoard):
        async def read_state(self):
            if self.writes:
                raise OSError("gone")
            return await super().read_state()

    device = pull(home, Dies(samples.home_screen(), samples.installed_apps()))
    write_layout(Path("layout.toml"), moved_camera(), newest_pull(home))

    assert main(["push", "--yes", *FAST], open_device=opener_for(device)) == 4
    assert list((home / "backups").glob("backup-*.plist"))


# ------------------------------------------------------------------ backups


def _backup(home, stamp: str, state=None, *, device=None) -> Path:
    data = make_backup(
        state or samples.home_screen(),
        device=device if device is not None else {"name": "Test iPhone", "udid": UDID},
    )
    return save_plist(home / "backups" / f"backup-{stamp}.plist", data)


def test_backups_lists_the_newest_first_with_the_iphone_and_a_summary(home, capsys):
    _backup(home, "20261009-091200-000000", [[], [samples.app("com.apple.Maps", "Maps")]])
    _backup(home, "20261010-144400-000000")
    save_plist(home / "backups" / "backup-20261001-080000-000000.plist", [[], []])

    assert main(["backups"]) == 0

    lines = capsys.readouterr().out.splitlines()
    rows = [line for line in lines if line.startswith("  ")]
    assert rows[0].startswith("  latest  2026-10-10 14:44:00  Test iPhone     dock 4, 2 pages")
    assert rows[0].endswith("backup-20261010-144400-000000")
    assert "33 items" in rows[0]
    assert "2026-10-09 09:12:00  Test iPhone     dock 0, 1 pages, 1 items" in rows[1]
    assert "unknown iPhone" in rows[2]
    assert lines[-1].startswith("Restore one with: ios-homescreen restore latest")


def test_backups_shows_the_newest_twenty_unless_asked(home, capsys):
    for n in range(25):
        _backup(home, f"202610{n + 1:02d}-120000-000000")

    main(["backups"])
    out = capsys.readouterr().out
    main(["backups", "--all"])
    everything = capsys.readouterr().out

    assert out.count("backup-2026") == 20
    assert "...and 5 older ones (--all lists them)." in out
    assert everything.count("backup-2026") == 25


def test_backups_when_there_are_none(home, capsys):
    assert main(["backups"]) == 0
    assert "No backups in" in capsys.readouterr().out


# ------------------------------------------------------------------ restore


def _maps_only() -> FakeSpringBoard:
    return phone([[], [samples.app("com.apple.Maps", "Maps")]])


def test_restore_latest_writes_the_newest_backup(home, capsys):
    _backup(home, "20261009-091200-000000", [[], [samples.app("com.apple.Maps", "Maps")]])
    _backup(home, "20261010-144400-000000")
    device = _maps_only()

    assert main(["restore", "latest", "--yes", *FAST], open_device=opener_for(device)) == 0

    assert same_layout(asyncio.run(device.read_state()), samples.home_screen())
    out = capsys.readouterr().out
    assert out.startswith("Backup: backup-20261010-144400-000000.plist, Test iPhone\n")
    assert "Changes to Test iPhone:" in out
    assert "[5/5] Layout verified." in out
    # Restoring backs up the layout it replaces, too.
    assert len(list((home / "backups").glob("backup-*.plist"))) == 3


@pytest.mark.parametrize(
    "ref", ["backup-20261010-144400-000000", "backup-20261010-144400-000000.plist"]
)
def test_restore_by_name(home, ref):
    _backup(home, "20261010-144400-000000")
    device = _maps_only()

    assert main(["restore", ref, "--yes", *FAST], open_device=opener_for(device)) == 0
    assert same_layout(asyncio.run(device.read_state()), samples.home_screen())


def test_restore_asks_at_a_terminal(home, terminal, capsys):
    _backup(home, "20261010-144400-000000")
    device = _maps_only()
    terminal("n\n")

    assert main(["restore", "latest", *FAST], open_device=opener_for(device)) == 2
    assert not device.writes
    assert "Restore this backup? The current layout is saved first. [y/N]" in (
        capsys.readouterr().err
    )
    terminal("yes\n")
    assert main(["restore", "latest", *FAST], open_device=opener_for(device)) == 0
    assert len(device.writes) == 1


def test_restore_without_a_terminal_needs_yes_and_never_connects(home, capsys):
    _backup(home, "20261010-144400-000000")

    assert main(["restore", "latest"], open_device=must_not_connect) == 2
    assert "there is no terminal to ask in" in capsys.readouterr().out


def test_restore_refuses_a_backup_from_another_iphone(home, capsys):
    _backup(home, "20261010-144400-000000", device={"name": "Other iPhone", "udid": "OTHER"})
    device = _maps_only()

    assert main(["restore", "latest", "--yes", *FAST], open_device=opener_for(device)) == 1
    assert "was made on another iPhone (Other iPhone)" in capsys.readouterr().err
    assert not device.writes
    forced = ["restore", "latest", "--yes", "--force", *FAST]
    assert main(forced, open_device=opener_for(device)) == 0


def test_restore_when_the_phone_already_shows_it(home, capsys):
    _backup(home, "20261010-144400-000000")
    device = phone()

    assert main(["restore", "latest", "--yes", *FAST], open_device=opener_for(device)) == 0
    assert not device.writes
    assert "already shows this layout" in capsys.readouterr().out


def test_restore_latest_without_backups_explains(home, capsys):
    assert main(["restore", "latest", "--yes"], open_device=must_not_connect) == 1
    assert "there are no backups in" in capsys.readouterr().err


def test_restore_of_an_unknown_name_explains(home, capsys):
    _backup(home, "20261010-144400-000000")

    assert main(["restore", "backup-nope", "--yes"], open_device=must_not_connect) == 1
    assert "ios-homescreen backups" in capsys.readouterr().err


@pytest.mark.parametrize("bad", [[], ["not a page"], {"state": "nope"}])
@pytest.mark.parametrize("yes", [[], ["--yes"]])
def test_restore_rejects_malformed_backups_without_connecting(home, tmp_path, capsys, bad, yes):
    path = tmp_path / "bad.plist"
    save_plist(path, bad)

    assert main(["restore", str(path), *yes], open_device=must_not_connect) == 1
    assert "error:" in capsys.readouterr().err


def test_restore_refuses_json_and_plans(home, tmp_path, capsys):
    json_backup = tmp_path / "state.json"
    json_backup.write_text("[[], []]")

    assert main(["restore", str(json_backup), "--yes"], open_device=must_not_connect) == 1
    assert "JSON" in capsys.readouterr().err
    from ios_homescreen.planner import plan_layout

    read = samples.read_snapshot()
    plan = save_plist(tmp_path / "plan.plist", plan_layout(export_layout(read), read).payload)
    assert main(["restore", str(plan), "--yes"], open_device=must_not_connect) == 1
    assert "is a plan, not a backup" in capsys.readouterr().err


def test_restore_upgrades_legacy_icon_type_folders(home, tmp_path):
    backup = save_plist(
        tmp_path / "old.plist",
        [
            [],
            [
                {
                    "iconType": "folder",
                    "displayName": "Old",
                    "iconLists": [[{"bundleIdentifier": "a"}]],
                }
            ],
        ],
    )
    device = FakeSpringBoard(
        [[], [{"bundleIdentifier": "a"}]], {"a": {"name": "A", "type": "User"}}
    )

    assert main(["restore", str(backup), "--yes", *FAST], open_device=opener_for(device)) == 0

    folder = asyncio.run(device.read_state())[1][0]
    assert folder["listType"] == "folder"
    assert "iconType" not in folder


def test_restore_recomputes_ignored_from_the_apps_installed_now(home, tmp_path):
    target = [[], [{"bundleIdentifier": "a"}]]
    backup = save_plist(tmp_path / "backup.plist", make_backup(target))
    device = FakeSpringBoard(
        [[], [{"bundleIdentifier": "a"}, {"bundleIdentifier": "b"}]],
        {"a": {"name": "A", "type": "User"}, "b": {"name": "B", "type": "User"}},
    )

    assert main(["restore", str(backup), "--yes", *FAST], open_device=opener_for(device)) == 0

    assert same_layout(asyncio.run(device.read_state()), target)
    assert device.writes[0]["ignored"] == ["b"]


def test_restore_accepts_a_pull_snapshot(home):
    pull(home)
    snapshot = home / "pulls" / newest_pull(home)
    device = FakeSpringBoard([[], []], samples.installed_apps())

    assert main(["restore", str(snapshot), "--yes", *FAST], open_device=opener_for(device)) == 0
    assert same_layout(asyncio.run(device.read_state()), samples.home_screen())


def test_restore_reports_a_rollback_with_exit_code_3(home):
    _backup(home, "20261010-144400-000000")
    device = phone([[], [samples.app("com.apple.Maps", "Maps")]], ignore_writes=True)

    assert main(["restore", "latest", "--yes", *FAST], open_device=opener_for(device)) == 3
    assert len(device.writes) == 2


# ------------------------------------------------------------------ Wi-Fi


def test_wifi_status_shows_the_setting_the_pairing_and_the_network(home, tmp_path, capsys):
    record = tmp_path / f"remote_{UDID}.plist"
    backend = FakeWifiBackend([RemoteRecord(UDID, record, True)])
    device = phone(wifi_enabled=True)

    code = main(["wifi", "status"], open_device=opener_for(device), wifi_backend=backend)

    out = capsys.readouterr().out
    assert code == 0
    assert "Wi-Fi connections setting: on" in out
    assert f"Wi-Fi pairing: {record}" in out
    assert "On the network: answering at 192.0.2.7" in out
    assert device.closed


def test_wifi_status_explains_a_missing_pairing_and_a_silent_phone(home, capsys):
    backend = FakeWifiBackend(answering=False)

    main(["wifi", "status"], open_device=opener_for(phone()), wifi_backend=backend)

    out = capsys.readouterr().out
    assert "Wi-Fi connections setting: off" in out
    assert "Wi-Fi pairing: this computer has no Wi-Fi pairing" in out
    assert "wifi setup" in out


def test_wifi_setup_turns_the_setting_on_and_pairs_once(home, tmp_path, capsys):
    backend = FakeWifiBackend(home=tmp_path)
    device = phone(wifi_enabled=False)

    assert main(["wifi", "setup"], open_device=opener_for(device), wifi_backend=backend) == 0

    out = capsys.readouterr().out
    assert device.wifi_enabled is True
    assert backend.paired == [device]
    assert f"Wi-Fi pairing: {tmp_path / f'remote_{UDID}.plist'}" in out
    assert "Add --wifi to other commands" in out


def test_wifi_off_keeps_the_pairing_unless_asked_to_forget(home, tmp_path):
    record = tmp_path / f"remote_{UDID}.plist"
    record.write_bytes(b"record")
    backend = FakeWifiBackend([RemoteRecord(UDID, record, True)])
    device = phone(wifi_enabled=True)

    assert main(["wifi", "off"], open_device=opener_for(device), wifi_backend=backend) == 0
    assert record.exists()
    assert device.wifi_enabled is False
    main(["wifi", "off", "--forget"], open_device=opener_for(device), wifi_backend=backend)
    assert not record.exists()


def test_forget_only_goes_with_off(home, capsys):
    assert main(["wifi", "setup", "--forget"], open_device=must_not_connect) == 2
    assert "--forget only goes with off" in capsys.readouterr().err


def test_wifi_setup_fails_when_the_phone_does_not_keep_it(home, tmp_path, capsys):
    class Stubborn(FakeSpringBoard):
        async def set_wifi_connections(self, enabled):
            return None

    device = Stubborn(samples.home_screen(), samples.installed_apps())
    backend = FakeWifiBackend(home=tmp_path)

    assert main(["wifi", "setup"], open_device=opener_for(device), wifi_backend=backend) == 1
    assert "did not keep" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["toggle", "enable", "disable"])
def test_wifi_rejects_unknown_actions(action, capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["wifi", action], open_device=must_not_connect)

    assert exit_.value.code == 2


def test_layout_files_keep_widget_data_through_a_round_trip(home):
    # The file holds ids only; the widget's own data comes back from the pull unchanged.
    device = pull(home)
    state = deepcopy(samples.home_screen())
    state[1], state[2] = state[2], state[1]
    write_layout(Path("layout.toml"), state, newest_pull(home))

    assert main(["push", "--yes", *FAST], open_device=opener_for(device)) == 0
    assert asyncio.run(device.read_state()) == state
