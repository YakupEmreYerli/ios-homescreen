<h1 align="center">ios-homescreen</h1>

<p align="center">
Read your iPhone's home screen, plan a new layout in a text file, and write it back safely from Linux, over USB or Wi-Fi.
</p>

<p align="center">
<a href="https://github.com/YakupEmreYerli/ios-homescreen/actions/workflows/ci.yml"><img src="https://github.com/YakupEmreYerli/ios-homescreen/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
<img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776ab" alt="Python 3.11, 3.12, 3.13">
</p>

<p align="center"><a href="README.tr.md">Türkçe</a></p>

![ios-homescreen](docs/assets/banner.png)

Rearranging dozens of icons by dragging them around on the phone is slow. ios-homescreen
saves the current layout to your computer, turns it into a TOML file you can edit in any
text editor, checks your edits offline, and writes the result to the phone. Every write is
backed up first, verified by reading the phone again, and rolled back automatically if the
phone does not end up with the layout you asked for.

## Features

- Exports the dock, pages, folders (including multi-page folders), widgets, widget stacks,
  web clips, Safari web apps and offloaded apps to an editable TOML file.
- Refers to apps by bundle id or by the name under the icon.
- Checks a layout before anything touches the phone: unknown or duplicate items, a full dock,
  pages over 24 cells (widgets count by size), empty or nested folders, widgets in folders.
- Apps you leave out of the layout go to the App Library and stay there.
- Shows what will move, what goes to the App Library and what comes back before you write.
- Writes only with an explicit `--yes`, after a backup, and checks the result by reading the
  phone again. If the check fails, the backup is written back.
- Works over USB, or over Wi-Fi (iOS 17 and later) after a one-time setup over USB. Neither
  needs root or Developer Mode.
- Keeps reads, backups and plans in `~/.local/share/ios-homescreen`, not in the current directory.
- Can be used from Python: the CLI is a thin layer over `ios_homescreen.api`.

## Requirements

- Linux. macOS may work but has not been tested.
- Python 3.11 or newer.
- `usbmuxd`, installed and running. Most distributions ship it as `usbmuxd`
  (`sudo pacman -S usbmuxd`, `sudo apt install usbmuxd`, `sudo dnf install usbmuxd`).
- An iPhone that trusts this computer. Connect it with a cable, unlock it and tap
  **Trust This Computer**, then enter the passcode. You need to do this once.

## Install

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/YakupEmreYerli/ios-homescreen
```

With [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/YakupEmreYerli/ios-homescreen
```

From a clone, for development:

```bash
git clone https://github.com/YakupEmreYerli/ios-homescreen
cd ios-homescreen
uv sync
uv run ios-homescreen --help
```

## Quick start

```bash
# 1. Save the current layout. Read-only; nothing is written to the phone.
ios-homescreen read

# 2. Turn the newest read into a layout file and edit it.
ios-homescreen export -o layout.toml
$EDITOR layout.toml

# 3. Check the layout and see what would change. Offline.
ios-homescreen plan layout.toml -o plan.plist

# 4. Write it. Backup, write, verify, and roll back if needed.
ios-homescreen apply plan.plist --yes
```

To undo, restore the backup that `apply` printed:

```bash
ios-homescreen restore ~/.local/share/ios-homescreen/backups/backup-20261010-101500-000000.plist --yes
```

## Commands

| Command | What it does | Talks to the phone |
| --- | --- | --- |
| `read` | Saves the layout and the installed apps as a read snapshot, plus a text summary | Reads only |
| `export [READ]` | Prints the layout of a read (the newest by default) as TOML, or writes it with `-o FILE` | No |
| `plan LAYOUT` | Checks a layout against a read (`--read`, newest by default), shows the changes and saves a plan | No |
| `apply PLAN --yes` | Backs up, writes the plan, verifies it and rolls back on failure | Writes |
| `restore BACKUP --yes` | Writes a backup or read snapshot back, with the same safety steps | Writes |
| `diff BEFORE AFTER` | Compares two saved layouts (reads, backups, plans, or plist/JSON state dumps) | No |
| `wifi status\|enable\|disable` | Sets up, checks or turns off Wi-Fi access to the phone | Yes |

Options for `export` and `plan`: `-o/--output FILE`, and `--allow-removal` for `plan` (see the
layout reference). `read` takes `-o/--output DIR`. `apply` takes `--force` (see the safety model).
Every command except `diff` and `wifi` takes `--data-dir DIR`.

Connection options, for `read`, `apply`, `restore` and `wifi`:

| Option | Meaning |
| --- | --- |
| *(none)* | USB through usbmuxd |
| `--wifi` | Wi-Fi (iOS 17 or later); run `wifi enable` over USB once first |
| `--udid UDID` | Pick a device when several are connected or paired |
| `--discovery-timeout SECONDS` | How long to listen for Bonjour answers (default 5) |
| `--connect-timeout SECONDS` | Time limit for opening the connection (default 30) |

Write options, for `apply` and `restore`:

| Option | Meaning |
| --- | --- |
| `--yes` | Required. Without it the phone is not contacted at all |
| `--backup-dir DIR` | Where the automatic backup goes (default `DATA_DIR/backups`) |
| `--verify-attempts N` | Re-reads used to verify the write (default 6) |
| `--verify-interval SECONDS` | Pause between those re-reads (default 3) |
| `--write-timeout SECONDS` | Time limit for sending the layout (default 10) |
| `--read-timeout SECONDS` | Time limit for each read (default 30) |

Exit codes: `0` done; `1` error (`apply` and `restore` stop before writing); `2` usage error
or `--yes` missing; `3` the new layout did not verify and the backup was restored; `4` the
restore did not verify either. The backup file is kept in every case.

## Layout file

A layout has a `[dock]` table and one `[[pages]]` table per page, each with an `items`
array in home screen order: left to right, top to bottom.

```toml
[dock]
items = ["Phone", "Safari", "Messages", "Camera"]

[[pages]]
items = [
  { type = "widget", id = "6F1D3A52-0000-4000-8000-000000000001" },  # Weather, medium
  "com.apple.mobilecal",        # Calendar, by bundle id
  "Mail",                       # or by the name under the icon
  { type = "folder", name = "Utilities", items = ["Calculator", "Voice Memos", "Find My"] },
  { type = "folder", name = "Media", pages = [["Music", "Podcasts", "TV"], ["Books"]] },
  { type = "webclip", id = "0A1B2C3D4E5F40718293A4B5C6D7E8F9" },  # a Safari bookmark
  { type = "webapp", id = "9E8D7C6B-0000-4000-8000-000000000002" },  # a Safari web app
]

[[pages]]
items = ["Health", "Wallet"]
```

[`examples/layout.toml`](examples/layout.toml) is a complete example with Apple's stock apps.
Start from `export` instead: it fills in your real ids and adds a comment with the name of
every item.

| Item | How to write it | Notes |
| --- | --- | --- |
| App | `"com.apple.Maps"` or `"Maps"` | A bundle id, or the app's name if only one app has it. `{ type = "app", id = "com.apple.Maps" }` also works and takes ids only. Any installed app can be added, including apps that are only in the App Library. |
| Folder | `{ type = "folder", name = "Work", items = [...] }` | `pages = [[...], [...]]` instead of `items` for a folder with several pages. Holds apps, web clips and web apps. |
| Widget or widget stack | `{ type = "widget", id = "..." }` | Small 4 cells, medium 8, large 16. Not allowed in the dock or in folders. |
| Web clip | `{ type = "webclip", id = "..." }` | A bookmark added with Add to Home Screen. Can be moved, not removed (see below). |
| Safari web app | `{ type = "webapp", id = "..." }` | A site added with Add to Home Screen and "Open as Web App" (iOS 26 and later). It has Safari's bundle id and its own id; it is a separate item from Safari. Can be moved, not removed. |

Rules the planner enforces:

- The dock holds at most 4 items. A page holds 24 cells; an app, folder, web clip or web app
  takes one.
- Each item appears once. Two widgets from the same app are different items with different ids.
- Folders need a name and at least one item, and cannot contain folders or widgets.
- Widgets, web clips and web apps can be moved, but a layout file cannot create them: they
  are referenced by the id they had in the read, and the planner copies the phone's own data
  for them unchanged. Leaving out a widget is an error unless you pass `plan --allow-removal`.
- Web clips and Safari web apps cannot be removed by a write at all. When a written layout
  leaves one out, the phone puts it back on a new last page, the check after writing fails
  and the backup is restored. So the planner refuses such a layout (code `not_removable`),
  even with `--allow-removal`. Delete them on the phone (touch and hold, then Delete
  Bookmark), then `read` again.
- Every installed app that is not in the layout goes to the App Library.
- Unknown keys are errors, so a typo such as `itmes` does not silently empty a page.

`plan` reports every problem it finds with its place, for example
`page 2, item 5: unknown app 'Mpas'`.

## How the safety model works

The home screen protocol is undocumented, and two of its behaviours caused real damage while
this tool was being built. The design works around both.

1. The phone has to be told which apps to keep off the home screen. When `setIconState`
   receives only a list of pages, SpringBoard appends every installed app that is not on
   that list to the end of the home screen, App Library apps and Apple's stock apps
   included. ios-homescreen always sends `{buttonBar, iconLists, ignored}`, where `ignored`
   lists every installed User and System app that is not on the home screen. It recomputes
   that list from the apps installed at the moment of writing.
2. A write gets no reliable answer. SpringBoard often never replies to `setIconState`, and
   pymobiledevice3's `set_icon_state` waits for that reply forever. ios-homescreen sends the
   request itself with a time limit and treats a missing reply as "unknown". The proof is a
   fresh read of the phone that matches the plan.

Every `apply` and `restore` runs the same steps:

1. Read the current layout and save it as a timestamped backup.
2. Stop if the layout differs from the read the plan was made from (the phone was changed in
   the meantime). `--force` skips this check. `restore` has no such check.
3. Send the layout with a time limit.
4. Read the layout again on a new connection, up to `--verify-attempts` times, and compare it
   with the plan: kinds, ids and order on every page and in every folder.
5. If it never matches, write the backup back the same way and verify that too.

Without `--yes`, `apply` and `restore` only check the file and exit with code 2; they do not
connect to the phone. Reads, backups and plans are binary plists because the layout contains
dates and binary data that JSON would lose.

## Wi-Fi

Wi-Fi needs iOS 17 or later. Set it up once, with the phone connected over USB:

```bash
ios-homescreen wifi enable     # over USB, once
ios-homescreen wifi status     # the setting, the pairing, and whether the phone answers on Wi-Fi
```

`wifi enable` turns on the phone's Wi-Fi connections setting and pairs this computer for
Wi-Fi with RemotePairing, the mechanism Xcode uses for wireless devices. The computer is
already trusted over USB, so the phone shows no prompt. Root, Developer Mode and a tunnel
service are not needed: the connection runs through pymobiledevice3's userspace network stack
inside the ios-homescreen process.

After that, add `--wifi` to `read`, `apply` or `restore`. The phone must be on the same
network as the computer, awake and unlocked. ios-homescreen looks for it with Bonjour
(`_remotepairing._tcp`) for `--discovery-timeout` seconds and recognises it by the pairing,
not by its address (iOS uses private, changing Wi-Fi addresses). If this computer is paired
with several phones, pass `--udid`.

The pairing is a file kept by pymobiledevice3: `~/.local/share/pymobiledevice3/remote_<UDID>.plist`,
or `~/.pymobiledevice3/` if that folder already exists. It holds the key that lets this
computer talk to the phone; ios-homescreen never copies or sends it. `wifi disable` turns the
phone's setting off, and `wifi disable --forget` also deletes the pairing file.

The older way of reaching a phone over the network, lockdown on port 62078 found as
`_apple-mobdev2._tcp`, is not used: current iOS versions accept that connection but close
every service on the first request.

## Files and environment

| What | Default | Override |
| --- | --- | --- |
| Reads, backups, plans | `$XDG_DATA_HOME/ios-homescreen`, or `~/.local/share/ios-homescreen` | `--data-dir`, `IOS_HOMESCREEN_DATA_DIR` |
| App icon cache (Python API) | `$XDG_CACHE_HOME/ios-homescreen`, or `~/.cache/ios-homescreen` | `IOS_HOMESCREEN_CACHE_DIR` |
| Wi-Fi pairing (pymobiledevice3) | `$XDG_DATA_HOME/pymobiledevice3`, or `~/.local/share/pymobiledevice3` | `XDG_DATA_HOME` |

Inside the data directory: `reads/read-*.plist` with a `.txt` summary next to each,
`backups/backup-*.plist` and `plans/plan-*.plist`. Nothing is written to the current
directory unless you pass a path there.

## Python API

```python
import asyncio
from ios_homescreen import api


async def main():
    device = await api.connect(api.Transport())  # api.Transport(wifi=True) for Wi-Fi
    try:
        snapshot = await api.read_device(device)
        view = api.describe(snapshot)  # JSON-ready layout for a UI
        plan = api.plan_layout(api.to_document(view), snapshot)
        result = await api.apply_plan(
            device,
            plan.payload,
            backup_dir=api.data_dir() / "backups",
            on_event=lambda event: print(event.message),
        )
        print(result.status)
    finally:
        await device.close()


asyncio.run(main())
```

Progress arrives as `Event` objects with a stable `code`; results and errors have `to_dict()`
and machine-readable codes. `api.fetch_icons` returns app icons as PNG bytes.

## Limitations

- The protocol has no setting for hidden home screen pages, so ios-homescreen cannot hide or
  show pages.
- The Today view and Lock Screen widgets are not part of the home screen layout and are out
  of scope.
- Widgets can be moved or removed but not created. Web clips and Safari web apps can only be
  moved; delete them on the phone.
- Writing a layout can put widgets where you chose what they show, such as a stack's selected
  widget, back to their default choice: SpringBoard drops that choice on a write (seen on
  iOS 27). The check after writing ignores it for that reason.
- Wi-Fi needs iOS 17 or later.
- Page capacity uses the iPhone grid (6 by 4). iPads have not been tested.
- The layout format is Apple's and undocumented, and an iOS update can change it. Run `read`
  first after an update; the backup and rollback are there for the case where it changes.
- The write format was verified on an iPhone 15 with iOS 26 and iOS 27.

## Troubleshooting

`no iPhone found over USB`: plug the phone in, unlock it, and check that usbmuxd is running
(`systemctl status usbmuxd`). On some distributions udev starts usbmuxd only when a device
appears.

A command hangs or every connection times out after an earlier session: usbmuxd sometimes
stops responding after a session. Restart it with `sudo systemctl restart usbmuxd` and
reconnect the phone.

`Mux error -8`, or a pairing error, on the first connection: the phone has not trusted this
computer yet. Unlock it, tap **Trust This Computer**, enter the passcode and run the command
again.

`the iPhone did not answer on the network`: check that the phone and the computer are on the
same network and that the phone is awake and unlocked; `wifi status` over USB shows whether it
answers. Guest networks and client isolation keep the two apart, and firewalls must allow mDNS
(UDP 5353).

`this computer has no Wi-Fi pairing yet`, or a pairing made by an older pymobiledevice3: run
`wifi enable` over USB again.

`the device layout changed since the read`: the phone was edited after your `read`. Run
`read` again and plan again, or use `--force` if you are sure.

Exit code 3 (rolled back): the phone did not show the new layout in time. SpringBoard can be
slow, especially over Wi-Fi. Try `--verify-attempts 10 --verify-interval 5`.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and the pitfalls behind the design.
Report security problems privately as described in [SECURITY.md](SECURITY.md).

## Credits

The dictionary payload with an `ignored` list comes from what
[chungty/unjiggle](https://github.com/chungty/unjiggle) pull request #4 found about
`setIconState`. The notes on the icon state format in [facebook/idb](https://github.com/facebook/idb)
helped too. No code was copied from either project.

Device communication goes through [pymobiledevice3](https://github.com/doronz88/pymobiledevice3),
including its RemotePairing support and userspace tunnel for Wi-Fi, and USB access through
[usbmuxd](https://github.com/libimobiledevice/usbmuxd) from the libimobiledevice project.

## License

[MIT](LICENSE). ios-homescreen depends on pymobiledevice3, which is licensed GPL-3.0-or-later;
if you distribute the two together as one program, that combination falls under the GPL.
