## What and why

<!-- What does this change, and what problem does it solve? -->

## Checks

- [ ] `uv run ruff check` and `uv run ruff format --check` pass
- [ ] `uv run pytest` passes
- [ ] New behaviour has tests that use the fakes (no test talks to a real device)
- [ ] README / README.tr.md updated if commands, flags or the layout format changed

## Device testing

<!--
If you changed anything that talks to the phone (device.py, transport.py, workflow.py,
the write payload), say what you ran on a real device: model, iOS version, USB or Wi-Fi,
and whether you started with `pull` and kept the backup. "Not tested on a device" is a
fine answer; just say so.
-->
