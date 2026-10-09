"""The Python API that the CLI (and later a UI) sit on."""

from __future__ import annotations

import asyncio
import json

import pytest

import samples
from fakes import FakeSpringBoard, FakeWifiBackend
from ios_homescreen import api
from ios_homescreen.transport import RemoteRecord


def run(coro):
    return asyncio.run(coro)


def test_connect_takes_a_backend_and_reports_progress():
    events = []

    backend = FakeWifiBackend()
    device = run(api.connect(on_event=events.append, backend=backend))

    assert isinstance(device, api.Device)
    assert device.info["udid"] == "UDID-1"
    assert device.transport == "usb"
    assert [event.to_dict()["code"] for event in events] == ["connecting"]
    run(device.close())
    assert device.lockdown.closed


def test_connect_over_wifi_closes_the_tunnel_with_the_device(tmp_path):
    backend = FakeWifiBackend([RemoteRecord("UDID-1", tmp_path / "remote_UDID-1.plist", True)])

    device = run(api.connect(api.Transport(wifi=True), backend=backend))
    run(device.close())

    assert device.transport == "wifi"
    assert backend.closed == 1


def test_a_whole_session_through_the_api(tmp_path):
    device = FakeSpringBoard(samples.home_screen(), samples.installed_apps())
    events = []

    snapshot = run(api.read_device(device))
    saved = api.save_read(snapshot, tmp_path / "reads")
    read = api.load_read(saved.path)
    view = api.describe(read)
    view["dock"].reverse()
    plan = api.plan_layout(api.to_document(view), read)
    plan_path = api.save_plan(plan, tmp_path / "plan.plist")
    result = run(
        api.apply_plan(
            device,
            api.load_plan(plan_path),
            backup_dir=tmp_path / "backups",
            timing=api.Timing(verify_attempts=1, verify_interval=0),
            on_event=events.append,
        )
    )

    assert result.ok
    assert json.loads(json.dumps(result.to_dict()))["status"] == "applied"
    assert json.dumps(plan.summary())
    assert run(device.read_state())[0][0]["bundleIdentifier"] == "com.apple.camera"
    assert saved.summary_path.read_text().startswith("Home screen summary")
    assert events[-1].code == "verified"

    restored = run(
        api.restore(
            device,
            api.load_backup(result.backup),
            backup_dir=tmp_path / "backups",
            timing=api.Timing(verify_attempts=1, verify_interval=0),
        )
    )
    assert restored.ok
    assert run(device.read_state()) == samples.home_screen()


def test_apply_plan_validates_before_touching_the_device(tmp_path):
    device = FakeSpringBoard(samples.home_screen(), samples.installed_apps())

    with pytest.raises(api.StateError):
        run(api.apply_plan(device, {"buttonBar": []}, backup_dir=tmp_path))

    assert device.reads == 0


def test_enabling_wifi_pairs_this_computer_once_and_checks_the_network(tmp_path):
    backend = FakeWifiBackend(home=tmp_path)
    device = FakeSpringBoard([[]], {}, wifi_enabled=False)

    status = run(api.set_wifi(device, True, backend=backend))
    again = run(api.set_wifi(device, True, backend=backend))

    data = json.loads(json.dumps(status.to_dict()))
    assert data["enabled"] is True
    assert data["pair_record"].endswith("remote_00008120-000A1B2C3D4E5F60.plist")
    assert data["pair_record_problem"] is None
    assert (data["reachable"], data["address"]) == (True, "192.0.2.7")
    assert len(backend.paired) == 1
    assert again.pair_record == status.pair_record


def test_an_old_pairing_is_made_again(tmp_path):
    stale = tmp_path / "remote_00008120-000A1B2C3D4E5F60.plist"
    stale.write_bytes(b"old")
    backend = FakeWifiBackend(
        [RemoteRecord("00008120-000A1B2C3D4E5F60", stale, False)], home=tmp_path
    )

    run(api.set_wifi(FakeSpringBoard([[]], {}), True, backend=backend))

    assert len(backend.paired) == 1


def test_wifi_status_without_pairing_or_network(tmp_path):
    backend = FakeWifiBackend(answering=False)
    device = FakeSpringBoard([[]], {}, wifi_enabled=True)

    status = run(api.wifi_status(device, backend=backend))

    assert status.enabled is True
    assert status.pair_record is None
    assert "wifi enable" in status.pair_record_problem
    assert status.reachable is None
    assert ("reachable", "00008120-000A1B2C3D4E5F60") not in backend.calls


def test_disabling_wifi_can_forget_the_pairing(tmp_path):
    path = tmp_path / "remote_00008120-000A1B2C3D4E5F60.plist"
    path.write_bytes(b"record")
    backend = FakeWifiBackend([RemoteRecord("00008120-000A1B2C3D4E5F60", path, True)])
    device = FakeSpringBoard([[]], {}, wifi_enabled=True)

    run(api.set_wifi(device, False, backend=backend))
    assert path.exists()
    status = run(api.set_wifi(device, False, backend=backend, forget=True))

    assert not path.exists()
    assert status.enabled is False
    assert status.reachable is None


def test_fetch_icons_caches_app_icons_only(tmp_path):
    device = FakeSpringBoard(samples.home_screen(), samples.installed_apps())
    cache = api.IconCache(tmp_path)

    icons = run(api.fetch_icons(device, ["com.apple.Maps", samples.WEBAPP_PAGE], cache))

    assert icons == {"com.apple.Maps": b"\x89PNGcom.apple.Maps", samples.WEBAPP_PAGE: None}
    assert cache.get("com.apple.Maps") == b"\x89PNGcom.apple.Maps"
