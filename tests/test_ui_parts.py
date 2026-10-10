"""Pieces of the browser UI that need no server: the change list, the demo phone, the
friendly errors, the shipped static files and the `ui` command."""

from __future__ import annotations

import asyncio
import hashlib
import re
from copy import deepcopy
from pathlib import Path

import pytest

import samples
from ios_homescreen import api
from ios_homescreen.cli import main
from ios_homescreen.model import describe, describe_changes, to_document
from ios_homescreen.planner import plan_layout
from ios_homescreen.state import same_layout
from ios_homescreen.transport import TransportError
from ios_homescreen.ui import demo
from ios_homescreen.ui.errors import classify, friendly
from ios_homescreen.workflow import WorkflowError

STATIC = Path(__file__).resolve().parents[1] / "src" / "ios_homescreen" / "ui" / "static"


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ change list


def _view():
    return describe(samples.read_snapshot())


def _kinds(changes):
    return [(c["kind"], c.get("id")) for c in changes]


def test_no_edit_means_no_changes():
    view = _view()

    assert describe_changes(view, deepcopy(view)) == []


def test_moving_an_item_elsewhere_is_one_change_not_a_cascade():
    before = _view()
    after = deepcopy(before)
    camera = after["dock"].pop()
    after["pages"][0]["items"].insert(1, camera)

    changes = describe_changes(before, after)

    assert _kinds(changes) == [("moved", "com.apple.camera")]
    assert changes[0]["from"] == {"section": "dock", "index": 4}
    assert changes[0]["to"] == {"section": "page", "page": 1, "index": 2}


def test_reordering_within_a_page_names_only_what_moved():
    before = _view()
    after = deepcopy(before)
    items = after["pages"][1]["items"]
    items.insert(0, items.pop())  # Lights to the front

    assert _kinds(describe_changes(before, after)) == [("reordered", "com.example.lights")]


def test_folders_library_removals_and_pages():
    before = _view()
    after = deepcopy(before)
    page1, page2 = after["pages"][0]["items"], after["pages"][1]["items"]
    maps = next(i for i in page1 if i["id"] == "com.apple.Maps")
    page1[page1.index(maps)] = {"type": "folder", "id": "new-1", "name": "Go", "pages": [[maps]]}
    utilities = next(i for i in page1 if i["id"] == "folder-1")
    utilities["name"] = "Tools"
    media = next(i for i in page2 if i["id"] == "folder-2")
    page2.remove(media)
    page2.extend(x for page in media["pages"] for x in page)
    page2.remove(next(i for i in page2 if i["id"] == "com.apple.Health"))
    page2.remove(next(i for i in page2 if i["id"] == samples.LIGHTS_A))
    after["pages"][1]["items"] = page2
    after["pages"].append({"items": [after["library"][0]]})

    kinds = _kinds(describe_changes(before, after))

    assert ("folder_created", "new-1") in kinds
    assert ("moved", "com.apple.Maps") in kinds
    assert ("folder_renamed", "folder-1") in kinds
    assert ("folder_deleted", "folder-2") in kinds
    assert ("moved", "com.apple.Music") in kinds
    assert ("to_library", "com.apple.Health") in kinds
    assert ("removed", samples.LIGHTS_A) in kinds
    assert ("added", after["library"][0]["id"]) in kinds
    assert ("pages", None) in kinds
    renamed = next(c for c in describe_changes(before, after) if c["kind"] == "folder_renamed")
    assert (renamed["old_name"], renamed["name"]) == ("Utilities", "Tools")


def test_empty_pages_do_not_count():
    before = _view()
    after = deepcopy(before)
    after["pages"].insert(0, {"items": []})

    assert describe_changes(before, after) == []


# ------------------------------------------------------------------ hidden system services


def _with_hidden_services():
    read = samples.read_snapshot()
    read["apps"]["com.apple.AirDropUI"] = {"name": "AirDropUI", "type": "System", "hidden": True}
    # Shares its name with the real Settings app.
    read["apps"]["com.apple.SettingsHost"] = {"name": "Settings", "type": "System", "hidden": True}
    return read


def test_hidden_services_stay_out_of_the_app_library_but_are_still_ignored():
    read = _with_hidden_services()

    view = describe(read)
    plan = plan_layout(to_document(view), read)

    library = {app["id"] for app in view["library"]}
    assert "com.apple.AirDropUI" not in library
    assert "com.apple.tips" in library
    assert {"com.apple.AirDropUI", "com.apple.SettingsHost"} <= set(plan.payload["ignored"])
    exported = api.export_layout(read)
    assert "AirDropUI" not in exported
    assert '#   "com.apple.tips",  # tips' in exported


def test_hidden_services_are_not_offered_by_name():
    read = _with_hidden_services()

    plan = plan_layout('[dock]\nitems = ["Settings"]\n' + _keep_web(), read, allow_removal=True)

    assert plan.payload["buttonBar"][0]["bundleIdentifier"] == "com.apple.Preferences"


def _keep_web():
    return (
        "[[pages]]\nitems = ["
        f'{{ type = "webclip", id = "{samples.STATUS_CLIP}" }}, '
        f'{{ type = "webclip", id = "{samples.DOCS_CLIP}" }}, '
        f'{{ type = "webapp", id = "{samples.WEBAPP_FOLDER}" }}, '
        f'{{ type = "webapp", id = "{samples.WEBAPP_PAGE}" }}]\n'
    )


# ------------------------------------------------------------------ demo phone


def test_demo_phone_is_a_believable_full_home_screen():
    device = demo.DemoDevice(delay=0)
    snapshot = run(api.read_device(device))
    view = describe(snapshot)

    assert len(view["dock"]) == 4
    assert [page["cells"] for page in view["pages"]] == [24, 20, 20]
    kinds = {i["type"] for p in view["pages"] for i in p["items"]}
    assert kinds == {"app", "folder", "widget", "webclip", "webapp"}
    sizes = {i["size"] for p in view["pages"] for i in p["items"] if i["type"] == "widget"}
    assert sizes == {"small", "medium", "large"}
    assert len(view["library"]) >= 15
    # The view plans back to exactly what the demo phone has.
    plan = plan_layout(to_document(view), snapshot)
    assert same_layout(plan.payload, snapshot["state"])


def test_demo_apps_are_invented_and_all_have_generated_icons():
    apps = demo.installed_apps()
    ids = [*apps, demo.HANDBOOK, demo.PLANNER]

    assert all(ident.startswith("com.example.") for ident in apps)
    icons = run(demo.DemoDevice(delay=0).icons(ids))
    assert all(data and data.startswith(b"<svg") for data in icons.values())
    # Simple markup only: no scripts, links or external references.
    for data in icons.values():
        assert not re.search(rb"<script|href=|https?://(?!www\.w3\.org/2000/svg)", data)


def test_demo_phone_takes_a_safe_write(tmp_path):
    device = demo.DemoDevice(delay=0)
    snapshot = run(api.read_device(device))
    view = describe(snapshot)
    view["dock"].reverse()
    plan = plan_layout(to_document(view), snapshot)

    result = run(
        api.push(
            device,
            plan,
            backup_dir=tmp_path,
            timing=api.Timing(verify_attempts=1, verify_interval=0),
        )
    )

    assert result.ok
    assert run(device.read_state())[0][0]["displayName"] == "Melodia"
    with pytest.raises(Exception, match="dictionary"):
        run(device.write_state([[]]))


# ------------------------------------------------------------------ friendly errors


def _named(name: str, base: type = Exception) -> Exception:
    return type(name, (base,), {})("boom")


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda: TransportError("x", code="no_usb_device"), "no_usb_device"),
        (lambda: TransportError("x", code="not_advertising"), "not_advertising"),
        (lambda: WorkflowError("x", code="layout_changed"), "layout_changed"),
        (lambda: _named("PasswordRequiredError"), "locked"),
        (lambda: _named("PairingDialogResponsePendingError"), "trust_pending"),
        (lambda: _named("UserDeniedPairingError"), "trust_denied"),
        (lambda: TimeoutError(), "timeout"),
        (lambda: RuntimeError("Mux error -8"), "not_trusted"),
        (lambda: ValueError("odd"), "unexpected"),
    ],
)
def test_errors_get_a_stable_code(make, code):
    assert classify(make()) == code


def test_a_wrapped_pymobiledevice3_error_is_found_through_the_chain():
    try:
        try:
            raise _named("PasswordRequiredError")
        except Exception as inner:
            raise TransportError("could not connect over USB", code="connection_failed") from inner
    except TransportError as outer:
        error = friendly(outer)

    assert error["code"] == "locked"
    assert error["title"] == "The iPhone is locked"
    assert error["detail"] == "could not connect over USB"


def test_unknown_errors_still_read_like_a_sentence():
    error = friendly(ValueError("something odd"))

    assert error["title"] == "Something went wrong"
    assert error["steps"]
    assert error["detail"] == "something odd"


# ------------------------------------------------------------------ static files


def test_vendored_libraries_match_their_recorded_checksums():
    sources = (STATIC / "vendor" / "SOURCES.txt").read_text()
    recorded = dict(re.findall(r"^(\S+\.mjs)\n(?:.*\n)*?  sha256:  ([0-9a-f]{64})", sources, re.M))

    assert set(recorded) == {"preact.mjs", "preact-hooks.mjs", "htm.mjs"}
    for name, digest in recorded.items():
        assert hashlib.sha256((STATIC / "vendor" / name).read_bytes()).hexdigest() == digest
    assert (STATIC / "vendor" / "LICENSE-preact.txt").read_text().startswith("The MIT License")
    assert "Apache License" in (STATIC / "vendor" / "LICENSE-htm.txt").read_text()


def test_the_vendored_font_matches_its_recorded_checksums():
    fonts = STATIC / "fonts"
    recorded = {
        name: digest
        for digest, name in re.findall(
            r"^([0-9a-f]{64})  (\S+\.woff2)$", (fonts / "SOURCES.txt").read_text(), re.M
        )
    }

    assert len(recorded) == 6
    for name, digest in recorded.items():
        assert hashlib.sha256((fonts / name).read_bytes()).hexdigest() == digest
        assert f"/static/fonts/{name}" in (STATIC / "app.css").read_text()
    assert "SIL Open Font License" in (fonts / "LICENSE-ibm-plex-sans.txt").read_text()


def test_the_editor_stays_flat():
    # The look is deliberately plain: no gradients, no frosted glass, and only the motion
    # that answers something the user did.
    css = (STATIC / "app.css").read_text()
    scripts = "".join(p.read_text() for p in (STATIC / "js").glob("*.js"))

    for banned in ("gradient", "backdrop-filter", "text-shadow"):
        assert banned not in css
        assert banned not in scripts
    assert set(re.findall(r"@keyframes (\S+)", css)) == {"spin", "open", "flash"}
    icons = run(demo.DemoDevice(delay=0).icons(list(demo.installed_apps())))
    assert not any(b"Gradient" in data for data in icons.values())


def test_every_module_and_asset_the_page_loads_exists():
    page = (STATIC / "index.html").read_text()
    referenced = re.findall(r'"/static/([^"]+)"', page)
    for script in (STATIC / "js").glob("*.js"):
        text = script.read_text()
        for target in re.findall(r'from "\./([^"]+)"', text):
            assert (STATIC / "js" / target).is_file(), f"{script.name} imports {target}"
        for bare in re.findall(r'from "([a-z][^".]*)"', text):
            assert f'"{bare}"' in page, f"{script.name} imports {bare} without an import map entry"

    assert referenced
    for path in referenced:
        assert (STATIC / path).is_file(), path


def test_the_page_has_no_inline_code_besides_the_import_map():
    page = (STATIC / "index.html").read_text()

    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", page, re.S)
    inline = [attrs for attrs, body in scripts if body.strip()]
    assert inline == [' type="importmap"']
    assert "style=" not in page
    assert "on" + "click" not in page.lower()


# ------------------------------------------------------------------ the command


def test_editor_help_lists_the_connection_and_editor_options(capsys):
    with pytest.raises(SystemExit):
        main(["editor", "--help"])

    text = capsys.readouterr().out
    for flag in ("--wifi", "--udid", "--port", "--no-browser", "--demo", "--verify-attempts"):
        assert flag in text
    assert "--yes" not in text


def test_editor_without_the_web_dependencies_explains_how_to_install(monkeypatch, capsys):
    import ios_homescreen.ui as ui

    def missing(options, say):
        raise ui.UIUnavailable("the browser UI needs Starlette and uvicorn")

    monkeypatch.setattr(ui, "serve", missing)

    assert main(["editor", "--demo", "--no-browser"]) == 1
    assert "needs Starlette and uvicorn" in capsys.readouterr().err


def test_editor_passes_the_options_through(monkeypatch, tmp_path):
    import ios_homescreen.ui as ui

    seen = []
    monkeypatch.setattr(ui, "serve", lambda options, say: seen.append(options) or 0)

    main(
        [
            "editor",
            "--wifi",
            "--udid",
            "U",
            "--port",
            "8123",
            "--no-browser",
            "--data-dir",
            str(tmp_path),
        ]
    )

    (options,) = seen
    assert options.transport == api.Transport(wifi=True, udid="U")
    assert (options.port, options.open_browser, options.demo) == (8123, False, False)
    assert options.data_dir == tmp_path
    assert options.backup_dir == tmp_path / "backups"


def test_editor_showcase_passes_the_layout_file_through(monkeypatch, tmp_path):
    import ios_homescreen.ui as ui

    seen = []
    monkeypatch.setattr(ui, "serve", lambda options, say: seen.append(options) or 0)
    layout = tmp_path / "showcase.toml"
    layout.write_text('[showcase]\nlibrary = ["Maps"]\n[dock]\nitems = ["Phone"]\n')

    assert main(["editor", "--showcase", str(layout), "--wifi"]) == 0

    (options,) = seen
    assert options.showcase == layout
    assert options.transport == api.Transport(wifi=True)
    assert options.demo is False


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (None, "No such file"),
        ("[dock\n", "invalid TOML"),
        ('[showcase]\nlibary = ["Maps"]\n', "unknown key(s) in [showcase]: libary"),
    ],
)
def test_editor_showcase_checks_the_file_before_starting(
    monkeypatch, tmp_path, capsys, text, message
):
    import ios_homescreen.ui as ui

    monkeypatch.setattr(ui, "serve", lambda options, say: pytest.fail("must not start"))
    layout = tmp_path / "showcase.toml"
    if text is not None:
        layout.write_text(text)

    assert main(["editor", "--showcase", str(layout)]) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("table", "files", "message"),
    [
        ('wallpaper = "wall.png"\n', {"wall.png": b"not an image"}, "is not a PNG or JPEG"),
        ('wallpaper = "gone.png"\n', {}, "No such file"),
        ('before = "gone.toml"\n', {}, "No such file"),
        ('before = "bad.toml"\n', {"bad.toml": b"[dock\n"}, "[showcase] before = 'bad.toml'"),
    ],
)
def test_editor_showcase_checks_its_wallpaper_and_before_files(
    monkeypatch, tmp_path, capsys, table, files, message
):
    import ios_homescreen.ui as ui

    monkeypatch.setattr(ui, "serve", lambda options, say: pytest.fail("must not start"))
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    layout = tmp_path / "showcase.toml"
    layout.write_text("[showcase]\n" + table + '[dock]\nitems = ["Phone"]\n')

    assert main(["editor", "--showcase", str(layout)]) == 1
    assert message in capsys.readouterr().err


def test_every_job_the_page_follows_ends_in_the_servers_state():
    # The editor starts the first read itself, so the page often finds it running. A job
    # followed without reloading the state afterwards ended on an empty phone with no
    # error (seen with a Wi-Fi read that failed after its retry).
    actions = (STATIC / "js" / "actions.js").read_text()
    settle = actions[actions.index("async function settle(") :]
    settle = settle[: settle.index("\n}\n")]

    assert actions.count("await follow(") == 1
    assert "await follow(" in settle
    assert "await reload(" in settle
    assert actions.count("await settle(") == 4  # boot, read, apply, restore
