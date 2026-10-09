"""The pymobiledevice3 surface this tool relies on. Imports only; nothing connects.

If a version bump breaks one of these, read CONTRIBUTING.md before adapting the code.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("pymobiledevice3")


def _params(function) -> set[str]:
    return set(inspect.signature(function).parameters)


def test_lockdown_constructors():
    from pymobiledevice3.lockdown import create_using_tcp, create_using_usbmux

    assert {"serial", "connection_type", "pair_timeout"} <= _params(create_using_usbmux)
    assert {"hostname", "autopair", "pair_record", "keep_alive"} <= _params(create_using_tcp)


def test_wifi_setting_and_close_on_the_lockdown_client():
    from pymobiledevice3.lockdown import LockdownClient

    for name in ("set_enable_wifi_connections", "get_enable_wifi_connections", "close"):
        assert inspect.iscoroutinefunction(getattr(LockdownClient, name))


def test_bonjour_browsing():
    from pymobiledevice3.bonjour import MOBDEV2_SERVICE_NAME, Address, ServiceInstance

    assert MOBDEV2_SERVICE_NAME == "_apple-mobdev2._tcp.local."
    assert {"instance", "addresses"} <= set(ServiceInstance.__dataclass_fields__)
    assert Address("192.0.2.1", "wlan0").full_ip == "192.0.2.1"


def test_services():
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    assert {"format_version"} <= _params(SpringBoardServicesService.get_icon_state)
    assert inspect.iscoroutinefunction(SpringBoardServicesService.get_icon_pngdata)
    assert {"application_type"} <= _params(InstallationProxyService.get_apps)


def test_exceptions():
    from pymobiledevice3 import exceptions

    for name in ("ConnectionFailedToUsbmuxdError", "DeviceNotFoundError", "NoDeviceConnectedError"):
        assert issubclass(getattr(exceptions, name), Exception)
