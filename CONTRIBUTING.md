# Contributing

Thanks for helping. Bug reports with the exact command and its output are as useful as code.

## Setup

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/YakupEmreYerli/ios-homescreen
cd ios-homescreen
uv sync
```

Before you push, run what CI runs:

```bash
uv run ruff check
uv run ruff format --check     # `uv run ruff format` fixes it
uv run pytest
```

CI runs the tests on Python 3.11, 3.12 and 3.13. To try another version locally:
`uv run --python 3.11 pytest`.

To try the browser editor without a phone: `uv run ios-homescreen editor --demo`.

## Layout of the code

| Module | Role |
| --- | --- |
| `state.py` | Icon state: plist storage, item kinds and ids, cell counts, comparison, the safe payload, validation |
| `planner.py` | TOML or JSON layout to plan payload; collects every problem with a code and a location, and lists the changes |
| `export.py` | Pull snapshot to an editable TOML layout |
| `snapshots.py`, `storage.py` | Pull snapshot and backup files, the data directory, and the `[pull]` link from a layout file |
| `report.py` | Plain-text change lists and summaries |
| `model.py` | JSON view of a read for a UI, back to a layout document, and the change list between two views |
| `workflow.py` | Backup, drift check, timed write, verify by re-reading, rollback |
| `device.py` | The only code that talks to SpringBoard and Installation Proxy; every call has a time limit |
| `transport.py` | USB connection, or Wi-Fi through RemotePairing and pymobiledevice3's userspace tunnel |
| `api.py` | The Python API; no printing, progress through `Event` callbacks |
| `cli.py` | argparse, printing and the y/N question on top of `api.py` |
| `ui/` | The browser editor: `session.py` (jobs, icons, planning), `app.py` (HTTP API), `security.py` (token, Host and Origin checks), `demo.py` (the pretend phone), `static/` (the page) |

The core never prints. If you need to report progress, emit an `Event` with a stable `code`.

## For AI agents

`docs/agent-guide.md` is written for AI coding agents that set up and use the tool for
someone; `llms.txt` points to it, and `skills/ios-homescreen/SKILL.md` is the same workflow
as a Claude Code skill that defers to the guide. When a command, flag, JSON field or error
code changes, update the guide (and the skill if it names it). `tests/test_docs.py` checks
that every command and flag they mention exists, that the error codes in the guide are
real, and that the skill's frontmatter is valid. The `--json` output is a public
interface: add fields rather than rename them.

## The browser editor

The page is plain JavaScript modules in `src/ios_homescreen/ui/static/js`, written with
[Preact](https://preactjs.com) and [htm](https://github.com/developit/htm) (tagged templates
instead of JSX). There is no build step and no Node.js: the browser loads the modules as they
are, and the wheel ships them as package data. Edit a file, reload the page.

- `actions.js` holds every action (edits with undo/redo, validation, device jobs);
  `ops.js` the pure edits on a draft layout; `layout.js` the phone geometry and how items
  flow into the 4 x 6 grid; `drag.js` the pointer-based drag and drop; `preview.js` what the
  phone shows while dragging, so the preview and the drop use the same code.
- The server is the only judge of a layout: after each edit the page sends it to
  `POST /api/plan`, which runs the real planner and returns issues with their codes and the
  change list (`model.describe_changes`). The page only refuses drops that cannot be shown,
  like a fifth dock item.
- `static/vendor` holds unmodified copies of Preact and htm, with their licenses and
  `SOURCES.txt` (versions, URLs, SHA-256). To update them, run `npm pack preact@VERSION
  htm@VERSION` in an empty directory, unpack, copy the files listed in `SOURCES.txt`, and
  update the versions and checksums there; `tests/test_ui_parts.py` checks them.
- `static/fonts` holds IBM Plex Sans (latin and latin-ext, three weights) with its OFL license
  and checksums; update it the same way from `@fontsource/ibm-plex-sans`.
- Keep the Content Security Policy intact: no inline scripts or styles in `index.html`
  (the import map is allowed by its hash, computed at start), no `eval`.
- Keep the look plain: flat colours, no gradients, blur or text shadows, and motion only
  where it answers the user (drag, reflow, folder open, progress). `test_the_editor_stays_flat`
  checks the first part. Translucent flat fills are fine where the wallpaper should show
  through (dock, folders).
- The wallpaper comes from SpringBoard's `getHomeScreenWallpaperPNGData` after each read
  and is cached per device next to the icons; without it the screen keeps the flat colour.
  iOS 27 drops that request over Wi-Fi (ConnectionTerminatedError on 27.0.1), so the call
  has a short time limit and a phone that sent nothing is not asked again in that session.
  Do not use `getWallpaperPreviewImage` instead: it returns a screenshot of the home screen,
  icons and badges included.
  Widgets are drawn from what the layout says about them (size, stack, app, widget
  identifier). The phone sends no picture of a widget's content, so the editor draws none.
- Check UI changes in a real browser, in demo mode, and at a narrow window width.

## Screenshots for the README

`docs/assets/ui.png` should show a real phone's icons and widgets, but not the rest of
that phone. `editor --showcase LAYOUT` does that: it reads the phone, shows LAYOUT instead
of the phone's own layout, and never writes. The page looks like the normal editor, so the
terminal says when it starts in this mode; Apply only opens a notice, Restore is refused
and backups are not listed (the server refuses writes, and the device is wrapped so a write
fails anyway). The phone is called by its model instead of its name, and the App Library
lists only the apps in the file's optional `[showcase]` table:

```toml
[showcase]
library = ["Translate", "Stocks", "com.apple.measure"]   # names or bundle ids
wallpaper = "wallpaper.png"   # PNG or JPEG, relative to this file
before = "before.toml"        # the change list is computed from this layout

[dock]
items = ["Phone", "Safari", "Messages", "Camera"]

[[pages]]
items = [
  { type = "widget", id = "..." },   # widget ids from `ios-homescreen pull`
  "Calendar", "Photos", "Mail", "Maps",
  { type = "folder", name = "Utilities", items = ["Calculator", "Voice Memos"] },
]
```

- `wallpaper` is the phone background. iOS 27 does not send its wallpaper over Wi-Fi, so
  without this key the screen is a plain colour.
- `before` is a second layout file. The editor counts the changes from it, so the change
  list is filled without dragging anything; it may hold other apps and fewer or more
  widgets than the shown layout.
- A showcase layout may leave out widgets, web clips and web apps.

```bash
uv run ios-homescreen editor --showcase showcase.toml          # add --wifi for Wi-Fi
uv run ios-homescreen editor --demo --showcase showcase.toml   # the same on the demo phone
```

Read from phone loads the files again, so they can be adjusted while the editor runs. Take
the screenshot at 1600 x 1000 and run `magick mogrify -strip` on it.

## Tests

No test may talk to a real device, usbmuxd or the network. Device behaviour is simulated:

- `tests/fakes.py` has `FakeSpringBoard`, which reproduces the dangerous parts of SpringBoard:
  a list-form write re-adds every unlisted app, `iconType` folders vanish, pages overflow at
  24 cells, and a write can go unanswered or be ignored. A new safety rule needs a test against it.
- `tests/samples.py` builds a realistic home screen from Apple stock apps and `com.example.*`
  placeholders. Never commit data read from your own phone, not even as a fixture.
- `FakeWifiBackend` in `tests/fakes.py` stands in for the USB lockdown, the RemotePairing
  records, the network lookup and the Wi-Fi tunnel.
- `tests/test_ui_server.py` drives the browser editor's HTTP API with Starlette's test client
  against the fakes, including the security checks.
- `tests/test_pymobiledevice3_contract.py` checks the pymobiledevice3 functions we rely on
  (imports only).

## Pitfalls: why the code is the way it is

Each of these was learned on a real phone. Please keep them unless you have tested the
alternative on a device.

- Always write the dictionary form `{buttonBar, iconLists, ignored}`. With the list form, or
  with a dictionary whose `ignored` list is incomplete, SpringBoard appends every installed app
  that is missing from the payload to the end of the home screen, including archived apps.
- `ignored` must contain every installed User and System app that is not on the home screen.
  User apps alone are not enough: Apple's stock apps come back. Installation Proxy's
  `ApplicationType` tells them apart; plugins and other types are left out.
- About 200 of the System apps are hidden services (AirDropUI, AccountAuthenticationDialog and
  the like): Installation Proxy tags them with `hidden` in `SBAppTags`. They still belong in
  `ignored`, but they are not App Library apps and are not offered by name.
- Recompute `ignored` at write time from the apps installed then. Apps get installed and
  deleted between a read and a write.
- Folders are written as `{"listType": "folder", "displayName", "iconLists": [[...]]}`. A
  folder written with `iconType: folder` disappears without an error.
- Reuse the dictionaries from the read for every existing item. Widgets, widget stacks, web
  clips, Safari web apps and offloaded apps carry data we do not understand, and it has to go
  back unchanged. Only an app new to the home screen gets the minimal
  `{"bundleIdentifier": id, "displayIdentifier": id}`.
- An item's id is its `displayIdentifier` when it has one. Widgets carry their extension's
  bundle id (two widgets from one app share it), and Safari web apps carry Safari's bundle id.
  Keying by `bundleIdentifier` makes them collide. A web app does not count as Safari when
  computing `ignored`.
- Never call pymobiledevice3's `set_icon_state` or `reload_icon_state`. The second reads the
  layout and writes it back in the list form, which is the accident above; the first waits
  forever for a reply SpringBoard usually does not send. The SpringBoard service that
  `device.py` creates refuses both, and a test fails if the code calls them. `device.py`
  sends the plist on the raw service connection with a time limit and waits only briefly
  for a reply.
- A reply proves nothing. Success is a re-read on a new service connection that matches the
  plan. Without that proof, the workflow writes the backup back.
- Store reads, backups and plans as binary plist. The state has `datetime` and `bytes` values
  that JSON loses.
- A write needs a yes: `y` at the prompt, `--yes`, or Apply in the editor. Without a terminal
  and without `--yes`, `push` and `restore` must not even connect. Validate input files before
  connecting, and check for a changed phone before asking.
- A layout file names its pull in `[pull]`; that name is only ever looked up inside
  `DATA_DIR/pulls`. After a verified push, the CLI saves the new phone state as a pull and
  points the file at it, so the next push compares against what the phone really has.
- Import pymobiledevice3 lazily, inside functions. `--help` and the tests must not need it.
- Wi-Fi uses RemotePairing, not lockdown over TCP. On iOS 17 and later the phone answers on
  port 62078 (`_apple-mobdev2._tcp`) and even validates the pairing, but closes every service
  on the first request. The `_apple-mobdev2` answer also carries the private, changing Wi-Fi
  MAC address, so matching it against the pair record never worked.
- The RemotePairing record is made over USB with `RemotePairingLockdownService` (promptless,
  since the computer is trusted). The phone closes the channel when pairing completes; that
  shows up as `RemotePairingCompletedError` and means success. Records without the phone's
  `peer_alt_irk` (made by older pymobiledevice3 versions) cannot be matched on the network;
  `wifi setup` replaces them.
- pymobiledevice3's Bonjour browse often gets no answer for 5 to 20 seconds while the phone
  keeps advertising on the same address and port for hours. `transport.locate` therefore
  races a direct `RemotePairingTunnelService` connection to the address remembered from the
  last success (`wifi-addresses.json` in the cache directory, `autopair=False`) against the
  browse, which gets two tries within `--discovery-timeout`. Whichever answers first wins;
  everything else is cancelled and closed.
- The Wi-Fi session is pymobiledevice3's `UserspaceRsdTunnel` fed with the service that
  `get_remote_pairing_tunnel_services` (or the direct connection) found. The tunnel asks a module function for its
  provider; `transport.py` swaps that function only for the length of `aopen()` and puts it
  back. Only one userspace tunnel can exist per process, so close a Wi-Fi device before
  opening the next one (the browser editor runs one job at a time for this reason).
- Web clips and Safari web apps cannot be removed by `setIconState`: SpringBoard puts a
  left-out web clip back on a new last page (seen on iOS 27), so verification fails and the
  write is rolled back. The planner refuses such layouts with `not_removable`. Widgets can be
  removed.
- `userSelectedElementIdentifier` is not part of the layout comparison: SpringBoard drops it
  on a write and Smart Rotate changes it on its own.

## pymobiledevice3 version

The dependency is pinned exactly (`pymobiledevice3==11.26.0`) because the tool uses parts of
it that are not a stable API (the raw service connection, RemotePairing over USB, the
RemotePairing Bonjour lookup and the userspace tunnel's provider hook) and that version was
checked on real phones. To bump it:

1. Change the pin and run `uv lock`.
2. Run the tests, including `tests/test_pymobiledevice3_contract.py`.
3. On a real phone: `pull`, move one app in the file, `push`, then `restore latest`. Do it
   over USB and over Wi-Fi, and say in the pull request what you tested.

## Commits and pull requests

- Commit messages in English, conventional style: `feat:`, `fix:`, `docs:`, `test:`, `ci:`,
  `refactor:`. Imperative subject; the body says why.
- Keep pull requests focused. Update `README.md` and `README.tr.md` when commands, flags or the
  layout format change.
- Say whether you tested on a device, and which model and iOS version.
