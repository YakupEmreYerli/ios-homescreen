from __future__ import annotations

import json

import pytest

import samples
from ios_homescreen.model import describe, to_document
from ios_homescreen.planner import LayoutError, plan_layout
from ios_homescreen.state import same_layout


def _find(items, item_id):
    return next(item for item in items if item["id"] == item_id)


def test_describe_is_plain_json_with_kinds_sizes_and_the_app_library():
    read = samples.read_snapshot()
    read["device"] = {"name": "Test iPhone", "ios_version": "26.0"}

    view = json.loads(json.dumps(describe(read)))

    assert [item["id"] for item in view["dock"]][:2] == [
        "com.apple.mobilephone",
        "com.apple.mobilesafari",
    ]
    assert [page["cells"] for page in view["pages"]] == [20, 18]
    assert view["limits"] == {
        "dock_items": 4,
        "page_cells": 24,
        "widget_cells": {"small": 4, "medium": 8, "large": 16, "extraLarge": 16},
    }
    page1, page2 = view["pages"][0]["items"], view["pages"][1]["items"]
    weather = _find(page1, samples.WEATHER_WIDGET)
    assert (weather["type"], weather["size"], weather["cells"]) == ("widget", "medium", 8)
    webapp = _find(page1, samples.WEBAPP_PAGE)
    assert webapp["type"] == "webapp"
    assert webapp["app"] == "com.apple.mobilesafari"
    assert _find(page2, samples.STACK)["stack"] is True
    assert _find(page2, samples.OFFLOADED)["offloaded"] is True
    folders = [item for page in view["pages"] for item in page["items"] if item["type"] == "folder"]
    assert [(f["id"], f["name"], len(f["pages"])) for f in folders] == [
        ("folder-1", "Utilities", 1),
        ("folder-2", "Media", 2),
    ]
    assert len(view["library"]) == 31
    assert view["device"] == {"name": "Test iPhone", "ios_version": "26.0"}


def test_describe_then_to_document_plans_back_to_the_same_layout():
    read = samples.read_snapshot()

    document = to_document(json.loads(json.dumps(describe(read))))
    plan = plan_layout(document, read)

    assert same_layout(plan.payload, read["state"])


def test_an_edited_view_becomes_a_valid_plan():
    read = samples.read_snapshot()
    view = describe(read)
    camera = view["dock"].pop()
    view["pages"][1]["items"].append(camera)
    view["dock"].append(view["library"][0])  # bring an App Library app to the dock

    plan = plan_layout(to_document(view), read)

    assert plan.to_home_screen == (view["library"][0]["id"],)
    assert plan.payload["iconLists"][1][-1]["bundleIdentifier"] == "com.apple.camera"


def test_problems_come_back_with_codes_and_locations():
    read = samples.read_snapshot()
    view = describe(read)
    view["dock"].append(view["library"][0])  # five dock items
    view["pages"][0]["items"].append({"type": "widget", "id": "NOT-THERE"})
    view["pages"][1]["items"].append(view["dock"][0])  # Phone twice

    with pytest.raises(LayoutError) as error:
        plan_layout(to_document(view), read)

    issues = error.value.to_dict()["issues"]
    json.dumps(issues)
    assert [issue["code"] for issue in issues] == ["dock_full", "unknown_item", "duplicate_item"]
    assert issues[0]["details"] == {"count": 5, "capacity": 4}
    assert issues[1]["location"] == {"section": "page", "page": 1, "item": 14}
    assert issues[2]["details"]["id"] == "com.apple.mobilephone"
    assert str(error.value).startswith("3 problems in the layout:")


def test_page_capacity_issue_carries_the_numbers():
    read = samples.read_snapshot()
    view = describe(read)
    view["pages"][1]["items"].extend(view["library"][:7])  # 18 + 7 = 25 cells

    with pytest.raises(LayoutError) as error:
        plan_layout(to_document(view), read)

    (issue,) = error.value.issues
    assert issue.code == "page_full"
    assert issue.location.page == 2
    assert issue.details == {"cells": 25, "capacity": 24}


def test_issues_inside_folders_point_into_the_folder():
    read = samples.read_snapshot()
    view = describe(read)
    folder = _find(view["pages"][0]["items"], "folder-1")
    folder["pages"][0].append({"type": "widget", "id": samples.WEATHER_WIDGET})

    with pytest.raises(LayoutError) as error:
        plan_layout(to_document(view), read)

    (issue,) = error.value.issues
    assert issue.code == "widget_in_folder"
    assert issue.location.to_dict() == {
        "section": "page",
        "page": 1,
        "item": 10,
        "folder": "Utilities",
        "folder_page": 1,
        "folder_item": 6,
    }
