from __future__ import annotations

import asyncio
import plistlib
from pathlib import Path

import pytest

import samples
from fakes import FakeSpringBoard, must_not_connect, opener_for
from ios_homescreen import __version__
from ios_homescreen.cli import main
from ios_homescreen.state import fingerprint, load_plist, same_layout, save_plist
from ios_homescreen.transport import Transport

UDID = "00008120-000A1B2C3D4E5F60"
FAST = ["--verify-attempts", "2", "--verify-interval", "0", "--write-timeout", "1"]


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """An isolated XDG data dir; the working directory must stay empty."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("IOS_HOMESCREEN_DATA_DIR", raising=False)
    monkeypatch.delenv("IOS_HOMESCREEN_PAIR_RECORDS", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return tmp_path / "xdg" / "ios-homescreen"


def phone(**kwargs) -> FakeSpringBoard:
    return FakeSpringBoard(samples.home_screen(), samples.installed_apps(), **kwargs)


COMMANDS = ["read", "export", "plan", "apply", "restore", "diff", "wifi"]


@pytest.mark.parametrize("argv", [["--help"], *([c, "--help"] for c in COMMANDS)])
def test_every_help_page_works(argv, capsys):
    with pytest.raises(SystemExit) as exit_:
        main(argv)

    text = capsys.readouterr().out
    assert exit_.value.code == 0
    assert text.startswith("usage: ios-homescreen")


@pytest.mark.parametrize("command", ["read", "apply", "restore", "wifi"])
def test_device_commands_offer_usb_and_wifi_options(command, capsys):
    with pytest.raises(SystemExit):
        main([command, "--help"])

    text = capsys.readouterr().out
    for flag in ("--wifi", "--host", "--udid", "--pair-records", "--discovery-timeout"):
        assert flag in text


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.strip() == f"ios-homescreen {__version__}"


def test_read_saves_into_the_xdg_data_dir_and_not_the_working_directory(home, capsys):
    device = phone()

    assert main(["read"], open_device=opener_for(device)) == 0

    reads = sorted((home / "reads").iterdir())
    assert [p.suffix for p in reads] == [".plist", ".txt"]
    snapshot = load_plist(reads[0])
    assert snapshot["format"] == "ios-homescreen.read"
    assert snapshot["state"] == samples.home_screen()
    assert snapshot["apps"] == samples.installed_apps()
    assert snapshot["device"]["udid"] == UDID
    assert "wifi_mac" not in snapshot["device"]
    assert "raw_state_v3" in snapshot
    summary = reads[1].read_text()
    assert "Page 1: 20/24 cells" in summary
    assert "Only in the App Library (31)" in summary
    assert device.closed
    assert not list(Path.cwd().iterdir())
    out = capsys.readouterr().out
    assert "Read saved:" in out
    assert "dock 4 items, 2 pages, 31 apps only in the App Library" in out


def test_read_records_a_failed_format_3_read(home, tmp_path):
    class NoRaw(FakeSpringBoard):
        async def read_raw_state(self):
            raise RuntimeError("format 3 not supported")

    device = NoRaw(samples.home_screen(), samples.installed_apps())

    assert main(["read", "-o", str(tmp_path / "out")], open_device=opener_for(device)) == 0

    snapshot = load_plist(next((tmp_path / "out").glob("read-*.plist")))
    assert snapshot["raw_state_v3_error"] == "format 3 not supported"


def test_data_dir_flag_and_env_override_the_default(home, tmp_path, monkeypatch):
    assert (
        main(["read", "--data-dir", str(tmp_path / "flag")], open_device=opener_for(phone())) == 0
    )
    monkeypatch.setenv("IOS_HOMESCREEN_DATA_DIR", str(tmp_path / "env"))
    assert main(["read"], open_device=opener_for(phone())) == 0

    assert list((tmp_path / "flag" / "reads").glob("read-*.plist"))
    assert list((tmp_path / "env" / "reads").glob("read-*.plist"))
    assert not home.exists()


def test_export_and_plan_use_the_newest_read_and_keep_plans_in_the_data_dir(home, capsys):
    main(["read"], open_device=opener_for(phone()))
    capsys.readouterr()

    assert main(["export"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("# ios-homescreen layout")
    assert "Using read:" in captured.err

    Path("layout.toml").write_text(captured.out)
    assert main(["plan", "layout.toml"]) == 0
    out = capsys.readouterr().out
    (plan,) = (home / "plans").glob("plan-*.plist")
    assert plan.read_bytes().startswith(b"bplist00")
    assert same_layout(load_plist(plan), samples.home_screen())
    assert "Apps kept off the home screen (ignored): 31" in out
    assert f"ios-homescreen apply {plan} --yes" in out
    assert sorted(p.name for p in Path.cwd().iterdir()) == ["layout.toml"]


def test_export_to_a_file(home, tmp_path):
    read = tmp_path / "read.plist"
    save_plist(read, samples.read_snapshot())

    assert main(["export", str(read), "-o", str(tmp_path / "out" / "layout.toml")]) == 0

    assert (tmp_path / "out" / "layout.toml").read_text().startswith("# ios-homescreen layout")


def test_plan_reports_every_layout_problem(home, tmp_path, capsys):
    read = tmp_path / "read.plist"
    save_plist(read, samples.read_snapshot())
    layout = tmp_path / "layout.toml"
    layout.write_text('[[pages]]\nitems = ["Nope", "Calendar", "Calendar"]\n')

    assert main(["plan", str(layout), "--read", str(read), "--allow-removal"]) == 1

    err = capsys.readouterr().err
    assert "error: 2 problems in the layout:" in err
    assert "page 1, item 1: unknown app 'Nope'" in err
    assert "com.apple.mobilecal is used more than once" in err


def test_plan_without_any_read_explains(home, tmp_path, capsys):
    layout = tmp_path / "layout.toml"
    layout.write_text("")

    assert main(["plan", str(layout)]) == 1
    assert "no read-*.plist file" in capsys.readouterr().err


def _plan_file(tmp_path, state=None) -> Path:
    state = state or samples.home_screen()
    from ios_homescreen.export import export_layout
    from ios_homescreen.planner import plan_layout

    read = {"state": state, "apps": samples.installed_apps()}
    path = tmp_path / "plan.plist"
    save_plist(path, plan_layout(export_layout(read), read).payload)
    return path


def test_apply_without_yes_never_contacts_the_device(home, tmp_path, capsys):
    plan = _plan_file(tmp_path)

    assert main(["apply", str(plan)], open_device=must_not_connect) == 2

    out = capsys.readouterr().out
    assert "Nothing was written and the device was not contacted" in out
    assert "31 apps kept off the home screen" in out


@pytest.mark.parametrize(
    "plan",
    [
        {},
        [[], []],
        {"buttonBar": [], "iconLists": [], "ignored": []},
        {
            "buttonBar": [],
            "iconLists": [],
            "ignored": [],
            "unexpected": "key",
            "_ios_homescreen": {"version": 1, "source_fingerprint": "a" * 64},
        },
        {
            "buttonBar": "not a list",
            "iconLists": [],
            "ignored": [],
            "_ios_homescreen": {"version": 1, "source_fingerprint": "a" * 64},
        },
    ],
)
@pytest.mark.parametrize("yes", [[], ["--yes"]])
def test_apply_rejects_malformed_plans_without_connecting(home, tmp_path, capsys, plan, yes):
    path = tmp_path / "plan.plist"
    save_plist(path, plan)

    assert main(["apply", str(path), *yes], open_device=must_not_connect) == 1
    assert "error:" in capsys.readouterr().err


def test_apply_writes_verifies_and_backs_up_into_the_data_dir(home, tmp_path, capsys):
    start = [[], [samples.app("com.apple.Maps", "Maps")]]
    device = FakeSpringBoard(start, samples.installed_apps())
    plan = _plan_file(tmp_path, start)
    seen: list[Transport] = []

    code = main(["apply", str(plan), "--yes", *FAST], open_device=opener_for(device, seen))

    assert code == 0
    assert seen == [Transport()]
    (backup,) = (home / "backups").glob("backup-*.plist")
    assert load_plist(backup) == start
    assert device.writes[0]["ignored"]
    assert device.closed
    out = capsys.readouterr().out
    assert "[1/5] Reading the current layout" in out
    assert "[5/5] Layout verified." in out


def test_apply_reports_a_rollback_with_exit_code_3(home, tmp_path):
    start = [[], [samples.app("com.apple.Maps", "Maps")]]
    device = FakeSpringBoard(start, samples.installed_apps(), ignore_writes=True)
    layout = tmp_path / "layout.toml"
    layout.write_text('[[pages]]\nitems = ["Calendar"]\n')
    read = tmp_path / "read.plist"
    save_plist(read, {"state": start, "apps": samples.installed_apps()})
    plan = tmp_path / "plan.plist"
    assert main(["plan", str(layout), "--read", str(read), "-o", str(plan)]) == 0

    assert main(["apply", str(plan), "--yes", *FAST], open_device=opener_for(device)) == 3
    assert len(device.writes) == 2


def test_apply_reports_a_failed_rollback_with_exit_code_4(home, tmp_path):
    class Dies(FakeSpringBoard):
        async def read_state(self):
            if self.writes:
                raise OSError("gone")
            return await super().read_state()

    start = [[], [samples.app("com.apple.Maps", "Maps")]]
    plan = _plan_file(tmp_path, start)

    code = main(
        ["apply", str(plan), "--yes", *FAST],
        open_device=opener_for(Dies(start, samples.installed_apps())),
    )

    assert code == 4


def test_apply_refuses_when_the_phone_changed_since_the_read(home, tmp_path, capsys):
    plan = _plan_file(tmp_path, [[], [samples.app("com.apple.Maps", "Maps")]])
    device = phone()

    assert main(["apply", str(plan), "--yes", *FAST], open_device=opener_for(device)) == 1

    assert "changed since the read" in capsys.readouterr().err
    assert not device.writes
    assert device.closed


def test_transport_flags_reach_the_connection(home, tmp_path, monkeypatch):
    plan = _plan_file(tmp_path, [[], [samples.app("com.apple.Maps", "Maps")]])
    seen: list[Transport] = []
    base = ["apply", str(plan)]

    def run(*flags):
        main([*base, *flags], open_device=opener_for(phone(), seen))

    run("--yes", "--wifi")
    run("--yes", "--host", "192.168.1.20", "--udid", UDID, "--pair-records", str(tmp_path))
    run("--yes", "--wifi", "--discovery-timeout", "9", "--connect-timeout", "4")

    assert seen[0] == Transport(wifi=True)
    assert seen[1] == Transport(wifi=True, host="192.168.1.20", udid=UDID, pair_records=tmp_path)
    assert (seen[2].discovery_timeout, seen[2].connect_timeout) == (9, 4)

    monkeypatch.setenv("IOS_HOMESCREEN_PAIR_RECORDS", str(tmp_path / "records"))
    run("--yes")
    assert seen[3] == Transport(pair_records=tmp_path / "records")
    assert not seen[3].network


@pytest.mark.parametrize("bad", [[], ["not a page"]])
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
    plan = _plan_file(tmp_path)
    assert main(["restore", str(plan), "--yes"], open_device=must_not_connect) == 1
    assert "use apply" in capsys.readouterr().err


def test_restore_without_yes_never_contacts_the_device(home, tmp_path, capsys):
    backup = save_plist(tmp_path / "backup.plist", samples.home_screen())

    assert main(["restore", str(backup)], open_device=must_not_connect) == 2
    assert "device was not contacted" in capsys.readouterr().out


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
    backup = save_plist(tmp_path / "backup.plist", target)
    device = FakeSpringBoard(
        [[], [{"bundleIdentifier": "a"}, {"bundleIdentifier": "b"}]],
        {"a": {"name": "A", "type": "User"}, "b": {"name": "B", "type": "User"}},
    )

    assert main(["restore", str(backup), "--yes", *FAST], open_device=opener_for(device)) == 0

    assert same_layout(asyncio.run(device.read_state()), target)
    assert device.writes[0]["ignored"] == ["b"]


def test_restore_accepts_a_read_snapshot(home, tmp_path):
    read = save_plist(tmp_path / "read.plist", samples.read_snapshot())
    device = FakeSpringBoard([[], []], samples.installed_apps())

    assert main(["restore", str(read), "--yes", *FAST], open_device=opener_for(device)) == 0
    assert same_layout(asyncio.run(device.read_state()), samples.home_screen())


def test_diff_shows_moves_and_additions_with_places(tmp_path, capsys):
    a = save_plist(tmp_path / "a.plist", [[], [{"bundleIdentifier": "a"}]])
    b = save_plist(tmp_path / "b.plist", [[{"bundleIdentifier": "a"}], [{"bundleIdentifier": "b"}]])

    assert main(["diff", str(a), str(b)]) == 0

    out = capsys.readouterr().out
    assert "Moved: a: page 1 -> dock" in out
    assert "Added: b: page 1" in out


def test_diff_shows_order_changes_and_reads_json(tmp_path, capsys):
    a = save_plist(
        tmp_path / "a.plist", [[], [{"bundleIdentifier": "a"}, {"bundleIdentifier": "b"}]]
    )
    b = tmp_path / "b.json"
    b.write_text('[[], [{"bundleIdentifier": "b"}, {"bundleIdentifier": "a"}]]')

    assert main(["diff", str(a), str(b)]) == 0

    out = capsys.readouterr().out
    assert "Order or structure changed:" in out
    assert "before: a, b" in out
    assert "after:  b, a" in out


def test_diff_of_identical_layouts(tmp_path, capsys):
    a = save_plist(tmp_path / "a.plist", samples.read_snapshot())

    assert main(["diff", str(a), str(a)]) == 0
    assert capsys.readouterr().out == "No layout differences.\n"


def _pair_record(directory: Path) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / f"{UDID}.plist"
    path.write_bytes(
        plistlib.dumps(
            {"HostID": "H", "HostCertificate": b"c", "WiFiMACAddress": "a0:b1:c2:d3:e4:f5"}
        )
    )
    return path


def test_wifi_status_shows_the_setting_and_the_pair_record(home, tmp_path, capsys):
    record = _pair_record(tmp_path / "records")
    device = phone(wifi_enabled=True)

    code = main(
        ["wifi", "status", "--pair-records", str(tmp_path / "records")],
        open_device=opener_for(device),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Wi-Fi connections: enabled" in out
    assert "Wi-Fi MAC: a0:b1:c2:d3:e4:f5" in out
    assert f"Pair record for network use: {record}" in out
    assert device.closed


@pytest.mark.parametrize(("action", "expected"), [("enable", True), ("disable", False)])
def test_wifi_enable_and_disable_change_the_setting(home, tmp_path, capsys, action, expected):
    device = phone(wifi_enabled=not expected)

    code = main(
        ["wifi", action, "--pair-records", str(tmp_path / "none")], open_device=opener_for(device)
    )

    assert code == 0
    assert device.wifi_enabled is expected
    out = capsys.readouterr().out
    assert f"Wi-Fi connections: {'enabled' if expected else 'disabled'}" in out
    assert "Pair record for network use: pair record directory" in out


def test_wifi_enable_fails_when_the_phone_does_not_keep_it(home, capsys):
    class Stubborn(FakeSpringBoard):
        async def set_wifi_connections(self, enabled):
            return None

    device = Stubborn(samples.home_screen(), samples.installed_apps())

    assert main(["wifi", "enable"], open_device=opener_for(device)) == 1
    assert "did not keep" in capsys.readouterr().err


def test_wifi_rejects_unknown_actions(capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["wifi", "toggle"], open_device=must_not_connect)

    assert exit_.value.code == 2


def test_connection_errors_are_reported_cleanly(home, capsys):
    from ios_homescreen.transport import TransportError

    async def unreachable(transport):
        raise TransportError("no iPhone found over USB", code="no_usb_device")

    assert main(["read"], open_device=unreachable) == 1
    assert capsys.readouterr().err == "error: no iPhone found over USB\n"


def test_plan_fingerprint_matches_the_read(home, tmp_path):
    read = tmp_path / "read.plist"
    save_plist(read, samples.read_snapshot())
    layout = tmp_path / "layout.toml"
    main(["export", str(read), "-o", str(layout)])
    main(["plan", str(layout), "--read", str(read), "-o", str(tmp_path / "p.plist")])

    meta = load_plist(tmp_path / "p.plist")["_ios_homescreen"]
    assert meta["source_fingerprint"] == fingerprint(samples.home_screen())


def test_help_does_not_load_the_device_stack():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from ios_homescreen.cli import main\n"
        "try:\n"
        "    main(['apply', '--help'])\n"
        "except SystemExit:\n"
        "    pass\n"
        "print('pymobiledevice3' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip().endswith("False")
