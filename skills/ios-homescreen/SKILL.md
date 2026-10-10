---
name: ios-homescreen
description: Rearrange a person's iPhone home screen with the ios-homescreen command-line tool - pull the layout into layout.toml, edit it (move apps, make folders, move apps between pages or to the App Library), check it, and push it back with a backup, verification and automatic rollback, or undo with a backup. Use when someone wants to organize, group, move or clean up the apps, folders and pages on their iPhone home screen, set up ios-homescreen, or undo such a change.
---

# ios-homescreen

The full guide is `docs/agent-guide.md` in the ios-homescreen repository
(<https://github.com/YakupEmreYerli/ios-homescreen/blob/main/docs/agent-guide.md>). Read it
before the first edit: it has setup, the layout rules and limits, the JSON shapes and what
every error code means. This skill is the short version of the same workflow.

## Rules that are never bent

- Write to the phone only after the person said yes to the change list you showed them,
  in this conversation. Only then add `--yes` to `push` or `restore`.
- Never pass `--force` or `--allow-removal` on your own.
- Never leave web clips or Safari web apps out of the layout, nor widgets unless asked.
- Never touch the `[pull]` table or the data directory, and never write the home screen
  with anything but `ios-homescreen` (no `pymobiledevice3 springboard`, no list-form state).

## Workflow

1. Setup if needed: on Linux, usbmuxd; then
   `uv tool install git+https://github.com/YakupEmreYerli/ios-homescreen`; the person
   connects the iPhone by cable, unlocks it and taps Trust This Computer.
2. `ios-homescreen pull --json` (add `--wifi` after `ios-homescreen wifi setup` was done
   once over USB). It writes `layout.toml`.
3. `ios-homescreen apps --json` to map the person's words to app names, bundle ids and
   current places. The tool knows no categories: pick the apps yourself and ask when unsure.
4. Edit `layout.toml`: the dock holds 4 items, a page 24 cells (widgets 4, 8 or 16),
   folders hold apps, web clips and web apps (9 per folder page). Apps left out go to the
   App Library and stay installed.
5. `ios-homescreen check --json` until `valid` is true; fix each entry of `error.issues`.
6. Tell the person what will change, in plain words, and ask.
7. After their yes: `ios-homescreen push --yes --json`. Report `status` and the `backup`.

Undo: `ios-homescreen backups --json`, show what changes, and after a yes
`ios-homescreen restore latest --yes --json`.

Install this skill by copying this folder into the `skills` folder inside `~/.claude`
(or inside a project's `.claude` folder).
