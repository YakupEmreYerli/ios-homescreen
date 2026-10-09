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

## Layout of the code

| Module | Role |
| --- | --- |
| `state.py` | Icon state: plist storage, item kinds and ids, cell counts, comparison, the safe payload, validation |
| `planner.py` | TOML or JSON layout to plan payload; collects every problem with a code and a location |
| `export.py` | Read snapshot to an editable TOML layout |
| `model.py` | JSON view of a read for a UI, and back to a layout document |
| `workflow.py` | Backup, drift check, timed write, verify by re-reading, rollback |
| `device.py` | The only code that talks to SpringBoard and Installation Proxy; every call has a time limit |
| `transport.py` | USB or network connection, pair records, Bonjour matching |
| `api.py` | The Python API; no printing, progress through `Event` callbacks |
| `cli.py` | argparse and printing on top of `api.py` |

The core never prints. If you need to report progress, emit an `Event` with a stable `code`.

## Tests

No test may talk to a real device, usbmuxd or the network. Device behaviour is simulated:

- `tests/fakes.py` has `FakeSpringBoard`, which reproduces the dangerous parts of SpringBoard:
  a list-form write re-adds every unlisted app, `iconType` folders vanish, pages overflow at
  24 cells, and a write can go unanswered or be ignored. A new safety rule needs a test against it.
- `tests/samples.py` builds a realistic home screen from Apple stock apps and `com.example.*`
  placeholders. Never commit data read from your own phone, not even as a fixture.
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
- Never call pymobiledevice3's `set_icon_state`: it waits forever for a reply SpringBoard
  usually does not send. `device.py` sends the plist on the raw service connection with a
  time limit and waits only briefly for a reply.
- A reply proves nothing. Success is a re-read on a new service connection that matches the
  plan. Without that proof, the workflow writes the backup back.
- Store reads, backups and plans as binary plist. The state has `datetime` and `bytes` values
  that JSON loses.
- Writes need `--yes`, and without it the command must not even connect. Validate input files
  before connecting.
- Import pymobiledevice3 lazily, inside functions. `--help` and the tests must not need it.
- Over TCP, pass the pair record to `create_using_tcp` yourself. pymobiledevice3 would look it
  up by host name and find nothing. Never start pairing over Wi-Fi (`autopair=False`).
- usbmuxd's pair record directory also holds files that are not pair records, such as
  `SystemConfiguration.plist`; skip them.

## pymobiledevice3 version

The dependency is pinned exactly (`pymobiledevice3==11.12.5`) because the tool uses parts of
it that are not a stable API (the raw service connection, lockdown over TCP, Bonjour
browsing) and that version was checked on real phones. To bump it:

1. Change the pin and run `uv lock`.
2. Run the tests, including `tests/test_pymobiledevice3_contract.py`.
3. On a real phone: `read`, then `apply` a plan that only moves one app, then `restore` the
   backup. Do it over USB and over Wi-Fi, and say in the pull request what you tested.

## Commits and pull requests

- Commit messages in English, conventional style: `feat:`, `fix:`, `docs:`, `test:`, `ci:`,
  `refactor:`. Imperative subject; the body says why.
- Keep pull requests focused. Update `README.md` and `README.tr.md` when commands, flags or the
  layout format change.
- Say whether you tested on a device, and which model and iOS version.
