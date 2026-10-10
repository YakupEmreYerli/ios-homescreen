# Security

## Reporting a problem

Please do not open a public issue for a security problem. Report it privately through
GitHub: open the repository's **Security** tab and choose **Report a vulnerability**, or go
straight to
<https://github.com/YakupEmreYerli/ios-homescreen/security/advisories/new>.

Include what you found, how to reproduce it, and what it lets an attacker do. Once a fix is
released, the advisory is published with credit to you unless you prefer otherwise.

## Supported versions

Only the latest release gets security fixes.

## Scope

In scope:

- Anything that makes ios-homescreen write to the phone without the user's yes (`y` at the
  prompt, `--yes`, or Apply in the browser editor), skip the backup, skip verification or
  rollback, or send a payload other than the validated `{buttonBar, iconLists, ignored}`
  dictionary.
- Leaking or copying pairing records. They contain the private key that lets a computer
  access the phone. ios-homescreen has pymobiledevice3 create the Wi-Fi (RemotePairing)
  record on `wifi setup`, deletes it on `wifi off --forget`, and otherwise only reads
  it; it must never copy or send it anywhere.
- Anything that lets another website, another origin or another machine use the browser
  editor (`ios-homescreen editor`), read its icons, backups or layout, or write to the phone
  without the user pressing Apply or Restore and confirming.
- Writing outside the data, cache or output paths the user chose, for example through a
  crafted file name, bundle id or layout file.
- Crafted pull snapshots, backups or layout files that make the tool do something other than
  reject them or process them as documented, for example a `[pull]` table that points
  outside the data directory.

Out of scope:

- Problems in pymobiledevice3, usbmuxd, libimobiledevice or iOS itself. Please report those
  to their projects.
- Someone who already has your user account and your pair records. They can talk to the
  phone without this tool.
- Damage from `--force` or `--allow-removal` used as documented.

## What the design already does

- Writes need the user's yes (the y/N prompt or `--yes`); without a terminal and without
  `--yes` nothing connects. Input files are validated before any connection is opened.
- The device layer refuses any payload that is not the exact safe dictionary.
- Every write is preceded by a backup and followed by verification; a failed verification
  triggers an automatic rollback.
- Network connections never start pairing (`autopair=False`); they only use pair records the
  user already has.
- App icon cache file names are restricted to plain identifier characters, so an id cannot
  point outside the cache directory.
- The browser editor listens on 127.0.0.1 only. A random key printed at start is traded for an
  `HttpOnly`, `SameSite=Strict` cookie; every API call also needs the key in a header, the
  `Host` header must be the server's own (against DNS rebinding), `Sec-Fetch-Site` must be
  same-origin, and requests that change something must carry the server's own `Origin`.
  Responses forbid framing and cross-origin embedding, and the page runs under a strict
  Content Security Policy. Backups are listed and restored by name; their contents are never
  served.
