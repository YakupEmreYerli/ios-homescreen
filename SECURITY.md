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

- Anything that makes ios-homescreen write to the phone without `--yes`, skip the backup,
  skip verification or rollback, or send a payload other than the validated
  `{buttonBar, iconLists, ignored}` dictionary.
- Leaking or copying pair records. They contain the private key that lets a computer access
  the phone. ios-homescreen reads them for Wi-Fi connections and must never write, copy or
  send them anywhere.
- Writing outside the data, cache or output paths the user chose, for example through a
  crafted file name, bundle id or layout file.
- Crafted read, backup, plan or layout files that make the tool do something other than
  reject them or process them as documented.

Out of scope:

- Problems in pymobiledevice3, usbmuxd, libimobiledevice or iOS itself. Please report those
  to their projects.
- Someone who already has your user account and your pair records. They can talk to the
  phone without this tool.
- Damage from `--force` or `--allow-removal` used as documented.

## What the design already does

- Writes require `--yes`, and input files are validated before any connection is opened.
- The device layer refuses any payload that is not the exact safe dictionary.
- Every write is preceded by a backup and followed by verification; a failed verification
  triggers an automatic rollback.
- Network connections never start pairing (`autopair=False`); they only use pair records the
  user already has.
- App icon cache file names are restricted to plain identifier characters, so an id cannot
  point outside the cache directory.
