# Changelog

## 0.1.0 — 2026-10-10

First release.

- Browser editor (`ios-homescreen editor`): a mirror of the phone with its real icons and widgets. Drag apps between pages, the dock and folders, make and rename folders, send apps to the App Library, undo and redo, see the list of changes, then Apply. `--demo` runs it against a pretend phone.
- AI agents: [`docs/agent-guide.md`](docs/agent-guide.md) and `llms.txt` tell a coding agent how to install and use the tool and to show the changes and wait for a yes before writing. A Claude Code skill in `skills/ios-homescreen`. `--json` output on every command and `ios-homescreen apps` to find an app and where it is.
- Safe writes: every write saves a backup first, reads the phone back and compares, and puts the backup back if the phone does not match. `backups` and `restore latest` undo a change.
- Command line: `pull` writes the layout to an editable TOML file, `check` shows what would change without touching the phone, `push` asks and writes.
- USB, and Wi-Fi without root: `wifi setup` once over USB, then the tool reaches the phone through a RemotePairing tunnel and remembers its address.
- Tested on an iPhone 15 with iOS 27.0.1 from Linux. Wi-Fi needs iOS 17 or later.
- Known limits: web clips and Safari web apps can only be deleted on the phone; a configurable widget may fall back to its default selection after a write; iOS 27 does not hand out the wallpaper over Wi-Fi.
