#!/usr/bin/env python3
"""Hold the definition and the corpus to their own rules.

A standard nobody can check is a document. This reads what the repo
publishes, the rendered JSON rather than the YAML behind it, because
that is what an implementation reads, and reports every problem it
finds rather than stopping at the first.

Standard library only. A repo that defines a cross-language standard
should not need a toolchain to say whether it is well formed.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: The types a corpus case may state, and the keys each one carries
#: beyond ``type``. Mirrors the table in the encoding document.
SCALARS = {"bool", "int", "float", "string"}
LITERALS: dict[str, set[str]] = {
    "null": set(),
    "bool": {"value"},
    "int": {"value"},
    "float": {"value"},
    "string": {"value"},
    "list": {"of", "value"},
    "map": {"key", "of", "value"},
}

#: JSON carries no NaN or infinity, so a float may name one instead.
NON_FINITE = {"NaN", "Inf", "-Inf"}

#: What a case may say it expects of the assertion under test.
OUTCOMES = {"pass", "fail"}

#: Ids and names are lowercase words joined by hyphens. A qualified
#: name adds one dot, naming a member of a subpackage.
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CASE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*$")


class Problems:
    """Every problem found, in the order they were found."""

    def __init__(self) -> None:
        """Return a report with nothing in it."""
        self._found: list[str] = []

    def at(self, where: str, what: str) -> None:
        """Record one problem, and where it is."""
        self._found.append(f"{where}: {what}")

    def unless(self, held: bool, where: str, what: str) -> bool:
        """Record a problem when held is false, and answer held."""
        if not held:
            self.at(where, what)
        return held

    def report(self) -> int:
        """Print what was found and answer the exit status."""
        for problem in self._found:
            print(problem, file=sys.stderr)
        if self._found:
            print(f"\n{len(self._found)} problem(s)", file=sys.stderr)
            return 1
        return 0


def _load(path: Path, problems: Problems) -> Any:
    """Read one JSON file, recording a problem rather than raising."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as err:
        problems.at(str(path.relative_to(ROOT)), f"cannot be read: {err}")
        return None


def check_version(spec: Any, naming: Any, version: str, problems: Problems) -> None:
    """The VERSION file and both tables must agree."""
    problems.unless(
        spec.get("version") == version,
        "spec/assertions.json",
        f"states version {spec.get('version')!r}, VERSION says {version!r}",
    )
    problems.unless(
        naming.get("version") == version,
        "spec/naming.json",
        f"states version {naming.get('version')!r}, VERSION says {version!r}",
    )


def check_assertions(spec: Any, problems: Problems) -> set[str]:
    """Every assertion states an id, an arity and a summary."""
    assertions = spec.get("assertions", {})
    problems.unless(bool(assertions), "spec/assertions.json", "states no assertions")

    for aid, body in sorted(assertions.items()):
        where = f"spec/assertions.json: {aid}"
        problems.unless(bool(ID.match(aid)), where, "is not a hyphenated lowercase id")
        arity = body.get("arity")
        problems.unless(
            isinstance(arity, int) and arity >= 1,
            where,
            f"states arity {arity!r}; an assertion takes at least one argument",
        )
        problems.unless(
            bool(str(body.get("summary", "")).strip()), where, "states no summary"
        )
        fields = body.get("message_fields", [])
        problems.unless(isinstance(fields, list), where, "message_fields is not a list")
        package = body.get("package", "")
        problems.unless(
            package == "" or bool(ID.match(package)),
            where,
            f"names package {package!r}, which is not an id",
        )
    return set(assertions)


def check_naming(
    naming: Any, spec: Any, assertions: set[str], problems: Problems
) -> None:
    """The naming table covers every assertion, in every language.

    A name is qualified exactly when the assertion names a package.
    The separator is the language's own: a dot in Go, Java and Python,
    two colons in Rust.
    That is the check worth having: the two tables are edited apart,
    and a name that says ``golden.match`` for an assertion in the root
    namespace sends every implementation looking in the wrong place.

    What the qualifier is stays the language's business. Python and
    TypeScript qualify by module, so the head is the package name. Java
    and Kotlin qualify by type and reach the package through an import,
    so theirs is a class name. Requiring the package name would be
    requiring one language's conventions of all of them.
    """
    defined = spec.get("assertions", {})
    languages = naming.get("languages", [])
    names = naming.get("names", {})

    problems.unless(bool(languages), "spec/naming.json", "declares no languages")

    for missing in sorted(assertions - set(names)):
        problems.at("spec/naming.json", f"{missing} has no entry")
    for extra in sorted(set(names) - assertions):
        problems.at("spec/naming.json", f"{extra} is named but not defined")

    for aid, per_language in sorted(names.items()):
        for language, name in sorted(per_language.items()):
            where = f"spec/naming.json: {aid}.{language}"
            problems.unless(
                language in languages,
                where,
                f"{language} is not in the declared languages",
            )
            problems.unless(
                isinstance(name, str) and name.strip() != "", where, "is empty"
            )
            package = defined.get(aid, {}).get("package", "")
            qualified = "." in str(name) or "::" in str(name)
            problems.unless(
                qualified == bool(package),
                where,
                f"{name!r} is not qualified, but the assertion names "
                f"package {package!r}"
                if package
                else f"{name!r} is qualified, but the assertion names no package",
            )


def check_literal(value: Any, where: str, problems: Problems) -> None:
    """One typed literal, held to the encoding."""
    if not isinstance(value, dict):
        problems.at(where, f"is {type(value).__name__}, not a typed literal")
        return

    kind = value.get("type")
    if kind not in LITERALS:
        problems.at(where, f"states type {kind!r}, which the encoding does not define")
        return

    allowed = LITERALS[kind] | {"type"}
    for key in sorted(set(value) - allowed):
        problems.at(where, f"carries {key!r}, which type {kind!r} does not take")
    for key in sorted(LITERALS[kind] - set(value)):
        problems.at(where, f"type {kind!r} needs {key!r}")

    for key in ("of", "key"):
        if key in value:
            problems.unless(
                value[key] in SCALARS,
                where,
                f"{key} is {value[key]!r}, which is not a scalar type",
            )

    if kind == "float" and isinstance(value.get("value"), str):
        problems.unless(
            value["value"] in NON_FINITE,
            where,
            f"states float {value['value']!r}; only {sorted(NON_FINITE)} are named",
        )


def check_case(case: Any, assertion: str, where: str, problems: Problems) -> str | None:
    """One corpus case, held to its own shape. Answers its id."""
    if not isinstance(case, dict):
        problems.at(where, "is not an object")
        return None

    cid = case.get("id", "")
    problems.unless(
        bool(CASE_ID.match(str(cid))),
        where,
        f"states id {cid!r}, want <assertion>/<case> in hyphenated lowercase",
    )
    problems.unless(
        str(cid).startswith(f"{assertion}/"),
        where,
        f"id {cid!r} does not begin with {assertion!r}",
    )

    outcome = case.get("expect")
    problems.unless(
        outcome in OUTCOMES,
        f"{where} [{cid}]",
        f"expects {outcome!r}, want one of {sorted(OUTCOMES)}",
    )

    args = case.get("args")
    if isinstance(args, list):
        for index, arg in enumerate(args):
            check_literal(arg, f"{where} [{cid}] arg {index}", problems)
    else:
        problems.at(f"{where} [{cid}]", "states no args")

    contains = case.get("message_contains", [])
    if problems.unless(
        isinstance(contains, list), f"{where} [{cid}]", "message_contains is not a list"
    ):
        problems.unless(
            outcome == "fail" or not contains,
            f"{where} [{cid}]",
            "expects a pass but states message_contains, which only a failure has",
        )

    skip = case.get("skip", {})
    if problems.unless(
        isinstance(skip, dict), f"{where} [{cid}]", "skip is not an object"
    ):
        for language, reason in sorted(skip.items()):
            problems.unless(
                bool(str(reason).strip()),
                f"{where} [{cid}] skip.{language}",
                "states no reason; a skip is a claim people read",
            )
    return str(cid)


def check_corpus(assertions: set[str], problems: Problems) -> int:
    """Every corpus file names a defined assertion; every id is unique."""
    seen: dict[str, str] = {}
    total = 0

    files = sorted((ROOT / "corpus").glob("*.json"))
    problems.unless(bool(files), "corpus/", "holds no cases")

    for path in files:
        where = str(path.relative_to(ROOT))
        document = _load(path, problems)
        if document is None:
            continue

        assertion = document.get("assertion", "")
        problems.unless(
            assertion in assertions,
            where,
            f"names assertion {assertion!r}, which the definition does not state",
        )
        problems.unless(
            path.stem == assertion,
            where,
            f"is named {path.stem!r} but carries {assertion!r}",
        )

        cases = document.get("cases", [])
        if not problems.unless(
            isinstance(cases, list) and bool(cases), where, "states no cases"
        ):
            continue

        for case in cases:
            cid = check_case(case, str(assertion), where, problems)
            total += 1
            if cid is None:
                continue
            problems.unless(
                cid not in seen, where, f"repeats case id {cid!r} from {seen.get(cid)}"
            )
            seen.setdefault(cid, where)
    return total


@dataclass(frozen=True)
class Relaxations:
    """What the definition and the table say about the relaxations.

    One value rather than three arguments, because the three travel
    together: the ids the definition declares, which of them each
    language names, and which languages implement anything at all.
    """

    declared: frozenset[str]
    named: dict[str, set[str]]
    implementing: frozenset[str]


def check_relaxations(spec: Any, naming: Any, problems: Problems) -> Relaxations:
    """The relaxations are named, and every assertion referencing one means it.

    A relaxation widens what counts as equal for one call. Naming them
    here is what stops each language inventing its own set: four of the
    implementations arrived at the same two, and a fifth at neither,
    which is only comparable once the standard states what they are.

    Returns what the overlay check holds each language to.
    """
    declared = spec.get("relaxations", {})
    problems.unless(bool(declared), "spec/assertions.json", "states no relaxations")

    for rid, entry in sorted(declared.items()):
        where = f"spec/assertions.json:{rid}"
        problems.unless(bool(ID.match(rid)), where, "is not a hyphenated lowercase id")
        problems.unless(
            bool(str(entry.get("summary", "")).strip()), where, "has no summary"
        )

    for aid, entry in sorted(spec.get("assertions", {}).items()):
        for rid in entry.get("relaxations", []):
            problems.unless(
                rid in declared,
                f"spec/assertions.json:{aid}",
                f"accepts unknown relaxation {rid!r}",
            )

    named = naming.get("relaxations", {})
    for rid in sorted(declared):
        problems.unless(
            rid in named, "spec/naming.json", f"names no relaxation {rid!r}"
        )
    for rid in sorted(named):
        problems.unless(
            rid in declared,
            "spec/naming.json",
            f"names relaxation {rid!r}, which the definition does not state",
        )

    by_language: dict[str, set[str]] = {}
    for rid, per_language in named.items():
        for language in per_language:
            by_language.setdefault(language, set()).add(rid)

    # A declared target with no names yet owes nothing: requiring it to
    # decline every relaxation would make declaring a target language a
    # chore before any work exists.
    implementing: set[str] = set()
    for per_language in naming.get("names", {}).values():
        implementing.update(per_language)

    return Relaxations(
        declared=frozenset(declared),
        named=by_language,
        implementing=frozenset(implementing),
    )


SURFACE_SECTIONS = ("types", "members", "helpers")

#: Surface ids: kebab words, one dot for a member's owner or a helper's
#: package. `recorder-seat.message` and `golden.should-update` fit;
#: bare `flush` and `a.b.c` do not.
SURFACE_ID = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)?$")


def check_surface(naming: Any, languages: set[str], problems: Problems) -> None:
    """The surface table names what a caller touches beyond the assertions.

    Every entry is well formed, every member names an owner the types
    section declares, and every name belongs to a declared language. The
    per-language completeness rule lives with the overlays, the same way
    the relaxations' does.
    """
    surface = naming.get("surface", {})
    problems.unless(bool(surface), "spec/naming.json", "states no surface table")

    types = set(surface.get("types", {}))
    for section in SURFACE_SECTIONS:
        for sid, per_language in sorted(surface.get(section, {}).items()):
            where = f"spec/naming.json: surface.{section}.{sid}"
            problems.unless(
                bool(SURFACE_ID.match(sid)), where, "is not a well-formed id"
            )
            if section == "members":
                owner = sid.split(".", 1)[0]
                problems.unless(
                    owner in types,
                    where,
                    f"names a member of {owner!r}, which the types "
                    "section does not declare",
                )
            for language, name in sorted(per_language.items()):
                problems.unless(
                    language in languages,
                    where,
                    f"{language} is not in the declared languages",
                )
                problems.unless(
                    isinstance(name, str) and name.strip() != "",
                    where,
                    f"{language} is empty",
                )


@dataclass(frozen=True)
class Tables:
    """Everything the overlay checks hold a language to.

    One value rather than four arguments: the relaxations, the surface
    ids and who names them, and the declared languages all describe the
    same naming document and travel together.
    """

    relaxations: Relaxations
    surface_ids: frozenset[str]
    surface_named: dict[str, set[str]]
    languages: frozenset[str]


def surface_names_by_language(naming: Any) -> dict[str, set[str]]:
    """Which surface ids each language names, across all three sections."""
    out: dict[str, set[str]] = {}
    for section in SURFACE_SECTIONS:
        for sid, per_language in naming.get("surface", {}).get(section, {}).items():
            for language in per_language:
                out.setdefault(language, set()).add(sid)
    return out


def surface_ids(naming: Any) -> frozenset[str]:
    """Every id the surface table states."""
    found: set[str] = set()
    for section in SURFACE_SECTIONS:
        found.update(naming.get("surface", {}).get(section, {}))
    return frozenset(found)


def check_overlay_surface(
    overlay: Any, where: str, language: Any, tables: Tables, problems: Problems
) -> None:
    """One language's answer to the surface, held to name-or-decline.

    The same rule as the relaxations: an implementing language answers
    every surface id one way, declining needs a reason, and declining
    something the table also names for it is a contradiction.
    """
    declined_entries = overlay.get("surface", [])
    if not problems.unless(
        isinstance(declined_entries, list), where, "surface is not a list"
    ):
        return

    for entry in declined_entries:
        if not problems.unless(
            isinstance(entry, dict), where, f"surface entry {entry!r} is not an object"
        ):
            continue
        sid = entry.get("id")
        problems.unless(
            sid in tables.surface_ids,
            where,
            f"declines surface id {sid!r}, which the table does not state",
        )
        problems.unless(
            bool(str(entry.get("why", "")).strip()),
            where,
            f"declines surface id {sid!r} with no why",
        )

    declined = {e.get("id") for e in declined_entries if isinstance(e, dict)}
    if language not in tables.relaxations.implementing:
        return

    named_here = tables.surface_named.get(str(language), set())
    for sid in sorted(tables.surface_ids):
        problems.unless(
            sid in named_here or sid in declined,
            where,
            f"neither names nor declines surface id {sid!r}",
        )
        problems.unless(
            not (sid in named_here and sid in declined),
            where,
            f"both names and declines surface id {sid!r}, which is a contradiction",
        )


def check_overlay_relaxations(
    overlay: Any,
    where: str,
    language: Any,
    relaxations: Relaxations,
    problems: Problems,
) -> None:
    """One language's answer to the relaxations, held to name-or-decline.

    Declining needs a reason, declining the undefined is refused, and an
    implementing language answers every relaxation exactly one way:
    named and declined is a contradiction, neither is a silent gap.
    """
    relaxed = overlay.get("relaxations", [])
    if problems.unless(isinstance(relaxed, list), where, "relaxations is not a list"):
        for entry in relaxed:
            if not problems.unless(
                isinstance(entry, dict),
                where,
                f"relaxation {entry!r} is not an object",
            ):
                continue
            rid = entry.get("id")
            problems.unless(
                rid in relaxations.declared,
                where,
                f"declares relaxation {rid!r} absent, which is not defined",
            )
            problems.unless(
                bool(str(entry.get("why", "")).strip()),
                where,
                f"declares relaxation {rid!r} absent with no why",
            )

    declined = {e.get("id") for e in relaxed if isinstance(e, dict)}
    if language not in relaxations.implementing:
        return

    named_here = relaxations.named.get(str(language), set())
    for rid in sorted(relaxations.declared):
        problems.unless(
            rid in named_here or rid in declined,
            where,
            f"neither names nor declines relaxation {rid!r}; "
            "an implementing language answers every relaxation "
            "one way or the other",
        )
        problems.unless(
            not (rid in named_here and rid in declined),
            where,
            f"both names and declines relaxation {rid!r}, which is a contradiction",
        )


def check_overlays(
    assertions: set[str], tables: Tables, version: str, problems: Problems
) -> None:
    """An overlay extends this version and diverges only on real ids.

    A divergence carries id, stance and why. The point of the mechanism
    is that a gap nobody could close and a gap nobody got to look
    identical unless someone writes down which it is, so an entry with
    no reason defeats it and fails here.

    A limit is the third state: the assertion is implemented, and there
    is a case it cannot see. It carries id, what and why, and an
    assertion cannot be both, because a divergence must be absent and a
    limit must be present.
    """
    for path in sorted((ROOT / "overlays").glob("*.json")):
        where = str(path.relative_to(ROOT))
        overlay = _load(path, problems)
        if overlay is None:
            continue

        want = f"spec://assertions@{version}"
        problems.unless(
            overlay.get("extends") == want,
            where,
            f"extends {overlay.get('extends')!r}, want {want!r}",
        )
        language = overlay.get("language")
        problems.unless(
            path.stem == language,
            where,
            f"is named {path.stem!r} but declares {language!r}",
        )
        problems.unless(
            language in tables.languages,
            where,
            f"declares {language!r}, which the naming table does not list",
        )

        check_overlay_relaxations(
            overlay, where, language, tables.relaxations, problems
        )
        check_overlay_surface(overlay, where, language, tables, problems)

        limits = overlay.get("limits", [])
        if problems.unless(isinstance(limits, list), where, "limits is not a list"):
            for entry in limits:
                if not problems.unless(
                    isinstance(entry, dict), where, f"limit {entry!r} is not an object"
                ):
                    continue
                aid = entry.get("id")
                problems.unless(
                    aid in assertions, where, f"limits {aid!r}, which is not defined"
                )
                for field in ("what", "why"):
                    problems.unless(
                        bool(str(entry.get(field, "")).strip()),
                        where,
                        f"limits {aid!r} with no {field}",
                    )

        diverge = overlay.get("diverge", [])
        if not problems.unless(
            isinstance(diverge, list), where, "diverge is not a list"
        ):
            continue

        seen: set[str] = set()
        for entry in diverge:
            if not problems.unless(
                isinstance(entry, dict), where, f"divergence {entry!r} is not an object"
            ):
                continue

            aid = entry.get("id")
            problems.unless(
                aid in assertions, where, f"diverges on {aid!r}, which is not defined"
            )
            problems.unless(aid not in seen, where, f"diverges on {aid!r} twice")
            seen.add(str(aid))
            problems.unless(
                aid not in {e.get("id") for e in limits if isinstance(e, dict)},
                where,
                f"{aid!r} is both diverged from and limited; it is one or "
                "the other, since a divergence is absent and a limit is not",
            )

            for field in ("stance", "why"):
                problems.unless(
                    bool(str(entry.get(field, "")).strip()),
                    where,
                    f"diverges on {aid!r} with no {field}",
                )


def main() -> int:
    """Read everything, check everything, report once."""
    problems = Problems()

    version = (ROOT / "VERSION").read_text().strip()
    spec = _load(ROOT / "spec" / "assertions.json", problems)
    naming = _load(ROOT / "spec" / "naming.json", problems)
    if spec is None or naming is None:
        return problems.report()

    check_version(spec, naming, version, problems)
    assertions = check_assertions(spec, problems)
    relaxations = check_relaxations(spec, naming, problems)
    check_naming(naming, spec, assertions, problems)
    cases = check_corpus(assertions, problems)
    check_surface(naming, set(naming.get("languages", [])), problems)
    check_overlays(
        assertions,
        Tables(
            relaxations=relaxations,
            surface_ids=surface_ids(naming),
            surface_named=surface_names_by_language(naming),
            languages=frozenset(naming.get("languages", [])),
        ),
        version,
        problems,
    )

    status = problems.report()
    if status == 0:
        print(
            f"spec {version}: {len(assertions)} assertions, "
            f"{cases} corpus cases, all consistent"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
