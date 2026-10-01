#!/usr/bin/env python3
"""Render the JSON an implementation reads from the YAML people edit.

People edit YAML, which takes comments and folded summaries. Every target
language parses JSON with its standard library, and several have no YAML
parser there, so the JSON is the published form.

The tables are sorted and indented by four, so a diff shows only the keys
an editor changed.

The property engine's vectors are authored as inputs only, in
corpus/prop/<kind>.yaml. Each rendered case is its inputs followed by the
outputs the executable reference computes for them, in the order the
reference returns them, indented by two as the rest of the corpus is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from prop.vectors import KINDS, Vector, compute

ROOT = Path(__file__).resolve().parent.parent

#: The tables that are authored in YAML and read as JSON.
TABLES = ("assertions", "naming")

#: Where the property engine's vectors are authored and rendered.
VECTORS = ROOT / "corpus" / "prop"


class RenderError(ValueError):
    """A vector file whose inputs cannot be rendered."""


def write(target: Path, rendered: str) -> bool:
    """Write rendered to target, and return whether the file on disk changed."""
    if target.exists() and target.read_text() == rendered:
        return False
    target.write_text(rendered)
    return True


def render(name: str) -> bool:
    """Render one table, and return whether the file on disk changed."""
    source = ROOT / "spec" / f"{name}.yaml"
    rendered = json.dumps(yaml.safe_load(source.read_text()), indent=4, sort_keys=True)
    return write(ROOT / "spec" / f"{name}.json", rendered + "\n")


def vector(kind: str, case: Any) -> Vector:
    """Return one case's inputs followed by the outputs the reference computes.

    Raises:
        RenderError: the case is not an object, or an output has the name
            of an input.
    """
    if not isinstance(case, dict):
        raise RenderError(f"a {kind} case is {case!r}, not an object")
    outputs = compute(kind, case)
    clash = sorted(set(outputs) & set(case))
    if clash:
        raise RenderError(f"{case.get('id')!r} states the outputs {clash}")
    return {**case, **outputs}


def vectors_text(kind: str) -> str:
    """Return the JSON of one kind of vector, rendered from its YAML inputs.

    Raises:
        RenderError: the YAML states another kind, or no list of cases.
    """
    source = VECTORS / f"{kind}.yaml"
    document = yaml.safe_load(source.read_text())
    if not isinstance(document, dict) or document.get("kind") != kind:
        raise RenderError(f"{source.name} does not state kind {kind!r}")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise RenderError(f"{source.name} states no list of cases")
    rendered = {"kind": kind, "cases": [vector(kind, case) for case in cases]}
    return json.dumps(rendered, indent=2) + "\n"


def render_vectors(kind: str) -> bool:
    """Render one kind of vector, and return whether the file on disk changed.

    Raises:
        RenderError: the YAML states another kind, or no list of cases.
    """
    return write(VECTORS / f"{kind}.json", vectors_text(kind))


def main() -> int:
    """Render every table and every kind of vector, and print which files changed."""
    for name in TABLES:
        changed = render(name)
        print(f"spec/{name}.json: {'rendered' if changed else 'unchanged'}")
    for kind in KINDS:
        changed = render_vectors(kind)
        print(f"corpus/prop/{kind}.json: {'rendered' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
