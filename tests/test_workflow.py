from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

import samples
from fakes import FakeSpringBoard
from ios_homescreen.export import export_layout
from ios_homescreen.planner import plan_layout
from ios_homescreen.state import (
    fingerprint,
    load_plist,
    safe_payload,
    same_layout,
    visible_apps,
)
from ios_homescreen.workflow import (
    APPLIED,
    ROLLBACK_FAILED,
    ROLLED_BACK,
    Timing,
    WorkflowError,
    apply_state,
)

FAST = Timing(read_timeout=1, write_timeout=1, verify_attempts=2, verify_interval=0)


def _installed(*ids: str) -> dict:
    return {i: {"name": i, "type": "System" if i.startswith("com.apple") else "User"} for i in ids}


def _plan_from(start: list, target_pages: list) -> dict:
    return {
        "buttonBar": [],
        "iconLists": target_pages,
        "ignored": [],
        "_ios_homescreen": {"version": 1, "source_fingerprint": fingerprint(start)},
    }


def run(coro):
    return asyncio.run(coro)


def test_list_form_write_reproduces_the_accident_and_the_safe_payload_does_not():
    start = [[], [{"bundleIdentifier": "shown"}]]
    installed = _installed("shown", "archived-1", "com.apple.tips")

    unsafe = FakeSpringBoard(start, installed)
    run(unsafe.write_state(deepcopy(start)))
    assert visible_apps(run(unsafe.read_state())) == {"shown", "archived-1", "com.apple.tips"}

    safe = FakeSpringBoard(start, installed)
    run(safe.write_state(safe_payload(start, installed)))
    assert visible_apps(run(safe.read_state())) == {"shown"}


def test_user_apps_alone_in_ignored_let_stock_apps_come_back():
    start = [[], [{"bundleIdentifier": "shown"}]]
    installed = _installed("shown", "com.example.user", "com.apple.tips")
    device = FakeSpringBoard(start, installed)

    run(
        device.write_state(
            {"buttonBar": [], "iconLists": start[1:], "ignored": ["com.example.user"]}
        )
    )

    assert "com.apple.tips" in visible_apps(run(device.read_state()))


def test_icon_type_folders_vanish_and_list_type_folders_stay():
    old = {"iconType": "folder", "displayName": "Old", "iconLists": [[{"bundleIdentifier": "a"}]]}
    new = {"listType": "folder", "displayName": "New", "iconLists": [[{"bundleIdentifier": "a"}]]}
    device = FakeSpringBoard([[], []], _installed("a"))

    run(device.write_state({"buttonBar": [], "iconLists": [[old, new]], "ignored": []}))

    assert [item["displayName"] for item in run(device.read_state())[1]] == ["New"]


def test_fake_spills_items_beyond_24_cells_onto_a_new_page():
    items = [{"bundleIdentifier": f"a{i}"} for i in range(25)]
    device = FakeSpringBoard([[], []], _installed(*(f"a{i}" for i in range(25))))

    run(device.write_state({"buttonBar": [], "iconLists": [items], "ignored": []}))

    assert [len(page) for page in run(device.read_state())[1:]] == [24, 1]


def test_unanswered_write_does_not_hang_and_is_verified_by_re_reading(tmp_path):
    start = [[], [{"bundleIdentifier": "a"}]]
    plan = _plan_from(start, [[{"bundleIdentifier": "b", "displayIdentifier": "b"}]])
    device = FakeSpringBoard(start, _installed("a", "b"), no_reply=True)

    result = run(
        apply_state(
            device,
            plan,
            backup_dir=tmp_path,
            timing=Timing(write_timeout=0.02, verify_interval=0),
        )
    )

    assert result.status == APPLIED
    assert result.write_unconfirmed
    assert same_layout(run(device.read_state()), plan)


def test_ignored_write_is_rolled_back_and_reported(tmp_path):
    start = [[], [{"bundleIdentifier": "a"}]]
    plan = _plan_from(start, [[{"bundleIdentifier": "b"}]])
    device = FakeSpringBoard(start, _installed("a", "b"), ignore_writes=True)

    result = run(apply_state(device, plan, backup_dir=tmp_path, timing=FAST))

    assert result.status == ROLLED_BACK
    assert result.rollback_verified
    assert len(device.writes) == 2
    assert device.writes[1]["ignored"] == ["b"]
    assert same_layout(run(device.read_state()), start)


def test_failed_re_reads_after_a_write_still_lead_to_rollback(tmp_path):
    class FlakyReads(FakeSpringBoard):
        failures = 0

        async def write_state(self, payload):
            await super().write_state(payload)
            self.failures = 2 if len(self.writes) == 1 else 0

        async def read_state(self):
            if self.failures:
                self.failures -= 1
                raise OSError("temporary read failure")
            return await super().read_state()

    start = [[], [{"bundleIdentifier": "a"}]]
    device = FlakyReads(start, _installed("a", "b"))

    result = run(
        apply_state(
            device,
            _plan_from(start, [[{"bundleIdentifier": "b"}]]),
            backup_dir=tmp_path,
            timing=FAST,
        )
    )

    assert result.status == ROLLED_BACK
    assert len(device.writes) == 2
    assert same_layout(run(device.read_state()), start)


def test_error_after_sending_counts_as_applied_when_the_re_read_matches(tmp_path):
    class FailsAfterSending(FakeSpringBoard):
        async def write_state(self, payload):
            await super().write_state(payload)
            raise OSError("reply connection dropped")

    start = [[], [{"bundleIdentifier": "a"}]]
    device = FailsAfterSending(start, _installed("a", "b"))

    result = run(
        apply_state(
            device,
            _plan_from(start, [[{"bundleIdentifier": "b"}]]),
            backup_dir=tmp_path,
            timing=FAST,
        )
    )

    assert result.status == APPLIED
    assert result.write_unconfirmed


def test_rollback_that_cannot_be_verified_is_reported_and_the_backup_kept(tmp_path):
    class ReadsDieAfterWriting(FakeSpringBoard):
        async def read_state(self):
            if self.writes:
                raise OSError("device gone")
            return await super().read_state()

    start = [[], [{"bundleIdentifier": "a"}]]
    events = []
    device = ReadsDieAfterWriting(start, _installed("a", "b"))

    result = run(
        apply_state(
            device,
            _plan_from(start, [[{"bundleIdentifier": "b"}]]),
            backup_dir=tmp_path,
            timing=FAST,
            on_event=events.append,
        )
    )

    assert result.status == ROLLBACK_FAILED
    assert not result.rollback_verified
    assert load_plist(result.backup)["state"] == start
    assert events[-1].code == "rollback_failed"
    assert events[-1].level == "error"


def test_drifted_device_is_refused_before_writing_but_backed_up(tmp_path):
    start = [[], [{"bundleIdentifier": "a"}]]
    plan = _plan_from([[], [{"bundleIdentifier": "z"}]], [[{"bundleIdentifier": "b"}]])
    device = FakeSpringBoard(start, _installed("a", "b"))

    with pytest.raises(WorkflowError, match="changed since") as error:
        run(apply_state(device, plan, backup_dir=tmp_path, timing=FAST))

    assert error.value.code == "layout_changed"
    assert not device.writes
    assert list(tmp_path.glob("backup-*.plist"))


def test_force_writes_over_a_drifted_device(tmp_path):
    start = [[], [{"bundleIdentifier": "a"}]]
    plan = _plan_from([[], [{"bundleIdentifier": "z"}]], [[{"bundleIdentifier": "b"}]])
    device = FakeSpringBoard(start, _installed("a", "b"))

    result = run(apply_state(device, plan, backup_dir=tmp_path, force=True, timing=FAST))

    assert result.status == APPLIED


def test_full_home_screen_export_plan_apply_read_is_identical(tmp_path):
    read = samples.read_snapshot()
    plan = plan_layout(export_layout(read), read).payload
    device = FakeSpringBoard(read["state"], read["apps"])

    result = run(apply_state(device, plan, backup_dir=tmp_path, timing=FAST))

    after = run(device.read_state())
    assert result.status == APPLIED
    assert same_layout(after, read["state"])
    assert after == read["state"]  # widgets, web clips and web apps byte for byte
    assert visible_apps(after) == visible_apps(read["state"])


def test_restoring_after_the_accident_keeps_31_apps_in_the_app_library(tmp_path):
    original = samples.home_screen()
    installed = samples.installed_apps()
    phone = FakeSpringBoard(original, installed)
    run(phone.write_state(deepcopy(original)))  # the list-form accident
    broken = run(phone.read_state())
    extra = visible_apps(broken) - visible_apps(original)
    assert len(extra) == 31

    result = run(
        apply_state(phone, safe_payload(original, installed), backup_dir=tmp_path, timing=FAST)
    )

    after = run(phone.read_state())
    assert result.status == APPLIED
    assert same_layout(after, original)
    assert not extra & visible_apps(after)
    assert load_plist(result.backup)["state"] == broken


def test_progress_events_have_stable_codes_and_serialize_to_json(tmp_path):
    start = [[], [{"bundleIdentifier": "a"}]]
    events = []
    device = FakeSpringBoard(start, _installed("a", "b"))

    result = run(
        apply_state(
            device,
            _plan_from(start, [[{"bundleIdentifier": "b"}]]),
            backup_dir=tmp_path,
            timing=FAST,
            on_event=events.append,
        )
    )

    assert [e.code for e in events] == [
        "reading",
        "backup_saved",
        "building",
        "writing",
        "verifying",
        "verified",
    ]
    assert [e.step for e in events if e.step] == [1, 2, 3, 4, 5]
    assert events == list(result.events)
    payload = json.dumps(result.to_dict())
    assert '"status": "applied"' in payload


def test_a_write_that_leaves_out_a_web_clip_is_rolled_back(tmp_path):
    # The planner refuses such a layout; this is the phone's side of the story. The fake,
    # like SpringBoard, puts the web clip back on a new last page, so verification fails.
    start = samples.home_screen()
    device = FakeSpringBoard(start, samples.installed_apps())
    pages = [
        [
            x
            for x in page
            if not (isinstance(x, dict) and x.get("displayIdentifier") == samples.STATUS_CLIP)
        ]
        for page in start[1:]
    ]
    plan = {
        "buttonBar": start[0],
        "iconLists": pages,
        "ignored": [],
        "_ios_homescreen": {"version": 1, "source_fingerprint": fingerprint(start)},
    }

    result = run(apply_state(device, plan, backup_dir=tmp_path, timing=FAST))

    assert result.status == ROLLED_BACK
    after_first_write = device.writes[0]
    assert samples.STATUS_CLIP not in json.dumps(after_first_write, default=str)
    assert same_layout(run(device.read_state()), start)
