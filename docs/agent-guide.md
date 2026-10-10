# ios-homescreen: guide for AI agents

You are helping a person rearrange their iPhone home screen with `ios-homescreen`, a
command-line tool. It reads the home screen into a text file (`layout.toml`), you edit that
file, and it writes the result back to the phone over USB or Wi-Fi. This page is everything
you need. Source: <https://github.com/YakupEmreYerli/ios-homescreen>.

## Rules

1. **Never write to the phone without the person's explicit yes.** Before `push` or
   `restore`, show the change list in plain words and ask. Run `push --yes` or
   `restore ... --yes` only after they said yes to that exact list, in this conversation.
   If the file changes after that, show the new list and ask again.
2. Never pass `--force` (write over changes made on the phone since the pull, or restore
   another iPhone's backup) or `--allow-removal` (delete widgets) unless the person asked for
   that after you explained what it does.
3. Never leave web clips (`type = "webclip"`) or Safari web apps (`type = "webapp"`) out of
   the layout, and never leave out a widget unless the person asked to remove it. A write
   cannot delete web clips or web apps; `check` refuses such a layout.
4. Never write the home screen any other way: no `pymobiledevice3 springboard` commands, no
   `set_icon_state` or `reload_icon_state`, no other tools or scripts, and never a
   list-form layout. SpringBoard then puts every installed app that is not on the list back
   on the home screen, archived apps included. Only `ios-homescreen push`, `restore` and
   the browser editor write, and they back up, verify and roll back.
5. Never edit or delete the `[pull]` table in a layout file, and never delete anything in
   the data directory (`~/.local/share/ios-homescreen`): it holds the backups.
6. Never copy, print or upload the Wi-Fi pairing files
   (`~/.local/share/pymobiledevice3/remote_*.plist`); they unlock the phone.
7. Keep the phone's data to yourself: do not paste app lists or device names anywhere
   outside this conversation.

## Setup

Linux is tested. macOS may work (it has usbmuxd built in) but is untested. Windows is not
supported. Python 3.11 or newer is needed.

1. **usbmuxd (Linux only).** Install and start it: `sudo apt install usbmuxd`,
   `sudo dnf install usbmuxd` or `sudo pacman -S usbmuxd`, then
   `sudo systemctl start usbmuxd`. Ask before running `sudo`.
2. **Install the tool**, with [uv](https://docs.astral.sh/uv/) or pipx:

   ```bash
   uv tool install git+https://github.com/YakupEmreYerli/ios-homescreen
   # or: pipx install git+https://github.com/YakupEmreYerli/ios-homescreen
   ios-homescreen --version
   ```

3. **Trust.** The person connects the iPhone with a cable, unlocks it, taps **Trust This
   Computer** and enters the passcode. Only they can do this; tell them when to.
4. **First pull**, over USB: `ios-homescreen pull`. It is read-only and writes
   `layout.toml` in the current directory.
5. **Wi-Fi (optional, iOS 17 or later).** Once, over USB: `ios-homescreen wifi setup`. After
   that, add `--wifi` to `pull`, `push` and `restore` while the phone is awake, unlocked and on
   the same network. `ios-homescreen wifi status --json` shows whether it answers.

To use this workflow as a Claude Code skill, copy the repository's `skills/ios-homescreen`
folder into the `skills` folder inside `~/.claude` (or inside a project's `.claude` folder).

## Commands

| Command | Does | Phone |
| --- | --- | --- |
| `ios-homescreen pull [LAYOUT]` | Read the home screen into `LAYOUT` (default `layout.toml`); refuses to overwrite a file with unpushed edits unless `--overwrite` | Reads |
| `ios-homescreen apps [QUERY]` | Installed apps, their bundle ids and where each one is, from the newest pull | No |
| `ios-homescreen check [LAYOUT]` | Validate the file and list what `push` would change | No |
| `ios-homescreen push [LAYOUT] --yes` | Back up, write, verify, roll back on failure. Without `--yes` it asks at a terminal; with `--json` it only reports the changes | Writes |
| `ios-homescreen backups` | Backups made before each write, newest first | No |
| `ios-homescreen restore latest --yes` | Write a backup back (`latest`, a name from `backups`, or a file), same safety steps | Writes |
| `ios-homescreen wifi setup\|status\|off` | Wi-Fi access | Yes |

Add `--json` to `pull`, `apps`, `check`, `push`, `backups`, `restore` and `wifi` to get one
JSON object on stdout (messages go to stderr). Other flags: `--wifi`, `--udid UDID`,
`--data-dir DIR`, `--force`, `--allow-removal`, `--overwrite`.

Exit codes: `0` done; `1` error, nothing written; `2` not confirmed (no `--yes`, or the person
answered no at the terminal) or a usage error; `3` the new layout did not verify and the
backup was written back; `4` that did not verify either (tell the person at once).

## The layout file

```toml
[pull]                      # which phone state this file came from; never edit
snapshot = "pull-20261010-144400-123456.plist"

[dock]                      # at most 4 items
items = ["com.apple.mobilephone", "Safari", "Messages", "Camera"]

[[pages]]                   # one table per page, items left to right, top to bottom
items = [
  { type = "widget", id = "6F1D3A52-..." },          # keep: moved, never created
  "com.apple.mobilecal",                             # an app by bundle id
  "Mail",                                            # or by the name under its icon
  { type = "folder", name = "Work", items = ["Slack", "Notion", "com.microsoft.Outlook"] },
  { type = "folder", name = "Games", pages = [["A", "B", "C"], ["D"]] },
  { type = "webclip", id = "0A1B2C3D..." },          # keep: cannot be removed
  { type = "webapp", id = "9E8D7C6B-..." },          # keep: cannot be removed
]

[[pages]]
items = ["Health", "Wallet"]
```

- Apps: a bundle id, or the app's name if only one app has it. Names follow the phone's
  language. Bundle ids are safer; `apps --json` gives both.
- An app that is in no `[dock]` or `[[pages]]` goes to the App Library and stays installed.
  Any installed app can be added, including App Library apps; the end of a pulled file
  lists them in comments.
- Each item appears once.
- The dock holds at most 4 items. A page holds 24 cells: an app, folder, web clip or web
  app takes 1; a widget takes 4 (small), 8 (medium) or 16 (large). Pull comments show each
  widget's size and each page's use.
- Folders need a non-empty name and at least one item. They hold apps, web clips and web
  apps, not widgets or folders. Keep at most 9 items per folder page (the iPhone shows 3 by
  3); use `pages = [[...], [...]]` for more.
- Widgets cannot go in the dock or in folders. Widgets, web clips and web apps are referred
  to by their `id` from the pull and cannot be created.
- Empty pages are dropped. Unknown keys are errors.

## Turning a request into edits

1. `ios-homescreen pull --json` (add `--wifi` if set up). If `layout.toml` holds unpushed
   edits, pull into a new file, for example `ios-homescreen pull fresh.toml`.
2. `ios-homescreen apps --json` to see every app, its id and where it is now.
3. Work out which apps the request means. The tool knows no categories: decide "games",
   "work apps" or "social" from the names and what you know, and when unsure, list your
   picks and ask. Match the person's words to `name` or `id`; ask when several match.
4. Edit the layout file as text. Move entries; do not drop any widget, web clip or web app
   entry. Keep the dock to 4 items and pages within 24 cells; if a page would overflow, put
   the rest on the next page or a new `[[pages]]` table.
5. `ios-homescreen check --json`. Fix every issue in `error.issues` (each has a `code`, a
   `location` and a `message`) and run it again until `valid` is true.
6. Show the person the change list in plain words (from `changes`, or the text `check`
   prints) and ask: "Write this to your iPhone? A backup is saved first."
7. Only after a yes: `ios-homescreen push --yes --json`. Report `status` (`applied`,
   `unchanged`, `rolled-back`, `rollback-failed`) and the `backup` file.

Examples: "put my work apps in one folder" becomes one folder entry holding those apps,
placed where the first of them was. "Move games to page 2" moves those entries into the
second `[[pages]]` table. "Clean up page 3" means asking what to keep; apps left out go to
the App Library and stay installed.

## Undo

`ios-homescreen backups --json` lists the backups (every push and restore makes one
first). To undo the last push, show the person what will change and, after a yes, run
`ios-homescreen restore latest --yes --json`. A restore backs up the current layout too.

## JSON results

Every `--json` result has `ok` (true when the exit code is 0), `command` and `exit_code`;
a failure adds `error: {code, message}`.

- `pull`: `layout`, `pull`, `device {name, model, ios_version, udid}`, `dock`, `pages`,
  `library` (counts).
- `apps`: `pull`, `pulled_from`, `apps: [{name, id, type, offloaded, where}]`. `where` is
  `{section: "dock"|"page"|"library", page, index, folder, folder_page, folder_index}`;
  indexes start at 1 and count every item on a page in order.
- `check`: `layout`, `pull`, `valid`, `unchanged`, `changes`, `summary`, `library`.
  A change is `{kind, id, type, name, from, to}`; `kind` is `added`, `moved`, `reordered`,
  `to_library`, `removed`, `folder_created`, `folder_renamed` (with `old_name`),
  `folder_deleted` or `pages` (with `before`, `after`); `from` and `to` are
  `{section, page, index, folder}`.
- `push`: like `check` plus `status`, `backup`, `write_unconfirmed`, `new_pull`,
  `layout_updated`. Without `--yes` it exits 2 with `error.code` `confirmation_needed` and
  the `changes`, and nothing connects.
- `backups`: `directory`, `backups: [{name, created, device, summary {dock, pages, items}}]`.
- `restore`: `restoring`, `made_on`, then like `push`.
- `wifi`: `action`, `enabled`, `device`, `pair_record`, `pair_record_problem`, `reachable`,
  `address`.

## Errors and what to tell the person

| `error.code` | Meaning and next step |
| --- | --- |
| `no_usb_device` | No iPhone over USB: plug it in with a data cable, unlock it, tap Trust |
| `usbmuxd_unreachable` | usbmuxd is not running: install and start it (Setup step 1) |
| `timeout`, `connection_failed` | Unlock the phone and keep it awake; if it repeats, `sudo systemctl restart usbmuxd` and reconnect |
| `not_advertising` | Not found on Wi-Fi: phone awake, unlocked, same network; try again or use the cable |
| `no_pair_record`, `stale_pair_record` | Wi-Fi not set up: over USB run `ios-homescreen wifi setup` |
| `several_pair_records` | More than one phone is paired: add `--udid` (ask which) |
| `layout_invalid` | Fix every entry in `error.issues`, then `check` again |
| `layout_changed` | The phone was edited since the pull. Pull into a new file, redo the edits there, check and ask again. `--force` would overwrite the phone's changes |
| `unpushed_edits` | `pull` would overwrite edits: pull into another file, or ask before `--overwrite` |
| `no_pull`, `pull_missing` | Run `ios-homescreen pull` (into a new file if needed) |
| `confirmation_needed`, `not_confirmed` | Nothing was written; show the changes and ask |
| `rolled_back` (exit 3) | The phone did not take the layout and was put back as it was. Retry later, or with `--verify-attempts 10 --verify-interval 5` |
| `rollback_failed` (exit 4) | Tell the person now: look at the phone, then restore the `backup` file with `ios-homescreen restore <file> --yes` after their yes |
| `other_device` | That backup is from another iPhone; ask before `--force` |
| `no_backup` | No such backup; list them with `backups` |

## Limits

Widgets cannot be created or resized, and web clips and web apps can only be moved; for
those, the person uses the phone (touch and hold the home screen, Edit). Hidden home screen
pages, the Today view and Lock Screen widgets are out of reach. A write can reset which
widget a stack shows. iPads are untested.
