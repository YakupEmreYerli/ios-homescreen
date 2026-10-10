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
AGENT_DOCS = ["docs/agent-guide.md", "skills/ios-homescreen/SKILL.md"]
DOCS = [*READMES, *AGENT_DOCS, "CONTRIBUTING.md", "SECURITY.md", "examples/layout.toml", "llms.txt"]
OLD_COMMANDS = re.compile(
    r"ios-homescreen (read|export|plan|apply|diff|ui)\b"
    r"|wifi (enable|disable)\b"
    r"|`(read|apply|export|diff)`"
)


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
    push = _parsers()["push"]
    defaults = {a.dest: a.default for a in push._actions}

    assert f"Re-reads used to verify the write (default {defaults['verify_attempts']})" in text
    assert f"Pause between those re-reads (default {defaults['verify_interval']:g})" in text
    assert f"(default {defaults['write_timeout']:g})" in text
    assert f"Bonjour answers (default {defaults['discovery_timeout']:g})" in text
    assert f"opening the connection (default {defaults['connect_timeout']:g})" in text


@pytest.mark.parametrize("doc", DOCS)
def test_the_docs_use_the_current_command_names(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")

    assert OLD_COMMANDS.findall(text) == []


# ------------------------------------------------------------------ for AI agents


@pytest.mark.parametrize("doc", AGENT_DOCS)
def test_every_command_and_flag_an_agent_is_told_about_exists(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    # Commands as written in code: inline spans and fenced blocks, not prose.
    code = re.findall(r"```.*?```|`[^`\n]+`", text, re.S)
    commands = {c for span in code for c in re.findall(r"ios-homescreen ([a-z]+)", span)}
    flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", text))

    assert {"pull", "check", "push", "apps", "restore", "backups"} <= commands
    assert commands - set(_parsers()) == set()
    assert flags - _flags() == set()


def test_the_commands_the_guide_gives_json_for_have_it():
    text = (ROOT / "docs/agent-guide.md").read_text(encoding="utf-8")
    listed = re.search(r"Add `--json` to (.*?) to get", text, re.S).group(1)
    named = set(re.findall(r"`([a-z]+)`", listed))

    assert named == {"pull", "apps", "check", "push", "backups", "restore", "wifi"}
    for command in named:
        assert "--json" in {o for a in _parsers()[command]._actions for o in a.option_strings}


def test_the_error_codes_in_the_guide_are_real():
    text = (ROOT / "docs/agent-guide.md").read_text(encoding="utf-8")
    table = text[text.index("## Errors and what to tell the person") :]
    codes = set(re.findall(r"^\| `([a-z_]+)`(?:, `([a-z_]+)`)?", table, re.M))
    codes = {code for pair in codes for code in pair if code}
    source = "".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))

    assert len(codes) > 15
    for code in codes:
        assert f'"{code}"' in source, code


def test_the_skill_is_a_valid_agent_skill_that_points_to_the_guide():
    text = (ROOT / "skills/ios-homescreen/SKILL.md").read_text(encoding="utf-8")
    front = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
    fields = dict(line.split(": ", 1) for line in front.splitlines())

    assert set(fields) == {"name", "description"}
    assert fields["name"] == "ios-homescreen"
    assert 50 < len(fields["description"]) <= 1024
    assert "docs/agent-guide.md" in text


def test_llms_txt_follows_the_convention_and_links_to_real_files():
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    links = re.findall(
        r"\]\(https://raw\.githubusercontent\.com/YakupEmreYerli/ios-homescreen/main/([^)]+)\)",
        text,
    )

    assert text.startswith("# ios-homescreen\n\n> ")
    assert "docs/agent-guide.md" in links
    for path in links:
        assert (ROOT / path).is_file(), path


@pytest.mark.parametrize("readme", READMES)
def test_the_readme_gives_agents_the_guide(readme):
    text = (ROOT / readme).read_text(encoding="utf-8")

    assert "https://github.com/YakupEmreYerli/ios-homescreen/blob/main/docs/agent-guide.md" in text
    assert "skills/ios-homescreen" in text
