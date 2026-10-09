"""The Python API that the CLI (and later a UI) sit on."""

from __future__ import annotations

import asyncio
import json
import plistlib

import pytest

import samples
from fakes import FakeSpringBoard
from ios_homescreen import api


def run(coro):
    return asyncio.run(coro)


class FakeLockdown:
    def __init__(self):
        self.paired = True
        self.all_values = {"DeviceName": "Test iPhone", "UniqueDeviceID": "UDID-1"}

    async def close(self):
        return None


class UsbOnly:
    async def usb(self, udid, pair_timeout):
        return FakeLockdown()

    async def tcp(self, host, pair_record):
        raise AssertionError("no network")

    async def browse(self, timeout):
        raise AssertionError("no network")


def test_connect_takes_a_backend_and_reports_progress():
    events = []

    device = run(api.connect(on_event=events.append, backend=UsbOnly()))

    assert isinstance(device, api.Device)
    assert device.info["udid"] == "UDID-1"
    assert [event.to_dict()["code"] for event in events] == ["connecting"]


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


def test_wifi_status_is_json_ready(tmp_path):
    (tmp_path / "00008120-000A1B2C3D4E5F60.plist").write_bytes(
        plistlib.dumps({"HostID": "H", "HostCertificate": b"c"})
    )
    device = FakeSpringBoard([[]], {}, wifi_enabled=False)

    status = run(api.set_wifi(device, True, tmp_path))

    data = json.loads(json.dumps(status.to_dict()))
    assert data["enabled"] is True
    assert data["pair_record"].endswith("00008120-000A1B2C3D4E5F60.plist")
    assert data["pair_record_problem"] is None


def test_fetch_icons_caches_app_icons_only(tmp_path):
    device = FakeSpringBoard(samples.home_screen(), samples.installed_apps())
    cache = api.IconCache(tmp_path)

    icons = run(api.fetch_icons(device, ["com.apple.Maps", samples.WEBAPP_PAGE], cache))

    assert icons == {"com.apple.Maps": b"\x89PNGcom.apple.Maps", samples.WEBAPP_PAGE: None}
    assert cache.get("com.apple.Maps") == b"\x89PNGcom.apple.Maps"
