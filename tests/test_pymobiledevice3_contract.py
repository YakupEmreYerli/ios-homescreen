"""The pymobiledevice3 surface this tool relies on. Imports only; nothing connects.

If a version bump breaks one of these, read CONTRIBUTING.md before adapting the code.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("pymobiledevice3")


def _params(function) -> set[str]:
    return set(inspect.signature(function).parameters)


def test_usb_lockdown():
    from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux

    assert {"serial", "connection_type", "pair_timeout"} <= _params(create_using_usbmux)
    for name in ("set_enable_wifi_connections", "get_enable_wifi_connections", "close"):
        assert inspect.iscoroutinefunction(getattr(LockdownClient, name))


def test_the_wifi_session_offers_the_same_calls():
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService

    for name in ("get_enable_wifi_connections", "set_enable_wifi_connections", "close"):
        assert inspect.iscoroutinefunction(getattr(RemoteServiceDiscoveryService, name))


def test_services_and_their_remote_shims():
    from pymobiledevice3.service_connection import ServiceConnection
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    assert {"format_version"} <= _params(SpringBoardServicesService.get_icon_state)
    assert inspect.iscoroutinefunction(SpringBoardServicesService.get_icon_pngdata)
    # getHomeScreenWallpaperPNGData, for the editor's wallpaper.
    assert inspect.iscoroutinefunction(SpringBoardServicesService.get_wallpaper_pngdata)
    assert _params(SpringBoardServicesService.get_wallpaper_pngdata) == {"self"}
    assert inspect.iscoroutinefunction(InstallationProxyService.lookup)
    assert {"options"} <= _params(InstallationProxyService.lookup)
    # Over the Wi-Fi tunnel the services are reached through their *.shim.remote names.
    assert SpringBoardServicesService.RSD_SERVICE_NAME.endswith(".shim.remote")
    assert InstallationProxyService.RSD_SERVICE_NAME.endswith(".shim.remote")
    # setIconState is sent on the raw service connection (device.py).
    for name in ("connect", "close"):
        assert inspect.iscoroutinefunction(getattr(SpringBoardServicesService, name))
    for name in ("send_plist", "recv_plist"):
        assert inspect.iscoroutinefunction(getattr(ServiceConnection, name))


def test_remote_pairing_over_usb():
    from pymobiledevice3.exceptions import RemotePairingCompletedError
    from pymobiledevice3.remote.tunnel_service import RemotePairingLockdownService

    assert issubclass(RemotePairingCompletedError, Exception)
    assert inspect.iscoroutinefunction(RemotePairingLockdownService.create)
    assert "autopair" in _params(RemotePairingLockdownService.connect)
    assert inspect.iscoroutinefunction(RemotePairingLockdownService.close)


def test_remote_pairing_records():
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier
    from pymobiledevice3.remote.tunnel_service import PEER_ALT_IRK_KEY

    from ios_homescreen.transport import ALT_IRK_KEY

    assert callable(iter_remote_pair_records_by_identifier)
    assert PEER_ALT_IRK_KEY == ALT_IRK_KEY


def test_finding_the_phone_on_the_network():
    from pymobiledevice3.remote.tunnel_service import (
        RemotePairingTunnelService,
        get_remote_pairing_tunnel_services,
    )

    assert inspect.iscoroutinefunction(get_remote_pairing_tunnel_services)
    assert {"bonjour_timeout", "udid"} <= _params(get_remote_pairing_tunnel_services)
    # A remembered address is tried directly: transport.PymobiledeviceBackend._direct.
    assert list(inspect.signature(RemotePairingTunnelService.__init__).parameters) == [
        "self",
        "remote_identifier",
        "hostname",
        "port",
    ]
    assert "autopair" in _params(RemotePairingTunnelService.connect)
    for name in ("connect", "close"):
        assert inspect.iscoroutinefunction(getattr(RemotePairingTunnelService, name))


def test_userspace_tunnel_takes_its_provider_from_the_module_function():
    # transport.PymobiledeviceBackend.wifi swaps this module function for the length
    # of aopen() to hand over the service it found; that only works while
    # _aopen_locked looks the function up by name at call time.
    from pymobiledevice3.remote import userspace_tunnel

    provider = userspace_tunnel._create_no_root_tunnel_provider
    assert inspect.iscoroutinefunction(provider)
    assert {"serial", "autopair", "remotepairing_fallback"} <= _params(provider)
    tunnel = userspace_tunnel.UserspaceRsdTunnel
    assert {"serial", "autopair"} <= _params(tunnel)
    assert "_create_no_root_tunnel_provider" in tunnel._aopen_locked.__code__.co_names
    for name in ("aopen", "aclose"):
        assert inspect.iscoroutinefunction(getattr(tunnel, name))


def test_exceptions():
    from pymobiledevice3 import exceptions

    for name in (
        "ConnectionFailedToUsbmuxdError",
        "DeviceNotFoundError",
        "NoDeviceConnectedError",
        "PasswordRequiredError",
        "PairingDialogResponsePendingError",
        "UserDeniedPairingError",
    ):
        assert issubclass(getattr(exceptions, name), Exception)
