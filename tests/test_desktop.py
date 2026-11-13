from __future__ import annotations

import asyncio
import http.cookiejar
import threading
import urllib.request

import pytest

import samples
from fakes import FakeSpringBoard
from ios_homescreen.transport import Transport, TransportError
from ios_homescreen.ui import Options, serve
from ios_homescreen.ui import session as session_module
from ios_homescreen.ui.session import Session, Settings
from ios_homescreen.workflow import Timing


def _session(tmp_path, monkeypatch, outcomes):
    """A desktop-app session whose connect() answers from ``outcomes`` by transport."""
    tried = []

    async def connect(transport, on_event=None, backend=None):
        kind = "wifi" if transport.wifi else "usb"
        tried.append(kind)
        result = outcomes[kind]
        if isinstance(result, Exception):
            raise result
        return FakeSpringBoard(samples.home_screen(), samples.installed_apps())

    monkeypatch.setattr(session_module.api, "connect", connect)
    session = Session(Settings(data_dir=tmp_path, backup_dir=tmp_path / "b", auto=True))
    return session, tried


def test_the_app_uses_usb_when_a_cable_is_in(tmp_path, monkeypatch):
    session, tried = _session(tmp_path, monkeypatch, {"usb": "ok", "wifi": "ok"})

    asyncio.run(session._connect(lambda event: None))

    assert tried == ["usb"]
    assert session.connection()["kind"] == "usb"


def test_without_a_cable_the_app_looks_on_the_network(tmp_path, monkeypatch):
    absent = TransportError("none", code="no_usb_device")
    session, tried = _session(tmp_path, monkeypatch, {"usb": absent, "wifi": "ok"})

    asyncio.run(session._connect(lambda event: None))

    assert tried == ["usb", "wifi"]
    assert session.connection()["kind"] == "wifi"


def test_no_phone_anywhere_is_one_clear_error(tmp_path, monkeypatch):
    session, _ = _session(
        tmp_path,
        monkeypatch,
        {
            "usb": TransportError("none", code="no_usb_device"),
            "wifi": TransportError("quiet", code="not_advertising"),
        },
    )

    with pytest.raises(TransportError) as error:
        asyncio.run(session._connect(lambda event: None))

    assert error.value.code == "no_device"


def test_a_real_usb_problem_is_not_hidden_behind_wifi(tmp_path, monkeypatch):
    untrusted = TransportError("trust it", code="not_trusted")
    session, tried = _session(tmp_path, monkeypatch, {"usb": untrusted, "wifi": "ok"})

    with pytest.raises(TransportError) as error:
        asyncio.run(session._connect(lambda event: None))

    assert error.value.code == "not_trusted"
    assert tried == ["usb"]


def test_the_server_reports_its_address_and_stops_when_asked(tmp_path):
    options = Options(
        transport=Transport(),
        data_dir=tmp_path,
        backup_dir=tmp_path / "b",
        timing=Timing(),
        open_browser=False,
        demo=True,
    )
    started = threading.Event()
    found = {}

    def on_started(url, stop):
        found.update(url=url, stop=stop)
        started.set()

    thread = threading.Thread(
        target=serve,
        args=(options,),
        kwargs={"say": lambda _: None, "on_started": on_started},
        daemon=True,  # a failing test must not leave pytest waiting for the server
    )
    thread.start()
    assert started.wait(10)
    # The address carries a one-time token that the server swaps for a cookie.
    browser = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    with browser.open(found["url"], timeout=5) as page:
        assert page.status == 200

    found["stop"]()
    thread.join(10)

    assert not thread.is_alive()
