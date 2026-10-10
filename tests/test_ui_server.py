"""The browser UI's HTTP API, run against fake phones. Nothing talks to a device."""

from __future__ import annotations

import asyncio
import json
import time
from copy import deepcopy

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx2")

from starlette.testclient import TestClient

import samples
from fakes import FakeSpringBoard
from ios_homescreen.state import load_plist, same_layout
from ios_homescreen.transport import TransportError
from ios_homescreen.ui.app import create_app
from ios_homescreen.ui.session import MemoryIcons, Session, Settings
from ios_homescreen.workflow import Timing

TOKEN = "test-token-0123456789abcdef"
PORT = 48765
ORIGIN = f"http://127.0.0.1:{PORT}"
FAST = Timing(read_timeout=2, write_timeout=1, verify_attempts=2, verify_interval=0)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def phone(**kwargs) -> FakeSpringBoard:
    return FakeSpringBoard(samples.home_screen(), samples.installed_apps(), **kwargs)


def make_session(tmp_path, device, *, demo=False, icons=None) -> Session:
    async def opener(emit):
        if isinstance(device, Exception):
            raise device
        return device

    settings = Settings(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "data" / "backups",
        timing=FAST,
        demo=demo,
    )
    return Session(settings, opener=opener, icons=icons or MemoryIcons())


class Api:
    """A logged-in browser: session cookie plus the token header and our Origin."""

    def __init__(self, client: TestClient):
        self.client = client
        client.cookies.set(f"ihs_{PORT}", TOKEN)
        self.headers = {"X-IHS-Token": TOKEN, "Origin": ORIGIN}

    def get(self, path, **kwargs):
        return self.client.get(path, headers={**self.headers, **kwargs.pop("headers", {})})

    def post(self, path, body=None, **kwargs):
        return self.client.post(
            path, json=body or {}, headers={**self.headers, **kwargs.pop("headers", {})}
        )

    def wait(self, timeout=10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get("/api/job").json()["job"]
            if job and job["state"] != "running":
                return job
            time.sleep(0.02)
        raise AssertionError("the job did not finish")

    def read(self) -> dict:
        assert self.post("/api/read").status_code == 202
        assert self.wait()["state"] == "done"
        return self.get("/api/state").json()


@pytest.fixture
def make_api(tmp_path):
    clients = []

    def build(device=None, **kwargs):
        session = make_session(tmp_path, device if device is not None else phone(), **kwargs)
        client = TestClient(create_app(session, token=TOKEN, port=PORT), base_url=ORIGIN)
        client.__enter__()
        clients.append(client)
        api = Api(client)
        api.session = session
        return api

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def layout_of(view: dict) -> dict:
    return {"dock": view["dock"], "pages": [{"items": p["items"]} for p in view["pages"]]}


def find(items, ident):
    return next(item for item in items if item["id"] == ident)


# ------------------------------------------------------------------ security


def test_the_page_needs_the_token_once_then_a_cookie(make_api):
    api = make_api()
    client = api.client
    client.cookies.clear()

    assert client.get("/").status_code == 403
    assert client.get("/?token=wrong").status_code == 403
    entry = client.get(f"/?token={TOKEN}", follow_redirects=False)

    assert entry.status_code == 303
    assert entry.headers["location"] == "/"
    cookie = entry.headers["set-cookie"]
    assert f"ihs_{PORT}={TOKEN}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    page = client.get("/")
    assert page.status_code == 200
    assert f'<meta name="ihs-token" content="{TOKEN}"' in page.text
    assert "script-src 'self' 'sha256-" in page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"


def test_api_calls_need_the_cookie_and_the_token_header(make_api):
    api = make_api()

    assert api.get("/api/state").status_code == 200
    no_header = api.client.get("/api/state")
    assert (no_header.status_code, no_header.json()["code"]) == (403, "no_token")
    api.client.cookies.clear()
    no_cookie = api.get("/api/state")
    assert (no_cookie.status_code, no_cookie.json()["code"]) == (403, "no_session")


@pytest.mark.parametrize("host", ["evil.example", f"evil.example:{PORT}", "127.0.0.1:1"])
def test_foreign_host_names_are_refused(make_api, host):
    # DNS rebinding: a foreign name that resolves to 127.0.0.1 must not reach the API.
    api = make_api()

    response = api.get("/api/state", headers={"Host": host})

    assert (response.status_code, response.json()["code"]) == (403, "unknown_host")


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_requests_from_other_sites_are_refused(make_api, site):
    api = make_api()

    for response in (
        api.get("/api/state", headers={"Sec-Fetch-Site": site}),
        api.get("/api/icons/com.apple.Maps", headers={"Sec-Fetch-Site": site}),
        api.client.get("/", headers={"Sec-Fetch-Site": site}),
    ):
        assert response.status_code == 403


@pytest.mark.parametrize("origin", [None, "http://evil.example", f"http://localhost:{PORT + 1}"])
def test_state_changes_need_our_own_origin(make_api, origin):
    api = make_api()
    headers = {"X-IHS-Token": TOKEN}
    if origin:
        headers["Origin"] = origin

    response = api.client.post("/api/read", json={}, headers=headers)

    assert (response.status_code, response.json()["code"]) == (403, "bad_origin")
    assert api.session.job is None


def test_icons_need_the_cookie_but_not_the_header(make_api):
    icons = MemoryIcons()
    icons.put("com.apple.Maps", PNG)
    api = make_api(icons=icons)

    image = api.client.get("/api/icons/com.apple.Maps")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cross-origin-resource-policy"] == "same-origin"
    again = api.client.get(
        "/api/icons/com.apple.Maps", headers={"If-None-Match": image.headers["etag"]}
    )
    assert again.status_code == 304
    api.client.cookies.clear()
    assert api.client.get("/api/icons/com.apple.Maps").status_code == 403


def test_only_images_are_served_as_icons(make_api):
    icons = MemoryIcons()
    icons.put("com.example.html", b"<html><script>alert(1)</script>")
    icons.put("com.example.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    api = make_api(icons=icons)

    assert api.get("/api/icons/com.example.html").status_code == 404
    # SVG only comes from the generated demo icons, never from a phone.
    assert api.get("/api/icons/com.example.svg").status_code == 404
    assert api.get("/api/icons/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_api_responses_are_not_cached_and_not_embeddable(make_api):
    response = make_api().get("/api/state")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in response.headers


def test_the_server_listens_on_localhost_only():
    from ios_homescreen.ui import _listen

    sock = _listen(0)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


# ------------------------------------------------------------------ reading


def test_read_gives_the_view_the_apps_and_saves_the_read(make_api, tmp_path):
    device = phone()
    api = make_api(device)

    state = api.read()

    view = state["read"]["view"]
    assert view["dock"][0]["id"] == "com.apple.mobilephone"
    assert len(view["pages"]) == 2
    assert {"id": "com.apple.tips", "name": "tips", "type": "System"} in state["read"]["apps"]
    assert state["device"]["name"] == "Test iPhone"
    assert state["connection"]["kind"] == "demo" or state["connection"]["label"]
    assert state["error"] is None
    saved = sorted((tmp_path / "data" / "pulls").glob("pull-*.plist"))
    assert len(saved) == 1
    assert load_plist(saved[0])["state"] == samples.home_screen()
    assert device.closed


def test_icons_are_fetched_after_a_read(make_api):
    class WithPng(FakeSpringBoard):
        async def icons(self, identifiers):
            return {ident: PNG if ident == "com.apple.Maps" else None for ident in identifiers}

    api = make_api(WithPng(samples.home_screen(), samples.installed_apps()))
    api.read()
    deadline = time.monotonic() + 5
    while api.get("/api/icons").json()["pending"] and time.monotonic() < deadline:
        time.sleep(0.02)

    assert "com.apple.Maps" in api.get("/api/icons").json()["available"]
    assert api.get("/api/icons/com.apple.Maps").content == PNG


def test_hidden_system_services_are_not_shown_or_fetched(make_api):
    installed = samples.installed_apps()
    installed["com.apple.AirDropUI"] = {"name": "AirDropUI", "type": "System", "hidden": True}

    class Asked(FakeSpringBoard):
        def __init__(self, *args):
            super().__init__(*args)
            self.asked = []

        async def icons(self, identifiers):
            self.asked.extend(identifiers)
            return await super().icons(identifiers)

    device = Asked(samples.home_screen(), installed)
    api = make_api(device)

    state = api.read()
    deadline = time.monotonic() + 5
    while api.get("/api/icons").json()["pending"] and time.monotonic() < deadline:
        time.sleep(0.02)

    assert "com.apple.AirDropUI" not in {app["id"] for app in state["read"]["apps"]}
    assert "com.apple.AirDropUI" not in {app["id"] for app in state["read"]["view"]["library"]}
    assert "com.apple.AirDropUI" not in device.asked
    assert "com.apple.tips" in device.asked


def test_a_missing_phone_becomes_a_friendly_state(make_api):
    api = make_api(TransportError("no iPhone found over USB", code="no_usb_device"))

    api.post("/api/read")
    job = api.wait()
    state = api.get("/api/state").json()

    assert job["state"] == "failed"
    assert state["read"] is None
    assert state["error"]["code"] == "no_usb_device"
    assert state["error"]["title"] == "No iPhone found over USB"
    assert any("Trust This Computer" in step for step in state["error"]["steps"])
    assert "Traceback" not in json.dumps(state)


def test_only_one_job_at_a_time(make_api):
    class Slow(FakeSpringBoard):
        async def read_state(self):
            await asyncio.sleep(0.3)
            return await super().read_state()

    api = make_api(Slow(samples.home_screen(), samples.installed_apps()))

    assert api.post("/api/read").status_code == 202
    busy = api.post("/api/read")
    assert (busy.status_code, busy.json()["code"]) == (409, "busy")
    api.wait()


def test_job_events_stream_as_ndjson(make_api):
    api = make_api()
    api.read()

    response = api.get("/api/job/events?since=0")
    lines = [json.loads(line) for line in response.text.splitlines()]

    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [line["seq"] for line in lines[:-1]] == list(range(1, len(lines)))
    assert lines[0]["event"]["code"] == "reading"
    assert lines[-1]["done"] is True
    assert lines[-1]["job"]["state"] == "done"


# ------------------------------------------------------------------ planning


def test_plan_lists_changes_and_problems_with_codes(make_api):
    api = make_api()
    view = api.read()["read"]["view"]
    layout = layout_of(view)
    camera = layout["dock"].pop()
    layout["pages"][1]["items"].append(camera)

    result = api.post("/api/plan", {"layout": layout}).json()

    assert result["ok"]
    assert result["dirty"]
    assert [(c["kind"], c["id"]) for c in result["changes"]] == [("moved", "com.apple.camera")]
    assert result["changes"][0]["to"] == {"section": "page", "page": 2, "index": 10}

    layout["dock"] += [camera, view["pages"][0]["items"][1]]
    issues = api.post("/api/plan", {"layout": layout}).json()["issues"]
    codes = [issue["code"] for issue in issues]
    assert "dock_full" in codes
    assert "duplicate_item" in codes


def test_unchanged_layout_is_not_dirty(make_api):
    api = make_api()
    view = api.read()["read"]["view"]

    result = api.post("/api/plan", {"layout": layout_of(view)}).json()

    assert result == {
        "ok": True,
        "issues": [],
        "changes": [],
        "summary": result["summary"],
        "dirty": False,
    }


def test_removing_a_widget_needs_the_users_confirmation(make_api):
    api = make_api()
    layout = layout_of(api.read()["read"]["view"])
    layout["pages"][1]["items"] = [
        i for i in layout["pages"][1]["items"] if i["id"] != samples.LIGHTS_A
    ]

    refused = api.post("/api/plan", {"layout": layout}).json()
    allowed = api.post("/api/plan", {"layout": layout, "remove": [samples.LIGHTS_A]}).json()

    assert [i["code"] for i in refused["issues"]] == ["removal_not_allowed"]
    assert refused["issues"][0]["details"] == {"ids": [samples.LIGHTS_A]}
    assert allowed["ok"]
    assert allowed["summary"]["removed"] == [samples.LIGHTS_A]
    assert [c["kind"] for c in allowed["changes"]] == ["removed"]


def test_web_clips_cannot_be_removed_from_the_ui_either(make_api):
    api = make_api()
    layout = layout_of(api.read()["read"]["view"])
    layout["pages"][0]["items"] = [
        i for i in layout["pages"][0]["items"] if i["id"] != samples.STATUS_CLIP
    ]

    result = api.post("/api/plan", {"layout": layout, "remove": [samples.STATUS_CLIP]}).json()

    assert [i["code"] for i in result["issues"]] == ["not_removable"]
    assert result["issues"][0]["details"]["name"] == "Status"


def test_empty_pages_are_dropped_and_issues_keep_the_editors_page_numbers(make_api):
    api = make_api()
    view = api.read()["read"]["view"]
    layout = layout_of(view)
    layout["pages"].insert(1, {"items": []})  # editor page 2 is empty
    extra = [
        {"type": "app", "id": a["id"]}
        for a in view["library"]
        if a["id"].startswith("com.example.app")
    ][:7]
    layout["pages"][2]["items"] += extra  # editor page 3: 18 + 7 = 25 cells

    result = api.post("/api/plan", {"layout": layout}).json()

    (issue,) = result["issues"]
    assert issue["code"] == "page_full"
    assert issue["location"]["page"] == 3


def test_bad_requests_are_rejected_cleanly(make_api):
    api = make_api()
    api.read()

    assert api.post("/api/plan", {"layout": "nope"}).status_code == 400
    raw = api.client.post(
        "/api/plan",
        content=b"{not json",
        headers={**api.headers, "content-type": "application/json"},
    )
    assert raw.status_code == 400
    form = api.client.post("/api/plan", data={"a": "b"}, headers=api.headers)
    assert form.status_code == 400


# ------------------------------------------------------------------ applying


def edited(view: dict) -> tuple[dict, dict]:
    """A realistic edit: a new folder, an app to the App Library, one from it, a move."""
    layout = layout_of(deepcopy(view))
    page1 = layout["pages"][0]["items"]
    maps = find(page1, "com.apple.Maps")
    clock = find(page1, "com.apple.mobiletimer")
    page1[page1.index(maps)] = {
        "type": "folder",
        "id": "new-folder-1",
        "name": "Getting around",
        "pages": [[maps, clock]],
    }
    page1.remove(clock)
    page1.remove(find(page1, "com.apple.mobilenotes"))  # to the App Library
    library = view["library"][0]
    layout["pages"][1]["items"].append({"type": "app", "id": library["id"], "name": "x"})
    layout["dock"].reverse()
    return layout, library


def test_an_edit_applies_verifies_and_becomes_the_new_baseline(make_api, tmp_path):
    device = phone()
    api = make_api(device)
    view = api.read()["read"]["view"]
    layout, library = edited(view)

    check = api.post("/api/plan", {"layout": layout}).json()
    assert check["ok"]
    kinds = {c["kind"] for c in check["changes"]}
    assert {"folder_created", "moved", "to_library", "added", "reordered"} <= kinds
    assert check["summary"]["to_library"] == ["com.apple.mobilenotes"]
    assert check["summary"]["to_home_screen"] == [library["id"]]

    assert api.post("/api/apply", {"layout": layout}).status_code == 202
    job = api.wait()

    assert job["state"] == "done"
    assert job["result"]["status"] == "applied"
    assert job["result"]["backup_name"].startswith("backup-")
    codes = [e["code"] for e in job["events"]]
    assert codes[0] == "reading"
    assert "verified" in codes
    written = device.writes[-1]
    assert "com.apple.mobilenotes" in written["ignored"]
    folder = next(i for i in written["iconLists"][0] if i.get("displayName") == "Getting around")
    assert folder["listType"] == "folder"
    assert folder["displayName"] == "Getting around"
    # The phone now has the new layout and the UI starts from it.
    new_view = api.get("/api/state").json()["read"]["view"]
    assert api.post("/api/plan", {"layout": layout_of(new_view)}).json()["dirty"] is False
    assert [i["id"] for i in new_view["dock"]] == [i["id"] for i in layout["dock"]]
    assert not (tmp_path / "data" / "plans").exists()
    (backup,) = api.get("/api/backups").json()["backups"]
    assert backup["device"]["name"] == "Test iPhone"
    # A layout exported now names the pull the editor made after the write.
    toml = api.post("/api/export", {"layout": layout_of(new_view)}).json()["toml"]
    newest = max(p.name for p in (tmp_path / "data" / "pulls").glob("pull-*.plist"))
    assert f'[pull]\nsnapshot = "{newest}"' in toml


def test_a_write_the_phone_ignores_is_rolled_back(make_api):
    device = phone(ignore_writes=True)
    api = make_api(device)
    layout, _ = edited(api.read()["read"]["view"])

    api.post("/api/apply", {"layout": layout})
    job = api.wait()

    assert job["result"]["status"] == "rolled-back"
    assert job["result"]["rollback_verified"] is True
    assert same_layout(asyncio.run(device.read_state()), samples.home_screen())


def test_apply_refuses_when_the_phone_changed_since_the_read(make_api):
    device = phone()
    api = make_api(device)
    layout, _ = edited(api.read()["read"]["view"])
    device._state[1].reverse()  # someone rearranged page 1 on the phone

    api.post("/api/apply", {"layout": layout})
    refused = api.wait()
    api.post("/api/apply", {"layout": layout, "force": True})
    forced = api.wait()

    assert refused["state"] == "failed"
    assert refused["error"]["code"] == "layout_changed"
    assert forced["result"]["status"] == "applied"


def test_apply_with_problems_is_refused_before_anything_runs(make_api):
    device = phone()
    api = make_api(device)
    view = api.read()["read"]["view"]
    layout = layout_of(view)
    layout["dock"].append(view["library"][0])
    reads_before = device.reads

    response = api.post("/api/apply", {"layout": layout})

    assert response.status_code == 422
    assert response.json()["issues"][0]["code"] == "dock_full"
    assert device.reads == reads_before
    assert device.writes == []


def test_nothing_can_be_planned_before_a_read(make_api):
    api = make_api()

    response = api.post("/api/plan", {"layout": {"dock": [], "pages": []}})

    assert (response.status_code, response.json()["code"]) == (409, "no_read")


# ------------------------------------------------------------------ files and backups


def test_export_and_import_round_trip(make_api):
    api = make_api()
    view = api.read()["read"]["view"]
    layout, _ = edited(view)

    toml = api.post("/api/export", {"layout": layout}).json()["toml"]
    imported = api.post("/api/import", {"toml": toml}).json()

    assert toml.startswith("# ios-homescreen layout")
    assert 'name = "Getting around"' in toml
    assert imported["removed"] == []
    again = api.post("/api/plan", {"layout": layout_of_pages(imported["view"])}).json()
    first = api.post("/api/plan", {"layout": layout}).json()
    assert again["summary"] == first["summary"]
    # Existing folders keep their ids, so the change list does not see them as new.
    utilities = find(imported["view"]["pages"][0]["items"], "folder-1")
    assert utilities["name"] == "Utilities"


def layout_of_pages(view: dict) -> dict:
    return {"dock": view["dock"], "pages": [{"items": p["items"]} for p in view["pages"]]}


def test_import_reports_problems_and_removals(make_api):
    api = make_api()
    api.read()

    bad = api.post("/api/import", {"toml": '[[pages]]\nitems = ["Nope"]\n'})
    broken = api.post("/api/import", {"toml": "[dock\n"})
    export = api.post("/api/export", {"layout": layout_of(api.session.view)}).json()["toml"]
    without_widget = export.replace(f'{{ type = "widget", id = "{samples.LIGHTS_A}" }},', "")
    removed = api.post("/api/import", {"toml": without_widget}).json()["removed"]

    assert bad.status_code == 422
    assert bad.json()["issues"][0]["code"] == "unknown_app"
    assert broken.json()["issues"][0]["code"] == "invalid_toml"
    assert removed == [{"id": samples.LIGHTS_A, "name": "Lights widget"}]


def test_backups_are_listed_and_restored(make_api):
    device = phone()
    api = make_api(device)
    layout, _ = edited(api.read()["read"]["view"])
    api.post("/api/apply", {"layout": layout})
    api.wait()

    (backup,) = api.get("/api/backups").json()["backups"]
    assert backup["summary"] == {"dock": 4, "pages": 2, "items": 33}
    assert api.post("/api/backups/restore", {"name": backup["name"]}).status_code == 202
    job = api.wait()

    assert job["result"]["status"] == "applied"
    assert same_layout(asyncio.run(device.read_state()), samples.home_screen())


@pytest.mark.parametrize("name", ["../x.plist", "/etc/passwd", ".hidden.plist", "nope.plist", ""])
def test_restore_only_takes_backups_from_the_backup_directory(make_api, name):
    api = make_api()
    api.read()

    response = api.post("/api/backups/restore", {"name": name})

    assert response.status_code == 400
    assert api.session.job.kind == "read"


# ------------------------------------------------------------------ Wi-Fi


def test_the_editor_looks_longer_when_the_phone_does_not_answer_at_first(tmp_path):
    from fakes import FakeWifiBackend
    from ios_homescreen.transport import RemoteRecord, Transport

    class Sleepy(FakeWifiBackend):
        async def wifi(self, udid, discovery_timeout):
            if not any(call[0] == "wifi" for call in self.calls):
                self.calls.append(("wifi", udid, discovery_timeout))
                raise TransportError("the iPhone did not answer", code="not_advertising")
            return await super().wifi(udid, discovery_timeout)

    backend = Sleepy([RemoteRecord("UDID-1", tmp_path / "remote_UDID-1.plist", True)])
    session = Session(
        Settings(data_dir=tmp_path, backup_dir=tmp_path / "b", transport=Transport(wifi=True)),
        backend=backend,
    )
    events = []

    device = asyncio.run(session._connect(events.append))

    assert [call[2] for call in backend.calls] == [5.0, 12.0]
    assert "retrying" in [event.code for event in events]
    assert device.transport == "wifi"


def test_usb_failures_are_not_retried(tmp_path):
    from fakes import FakeWifiBackend
    from ios_homescreen.transport import Transport

    class Unplugged(FakeWifiBackend):
        async def usb(self, udid, pair_timeout):
            self.calls.append(("usb", udid))
            raise TransportError("no iPhone found over USB", code="no_usb_device")

    backend = Unplugged()
    session = Session(
        Settings(data_dir=tmp_path, backup_dir=tmp_path / "b", transport=Transport()),
        backend=backend,
    )

    with pytest.raises(TransportError):
        asyncio.run(session._connect(lambda event: None))
    assert backend.calls == [("usb", None)]
