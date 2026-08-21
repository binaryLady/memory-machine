#!/usr/bin/env python3
"""Mechanical docs audit: installed commands x COMMANDS.md x config keys.

The drift this catches is real and recurring: a command ships a new flag and
its table row still shows the old set, or a config key appears that no doc
mentions. `--sync` regenerates COMMANDS.md's config reference from the
comments in config/config.default.ini — the ini is the single source of
truth; the audit fails when the generated block is stale.

Run by `make docs-check` (audit) and `make docs-sync` (regenerate), and by CI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMANDS_PATH = REPO / "COMMANDS.md"
DEFAULT_INI = REPO / "config" / "config.default.ini"

BEGIN = "<!-- config-reference:begin — generated from config/config.default.ini by scripts/check_docs.py --sync; edit the ini comments, not this block -->"
END = "<!-- config-reference:end -->"

# Commands documented in prose rather than the flag table.
TABLE_EXEMPT = {"motion-player-install-deb"}
# Flags every script may have without documenting.
FLAG_EXEMPT = {"-h", "--help"}

# Where a command's argument parser lives when it is not packaging/<name>.
SOURCE_OVERRIDES = {
    "motion-player-update": "scripts/update.sh",
    "motion-player-status": "scripts/status.sh",
}


def installed_commands() -> set[str]:
    text = (REPO / "packaging" / "build_deb.sh").read_text(encoding="utf-8")
    return set(re.findall(r'/usr/bin/(motion-player[\w-]*)"', text))


def table_rows(commands_text: str) -> dict[str, str]:
    rows = {}
    for line in commands_text.splitlines():
        match = re.match(r"\|\s*`(motion-player[\w-]*)`\s*\|(.*)", line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def script_flags(command: str) -> set[str]:
    override = SOURCE_OVERRIDES.get(command)
    source = REPO / override if override else REPO / "packaging" / command
    if not source.exists():
        return set()
    text = source.read_text(encoding="utf-8")
    flags: set[str] = set()
    # Case-parser patterns: `--size)`, `-h|--help)`, `--apply) ... ;;`
    for pattern in re.findall(r"^\s*((?:--?[\w-]+\|?)+)\)", text, flags=re.MULTILINE):
        flags.update(part for part in pattern.split("|") if part.startswith("-"))
    return flags - FLAG_EXEMPT


def parse_default_ini() -> list[tuple[str, list[tuple[str, str, str]]]]:
    """[(section, [(key, default, comment)])], in file order."""
    sections: list[tuple[str, list[tuple[str, str, str]]]] = []
    comment: list[str] = []
    for line in DEFAULT_INI.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            comment = []
            continue
        if stripped.startswith("["):
            sections.append((stripped.strip("[]"), []))
            comment = []
            continue
        if stripped.startswith(";"):
            comment.append(stripped.lstrip("; ").strip())
            continue
        match = re.match(r"([a-z0-9_]+)\s*=\s*(.*)", stripped)
        if match and sections:
            sections[-1][1].append(
                (match.group(1), match.group(2), " ".join(comment))
            )
            comment = []
    return sections


def render_config_reference() -> str:
    lines = [BEGIN, ""]
    for section, keys in parse_default_ini():
        lines.append(f"### `[{section}]`")
        lines.append("")
        lines.append("| Key | Default | What it is |")
        lines.append("| --- | --- | --- |")
        for key, default, comment in keys:
            cell = comment.replace("|", "\\|") or "—"
            shown = default.replace("|", "\\|") or "*(empty)*"
            lines.append(f"| `{key}` | `{shown}` | {cell} |")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def replace_reference(commands_text: str, block: str) -> str | None:
    """The doc with its generated block swapped in, or None if markers absent."""
    begin = commands_text.find(BEGIN)
    end = commands_text.find(END)
    if begin == -1 or end == -1:
        return None
    return commands_text[:begin] + block + commands_text[end + len(END):]


def sync() -> int:
    text = COMMANDS_PATH.read_text(encoding="utf-8")
    updated = replace_reference(text, render_config_reference())
    if updated is None:
        print(f"COMMANDS.md is missing the config-reference markers:\n  {BEGIN}\n  {END}")
        return 1
    if updated != text:
        COMMANDS_PATH.write_text(updated, encoding="utf-8")
        print("Config reference regenerated in COMMANDS.md.")
    else:
        print("Config reference already current.")
    return 0


def audit() -> int:
    commands_text = COMMANDS_PATH.read_text(encoding="utf-8")
    problems: list[str] = []
    rows = table_rows(commands_text)

    for command in sorted(installed_commands()):
        if f"`{command}`" not in commands_text:
            problems.append(f"{command}: installed but never mentioned in COMMANDS.md")
            continue
        if command in TABLE_EXEMPT:
            continue
        row = rows.get(command)
        if row is None:
            problems.append(f"{command}: installed but has no row in the command table")
            continue
        for flag in sorted(script_flags(command)):
            if flag not in row:
                problems.append(f"{command}: flag {flag} missing from its table row")

    if replace_reference(commands_text, render_config_reference()) != commands_text:
        problems.append(
            "config reference is stale or missing — run: python3 scripts/check_docs.py --sync"
        )

    if problems:
        print("Docs drift found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Docs audit clean: commands, flags, and config reference all current.")
    return 0


if __name__ == "__main__":
    sys.exit(sync() if "--sync" in sys.argv[1:] else audit())
