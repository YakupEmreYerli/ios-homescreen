from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import samples
from ios_homescreen.export import export_layout
from ios_homescreen.planner import LayoutError, plan_layout
from ios_homescreen.state import (
    PLAN_META_KEY,
    fingerprint,
    item_id,
    iter_items,
    same_layout,
    validate_plan,
)


def _read() -> dict:
    return {
        "state": [
            [{"bundleIdentifier": "com.a", "displayName": "A"}],
            [
                {"bundleIdentifier": "com.b", "displayName": "B"},
                {
                    "displayIdentifier": "widget-1",
                    "displayName": "Weather",
                    "elementType": "widget",
                    "gridSize": "medium",
                },
                {"displayIdentifier": "web-1", "displayName": "Panel", "webClipURL": "/panel"},
            ],
        ],
        "apps": {
            "com.a": {"name": "A", "type": "User"},
            "com.b": {"name": "B", "type": "System"},
            "com.c": {"name": "C", "type": "User"},
        },
    }


KEEP_SPECIALS = """
[[pages]]
items = [{ type = "widget", id = "widget-1" }, { type = "webclip", id = "web-1" }]
"""

# The sample's other web clips and web app: a layout cannot leave them out.
SAMPLE_WEB = (
    f'{{ type = "webclip", id = "{samples.STATUS_CLIP}" }}, '
    f'{{ type = "webclip", id = "{samples.DOCS_CLIP}" }}, '
    f'{{ type = "webapp", id = "{samples.WEBAPP_FOLDER}" }}'
)


def test_export_plans_back_to_the_same_layout():
    read = _read()

    text = export_layout(read)
    plan = plan_layout(text, read)

    assert '"com.a",  # A' in text
    assert same_layout(plan.payload, read["state"])
    assert plan.ignored_count == 1
    validate_plan(plan.payload)


def test_export_of_a_full_home_screen_round_trips_exactly():
    read = samples.read_snapshot()

    text = export_layout(read, pull="pull-20260101-000000-000000.plist", note="Pulled from a test.")
    plan = plan_layout(text, read)

    assert tomllib.loads(text)["pull"] == {"snapshot": "pull-20260101-000000-000000.plist"}
    assert "#\n# Pulled from a test.\n" in text
    assert plan.unchanged
    assert plan.changes == "No changes."
    assert same_layout(plan.payload, read["state"])
    assert plan.to_library == ()
    assert plan.to_home_screen == ()
    assert plan.removed == ()
    assert set(plan.payload["ignored"]) == samples.library_only()
    assert plan.payload[PLAN_META_KEY]["source_fingerprint"] == fingerprint(read["state"])


def test_round_trip_keeps_widgets_web_clips_and_web_apps_byte_for_byte():
    read = samples.read_snapshot()
    originals = {
        item_id(item): item
        for item in iter_items(read["state"])
        if isinstance(item, dict) and "listType" not in item
    }

    plan = plan_layout(export_layout(read), read)

    for item in iter_items(plan.payload):
        if "listType" not in item:
            assert item == originals[item_id(item)]


def test_export_references_web_apps_and_widgets_by_display_identifier():
    text = export_layout(samples.read_snapshot())

    assert f'{{ type = "webapp", id = "{samples.WEBAPP_PAGE}" }},  # web app (Safari)' in text
    assert f'{{ type = "webapp", id = "{samples.WEBAPP_FOLDER}" }}' in text
    assert f'{{ type = "widget", id = "{samples.LIGHTS_A}" }}' in text
    assert f'{{ type = "widget", id = "{samples.LIGHTS_B}" }}' in text
    assert '"com.apple.mobilesafari",  # Safari' in text


def test_safari_web_app_and_safari_are_separate_items_in_a_plan():
    read = samples.read_snapshot()
    layout = f"""
[dock]
items = ["Safari"]

[[pages]]
items = [{{ type = "webapp", id = "{samples.WEBAPP_PAGE}" }}, {SAMPLE_WEB}]
"""

    plan = plan_layout(layout, read, allow_removal=True)

    assert plan.payload["buttonBar"][0]["bundleIdentifier"] == "com.apple.mobilesafari"
    assert plan.payload["iconLists"][0][0] == samples.safari_webapp(samples.WEBAPP_PAGE)
    assert "com.apple.mobilesafari" not in plan.payload["ignored"]


def test_web_apps_without_safari_leave_safari_in_the_app_library():
    read = samples.read_snapshot()
    layout = f"""
[[pages]]
items = [{{ type = "webapp", id = "{samples.WEBAPP_PAGE}" }}, {SAMPLE_WEB}]
"""

    plan = plan_layout(layout, read, allow_removal=True)

    assert "com.apple.mobilesafari" in plan.payload["ignored"]
    assert "com.apple.mobilesafari" in plan.to_library


def test_two_widgets_from_one_extension_can_swap_places():
    read = samples.read_snapshot()
    layout = f"""
[[pages]]
items = [
  {{ type = "widget", id = "{samples.LIGHTS_B}" }},
  {{ type = "widget", id = "{samples.LIGHTS_A}" }},
  {{ type = "webapp", id = "{samples.WEBAPP_PAGE}" }}, {SAMPLE_WEB},
]
"""

    plan = plan_layout(layout, read, allow_removal=True)

    page = plan.payload["iconLists"][0]
    assert [item_id(w) for w in page[:2]] == [samples.LIGHTS_B, samples.LIGHTS_A]
    assert page[0]["userSelectedElementIdentifier"] == "scene-2"


def test_web_app_id_as_bare_string_explains_the_right_syntax():
    layout = f'[[pages]]\nitems = ["{samples.WEBAPP_PAGE}"]\n'

    with pytest.raises(LayoutError, match=r'is a webapp.*type = "webapp"'):
        plan_layout(layout, samples.read_snapshot(), allow_removal=True)


def test_left_out_apps_go_to_the_library_and_new_apps_get_the_minimal_form():
    layout = """
[dock]
items = ["C"]

[[pages]]
items = [{ type = "webclip", id = "web-1" }]
"""

    plan = plan_layout(layout, _read(), allow_removal=True)

    assert plan.payload["buttonBar"] == [
        {"bundleIdentifier": "com.c", "displayIdentifier": "com.c"}
    ]
    assert plan.payload["ignored"] == ["com.a", "com.b"]
    assert plan.to_library == ("com.a", "com.b")
    assert plan.to_home_screen == ("com.c",)


def test_explicit_app_table_takes_ids_only():
    plan = plan_layout(
        '[dock]\nitems = [{ type = "app", id = "com.a" }]\n'
        '[[pages]]\nitems = [{ type = "webclip", id = "web-1" }]\n',
        _read(),
        allow_removal=True,
    )
    assert plan.payload["buttonBar"] == [{"bundleIdentifier": "com.a", "displayName": "A"}]

    with pytest.raises(LayoutError, match="unknown app id 'A'"):
        plan_layout('[dock]\nitems = [{ type = "app", id = "A" }]\n', _read(), allow_removal=True)


@pytest.mark.parametrize(
    ("layout", "message"),
    [
        ('[dock]\nitems = ["com.a", "com.b", "com.c", "B", "A"]', "at most 4"),
        ('[[pages]]\nitems = ["com.a", "com.a"]', "more than once"),
        ('[dock]\nitems = ["com.a"]\n[[pages]]\nitems = ["A"]', "more than once"),
        ('[[pages]]\nitems = ["missing"]', "unknown app 'missing'"),
        ('[[pages]]\nitems = [{ type = "folder", name = "Empty", items = [] }]', "empty folders"),
        (
            '[[pages]]\nitems = [{ type = "folder", name = "", items = ["com.a"] }]',
            "non-empty name",
        ),
        (
            '[[pages]]\nitems = [{ type = "folder", name = "X", items = ["com.a"], pages = [] }]',
            "either items or pages",
        ),
        (
            '[[pages]]\nitems = [{ type = "folder", name = "X", pages = [["com.a"], []] }]',
            "folder page 2 is empty",
        ),
        (
            '[[pages]]\nitems = [{ type = "folder", name = "X", items = [{ type = "folder", '
            'name = "Y", items = ["com.a"] }] }]',
            "folders cannot contain folders",
        ),
        (
            '[[pages]]\nitems = [{ type = "folder", name = "X", items = [{ type = "widget", '
            'id = "widget-1" }] }]',
            "folders cannot contain widgets",
        ),
        ('[dock]\nitems = [{ type = "widget", id = "widget-1" }]', "dock cannot hold widgets"),
        ('[[pages]]\nitems = [{ type = "widget", id = "nope" }]', "unknown widget id"),
        (
            '[[pages]]\nitems = [{ type = "webclip", id = "widget-1" }]',
            "is a widget, not a webclip",
        ),
        ('[[pages]]\nitems = [{ type = "shortcut", id = "x" }]', "type must be one of"),
        ('[[pages]]\nitems = [{ type = "app", id = "com.a", size = 2 }]', "unknown key"),
        ("[[pages]]\nitems = [42]", "app string or an inline table"),
        ("theme = 'dark'", "unknown top-level key"),
        ('dock = "not a table"', "dock: must be a table"),
        ('pages = ["not a table"]', "page 1: must be a table"),
        ('[[pages]]\nitems = "not an array"', "items must be an array"),
        ("[[pages]]\nitmes = []", "unknown key"),
        ("[dock\n", "invalid TOML"),
    ],
)
def test_invalid_layouts_are_rejected_with_a_clear_error(layout, message):
    with pytest.raises(LayoutError, match=message):
        plan_layout(layout, _read(), allow_removal=True)


def test_ambiguous_app_name_asks_for_the_bundle_id():
    read = _read()
    read["apps"]["com.other"] = {"name": "A", "type": "User"}

    with pytest.raises(LayoutError, match="matches several apps"):
        plan_layout('[[pages]]\nitems = ["A"]', read, allow_removal=True)


def test_widget_cells_count_toward_page_capacity():
    read = _read()
    read["apps"].update({f"com.x{i}": {"name": f"X{i}", "type": "User"} for i in range(17)})
    apps = ", ".join(f'"com.x{i}"' for i in range(17))
    layout = f'[[pages]]\nitems = [{{ type = "widget", id = "widget-1" }}, {apps}]'

    with pytest.raises(LayoutError, match="25/24"):
        plan_layout(layout, read, allow_removal=True)


def test_leaving_out_a_widget_needs_allow_removal():
    layout = '[[pages]]\nitems = ["com.a", { type = "webclip", id = "web-1" }]'

    with pytest.raises(LayoutError, match="--allow-removal") as error:
        plan_layout(layout, _read())

    assert error.value.code == "removal_not_allowed"
    assert error.value.issues[0].details == {"ids": ["widget-1"]}
    plan = plan_layout(layout, _read(), allow_removal=True)
    assert plan.removed == ("widget-1",)


@pytest.mark.parametrize("allow_removal", [False, True])
def test_web_clips_cannot_be_removed_even_with_allow_removal(allow_removal):
    # SpringBoard puts a left-out web clip back on a new last page.
    layout = '[[pages]]\nitems = ["com.a", { type = "widget", id = "widget-1" }]'

    with pytest.raises(LayoutError, match="Delete Bookmark") as error:
        plan_layout(layout, _read(), allow_removal=allow_removal)

    (issue,) = error.value.issues
    assert issue.code == "not_removable"
    assert issue.details == {"id": "web-1", "kind": "webclip", "name": "Panel"}
    assert "'Panel' (web-1)" in str(issue)


def test_web_apps_cannot_be_removed_either():
    read = samples.read_snapshot()
    layout = export_layout(read).replace(
        f'  {{ type = "webapp", id = "{samples.WEBAPP_PAGE}" }},', ""
    )

    with pytest.raises(LayoutError, match=samples.WEBAPP_PAGE) as error:
        plan_layout(layout, read, allow_removal=True)

    assert [i.code for i in error.value.issues] == ["not_removable"]
    assert error.value.issues[0].details["kind"] == "webapp"


def test_unresolved_items_do_not_also_count_as_left_out():
    layout = '[[pages]]\nitems = ["com.a", { type = "webclip", id = "web-x" }]'

    with pytest.raises(LayoutError) as error:
        plan_layout(layout, _read(), allow_removal=True)

    assert [i.code for i in error.value.issues] == ["unknown_item"]


def test_folders_use_list_type_and_reuse_the_read_dictionaries():
    layout = """
[[pages]]
items = [
  { type = "folder", name = "New", items = ["com.a", "B"] },
  { type = "widget", id = "widget-1" },
  { type = "webclip", id = "web-1" },
]
"""

    plan = plan_layout(layout, _read())

    assert plan.payload["iconLists"][0][0] == {
        "listType": "folder",
        "displayName": "New",
        "iconLists": [
            [
                {"bundleIdentifier": "com.a", "displayName": "A"},
                {"bundleIdentifier": "com.b", "displayName": "B"},
            ]
        ],
    }


def test_multi_page_folders_keep_their_pages():
    layout = """
[[pages]]
items = [
  { type = "folder", name = "Two", pages = [
    ["com.a"],
    ["com.b", { type = "webclip", id = "web-1" }],
  ] },
  { type = "widget", id = "widget-1" },
]
"""

    plan = plan_layout(layout, _read())

    folder = plan.payload["iconLists"][0][0]
    assert [[item_id(x) for x in page] for page in folder["iconLists"]] == [
        ["com.a"],
        ["com.b", "web-1"],
    ]


def test_web_clip_inside_a_folder_round_trips_and_cannot_be_dropped_silently():
    clip = {"displayIdentifier": "folder-web", "displayName": "Panel", "webClipURL": "/"}
    read = {
        "state": [
            [],
            [
                {
                    "listType": "folder",
                    "displayName": "Links",
                    "iconLists": [[{"bundleIdentifier": "com.a", "displayName": "A"}, clip]],
                }
            ],
        ],
        "apps": {"com.a": {"name": "A", "type": "User"}},
    }

    text = export_layout(read)
    plan = plan_layout(text, read)

    assert 'type = "webclip"' in text
    assert same_layout(plan.payload, read["state"])
    with pytest.raises(LayoutError, match=r"folder-web.*Delete Bookmark"):
        plan_layout('[[pages]]\nitems = ["com.a"]', read, allow_removal=True)


def test_errors_say_where_the_problem_is():
    with pytest.raises(LayoutError, match=r"page 2, item 3"):
        plan_layout(
            '[[pages]]\nitems = []\n[[pages]]\nitems = ["com.a", "com.b", "nope"]',
            _read(),
            allow_removal=True,
        )


def test_change_summary_lists_moves_and_counts():
    layout = (
        KEEP_SPECIALS.replace("items = [", 'items = ["com.a", ') + '\n[dock]\nitems = ["com.b"]\n'
    )

    plan = plan_layout(layout, _read())

    assert [(c["kind"], c["id"]) for c in plan.change_list] == [
        ("moved", "com.b"),
        ("moved", "com.a"),
    ]
    assert "  A  moves from the dock to page 1, position 1" in plan.changes
    assert "  B  moves from page 1 to the dock, position 1" in plan.changes
    assert plan.changes.endswith("\n2 moved.")
    assert plan.ignored_count == 1


def test_the_pull_and_showcase_tables_are_accepted_and_ignored_for_planning():
    layout = (
        '[pull]\nsnapshot = "pull-20261010-000000-000000.plist"\n'
        '[showcase]\nlibrary = ["C", "com.a"]\n' + KEEP_SPECIALS + '[dock]\nitems = ["A"]\n'
    )

    plan = plan_layout(layout, _read())

    assert set(plan.payload) == {"buttonBar", "iconLists", "ignored", PLAN_META_KEY}
    assert plan.to_library == ("com.b",)


@pytest.mark.parametrize(
    ("tables", "message"),
    [
        ("[pull]\nsnapshot = 1\n", "[pull] snapshot has the wrong type"),
        ('[pull]\nsnaphot = "x.plist"\n', "unknown key(s) in [pull]: snaphot"),
        ("pull = 3\n", "pull must be a table"),
        ('[showcase]\nlibary = ["A"]\n', "unknown key(s) in [showcase]: libary"),
        ('[showcase]\nlibrary = "A"\n', "[showcase] library has the wrong type"),
        ('[showcase]\nlibrary = ["A", 3]\n', "[showcase] library must list app names or ids"),
        ("[dok]\n", "unknown top-level key(s): dok"),
    ],
)
def test_typos_in_the_extra_tables_are_errors(tables, message):
    with pytest.raises(LayoutError) as error:
        plan_layout(tables + KEEP_SPECIALS, _read(), allow_removal=True)

    assert message in str(error.value)


def test_a_renamed_folder_is_recognised_by_what_it_holds():
    read = samples.read_snapshot()
    text = export_layout(read).replace('name = "Utilities"', 'name = "Tools"')

    plan = plan_layout(text, read)

    assert [(c["kind"], c["name"]) for c in plan.change_list] == [("folder_renamed", "Tools")]
    assert plan.change_list[0]["old_name"] == "Utilities"
    assert 'Folder "Tools"  was "Utilities"' in plan.changes


def example_read() -> dict:
    """A read that holds everything examples/layout.toml and the READMEs refer to."""
    names = {
        "com.apple.mobilephone": "Phone",
        "com.apple.mobilesafari": "Safari",
        "com.apple.MobileSMS": "Messages",
        "com.apple.camera": "Camera",
        "com.apple.mobilecal": "Calendar",
        "com.apple.mobileslideshow": "Photos",
        "com.apple.mobilemail": "Mail",
        "com.apple.Maps": "Maps",
        "com.apple.mobilenotes": "Notes",
        "com.apple.reminders": "Reminders",
        "com.apple.mobiletimer": "Clock",
        "com.apple.Preferences": "Settings",
        "com.apple.calculator": "Calculator",
        "com.apple.VoiceMemos": "Voice Memos",
        "com.apple.findmy": "Find My",
        "com.apple.DocumentsApp": "Files",
        "com.apple.Music": "Music",
        "com.apple.podcasts": "Podcasts",
        "com.apple.tv": "TV",
        "com.apple.iBooks": "Books",
        "com.apple.AppStore": "App Store",
        "com.apple.Health": "Health",
        "com.apple.Passbook": "Wallet",
        "com.apple.shortcuts": "Shortcuts",
        "com.apple.tips": "Tips",
    }
    widget_kw = {"container": "com.apple.weather", "extension": "w", "kind": "k"}
    read = {
        "state": [
            [],
            [
                samples.widget("6F1D3A52-0000-4000-8000-000000000001", "medium", **widget_kw),
                samples.widget("6F1D3A52-0000-4000-8000-000000000003", "small", **widget_kw),
                samples.webclip(
                    "0A1B2C3D4E5F40718293A4B5C6D7E8F9", "Bookmark", "https://a.example"
                ),
                samples.safari_webapp("9E8D7C6B-0000-4000-8000-000000000002"),
            ],
        ],
        "apps": {bundle: {"name": name, "type": "System"} for bundle, name in names.items()},
    }
    return read


def test_example_layout_in_the_repository_plans_cleanly():
    example = Path(__file__).resolve().parents[1] / "examples" / "layout.toml"

    plan = plan_layout(example, example_read())

    assert plan.payload["ignored"] == ["com.apple.tips"]
    assert len(plan.payload["buttonBar"]) == 4
