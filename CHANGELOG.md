# Changelog

## 0.1.2 — 2026-11-13

- A correct write is no longer rolled back when iOS moves a widget within its page to keep a nearly full page packed ([rejig-app/rejig#3](https://github.com/rejig-app/rejig/issues/3)), or puts a web clip that no read had shown into a slot the write freed ([rejig-app/rejig#7](https://github.com/rejig-app/rejig/issues/7)). Either case is reported as a warning; any other difference still rolls back.
- A second home screen icon of an installed app is called an extra icon, not a web app ([rejig-app/rejig#6](https://github.com/rejig-app/rejig/issues/6)).
- The Apply dialog, the README and the agent guide say that a write makes hidden pages visible again: the iPhone reads the same whether a page is hidden or not ([rejig-app/rejig#5](https://github.com/rejig-app/rejig/issues/5)).

## 0.1.1 — 2026-11-13

- Offloaded apps that live only in the App Library stay there after a write. Installation Proxy lists them only when asked for placeholders, so a write left them out of its ignored list and SpringBoard put them back on a page. An offloaded app moved to the home screen is now written in SpringBoard's own form. Found by [Rejig](https://github.com/rejig-app/rejig).
- Over Wi-Fi, a read that fails after a write opens a new tunnel to the same iPhone and tries once more: a home screen write can drop the whole tunnel. Found by Rejig.
- The Apply dialog, the Backups dialog and the README say that empty spaces between icons are not kept. Found by Rejig.
- Model names over USB for the iPhone 17e, iPhone 18 Pro, iPhone 18 Pro Max and iPhone Duo (#3).

## 0.1.0 — 2026-10-10

First release.

- Browser editor (`ios-homescreen editor`): a mirror of the phone with its real icons and widgets. Drag apps between pages, the dock and folders, make and rename folders, send apps to the App Library, undo and redo, see the list of changes, then Apply. `--demo` runs it against a pretend phone.
- AI agents: [`docs/agent-guide.md`](docs/agent-guide.md) and `llms.txt` tell a coding agent how to install and use the tool and to show the changes and wait for a yes before writing. A Claude Code skill in `skills/ios-homescreen`. `--json` output on every command and `ios-homescreen apps` to find an app and where it is.
- Safe writes: every write saves a backup first, reads the phone back and compares, and puts the backup back if the phone does not match. `backups` and `restore latest` undo a change.
- Command line: `pull` writes the layout to an editable TOML file, `check` shows what would change without touching the phone, `push` asks and writes.
- USB, and Wi-Fi without root: `wifi setup` once over USB, then the tool reaches the phone through a RemotePairing tunnel and remembers its address.
- Tested on an iPhone 15 with iOS 27.0.1 from Linux. Wi-Fi needs iOS 17 or later.
- Known limits: web clips and Safari web apps can only be deleted on the phone; a configurable widget may fall back to its default selection after a write; iOS 27 does not hand out the wallpaper over Wi-Fi.
