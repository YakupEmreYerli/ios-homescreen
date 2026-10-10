"""--json output (one object on stdout, the documented schema) and the apps command."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import samples
from fakes import FakeSpringBoard, FakeWifiBackend, must_not_connect, opener_for
from ios_homescreen.cli import main
from ios_homescreen.export import export_layout
from ios_homescreen.snapshots import make_backup
from ios_homescreen.state import save_plist

UDID = "00008120-000A1B2C3D4E5F60"
FAST = ["--verify-attempts", "2", "--verify-interval", "0", "--write-timeout", "1"]
COMMON = {"ok", "command", "exit_code"}


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("IOS_HOMESCREEN_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return tmp_path / "xdg" / "ios-homescreen"


def phone(state=None, **kwargs) -> FakeSpringBoard:
    return FakeSpringBoard(state or samples.home_screen(), samples.installed_apps(), **kwargs)


def run_json(capsys, *argv, **kwargs) -> tuple[int, dict]:
    code = main([*argv, "--json"], **kwargs)
    out = capsys.readouterr().out
    result = json.loads(out)  # exactly one JSON document, nothing else on stdout
    assert result["exit_code"] == code
    assert result["ok"] is (code == 0)
    return code, result


def pulled(capsys, device=None) -> FakeSpringBoard:
    device = device or phone()
    run_json(capsys, "pull", open_device=opener_for(device))
    return device


def newest(home) -> str:
    return max(p.name for p in (home / "pulls").glob("pull-*.plist"))


def edit(home) -> None:
    state = samples.home_screen()
    camera = state[0].pop()
    state[2][0:0] = [camera, "com.apple.tips"]
    read = {"state": state, "apps": samples.installed_apps()}
    Path("layout.toml").write_text(export_layout(read, pull=newest(home)))


def test_pull(home, capsys):
    code, result = run_json(capsys, "pull", open_device=opener_for(phone()))

    assert code == 0
    assert result == {
        "ok": True,
        "command": "pull",
        "exit_code": 0,
        "layout": "layout.toml",
        "pull": newest(home),
        "device": {
            "name": "Test iPhone",
            "model": "iPhone 15",
            "ios_version": "26.0",
            "udid": UDID,
        },
        "dock": 4,
        "pages": 2,
        "library": 31,
    }


def test_progress_goes_to_stderr(home, capsys):
    main(["pull", "--json"], open_device=opener_for(phone()))

    captured = capsys.readouterr()
    assert "Reading the home screen" in captured.err
    assert captured.out.count("\n") == 1


def test_check(home, capsys):
    pulled(capsys)
    edit(home)

    code, result = run_json(capsys, "check")

    assert code == 0
    assert set(result) == COMMON | {
        "layout",
        "pull",
        "pull_named_by_file",
        "valid",
        "unchanged",
        "changes",
        "summary",
        "library",
    }
    assert (result["valid"], result["unchanged"], result["library"]) == (True, False, 30)
    assert result["changes"][0] == {
        "kind": "moved",
        "id": "com.apple.camera",
        "type": "app",
        "name": "Camera",
        "from": {"section": "dock", "index": 4},
        "to": {"section": "page", "page": 2, "index": 1},
    }
    assert result["summary"] == "1 moved and 1 added."


def test_check_of_a_layout_with_problems(home, capsys):
    pulled(capsys)
    Path("layout.toml").write_text('[[pages]]\nitems = ["Nope", "Calendar", "Calendar"]\n')

    code, result = run_json(capsys, "check", "--allow-removal")

    assert code == 1
    assert result["error"]["code"] == "layout_invalid"
    assert [issue["code"] for issue in result["error"]["issues"]] == [
        "unknown_app",
        "duplicate_item",
    ]
    assert result["error"]["issues"][0]["location"] == {"section": "page", "page": 1, "item": 1}


def test_check_before_any_pull(home, capsys):
    Path("layout.toml").write_text("[dock]\nitems = []\n")

    code, result = run_json(capsys, "check")

    assert (code, result["error"]["code"]) == (1, "no_pull")


def test_push_without_yes_reports_the_changes_and_does_not_connect(home, capsys):
    pulled(capsys)
    edit(home)
    sys.stdin = type("Tty", (io.StringIO,), {"isatty": lambda self: True})("y\n")

    # Even at a terminal, --json never asks: the agent must ask the user.
    code, result = run_json(capsys, "push", open_device=must_not_connect)

    assert code == 2
    assert result["error"]["code"] == "confirmation_needed"
    assert [c["id"] for c in result["changes"]] == ["com.apple.camera", "com.apple.tips"]
    assert result["summary"] == "1 moved and 1 added."


def test_push_with_yes(home, capsys):
    device = pulled(capsys)
    edit(home)
    first = newest(home)

    code, result = run_json(capsys, "push", "--yes", *FAST, open_device=opener_for(device))

    assert code == 0
    assert result["status"] == "applied"
    assert Path(result["backup"]).is_file()
    assert result["new_pull"] == newest(home) != first
    assert result["layout_updated"] is True
    assert result["write_unconfirmed"] is False
    assert len(result["changes"]) == 2
    assert "error" not in result
    code, again = run_json(capsys, "push", "--yes", open_device=must_not_connect)
    assert (code, again["status"], again["changes"]) == (0, "unchanged", [])


def test_push_onto_a_changed_phone(home, capsys):
    pulled(capsys)
    edit(home)
    changed = samples.home_screen()
    changed[1].reverse()

    code, result = run_json(capsys, "push", "--yes", *FAST, open_device=opener_for(phone(changed)))

    assert (code, result["error"]["code"]) == (1, "layout_changed")
    assert "--force" in result["error"]["message"]


def test_push_that_is_rolled_back(home, capsys):
    device = pulled(capsys, phone(ignore_writes=True))
    edit(home)

    code, result = run_json(capsys, "push", "--yes", *FAST, open_device=opener_for(device))

    assert code == 3
    assert result["status"] == "rolled-back"
    assert result["error"]["code"] == "rolled_back"
    assert Path(result["backup"]).is_file()


def test_pull_over_a_file_with_edits(home, capsys):
    pulled(capsys)
    edit(home)

    code, result = run_json(capsys, "pull", open_device=must_not_connect)

    assert (code, result["error"]["code"]) == (1, "unpushed_edits")


def test_a_connection_error(home, capsys):
    from ios_homescreen.transport import TransportError

    async def unreachable(transport):
        raise TransportError("no iPhone found over USB", code="no_usb_device")

    code, result = run_json(capsys, "pull", open_device=unreachable)

    assert code == 1
    assert result["error"] == {"code": "no_usb_device", "message": "no iPhone found over USB"}
    assert capsys.readouterr().err == ""


def _backup(home, stamp, device=None):
    data = make_backup(
        samples.home_screen(), device=device or {"name": "Test iPhone", "udid": UDID}
    )
    return save_plist(home / "backups" / f"backup-{stamp}.plist", data)


def test_backups(home, capsys):
    _backup(home, "20261009-091200-000000")
    _backup(home, "20261010-144400-000000")

    code, result = run_json(capsys, "backups")

    assert code == 0
    assert result["directory"] == str(home / "backups")
    assert result["backups"][0] == {
        "name": "backup-20261010-144400-000000.plist",
        "created": "2026-10-10T14:44:00",
        "device": {"name": "Test iPhone", "udid": UDID},
        "summary": {"dock": 4, "pages": 2, "items": 33},
    }
    assert len(result["backups"]) == 2


def test_restore(home, capsys):
    _backup(home, "20261010-144400-000000")
    device = phone([[], [samples.app("com.apple.Maps", "Maps")]])

    code, asked = run_json(capsys, "restore", "latest", open_device=must_not_connect)
    assert (code, asked["error"]["code"]) == (2, "confirmation_needed")
    assert asked["restoring"] == "backup-20261010-144400-000000.plist"
    assert asked["made_on"] == {"name": "Test iPhone", "udid": UDID}

    code, result = run_json(
        capsys, "restore", "latest", "--yes", *FAST, open_device=opener_for(device)
    )

    assert code == 0
    assert result["status"] == "applied"
    assert result["changes"]
    assert Path(result["backup"]).is_file()


def test_restore_of_another_iphones_backup(home, capsys):
    _backup(home, "20261010-144400-000000", {"name": "Other", "udid": "OTHER"})

    code, result = run_json(
        capsys, "restore", "latest", "--yes", *FAST, open_device=opener_for(phone())
    )

    assert (code, result["error"]["code"]) == (1, "other_device")


def test_restore_without_backups(home, capsys):
    code, result = run_json(capsys, "restore", "latest", "--yes", open_device=must_not_connect)

    assert (code, result["error"]["code"]) == (1, "no_backup")


def test_wifi_status(home, capsys, tmp_path):
    from ios_homescreen.transport import RemoteRecord

    record = tmp_path / f"remote_{UDID}.plist"
    backend = FakeWifiBackend([RemoteRecord(UDID, record, True)])

    code, result = run_json(
        capsys,
        "wifi",
        "status",
        open_device=opener_for(phone(wifi_enabled=True)),
        wifi_backend=backend,
    )

    assert code == 0
    assert result["action"] == "status"
    assert (result["enabled"], result["reachable"], result["address"]) == (True, True, "192.0.2.7")
    assert result["pair_record"] == str(record)
    assert "wifi_mac" not in result["device"]


# ------------------------------------------------------------------ apps


def test_apps_lists_every_visible_app_and_where_it_is(home, capsys):
    pulled(capsys)

    code, result = run_json(capsys, "apps")

    assert code == 0
    assert result["pull"] == newest(home)
    found = {app["id"]: app for app in result["apps"]}
    assert found["com.apple.camera"]["where"] == {"section": "dock", "index": 4}
    assert found["com.apple.mobilecal"]["where"] == {"section": "page", "page": 1, "index": 2}
    assert found["com.apple.iBooks"]["where"] == {
        "section": "page",
        "page": 2,
        "index": 4,
        "folder": "Media",
        "folder_page": 2,
        "folder_index": 1,
    }
    assert found["com.apple.tips"] == {
        "name": "tips",
        "id": "com.apple.tips",
        "type": "System",
        "offloaded": False,
        "where": {"section": "library"},
    }
    assert found[samples.OFFLOADED]["offloaded"] is True
    # Widgets, web clips and web apps are not apps; Safari is listed once.
    assert samples.LIGHTS_A not in found
    assert samples.WEBAPP_PAGE not in found
    assert len(result["apps"]) == 25 + 31
    assert [a["name"] for a in result["apps"]] == sorted(
        (a["name"] for a in result["apps"]), key=str.casefold
    )


def test_apps_filters_by_name_or_id(home, capsys):
    pulled(capsys)

    _, by_name = run_json(capsys, "apps", "cal")
    _, by_id = run_json(capsys, "apps", "MOBILESAFARI")

    assert [a["id"] for a in by_name["apps"]] == ["com.apple.calculator", "com.apple.mobilecal"]
    assert [a["id"] for a in by_id["apps"]] == ["com.apple.mobilesafari"]


def test_apps_as_text(home, capsys):
    pulled(capsys)

    assert main(["apps", "cal"]) == 0

    out = capsys.readouterr().out
    assert (
        '  Calculator  com.apple.calculator  page 1, position 10, folder "Utilities" (position 1)'
        in out
    )
    assert "  Calendar    com.apple.mobilecal   page 1, position 2\n" in out
    assert out.endswith("2 apps: 2 on the home screen, 0 only in the App Library.\n")


def test_apps_needs_a_pull(home, capsys):
    code, result = run_json(capsys, "apps")

    assert (code, result["error"]["code"]) == (1, "no_pull")
