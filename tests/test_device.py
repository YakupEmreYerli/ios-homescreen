from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

import pytest

from ios_homescreen.device import FORBIDDEN_SPRINGBOARD_CALLS, Device, DeviceError


class FakeService:
    """Stands in for pymobiledevice3's SpringBoardServicesService."""

    def __init__(
        self, *, no_reply: bool = False, read_delay: float = 0, icons=None, wallpaper=None
    ):
        self.no_reply = no_reply
        self.read_delay = read_delay
        self.icon_data = icons or {}
        self.wallpaper_data = wallpaper
        self.sent = None
        self.connects = 0
        self.closed = 0
        self.service = self

    async def connect(self):
        self.connects += 1

    async def close(self):
        self.closed += 1

    async def get_icon_state(self, format_version="2"):
        await asyncio.sleep(self.read_delay)
        return [[{"bundleIdentifier": f"fv{format_version}"}]]

    async def send_plist(self, data):
        self.sent = data

    async def recv_plist(self):
        if self.no_reply:
            await asyncio.Event().wait()
        return {"status": "ok"}

    async def get_icon_pngdata(self, bundle_id):
        value = self.icon_data.get(bundle_id)
        if isinstance(value, Exception):
            raise value
        return value

    async def get_wallpaper_pngdata(self):
        if isinstance(self.wallpaper_data, Exception):
            raise self.wallpaper_data
        return self.wallpaper_data


class FakeInstaller:
    def __init__(self, apps):
        self.apps = apps

    async def connect(self):
        return None

    async def close(self):
        return None

    async def lookup(self, options):
        self.options = options
        return self.apps


class FakeLockdown:
    def __init__(self):
        self.all_values = {
            "DeviceName": "Test iPhone",
            "ProductType": "iPhone15,4",
            "ProductVersion": "26.0",
            "UniqueDeviceID": "00008120-000A1B2C3D4E5F60",
            "WiFiAddress": "a0:b1:c2:d3:e4:f5",
        }
        self.wifi = False
        self.closed = False

    @property
    def display_name(self):
        return "iPhone 15"

    async def get_enable_wifi_connections(self):
        return self.wifi

    async def set_enable_wifi_connections(self, value):
        self.wifi = value

    async def close(self):
        self.closed = True


def run(coro):
    return asyncio.run(coro)


def _device(service=None, **kwargs) -> Device:
    service = service or FakeService()
    return Device(FakeLockdown(), springboard_factory=lambda _: service, **kwargs)


def test_info_comes_from_lockdown_values():
    assert _device().info == {
        "name": "Test iPhone",
        "model": "iPhone 15",
        "ios_version": "26.0",
        "udid": "00008120-000A1B2C3D4E5F60",
        "wifi_mac": "a0:b1:c2:d3:e4:f5",
    }


def test_read_timeout_stops_a_hanging_service():
    device = _device(FakeService(read_delay=1), read_timeout=0.01)

    with pytest.raises(DeviceError, match="timed out") as error:
        run(device.read_state())

    assert error.value.code == "timeout"


def test_raw_read_asks_for_format_version_3():
    assert run(_device().read_raw_state()) == [[{"bundleIdentifier": "fv3"}]]


def test_write_sends_the_plist_itself_and_waits_for_a_reply_only_briefly():
    service = FakeService(no_reply=True)
    device = _device(service, send_timeout=0.1, reply_timeout=0.01)
    payload = {"buttonBar": [], "iconLists": [], "ignored": ["com.apple.tips"]}

    started = time.monotonic()
    reply = run(device.write_state(payload))

    assert time.monotonic() - started < 0.2
    assert reply is None
    assert service.sent == {"command": "setIconState", "iconState": payload}
    assert service.closed == 1


def test_service_is_closed_even_when_sending_fails():
    class BreaksOnSend(FakeService):
        async def send_plist(self, data):
            raise OSError("connection dropped")

    service = BreaksOnSend()

    with pytest.raises(DeviceError, match="sending the layout failed"):
        run(_device(service).write_state({"buttonBar": [], "iconLists": [], "ignored": []}))

    assert service.closed == 1


@pytest.mark.parametrize(
    "payload",
    [
        [[], []],
        {"buttonBar": [], "iconLists": [], "ignored": [], "extra": True},
        {
            "buttonBar": [],
            "iconLists": [
                [
                    {
                        "iconType": "folder",
                        "displayName": "Old",
                        "iconLists": [[{"bundleIdentifier": "a"}]],
                    }
                ]
            ],
            "ignored": [],
        },
        {
            "buttonBar": [],
            "iconLists": [
                [
                    {
                        "listType": "folder",
                        "displayName": "Outer",
                        "iconLists": [
                            [{"listType": "folder", "displayName": "Inner", "iconLists": [[]]}]
                        ],
                    }
                ]
            ],
            "ignored": [],
        },
        {"buttonBar": [], "iconLists": [[{"bundleIdentifier": "a"}]], "ignored": ["a"]},
    ],
)
def test_unsafe_payloads_never_reach_the_device(payload):
    service = FakeService()

    with pytest.raises(DeviceError, match="refusing") as error:
        run(_device(service).write_state(payload))

    assert error.value.code == "unsafe_payload"
    assert service.sent is None
    assert service.connects == 0


def test_installed_apps_keep_user_and_system_only_and_flag_hidden_services():
    apps = {
        "u": {"CFBundleDisplayName": "User App", "ApplicationType": "User"},
        "s": {"CFBundleName": "System App", "ApplicationType": "System"},
        "e": {"CFBundleDisplayName": "Extension", "ApplicationType": "PluginKitPlugin"},
        "n": {"ApplicationType": "User"},
        "com.apple.AirDropUI": {
            "CFBundleName": "AirDropUI",
            "ApplicationType": "System",
            "SBAppTags": ["hidden"],
        },
        "com.apple.measure": {
            "CFBundleName": "Measure",
            "ApplicationType": "System",
            "SBAppTags": ["arkit"],
        },
    }
    installer = FakeInstaller(apps)
    device = Device(FakeLockdown(), installer_factory=lambda _: installer)

    assert run(device.installed_apps()) == {
        "u": {"name": "User App", "type": "User"},
        "s": {"name": "System App", "type": "System"},
        "n": {"name": "n", "type": "User"},
        "com.apple.AirDropUI": {"name": "AirDropUI", "type": "System", "hidden": True},
        "com.apple.measure": {"name": "Measure", "type": "System"},
    }
    assert installer.options["ApplicationType"] == "Any"
    assert "SBAppTags" in installer.options["ReturnAttributes"]


def test_a_missing_app_list_is_an_error():
    device = Device(FakeLockdown(), installer_factory=lambda _: FakeInstaller(None))

    with pytest.raises(DeviceError, match="no app list"):
        run(device.installed_apps())


def test_icons_use_one_connection_and_return_none_when_missing():
    service = FakeService(
        icons={"com.apple.mobilesafari": b"\x89PNG safari", "broken": RuntimeError("no icon")}
    )

    icons = run(_device(service).icons(["com.apple.mobilesafari", "WEBAPP-1", "broken"]))

    assert icons == {"com.apple.mobilesafari": b"\x89PNG safari", "WEBAPP-1": None, "broken": None}
    assert (service.connects, service.closed) == (1, 1)


def test_the_wallpaper_comes_from_springboard_on_its_own_connection():
    service = FakeService(wallpaper=b"\x89PNG wallpaper")

    assert run(_device(service).wallpaper()) == b"\x89PNG wallpaper"
    assert (service.connects, service.closed) == (1, 1)


@pytest.mark.parametrize("answer", [None, b""])
def test_no_wallpaper_is_none(answer):
    assert run(_device(FakeService(wallpaper=answer)).wallpaper()) is None


def test_a_failed_wallpaper_read_is_a_device_error_and_closes_the_service():
    service = FakeService(wallpaper=RuntimeError("not supported"))

    with pytest.raises(DeviceError, match="Reading the wallpaper failed"):
        run(_device(service).wallpaper())
    assert service.closed == 1


def test_wifi_setting_reads_and_writes_through_lockdown():
    device = _device()

    assert run(device.wifi_connections_enabled()) is False
    run(device.set_wifi_connections(True))
    assert run(device.wifi_connections_enabled()) is True


def test_close_closes_the_lockdown_connection():
    device = _device()

    run(device.close())

    assert device.lockdown.closed


# ------------------------------------------------------------------ the device's name


class NamelessLockdown(FakeLockdown):
    """A connection that does not resolve the model (the Wi-Fi RSD session)."""

    display_name = None


def test_the_model_is_the_name_the_connection_reported():
    device = _device(marketing_name="iPhone 15 Pro")

    assert device.info["model"] == "iPhone 15 Pro"


@pytest.mark.parametrize(
    ("product", "name"),
    [("iPhone15,4", "iPhone 15"), ("iPhone18,4", "iPhone Air"), ("iPhone99,1", "iPhone99,1")],
)
def test_without_a_name_a_table_names_recent_iphones(product, name):
    lockdown = NamelessLockdown()
    lockdown.all_values["ProductType"] = product

    assert Device(lockdown).info["model"] == name


# ------------------------------------------------------------------ the accident


def test_the_springboard_service_refuses_the_calls_that_write_the_list_form():
    pytest.importorskip("pymobiledevice3")
    from ios_homescreen.device import _springboard

    service = _springboard(object())

    for name in ("set_icon_state", "reload_icon_state"):
        with pytest.raises(DeviceError, match="never used"):
            run(getattr(service, name)())


def test_no_code_calls_the_springboard_writes_that_caused_the_accident():
    # reload_icon_state reads the layout and writes it back as a list: SpringBoard then
    # puts every app that is not on it back on the home screen.
    source = Path(__file__).resolve().parents[1] / "src" / "ios_homescreen"
    found = []
    mentions = 0
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_SPRINGBOARD_CALLS:
                found.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Constant) and node.value in FORBIDDEN_SPRINGBOARD_CALLS:
                mentions += 1

    assert found == []
    # The only string mentions are the guard's own list in device.py.
    assert mentions == len(FORBIDDEN_SPRINGBOARD_CALLS)
