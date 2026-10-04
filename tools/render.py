#!/usr/bin/env python3
"""Render the JSON an implementation reads from the YAML people edit.

People edit YAML, which takes comments and folded summaries. Every target
language parses JSON with its standard library, and several have no YAML
parser there, so the JSON is the published form.

The tables are sorted and indented by four, so a diff shows only the keys
an editor changed. Rendering adds an entry to each table for every
property form, by the rule the tables state. The rule stays in the
published tables, so the validator can check each entry against it.

Vectors are authored as inputs only, in corpus/<family>/<kind>.yaml. The
family prop contains the property engine's vectors, and history those of
the history seam and the checker. Each rendered case is its inputs followed by
the outputs the family's executable reference computes for them, in the
order the reference returns them, indented by two as the rest of the
corpus is.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from history import vectors as history_vectors
from prop import vectors as prop_vectors
from prop.vectors import Vector

ROOT = Path(__file__).resolve().parent.parent

#: The tables that are authored in YAML and read as JSON.
TABLES = ("assertions", "naming")

#: Where the vectors are authored and rendered, one folder per family.
CORPUS = ROOT / "corpus"

#: Each family of vectors by its folder: its kinds, and the reference
#: function that computes a kind's outputs.
FAMILIES: Final[
    dict[str, tuple[Collection[str], Callable[[str, Mapping[str, Any]], Vector]]]
] = {
    "prop": (prop_vectors.KINDS, prop_vectors.compute),
    "history": (history_vectors.KINDS, history_vectors.compute),
}

#: The assertion whose run every property form is, and the start of each
#: form's id.
FOR_ALL: Final = "prop-for-all"
FORM_PREFIX: Final = "prop-"

#: The package of every property form.
FORM_PACKAGE: Final = "prop"

#: The kinds of form, and the argument a form over a function generates.
FUNCTION: Final = "function"
RELATION: Final = "relation"
INPUT: Final = "input"


class RenderError(ValueError):
    """A table or a vector file whose content cannot be rendered."""


@dataclass(frozen=True)
class Form:
    """One property form: the assertion it runs, its kind and what it generates."""

    of: str
    kind: str
    generates: tuple[str, ...]

    @property
    def id(self) -> str:
        """Return the form's id: the prefix and the assertion's id."""
        return FORM_PREFIX + self.of


def write(target: Path, rendered: str) -> bool:
    """Write rendered to target, and return whether the file on disk changed."""
    if target.exists() and target.read_text() == rendered:
        return False
    target.write_text(rendered)
    return True


def forms(spec: Mapping[str, Any]) -> list[Form]:
    """Return the forms the assertion table's rule states, functions first.

    Raises:
        RenderError: the rule lists no functions or states no relations, or
            a relation generates no argument.
    """
    rule = spec.get("forms")
    if not isinstance(rule, Mapping):
        raise RenderError("spec/assertions.yaml states no rule for the forms")
    functions = rule.get("functions")
    relations = rule.get("relations")
    if not isinstance(functions, list) or not isinstance(relations, Mapping):
        raise RenderError("the rule for the forms needs functions and relations")
    out = [Form(str(of), FUNCTION, (INPUT,)) for of in functions]
    for of, generates in relations.items():
        if not isinstance(generates, list) or not generates:
            raise RenderError(f"the form of {of} generates no argument")
        out.append(Form(str(of), RELATION, tuple(str(g) for g in generates)))
    return out


def series(labels: Sequence[str]) -> str:
    """Return labels as an English series: "a and b", "a, b and c"."""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def summary(form: Form) -> str:
    """Return the summary of a form's entry."""
    if form.generates == (INPUT,):
        generated, pronoun = "the input", "it"
    else:
        generated, pronoun = series(form.generates), "them"
    return (
        f"The property form of {form.of}. Each case of a run generates "
        f"{generated}, and {form.of} runs on {pronoun} as {FOR_ALL} runs a body.\n"
    )


def form_entry(form: Form, assertions: Mapping[str, Any]) -> dict[str, Any]:
    """Return the assertion entry of one form.

    The arity of a form over a function is its assertion's, because the
    function takes the place of the value. A relation's form generates
    arguments the relation takes, so its arity is less by their number.

    Raises:
        RenderError: the form's assertion is not defined.
    """
    found = assertions.get(form.of)
    if not isinstance(found, Mapping):
        raise RenderError(f"the form of {form.of} runs an assertion nobody defined")
    runs_as = assertions.get(FOR_ALL)
    if not isinstance(runs_as, Mapping):
        raise RenderError(f"the forms run as {FOR_ALL}, which is not defined")
    base: Mapping[str, Any] = found
    for_all: Mapping[str, Any] = runs_as
    removed = len(form.generates) if form.kind == RELATION else 0
    entry: dict[str, Any] = {
        "arity": int(base["arity"]) - removed,
        "package": FORM_PACKAGE,
        "summary": summary(form),
        "detail_fields": list(for_all["detail_fields"]),
        "form": {"of": form.of, "kind": form.kind, "generates": list(form.generates)},
    }
    if base.get("relaxations"):
        entry["relaxations"] = list(base["relaxations"])
    return entry


def form_names(
    form: Form, names: Mapping[str, Any], rule: Mapping[str, Any]
) -> dict[str, str]:
    """Return a form's name in each language that the naming rule qualifies.

    A name is the language's qualifier followed by the assertion's name,
    unless the rule states an exception for the form's assertion.

    Raises:
        RenderError: the assertion has no name in a qualified language.
    """
    exceptions = rule.get("exceptions", {}).get(form.of, {})
    out: dict[str, str] = {}
    for language, qualifier in rule["qualifiers"].items():
        if language in exceptions:
            out[language] = str(exceptions[language])
            continue
        name = names.get(form.of, {}).get(language)
        if name is None:
            raise RenderError(f"{form.of} has no {language} name to qualify")
        out[language] = f"{qualifier}{name}"
    return out


def published(
    spec: dict[str, Any], naming: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return both tables with an entry and a name for every form.

    Raises:
        RenderError: a form's id is already an authored entry, or the rule
            cannot be read.
    """
    rule = naming.get("forms")
    if not isinstance(rule, Mapping) or not isinstance(rule.get("qualifiers"), Mapping):
        raise RenderError("spec/naming.yaml states no qualifiers for the forms")
    assertions, names = spec["assertions"], naming["names"]
    for form in forms(spec):
        if form.id in assertions or form.id in names:
            raise RenderError(f"{form.id} is authored; the rule renders it")
        assertions[form.id] = form_entry(form, assertions)
        names[form.id] = form_names(form, names, rule)
    return spec, naming


def load(name: str) -> dict[str, Any]:
    """Return one table as its YAML states it."""
    document: dict[str, Any] = yaml.safe_load(
        (ROOT / "spec" / f"{name}.yaml").read_text()
    )
    return document


def render(name: str, document: Mapping[str, Any]) -> bool:
    """Render one table, and return whether the file on disk changed."""
    rendered = json.dumps(document, indent=4, sort_keys=True)
    return write(ROOT / "spec" / f"{name}.json", rendered + "\n")


def vector(family: str, kind: str, case: Any) -> Vector:
    """Return one case's inputs followed by the outputs the reference computes.

    Raises:
        RenderError: the case is not an object, or an output has the name
            of an input.
    """
    if not isinstance(case, dict):
        raise RenderError(f"a {kind} case is {case!r}, not an object")
    outputs = FAMILIES[family][1](kind, case)
    clash = sorted(set(outputs) & set(case))
    if clash:
        raise RenderError(f"{case.get('id')!r} states the outputs {clash}")
    return {**case, **outputs}


def vectors_text(family: str, kind: str) -> str:
    """Return the JSON of one kind of vector, rendered from its YAML inputs.

    Raises:
        RenderError: the YAML states another kind, or no list of cases.
    """
    source = CORPUS / family / f"{kind}.yaml"
    document = yaml.safe_load(source.read_text())
    if not isinstance(document, dict) or document.get("kind") != kind:
        raise RenderError(f"{source.name} does not state kind {kind!r}")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise RenderError(f"{source.name} states no list of cases")
    rendered = {"kind": kind, "cases": [vector(family, kind, case) for case in cases]}
    return json.dumps(rendered, indent=2) + "\n"


def render_vectors(family: str, kind: str) -> bool:
    """Render one kind of vector, and return whether the file on disk changed.

    Raises:
        RenderError: the YAML states another kind, or no list of cases.
    """
    return write(CORPUS / family / f"{kind}.json", vectors_text(family, kind))


def main() -> int:
    """Render every table and every kind of vector, and print which files changed."""
    spec, naming = published(load("assertions"), load("naming"))
    for name, document in zip(TABLES, (spec, naming), strict=True):
        changed = render(name, document)
        print(f"spec/{name}.json: {'rendered' if changed else 'unchanged'}")
    for family, (kinds, _) in FAMILIES.items():
        for kind in kinds:
            changed = render_vectors(family, kind)
            state = "rendered" if changed else "unchanged"
            print(f"corpus/{family}/{kind}.json: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
