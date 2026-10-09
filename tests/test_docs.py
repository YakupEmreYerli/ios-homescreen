"""The READMEs must describe the CLI that actually exists."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from ios_homescreen.cli import build_parser
from ios_homescreen.planner import plan_layout

ROOT = Path(__file__).resolve().parents[1]
READMES = ["README.md", "README.tr.md"]


def _parsers() -> dict[str, argparse.ArgumentParser]:
    parser = build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return {"": parser, **action.choices}


def _flags() -> set[str]:
    return {
        option
        for parser in _parsers().values()
        for action in parser._actions
        for option in action.option_strings
    }


@pytest.mark.parametrize("readme", READMES)
def test_every_flag_in_the_readme_exists(readme):
    text = (ROOT / readme).read_text(encoding="utf-8")
    mentioned = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", text))

    assert mentioned - _flags() == set()


@pytest.mark.parametrize("readme", READMES)
def test_every_command_is_documented(readme):
    text = (ROOT / readme).read_text(encoding="utf-8")

    for command in _parsers():
        if command:
            assert f"| `{command}" in text


@pytest.mark.parametrize("readme", READMES)
def test_readme_layout_example_plans(readme):
    from test_planner import example_read

    text = (ROOT / readme).read_text(encoding="utf-8")
    layout = re.search(r"```toml\n(.*?)```", text, re.S).group(1)

    plan = plan_layout(layout, example_read(), allow_removal=True)

    assert len(plan.payload["buttonBar"]) == 4


def test_documented_defaults_match_the_parser():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    apply = _parsers()["apply"]
    defaults = {a.dest: a.default for a in apply._actions}

    assert f"Re-reads used to verify the write (default {defaults['verify_attempts']})" in text
    assert f"Pause between those re-reads (default {defaults['verify_interval']:g})" in text
    assert f"(default {defaults['write_timeout']:g})" in text
    assert f"Bonjour answers (default {defaults['discovery_timeout']:g})" in text
    assert f"opening the connection (default {defaults['connect_timeout']:g})" in text
