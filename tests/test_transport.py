from __future__ import annotations

import asyncio
import os
import plistlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ios_homescreen.transport import (
    Candidate,
    Transport,
    TransportError,
    connect,
    load_pair_records,
    mac_from_instance,
    match_discovered,
    normalize_mac,
    pick_candidate,
    record_for_host,
)

UDID_A = "00008120-000A1B2C3D4E5F60"
UDID_B = "00008030-0011223344556677"
MAC_A = "a0:b1:c2:d3:e4:f5"
MAC_B = "10:20:30:40:50:60"


def write_record(directory: Path, udid: str, mac: str | None) -> Path:
    record = {
        "HostID": "HOST-ID",
        "SystemBUID": "BUID",
        "HostCertificate": b"cert",
        "HostPrivateKey": b"key",
        "DeviceCertificate": b"device",
    }
    if mac:
        record["WiFiMACAddress"] = mac
    path = directory / f"{udid}.plist"
    path.write_bytes(plistlib.dumps(record))
    return path


@pytest.fixture
def records(tmp_path) -> Path:
    write_record(tmp_path, UDID_A, MAC_A)
    write_record(tmp_path, UDID_B, MAC_B)
    (tmp_path / "SystemConfiguration.plist").write_bytes(plistlib.dumps({"SystemBUID": "BUID"}))
    (tmp_path / "remote_ABC.plist").write_bytes(plistlib.dumps({"HostID": "x"}))
    (tmp_path / "broken.plist").write_text("not a plist")
    (tmp_path / "notes.txt").write_text("ignore me")
    return tmp_path


@dataclass
class Address:
    full_ip: str


@dataclass
class Answer:
    instance: str
    addresses: list = field(default_factory=list)


def answer(mac: str, *ips: str) -> Answer:
    return Answer(f"{mac}@fe80::1._apple-mobdev2._tcp.local.", [Address(ip) for ip in ips])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("A0:B1:C2:D3:E4:F5", "a0:b1:c2:d3:e4:f5"),
        ("a0:b:c2:d3:e4:5", "a0:0b:c2:d3:e4:05"),
        ("a0-b1-c2-d3-e4-f5", "a0:b1:c2:d3:e4:f5"),
        ("a0:b1:c2", None),
        ("zz:b1:c2:d3:e4:f5", None),
        ("100:b1:c2:d3:e4:f5", None),
        (None, None),
    ],
)
def test_normalize_mac(value, expected):
    assert normalize_mac(value) == expected


def test_mac_from_instance_reads_the_part_before_the_at_sign():
    assert mac_from_instance("A0:B1:C2:D3:E4:F5@fe80::1._apple-mobdev2._tcp.local.") == MAC_A
    assert mac_from_instance("no-at-sign._apple-mobdev2._tcp.local.") is None


def test_load_pair_records_keeps_device_records_only(records):
    found = load_pair_records(records)

    assert [(r.udid, r.wifi_mac) for r in found] == [(UDID_B, MAC_B), (UDID_A, MAC_A)]
    assert found[0].data["HostID"] == "HOST-ID"


def test_load_pair_records_filters_by_udid_ignoring_case(records):
    found = load_pair_records(records, UDID_A.lower())

    assert [r.udid for r in found] == [UDID_A]


def test_missing_pair_record_directory_is_a_clear_error(tmp_path):
    with pytest.raises(TransportError, match="does not exist") as error:
        load_pair_records(tmp_path / "nope")

    assert error.value.code == "pair_records_missing"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_unreadable_pair_record_directory_is_a_clear_error(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        with pytest.raises(TransportError, match="permission denied") as error:
            load_pair_records(locked)
    finally:
        locked.chmod(0o700)

    assert error.value.code == "pair_records_unreadable"


def test_discovery_matches_answers_to_records_by_wifi_mac(records):
    answers = [
        answer("ff:ff:ff:ff:ff:ff", "192.168.1.99"),  # someone else's phone
        answer("A0:B1:C2:D3:E4:F5", "fe80::1%wlan0", "2001:db8::5"),
        answer(MAC_A, "192.168.1.20", "fe80::1%wlan0"),
    ]

    found = match_discovered(answers, load_pair_records(records))

    assert len(found) == 1
    assert found[0].record.udid == UDID_A
    assert found[0].addresses == ("192.168.1.20", "2001:db8::5", "fe80::1%wlan0")


def test_pick_candidate_explains_every_failure(records):
    transport = Transport(wifi=True, pair_records=records)
    a, b = load_pair_records(records)[1], load_pair_records(records)[0]

    with pytest.raises(TransportError, match="no paired device answered") as error:
        pick_candidate([], 0, transport)
    assert error.value.code == "no_device_found"
    with pytest.raises(TransportError, match="none matches") as error:
        pick_candidate([], 2, transport)
    assert error.value.code == "no_matching_device"
    with pytest.raises(TransportError, match="--udid") as error:
        pick_candidate([Candidate(a, ("1.1.1.1",)), Candidate(b, ("1.1.1.2",))], 2, transport)
    assert error.value.code == "several_devices"
    with pytest.raises(TransportError, match="usable address") as error:
        pick_candidate([Candidate(a, ())], 1, transport)
    assert error.value.code == "no_address"
    assert pick_candidate([Candidate(a, ("1.1.1.1",))], 1, transport).record is a


def test_host_needs_exactly_one_pair_record(records, tmp_path):
    transport = Transport(host="192.168.1.20", pair_records=records)
    all_records = load_pair_records(records)

    with pytest.raises(TransportError, match="several pair records") as error:
        record_for_host(all_records, transport)
    assert error.value.code == "several_pair_records"
    with pytest.raises(TransportError, match="no pair record") as error:
        record_for_host([], transport)
    assert error.value.code == "no_pair_record"
    assert record_for_host(all_records[:1], transport) is all_records[0]


class FakeLockdown:
    def __init__(self, host: str, paired: bool = True):
        self.host = host
        self.paired = paired
        self.closed = False

    async def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self, answers=(), *, failing=(), unpaired=(), usb_hangs=False):
        self.answers = list(answers)
        self.failing = set(failing)
        self.unpaired = set(unpaired)
        self.usb_hangs = usb_hangs
        self.calls: list[tuple] = []
        self.lockdowns: list[FakeLockdown] = []

    async def usb(self, udid, pair_timeout):
        self.calls.append(("usb", udid, pair_timeout))
        if self.usb_hangs:
            await asyncio.Event().wait()
        return FakeLockdown("usb")

    async def tcp(self, host, pair_record):
        self.calls.append(("tcp", host, pair_record["WiFiMACAddress"]))
        if host in self.failing:
            raise ConnectionRefusedError("refused")
        lockdown = FakeLockdown(host, paired=host not in self.unpaired)
        self.lockdowns.append(lockdown)
        return lockdown

    async def browse(self, timeout):
        self.calls.append(("browse", timeout))
        return self.answers


def run(coro):
    return asyncio.run(coro)


def test_usb_is_the_default_and_never_touches_the_network(records):
    backend = FakeBackend()
    events = []

    lockdown = run(
        connect(
            Transport(udid=UDID_A, pair_records=records, connect_timeout=7),
            backend=backend,
            on_event=events.append,
        )
    )

    assert lockdown.host == "usb"
    assert backend.calls == [("usb", UDID_A, 7)]
    assert events[0].code == "connecting"
    assert events[0].data["transport"] == "usb"


def test_usb_connection_has_a_time_limit():
    with pytest.raises(TransportError, match="timed out") as error:
        run(connect(Transport(connect_timeout=0.01), backend=FakeBackend(usb_hangs=True)))

    assert error.value.code == "timeout"


def test_host_connects_directly_with_the_pair_record(records):
    backend = FakeBackend()

    lockdown = run(
        connect(Transport(host="192.168.1.20", udid=UDID_B, pair_records=records), backend=backend)
    )

    assert lockdown.host == "192.168.1.20"
    assert backend.calls == [("tcp", "192.168.1.20", MAC_B)]


def test_wifi_discovers_the_paired_phone_and_tries_its_addresses_in_order(records):
    backend = FakeBackend(
        [answer(MAC_A, "fe80::1%wlan0", "192.168.1.20")], failing={"192.168.1.20"}
    )
    transport = Transport(wifi=True, pair_records=records, discovery_timeout=2)

    lockdown = run(connect(transport, backend=backend))

    assert lockdown.host == "fe80::1%wlan0"
    assert backend.calls == [
        ("browse", 2),
        ("tcp", "192.168.1.20", MAC_A),
        ("tcp", "fe80::1%wlan0", MAC_A),
    ]


def test_wifi_with_udid_ignores_other_paired_phones(records):
    backend = FakeBackend([answer(MAC_A, "192.168.1.20"), answer(MAC_B, "192.168.1.30")])

    lockdown = run(
        connect(Transport(wifi=True, udid=UDID_B, pair_records=records), backend=backend)
    )

    assert lockdown.host == "192.168.1.30"


def test_rejected_pair_record_is_reported_and_the_connection_closed(records):
    backend = FakeBackend(unpaired={"192.168.1.20"})

    with pytest.raises(TransportError, match="did not accept the pair record") as error:
        run(
            connect(
                Transport(host="192.168.1.20", udid=UDID_A, pair_records=records),
                backend=backend,
            )
        )

    assert error.value.code == "not_paired"
    assert backend.lockdowns[0].closed


def test_wifi_without_a_usable_pair_record_fails_before_browsing(tmp_path):
    write_record(tmp_path, UDID_A, None)
    backend = FakeBackend()

    with pytest.raises(TransportError, match="Wi-Fi MAC") as error:
        run(connect(Transport(wifi=True, pair_records=tmp_path), backend=backend))

    assert error.value.code == "no_pair_record"
    assert backend.calls == []


def test_wifi_with_nobody_answering_explains_what_to_check(records):
    with pytest.raises(TransportError, match="same network") as error:
        run(connect(Transport(wifi=True, pair_records=records), backend=FakeBackend([])))

    assert error.value.code == "no_device_found"


def test_transport_description():
    assert Transport().describe() == "USB"
    assert not Transport().network
    assert Transport(wifi=True).network
    assert Transport(host="10.0.0.2").network
    assert Transport(host="10.0.0.2").describe() == "network (10.0.0.2)"
