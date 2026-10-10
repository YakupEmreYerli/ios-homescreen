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

    with pytest.raises(TransportError, match="wifi setup") as error:
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
    with pytest.raises(TransportError, match="wifi setup") as error:
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
    state = types.SimpleNamespace(
        services=[], opened=[], provider_seen=None, fail=False, direct=[], direct_fails=False
    )

    class Service:
        def __init__(self, host, port=49152):
            self.hostname = host
            self.port = port
            self.closed = False

        async def close(self):
            self.closed = True

    class RemotePairingTunnelService(Service):
        """A connection straight to a remembered address."""

        def __init__(self, identifier, hostname, port):
            super().__init__(hostname, port)
            self.identifier = identifier

        async def connect(self, autopair):
            state.direct.append((self.hostname, self.port, autopair))
            if state.direct_fails:
                raise ConnectionRefusedError("nothing listens there")

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
    tunnel_service.RemotePairingTunnelService = RemotePairingTunnelService
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

    window, udid = fake_pmd3.lookup
    assert udid == UDID_A
    assert 0 < window <= 3
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


def test_the_marketing_name_comes_from_the_wifi_handshake():
    from types import SimpleNamespace

    from ios_homescreen.transport import marketing_name

    tunnel = SimpleNamespace(
        handshake_info={"peerDeviceInfo": {"model": "iPhone15,4", "marketing-name": "iPhone 15"}}
    )
    key_value_data = SimpleNamespace(
        handshake_info={"peerDeviceInfo": {"model": "iPhone17,5"}},
        auxiliary_metadata={"NULL": {"marketing-name": "iPhone 16e"}},
    )
    session = SimpleNamespace(peer_info={"Properties": {"MarketingName": "iPhone Air"}})

    class Unfinished:
        @property
        def auxiliary_metadata(self):
            raise AssertionError("no handshake yet")

    assert marketing_name(tunnel, object()) == "iPhone 15"
    assert marketing_name(key_value_data, None) == "iPhone 16e"
    assert marketing_name(object(), session) == "iPhone Air"
    assert marketing_name(Unfinished(), None) is None


# ------------------------------------------------------------------ finding the phone


class Found:
    """A RemotePairing service, as the browse or a direct connection returns it."""

    def __init__(self, how, host="192.168.1.124", port=49152):
        self.how = how
        self.hostname = host
        self.port = port
        self.closed = False

    async def close(self):
        self.closed = True


def locate_with(*, browse, direct, known=None, timeout=1.0, direct_timeout=0.5):
    from ios_homescreen.transport import locate

    return run(
        locate(timeout, browse=browse, direct=direct, known=known, direct_timeout=direct_timeout)
    )


def test_the_remembered_address_wins_while_bonjour_is_silent():
    from ios_homescreen.transport import KnownAddress

    browses = []

    async def browse(window):
        browses.append(window)
        await asyncio.sleep(window)  # mDNS says nothing
        return None

    async def direct(address, port):
        return Found("direct", address, port)

    found = locate_with(
        browse=browse, direct=direct, known=KnownAddress(("192.168.1.124",), 49152), timeout=5
    )

    assert (found.how, found.hostname, found.port) == ("direct", "192.168.1.124", 49152)
    assert len(browses) == 1  # stopped as soon as the direct try answered


def test_a_stale_address_falls_back_to_the_browse():
    from ios_homescreen.transport import KnownAddress

    async def browse(window):
        await asyncio.sleep(0.05)
        return Found("browse", "192.168.1.130")

    async def direct(address, port):
        await asyncio.sleep(10)  # the old address does not answer at all

    found = locate_with(browse=browse, direct=direct, known=KnownAddress(("192.168.1.124",), 49152))

    assert (found.how, found.hostname) == ("browse", "192.168.1.130")


def test_the_browse_is_tried_again_within_the_time_limit():
    windows = []

    async def browse(window):
        windows.append(window)
        return Found("browse") if len(windows) == 2 else None

    async def direct(address, port):
        raise AssertionError("nothing is remembered")

    found = locate_with(browse=browse, direct=direct, timeout=2.0)

    assert found.how == "browse"
    assert len(windows) == 2
    # Half the time for the first try; the second gets what is left of the limit.
    assert windows[0] == pytest.approx(1.0, abs=0.05)
    assert windows[1] <= 2.0


def test_when_both_answer_the_other_connection_is_closed():
    from ios_homescreen.transport import KnownAddress

    opened = []

    # Neither waits, so both have connected by the time the first result is looked at.
    async def browse(window):
        opened.append(Found("browse"))
        return opened[-1]

    async def direct(address, port):
        opened.append(Found("direct", address, port))
        return opened[-1]

    found = locate_with(browse=browse, direct=direct, known=KnownAddress(("192.168.1.124",), 1))

    assert len(opened) == 2
    assert [x.closed for x in opened if x is not found] == [True]
    assert found.closed is False


def test_when_nothing_answers_there_is_nothing_found():
    from ios_homescreen.transport import KnownAddress

    async def browse(window):
        return None

    async def direct(address, port):
        raise ConnectionRefusedError()

    assert locate_with(browse=browse, direct=direct, known=KnownAddress(("192.0.2.1",), 1)) is None


def test_the_backend_remembers_where_the_phone_answered_and_goes_there_next(fake_pmd3, tmp_path):
    from ios_homescreen.transport import AddressMemory

    memory = AddressMemory(tmp_path / "wifi.json")
    fake_pmd3.services = [fake_pmd3.Service("192.168.1.124", 49152)]
    run(run(PymobiledeviceBackend(memory).wifi(UDID_A, 1)).close())

    assert memory.get(UDID_A).addresses == ("192.168.1.124",)
    fake_pmd3.services = []  # Bonjour goes quiet
    link = run(PymobiledeviceBackend(memory).wifi(UDID_A, 1))

    assert link.address == "192.168.1.124"
    assert fake_pmd3.direct == [("192.168.1.124", 49152, False)]  # never starts pairing


def test_a_phone_found_nowhere_is_a_clear_error(fake_pmd3, tmp_path):
    from ios_homescreen.transport import AddressMemory

    memory = AddressMemory(tmp_path / "wifi.json")
    memory.remember(UDID_A, "192.168.1.124", 49152)
    fake_pmd3.direct_fails = True

    with pytest.raises(TransportError) as error:
        run(PymobiledeviceBackend(memory).wifi(UDID_A, 0.5))

    assert error.value.code == "not_advertising"
    assert "did not answer at 192.168.1.124 either" in str(error.value)
    assert memory.get(UDID_A).addresses == ("192.168.1.124",)  # kept for next time


def test_the_address_memory_keeps_a_few_valid_addresses_per_phone(tmp_path):
    from ios_homescreen.transport import AddressMemory, KnownAddress

    memory = AddressMemory(tmp_path / "wifi.json")
    for host in ("192.168.1.10", "192.168.1.11", "fe80::1%en0", "192.168.1.12", "192.168.1.13"):
        memory.remember(UDID_A, host, 49152)
    memory.remember(UDID_A, "not an address", 49152)
    memory.remember(UDID_B, "10.0.0.2", 0)

    assert memory.get(UDID_A) == KnownAddress(
        ("192.168.1.13", "192.168.1.12", "fe80::1%en0", "192.168.1.11"), 49152
    )
    assert memory.get(UDID_B) is None
    (tmp_path / "wifi.json").write_text("garbage")
    assert memory.get(UDID_A) is None
