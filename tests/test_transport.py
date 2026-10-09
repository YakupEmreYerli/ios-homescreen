"""USB and Wi-Fi connection logic, with fakes. Nothing here touches a network or usbmuxd."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from fakes import FakeWifiBackend
from ios_homescreen.transport import (
    PymobiledeviceBackend,
    RemoteRecord,
    Transport,
    TransportError,
    connect,
    pick_record,
)

UDID_A = "00008120-000A1B2C3D4E5F60"
UDID_B = "00008030-0011223344556677"


def run(coro):
    return asyncio.run(coro)


def record(udid: str = UDID_A, usable: bool = True) -> RemoteRecord:
    return RemoteRecord(udid, Path(f"/records/remote_{udid}.plist"), usable)


def test_usb_is_the_default_and_never_looks_at_the_network():
    backend = FakeWifiBackend([record()])
    events = []

    link = run(connect(Transport(), backend=backend, on_event=events.append))

    assert link.kind == "usb"
    assert backend.calls == [("usb", None)]
    assert [e.code for e in events] == ["connecting"]
    run(link.close())
    assert link.provider.closed


def test_usb_connection_has_a_time_limit():
    class Slow(FakeWifiBackend):
        async def usb(self, udid, pair_timeout):
            await asyncio.sleep(1)

    with pytest.raises(TransportError) as error:
        run(connect(Transport(connect_timeout=0.01), backend=Slow()))

    assert error.value.code == "timeout"


def test_unexpected_usb_failures_become_connection_errors():
    class Broken(FakeWifiBackend):
        async def usb(self, udid, pair_timeout):
            raise OSError("cable")

    with pytest.raises(TransportError, match="cable") as error:
        run(connect(Transport(), backend=Broken()))

    assert error.value.code == "connection_failed"


def test_wifi_opens_the_tunnel_for_the_paired_phone():
    backend = FakeWifiBackend([record()])
    events = []

    link = run(
        connect(Transport(wifi=True, discovery_timeout=2), backend=backend, on_event=events.append)
    )

    assert (link.kind, link.address) == ("wifi", "192.0.2.7")
    assert backend.calls == [("wifi", UDID_A, 2)]
    assert [e.code for e in events] == ["discovering", "connected"]
    run(link.close())
    assert backend.closed == 1


def test_wifi_without_a_pairing_explains_the_one_time_setup():
    backend = FakeWifiBackend([])

    with pytest.raises(TransportError, match="wifi enable") as error:
        run(connect(Transport(wifi=True), backend=backend))

    assert error.value.code == "no_pair_record"
    assert backend.calls == []


def test_wifi_with_several_pairings_needs_a_udid():
    backend = FakeWifiBackend([record(UDID_A), record(UDID_B)])

    with pytest.raises(TransportError, match="--udid") as error:
        run(connect(Transport(wifi=True), backend=backend))
    assert error.value.code == "several_pair_records"

    run(connect(Transport(wifi=True, udid=UDID_B.lower()), backend=backend))
    assert backend.calls == [("wifi", UDID_B, 5.0)]


def test_old_pairings_without_the_alternate_irk_must_be_made_again():
    with pytest.raises(TransportError, match="wifi enable") as error:
        pick_record([record(usable=False)], None)

    assert error.value.code == "stale_pair_record"


def test_a_silent_phone_is_reported_as_not_answering():
    backend = FakeWifiBackend([record()], answering=False)

    with pytest.raises(TransportError) as error:
        run(connect(Transport(wifi=True), backend=backend))

    assert error.value.code == "not_advertising"


def test_wifi_connection_has_a_time_limit():
    class Slow(FakeWifiBackend):
        async def wifi(self, udid, discovery_timeout):
            await asyncio.sleep(1)

    with pytest.raises(TransportError) as error:
        run(
            connect(
                Transport(wifi=True, discovery_timeout=0.01, connect_timeout=0.01),
                backend=Slow([record()]),
            )
        )

    assert error.value.code == "timeout"


def test_transport_description():
    assert Transport().describe() == "USB"
    assert Transport(wifi=True).describe() == "Wi-Fi"
    assert not Transport().network
    assert Transport(wifi=True).network


# ------------------------------------------------- the pymobiledevice3 backend, faked


@pytest.fixture
def fake_pmd3(monkeypatch):
    """Replace the pymobiledevice3 modules the Wi-Fi backend imports."""
    state = types.SimpleNamespace(services=[], opened=[], provider_seen=None, fail=False)

    class Service:
        def __init__(self, host):
            self.hostname = host
            self.closed = False

        async def close(self):
            self.closed = True

    async def get_remote_pairing_tunnel_services(bonjour_timeout, udid):
        state.lookup = (bonjour_timeout, udid)
        return state.services

    async def original_provider(serial, autopair, remotepairing_fallback=True):
        raise AssertionError("the stock provider must not be used")

    userspace = types.ModuleType("pymobiledevice3.remote.userspace_tunnel")
    userspace._create_no_root_tunnel_provider = original_provider

    class Tunnel:
        def __init__(self, serial=None, autopair=True):
            self.serial = serial
            self.closed = False

        async def aopen(self):
            # What UserspaceRsdTunnel._aopen_locked does: ask the module for a provider.
            provider, _lockdown = await userspace._create_no_root_tunnel_provider(
                self.serial, False, True
            )
            state.provider_seen = provider
            if state.fail:
                raise RuntimeError("tunnel failed")
            state.opened.append(self)
            return "rsd"

        async def aclose(self):
            self.closed = True

    userspace.UserspaceRsdTunnel = Tunnel

    class RemotePairingCompletedError(Exception):
        pass

    class LockdownPairing:
        @classmethod
        async def create(cls, lockdown):
            state.pairing = cls()
            state.pairing.lockdown = lockdown
            return state.pairing

        async def connect(self, autopair):
            self.autopair = autopair
            raise RemotePairingCompletedError()

        async def close(self):
            self.closed = True

    tunnel_service = types.ModuleType("pymobiledevice3.remote.tunnel_service")
    tunnel_service.get_remote_pairing_tunnel_services = get_remote_pairing_tunnel_services
    tunnel_service.RemotePairingLockdownService = LockdownPairing
    exceptions = types.ModuleType("pymobiledevice3.exceptions")
    exceptions.RemotePairingCompletedError = RemotePairingCompletedError
    pair_records = types.ModuleType("pymobiledevice3.pair_records")
    pair_records.iter_remote_pair_records_by_identifier = lambda: iter(state.records)
    state.records = []
    remote = types.ModuleType("pymobiledevice3.remote")
    remote.userspace_tunnel = userspace
    remote.tunnel_service = tunnel_service
    package = types.ModuleType("pymobiledevice3")
    package.remote = remote
    for name, module in {
        "pymobiledevice3": package,
        "pymobiledevice3.remote": remote,
        "pymobiledevice3.remote.userspace_tunnel": userspace,
        "pymobiledevice3.remote.tunnel_service": tunnel_service,
        "pymobiledevice3.exceptions": exceptions,
        "pymobiledevice3.pair_records": pair_records,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    state.Service = Service
    state.userspace = userspace
    state.original_provider = original_provider
    return state


def test_backend_tunnels_through_the_service_found_on_the_network(fake_pmd3):
    found, other = fake_pmd3.Service("192.0.2.7"), fake_pmd3.Service("fe80::1")
    fake_pmd3.services = [found, other]

    link = run(PymobiledeviceBackend().wifi(UDID_A, 3))

    assert fake_pmd3.lookup == (3, UDID_A)
    assert fake_pmd3.provider_seen is found
    assert other.closed
    assert not found.closed
    assert (link.provider, link.kind, link.address) == ("rsd", "wifi", "192.0.2.7")
    # The provider hook is only swapped for the length of the call.
    assert fake_pmd3.userspace._create_no_root_tunnel_provider is fake_pmd3.original_provider
    run(link.close())
    assert fake_pmd3.opened[0].closed


def test_backend_restores_the_hook_and_closes_the_service_when_the_tunnel_fails(fake_pmd3):
    found = fake_pmd3.Service("192.0.2.7")
    fake_pmd3.services = [found]
    fake_pmd3.fail = True

    with pytest.raises(RuntimeError, match="tunnel failed"):
        run(PymobiledeviceBackend().wifi(UDID_A, 3))

    assert found.closed
    assert fake_pmd3.userspace._create_no_root_tunnel_provider is fake_pmd3.original_provider


def test_backend_reports_a_phone_that_does_not_advertise(fake_pmd3):
    with pytest.raises(TransportError) as error:
        run(PymobiledeviceBackend().wifi(UDID_A, 3))

    assert error.value.code == "not_advertising"
    assert run(PymobiledeviceBackend().reachable(UDID_A, 3)) is None


def test_backend_reachable_closes_what_it_opened(fake_pmd3):
    found = fake_pmd3.Service("192.0.2.7")
    fake_pmd3.services = [found]

    assert run(PymobiledeviceBackend().reachable(UDID_A, 3)) == "192.0.2.7"
    assert found.closed


def test_backend_pairs_over_usb_and_takes_the_completed_signal_as_success(fake_pmd3):
    lockdown = object()

    run(PymobiledeviceBackend().pair_remote(lockdown))

    assert fake_pmd3.pairing.lockdown is lockdown
    assert fake_pmd3.pairing.autopair is True
    assert fake_pmd3.pairing.closed


def test_backend_lists_remote_pairings_and_flags_old_ones(fake_pmd3):
    fake_pmd3.records = [
        (UDID_A, Path("/r/remote_a.plist"), {"peer_alt_irk": b"irk", "private_key": b"k"}),
        (UDID_B, Path("/r/remote_b.plist"), {"private_key": b"k"}),
    ]

    assert PymobiledeviceBackend().remote_records() == [
        RemoteRecord(UDID_A, Path("/r/remote_a.plist"), True),
        RemoteRecord(UDID_B, Path("/r/remote_b.plist"), False),
    ]
