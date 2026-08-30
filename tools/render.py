#!/usr/bin/env python3
"""Render the JSON an implementation reads from the YAML people edit.

People edit YAML because it takes comments and folded summaries. Every
target language parses JSON from its standard library, and several
would otherwise take a dependency just to read the definition at all,
so the JSON is what ships.

The output is sorted and indented by four, so a diff shows what the
editor changed rather than where a key happened to land.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

#: The tables that are authored in YAML and read as JSON.
TABLES = ("assertions", "naming")


def render(name: str) -> bool:
    """Render one table. Answers whether the file on disk changed."""
    source = ROOT / "spec" / f"{name}.yaml"
    target = ROOT / "spec" / f"{name}.json"

    rendered = json.dumps(yaml.safe_load(source.read_text()), indent=4, sort_keys=True)
    rendered += "\n"

    if target.exists() and target.read_text() == rendered:
        return False
    target.write_text(rendered)
    return True


def main() -> int:
    """Render every table and say which ones moved."""
    for name in TABLES:
        changed = render(name)
        print(f"spec/{name}.json: {'rendered' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
