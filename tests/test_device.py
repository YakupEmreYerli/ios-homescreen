from __future__ import annotations

import asyncio
import time

import pytest

from ios_homescreen.device import Device, DeviceError


class FakeService:
    """Stands in for pymobiledevice3's SpringBoardServicesService."""

    def __init__(self, *, no_reply: bool = False, read_delay: float = 0, icons=None):
        self.no_reply = no_reply
        self.read_delay = read_delay
        self.icon_data = icons or {}
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


class FakeInstaller:
    def __init__(self, apps):
        self.apps = apps

    async def connect(self):
        return None

    async def close(self):
        return None

    async def get_apps(self, application_type="Any"):
        assert application_type == "Any"
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


def test_installed_apps_keep_user_and_system_only():
    apps = {
        "u": {"CFBundleDisplayName": "User App", "ApplicationType": "User"},
        "s": {"CFBundleName": "System App", "ApplicationType": "System"},
        "e": {"CFBundleDisplayName": "Extension", "ApplicationType": "PluginKitPlugin"},
        "n": {"ApplicationType": "User"},
    }
    device = Device(FakeLockdown(), installer_factory=lambda _: FakeInstaller(apps))

    assert run(device.installed_apps()) == {
        "u": {"name": "User App", "type": "User"},
        "s": {"name": "System App", "type": "System"},
        "n": {"name": "n", "type": "User"},
    }


def test_icons_use_one_connection_and_return_none_when_missing():
    service = FakeService(
        icons={"com.apple.mobilesafari": b"\x89PNG safari", "broken": RuntimeError("no icon")}
    )

    icons = run(_device(service).icons(["com.apple.mobilesafari", "WEBAPP-1", "broken"]))

    assert icons == {"com.apple.mobilesafari": b"\x89PNG safari", "WEBAPP-1": None, "broken": None}
    assert (service.connects, service.closed) == (1, 1)


def test_wifi_setting_reads_and_writes_through_lockdown():
    device = _device()

    assert run(device.wifi_connections_enabled()) is False
    run(device.set_wifi_connections(True))
    assert run(device.wifi_connections_enabled()) is True


def test_close_closes_the_lockdown_connection():
    device = _device()

    run(device.close())

    assert device.lockdown.closed
