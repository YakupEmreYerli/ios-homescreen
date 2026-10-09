from __future__ import annotations

import plistlib
from datetime import datetime

import pytest

import samples
from ios_homescreen.state import (
    StateError,
    cell_count,
    fingerprint,
    item_id,
    item_kind,
    load_plist,
    safe_payload,
    same_layout,
    save_plist,
    to_payload,
    validate_backup,
    validate_plan,
    validate_write_payload,
    visible_apps,
)


def test_binary_plist_keeps_datetime_and_bytes(tmp_path):
    data = {
        "at": datetime(2026, 9, 15, 12, 30, 1),
        "raw": b"\x00\xff\x10",
        "state": [[{"bundleIdentifier": "com.example.a"}]],
    }
    path = tmp_path / "backup.plist"

    save_plist(path, data)

    assert path.read_bytes().startswith(b"bplist00")
    assert load_plist(path) == data


def test_sample_state_round_trips_through_plist_exactly(tmp_path):
    state = samples.home_screen()
    path = save_plist(tmp_path / "copy.plist", state)

    assert plistlib.loads(path.read_bytes()) == state


def test_load_plist_rejects_other_files(tmp_path):
    path = tmp_path / "notes.plist"
    path.write_text("not a plist")

    with pytest.raises(StateError, match="not a property list"):
        load_plist(path)


def test_to_payload_splits_list_form_into_dock_and_pages():
    state = [[{"bundleIdentifier": "dock"}], [{"bundleIdentifier": "page"}]]

    assert to_payload(state) == {
        "buttonBar": [{"bundleIdentifier": "dock"}],
        "iconLists": [[{"bundleIdentifier": "page"}]],
        "ignored": [],
    }


def test_ignored_holds_hidden_user_and_system_apps_and_nothing_on_screen():
    state = {
        "buttonBar": [{"bundleIdentifier": "com.visible.dock"}],
        "iconLists": [
            [
                {
                    "listType": "folder",
                    "displayName": "Folder",
                    "iconLists": [[{"bundleIdentifier": "com.visible.folder"}]],
                }
            ]
        ],
        "ignored": ["stale.value"],
    }
    installed = {
        "com.visible.dock": {"name": "Dock", "type": "System"},
        "com.visible.folder": {"name": "Inner", "type": "User"},
        "com.hidden.user": {"name": "Hidden", "type": "User"},
        "com.hidden.system": {"name": "Tips", "type": "System"},
        "com.extension": {"name": "Extension", "type": "PluginKitPlugin"},
    }

    payload = safe_payload(state, installed)

    assert payload["ignored"] == ["com.hidden.system", "com.hidden.user"]
    assert visible_apps(payload) == {"com.visible.dock", "com.visible.folder"}


def test_visible_offloaded_apps_stay_out_of_ignored():
    state = [
        [{"displayIdentifier": "offloaded.user", "displayName": "Offloaded"}],
        [
            {
                "listType": "folder",
                "displayName": "Folder",
                "iconLists": [[{"displayIdentifier": "offloaded.system", "displayName": "Sys"}]],
            }
        ],
    ]
    installed = {
        "offloaded.user": {"name": "Offloaded", "type": "User"},
        "offloaded.system": {"name": "Sys", "type": "System"},
        "hidden": {"name": "Hidden", "type": "User"},
    }

    payload = safe_payload(state, installed)

    assert visible_apps(payload) == {"offloaded.user", "offloaded.system"}
    assert payload["ignored"] == ["hidden"]


def test_sample_ignored_is_exactly_the_app_library():
    payload = safe_payload(samples.home_screen(), samples.installed_apps())

    assert set(payload["ignored"]) == samples.library_only()
    assert not set(payload["ignored"]) & visible_apps(payload)


def test_safari_web_app_has_its_own_identity():
    webapp = samples.safari_webapp("WEBAPP-1")

    assert item_kind(webapp) == "webapp"
    assert item_id(webapp) == "WEBAPP-1"
    assert item_kind(samples.app("com.apple.mobilesafari", "Safari")) == "app"


def test_safari_web_app_does_not_count_as_safari_for_ignored():
    state = [[], [samples.safari_webapp("WEBAPP-1")]]
    installed = {"com.apple.mobilesafari": {"name": "Safari", "type": "System"}}

    payload = safe_payload(state, installed)

    assert visible_apps(state) == set()
    assert payload["ignored"] == ["com.apple.mobilesafari"]
    validate_write_payload(payload)


def test_safari_and_its_web_app_coexist():
    state = [[samples.app("com.apple.mobilesafari", "Safari")], [samples.safari_webapp("W")]]

    assert visible_apps(state) == {"com.apple.mobilesafari"}
    assert {item_id(state[0][0]), item_id(state[1][0])} == {"com.apple.mobilesafari", "W"}


def test_widgets_from_one_extension_are_told_apart_by_display_identifier():
    a = samples.widget("W-A", "small", container="c", extension="c.widget", kind="K")
    b = samples.widget("W-B", "small", container="c", extension="c.widget", kind="K")

    assert (item_id(a), item_id(b)) == ("W-A", "W-B")
    assert not same_layout([[], [a, b]], [[], [b, a]])


def test_safe_payload_upgrades_icon_type_folders_to_list_type():
    state = [
        [],
        [{"iconType": "folder", "displayName": "Old", "iconLists": [[{"bundleIdentifier": "a"}]]}],
    ]

    payload = safe_payload(state, {"a": {"name": "A", "type": "User"}})

    folder = payload["iconLists"][0][0]
    assert folder["listType"] == "folder"
    assert "iconType" not in folder


def test_identifier_falls_back_to_display_identifier_and_rejects_items_without_one():
    assert item_id({"displayIdentifier": "web-123", "webClipURL": "/"}) == "web-123"
    assert item_id({"bundleIdentifier": "com.example.a"}) == "com.example.a"
    with pytest.raises(StateError, match="no identifier"):
        item_id({"displayName": "Broken"})


@pytest.mark.parametrize(
    ("item", "cells"),
    [
        ({"bundleIdentifier": "a"}, 1),
        ({"webClipURL": "/", "displayIdentifier": "w"}, 1),
        ({"listType": "folder", "displayName": "F", "iconLists": [[{"bundleIdentifier": "a"}]]}, 1),
        ({"bundleIdentifier": "com.apple.mobilesafari", "displayIdentifier": "W"}, 1),
        ({"elementType": "widget", "displayIdentifier": "s", "gridSize": "small"}, 4),
        ({"iconType": "custom", "displayIdentifier": "m", "gridSize": "medium"}, 8),
        ({"elementType": "widget", "displayIdentifier": "l", "gridSize": "large"}, 16),
        ({"elementType": "widget", "displayIdentifier": "x", "gridSize": "extraLarge"}, 16),
    ],
)
def test_cell_count_follows_item_kind_and_widget_size(item, cells):
    assert cell_count(item) == cells


def test_unknown_widget_size_is_an_error():
    with pytest.raises(StateError, match="unknown widget size"):
        cell_count({"elementType": "widget", "displayIdentifier": "w", "gridSize": "huge"})


def test_layout_comparison_ignores_metadata_and_ignored():
    left = [
        [{"bundleIdentifier": "dock", "iconModDate": datetime(2026, 1, 1)}],
        [
            {
                "listType": "folder",
                "displayName": "F",
                "iconLists": [[{"bundleIdentifier": "a", "bundleVersion": "1"}]],
            }
        ],
    ]
    right = {
        "buttonBar": [{"bundleIdentifier": "dock"}],
        "iconLists": [
            [{"listType": "folder", "displayName": "F", "iconLists": [[{"bundleIdentifier": "a"}]]}]
        ],
        "ignored": ["hidden"],
    }

    assert same_layout(left, right)
    assert fingerprint(left) == fingerprint(right)


def test_layout_comparison_catches_order_changes():
    a = [[], [{"bundleIdentifier": "a"}, {"bundleIdentifier": "b"}]]
    b = [[], [{"bundleIdentifier": "b"}, {"bundleIdentifier": "a"}]]

    assert not same_layout(a, b)
    assert fingerprint(a) != fingerprint(b)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gridSize", "large"),
        ("userSelectedElementIdentifier", "e2"),
        ("elements", [{"uniqueIdentifier": "e2"}, {"uniqueIdentifier": "e1"}]),
    ],
)
def test_widget_size_stack_order_and_selection_are_part_of_the_layout(field, value):
    stack = {
        "iconType": "custom",
        "displayIdentifier": "stack",
        "gridSize": "medium",
        "userSelectedElementIdentifier": "e1",
        "elements": [{"uniqueIdentifier": "e1"}, {"uniqueIdentifier": "e2"}],
    }
    changed = dict(stack)
    changed[field] = value

    assert not same_layout([[], [stack]], [[], [changed]])
    assert fingerprint([[], [stack]]) != fingerprint([[], [changed]])


def _plan(**overrides):
    plan = {
        "buttonBar": [],
        "iconLists": [],
        "ignored": [],
        "_ios_homescreen": {"version": 1, "source_fingerprint": "a" * 64},
    }
    plan.update(overrides)
    return plan


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        ([], "must be a dictionary"),
        ({"buttonBar": [], "iconLists": [], "ignored": []}, "exactly"),
        (_plan(extra=True), "exactly"),
        (_plan(_ios_homescreen={"version": 2, "source_fingerprint": "a" * 64}), "version"),
        (_plan(_ios_homescreen={"version": 1, "source_fingerprint": "xyz"}), "fingerprint"),
        (_plan(buttonBar="not a list"), "must be lists"),
        (_plan(buttonBar=[{"bundleIdentifier": f"a{i}"} for i in range(5)]), "at most 4"),
        (_plan(iconLists=[[{"bundleIdentifier": "a"}]], ignored=["a"]), "cannot also be"),
        (_plan(ignored=["a", "a"]), "duplicate"),
    ],
)
def test_validate_plan_rejects_malformed_plans(plan, message):
    with pytest.raises(StateError, match=message):
        validate_plan(plan)


@pytest.mark.parametrize(
    ("backup", "message"),
    [
        ([], "no dock"),
        (["not a page"], "list of items"),
        ({"buttonBar": [], "iconLists": []}, "exactly"),
        ("text", "list-form or dictionary-form"),
        (
            [[], [{"elementType": "widget", "displayIdentifier": "w", "gridSize": "large"}] * 2],
            "32/24",
        ),
    ],
)
def test_validate_backup_rejects_malformed_backups(backup, message):
    with pytest.raises(StateError, match=message):
        validate_backup(backup)


def test_validate_backup_accepts_both_forms():
    validate_backup(samples.home_screen())
    validate_backup(safe_payload(samples.home_screen(), samples.installed_apps()))


@pytest.mark.parametrize(
    "folder",
    [
        {"iconType": "folder", "displayName": "Old", "iconLists": [[{"bundleIdentifier": "a"}]]},
        {
            "listType": "folder",
            "displayName": "Outer",
            "iconLists": [
                [
                    {
                        "listType": "folder",
                        "displayName": "Inner",
                        "iconLists": [[{"bundleIdentifier": "a"}]],
                    }
                ]
            ],
        },
        {
            "listType": "folder",
            "displayName": "Widgets",
            "iconLists": [[{"elementType": "widget", "displayIdentifier": "w"}]],
        },
    ],
)
def test_write_payload_rejects_legacy_nested_and_widget_folders(folder):
    with pytest.raises(StateError, match="folder"):
        validate_write_payload({"buttonBar": [], "iconLists": [[folder]], "ignored": []})


def test_write_payload_must_be_the_exact_dictionary():
    with pytest.raises(StateError, match="not a list"):
        validate_write_payload([[], []])
    with pytest.raises(StateError, match="exactly"):
        validate_write_payload({"buttonBar": [], "iconLists": [], "ignored": [], "extra": 1})
