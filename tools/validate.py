#!/usr/bin/env python3
"""Check the definition, the corpus and the overlays against their rules.

The validator reads the published files, the rendered JSON an
implementation reads, and not the YAML behind them. It reports every
problem it finds in one run.

It needs the standard library and this repository's executable
reference, which needs nothing else, so a bare Python runs it.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prop import literal
from prop.coverage import Verdict
from prop.generator import IDS
from prop.runner import Kind
from prop.store import Verdict as StoreVerdict
from prop.vectors import KINDS

ROOT = Path(__file__).resolve().parent.parent

#: The scalar types a list's ``of`` and a map's ``key`` may name.
SCALARS = {"bool", "int", "float", "string"}

#: The types a typed literal may state, and the forms of each: the keys a
#: literal of the type has beside ``type``. The table in the encoding
#: document states the same forms.
FORMS: dict[str, tuple[frozenset[str], ...]] = {
    "null": (frozenset(),),
    "bool": (frozenset({"value"}),),
    "int": (frozenset({"value"}),),
    "float": (frozenset({"value"}),),
    "string": (frozenset({"value"}),),
    "bytes": (frozenset({"value"}),),
    "list": (frozenset({"of", "value"}), frozenset({"items"})),
    "map": (frozenset({"key", "of", "value"}), frozenset({"entries"})),
}

#: JSON has no NaN or infinity, so a float states them by these names.
NON_FINITE = {"NaN", "Inf", "-Inf"}

#: The outcomes a case may expect of the assertion under test.
OUTCOMES = {"pass", "fail"}

#: Ids and names are lowercase words joined by hyphens. A qualified
#: name adds one dot, naming a member of a subpackage.
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CASE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*$")

#: The vector kinds whose ids name the generator under test, as
#: <generator>/<case>. The ids of every other kind start with the kind.
GENERATOR_KINDS = frozenset({"decoding", "generation", "shrinking"})

#: The outcomes a shrinking vector of each generator must include.
SHRUNK_BOTH_WAYS = (Kind.COUNTEREXAMPLE.value, Kind.PASSED.value)


class Problems:
    """Every problem found, in the order the checks found them."""

    def __init__(self) -> None:
        """Start a report with no problem."""
        self._found: list[str] = []

    def at(self, where: str, what: str) -> None:
        """Record one problem and where it is."""
        self._found.append(f"{where}: {what}")

    def unless(self, held: bool, where: str, what: str) -> bool:
        """Record a problem when held is false, and return held."""
        if not held:
            self.at(where, what)
        return held

    def report(self) -> int:
        """Print every problem, and return 1 when there is one and 0 otherwise."""
        for problem in self._found:
            print(problem, file=sys.stderr)
        if self._found:
            print(f"\n{len(self._found)} problem(s)", file=sys.stderr)
            return 1
        return 0


def _load(path: Path, problems: Problems) -> Any:
    """Return a JSON file's content, or record a problem and return None."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as err:
        problems.at(str(path.relative_to(ROOT)), f"cannot be read: {err}")
        return None


def check_version(spec: Any, naming: Any, version: str, problems: Problems) -> None:
    """Record a problem for each table whose version differs from VERSION."""
    problems.unless(
        spec.get("version") == version,
        "spec/assertions.json",
        f"states version {spec.get('version')!r}, and VERSION states {version!r}",
    )
    problems.unless(
        naming.get("version") == version,
        "spec/naming.json",
        f"states version {naming.get('version')!r}, and VERSION states {version!r}",
    )


def check_assertions(spec: Any, problems: Problems) -> dict[str, set[str]]:
    """Check every assertion's id, arity, summary, detail fields and package.

    Returns each assertion's detail fields, by id.
    """
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
        fields = body.get("detail_fields", [])
        if problems.unless(
            isinstance(fields, list), where, "detail_fields is not a list"
        ):
            for field in fields:
                problems.unless(
                    isinstance(field, str) and bool(FIELD.match(str(field))),
                    where,
                    f"names detail field {field!r}, which is not a field name",
                )
            problems.unless(
                len(set(fields)) == len(fields),
                where,
                "names the same detail field twice",
            )
        package = body.get("package", "")
        problems.unless(
            package == "" or bool(ID.match(package)),
            where,
            f"names package {package!r}, which is not an id",
        )
    return {
        aid: set(body.get("detail_fields", []) or [])
        for aid, body in assertions.items()
        if isinstance(body, dict)
    }


def check_subjects(spec: Any, problems: Problems) -> set[str]:
    """Check the subject vocabulary, and return its kinds.

    A case that cannot state a callable names a subject kind instead, and
    each implementation builds that subject natively. Every implementation
    must build every kind, so the vocabulary is small.
    """
    subjects = spec.get("subjects", {})
    problems.unless(
        bool(subjects), "spec/assertions.json", "states no subject vocabulary"
    )
    for kind, body in sorted(subjects.items()):
        where = f"spec/assertions.json: subject {kind}"
        problems.unless(bool(ID.match(kind)), where, "is not a hyphenated lowercase id")
        stated = isinstance(body, dict) and bool(str(body.get("summary", "")).strip())
        problems.unless(stated, where, "states no summary")
    return set(subjects)


def check_naming(
    naming: Any, spec: Any, assertions: set[str], problems: Problems
) -> None:
    """Check that the naming table names every assertion in every language.

    A name is qualified exactly when its assertion names a package. The
    separator is the language's own: a dot in Go, Java and Python, and
    two colons in Rust. The two tables are edited separately, and a name
    such as ``golden.match`` for an assertion in the root namespace sends
    every implementation to the wrong place.

    The qualifier itself is the language's choice. Python and TypeScript
    qualify by module, so the head is the package name. Java and Kotlin
    qualify by type and reach the package through an import, so the head
    is a class name. A rule that required the package name would impose
    one language's conventions on all of them.
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
    """Check one typed literal against the encoding.

    A literal whose keys fit no form of its type is reported by key. A
    literal whose keys fit is decoded with the reference's codec, which
    reports a value the type cannot take, such as a JavaScript-unsafe
    integer stated as a number or bytes that are not lowercase hex.
    """
    if not isinstance(value, dict):
        problems.at(where, f"is {type(value).__name__}, not a typed literal")
        return

    kind = value.get("type")
    if kind not in FORMS:
        problems.at(where, f"states type {kind!r}, which the encoding does not define")
        return

    keys = frozenset(value) - {"type"}
    form = max(FORMS[kind], key=lambda f: len(f & keys))
    for key in sorted(keys - form):
        problems.at(where, f"states {key!r}, which type {kind!r} does not take")
    for key in sorted(form - keys):
        problems.at(where, f"type {kind!r} needs {key!r}")
    if keys != form:
        return

    for key in ("of", "key"):
        if key in value and value[key] not in SCALARS:
            problems.at(where, f"{key} is {value[key]!r}, which is not a scalar type")
            return

    named = value.get("value")
    if kind == "float" and isinstance(named, str) and named not in NON_FINITE:
        problems.at(
            where, f"states float {named!r}; only {sorted(NON_FINITE)} are named"
        )
        return

    try:
        literal.decode(value)
    except literal.LiteralError as bad:
        problems.at(where, str(bad).removeprefix("prop: "))


@dataclass(frozen=True)
class Vocabulary:
    """The names a corpus case may use.

    The detail fields of the assertion under test and the subject kinds
    of the definition are checked together, because a case names either
    detail fields or a subject.
    """

    detail: set[str]
    subjects: set[str]


def check_case(
    case: Any, assertion: str, vocabulary: Vocabulary, where: str, problems: Problems
) -> str | None:
    """Check one corpus case, and return its id, or None when it is no object."""
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
    subject = case.get("subject")
    if args is None and subject is None:
        problems.at(f"{where} [{cid}]", "states neither args nor a subject")
    problems.unless(
        args is None or subject is None,
        f"{where} [{cid}]",
        "states both args and a subject; a case states one of them",
    )
    if isinstance(args, list):
        for index, arg in enumerate(args):
            check_literal(arg, f"{where} [{cid}] arg {index}", problems)
    elif args is not None:
        problems.at(f"{where} [{cid}]", "states args that are not a list")

    if subject is not None and problems.unless(
        isinstance(subject, dict), f"{where} [{cid}]", "subject is not an object"
    ):
        kind = subject.get("kind")
        problems.unless(
            kind in vocabulary.subjects,
            f"{where} [{cid}]",
            f"names subject kind {kind!r}, which the definition does not state",
        )

    detail = case.get("detail", {})
    if problems.unless(
        isinstance(detail, dict), f"{where} [{cid}]", "detail is not an object"
    ):
        problems.unless(
            outcome == "fail" or not detail,
            f"{where} [{cid}]",
            "expects a pass but states detail, which only a failure has",
        )
        for name, value in sorted(detail.items()):
            problems.unless(
                name in vocabulary.detail,
                f"{where} [{cid}]",
                f"states detail {name!r}, which {assertion} does not declare",
            )
            check_literal(value, f"{where} [{cid}] detail.{name}", problems)

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


def check_corpus(
    assertions: dict[str, set[str]], subjects: set[str], problems: Problems
) -> int:
    """Check every corpus file and case, and return the number of cases.

    Each file names a defined assertion, and each case id is unique.
    """
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
            f"is named {path.stem!r} but states {assertion!r}",
        )

        cases = document.get("cases", [])
        if not problems.unless(
            isinstance(cases, list) and bool(cases), where, "states no cases"
        ):
            continue

        # A suite that drives an assertion only with inputs that satisfy
        # it passes when the assertion reports nothing. Each assertion
        # therefore has a passing and a failing case.
        outcomes = {case.get("expect") for case in cases if isinstance(case, dict)}
        for wanted in OUTCOMES:
            problems.unless(
                wanted in outcomes,
                where,
                f"states no case expecting {wanted!r}; an assertion is driven "
                "both ways or the corpus proves nothing about it",
            )

        for case in cases:
            cid = check_case(
                case,
                str(assertion),
                Vocabulary(
                    detail=assertions.get(str(assertion), set()), subjects=subjects
                ),
                where,
                problems,
            )
            total += 1
            if cid is None:
                continue
            problems.unless(
                cid not in seen, where, f"repeats case id {cid!r} from {seen.get(cid)}"
            )
            seen.setdefault(cid, where)
    return total


def literals(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Yield every typed literal under node with its path.

    A typed literal is an object with a ``type`` key. The parts of a
    literal are not yielded on their own, because check_literal checks a
    literal whole.
    """
    if isinstance(node, dict):
        if "type" in node:
            yield path, node
            return
        for key, child in node.items():
            yield from literals(child, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from literals(child, f"{path}[{index}]")


def check_vector_cases(
    kind: str, cases: list[Any], where: str, problems: Problems
) -> None:
    """Check one kind's vectors: their ids, their literals and what they cover.

    Every generator has decoding, generation and shrinking vectors, and a
    shrinking vector that fails and one that passes. The behaviour
    vectors end in every outcome, and the coverage and store vectors
    reach every verdict of their kind.
    """
    prefixes = IDS if kind in GENERATOR_KINDS else frozenset({kind})
    seen: set[str] = set()
    found: dict[str, set[str]] = {}
    for case in cases:
        if not problems.unless(
            isinstance(case, dict), where, "a case is not an object"
        ):
            continue
        cid = str(case.get("id", ""))
        problems.unless(
            bool(CASE_ID.match(cid)),
            where,
            f"states id {cid!r}, want <subject>/<case> in hyphenated lowercase",
        )
        problems.unless(cid not in seen, where, f"repeats case id {cid!r}")
        seen.add(cid)
        prefix = cid.split("/", 1)[0]
        problems.unless(
            prefix in prefixes,
            where,
            f"id {cid!r} begins with {prefix!r}, which names no "
            + ("generator" if kind in GENERATOR_KINDS else f"{kind} vector"),
        )
        for path, value in literals(case):
            check_literal(value, f"{where} [{cid}] {path}", problems)
        detail = case.get("detail")
        reached = case.get("outcome") or case.get("verdict")
        if isinstance(detail, dict):
            reached = detail.get("outcome")
        found.setdefault(prefix, set()).add(str(reached))

    if kind in GENERATOR_KINDS:
        for gen in sorted(IDS - set(found)):
            problems.at(where, f"has no vector for generator {gen!r}")
    if kind == "shrinking":
        for gen in sorted(IDS & set(found)):
            for outcome in SHRUNK_BOTH_WAYS:
                problems.unless(
                    outcome in found[gen],
                    where,
                    f"has no {gen} vector whose outcome is {outcome!r}; a "
                    "generator is shrunk both ways or the corpus proves nothing",
                )
    ends = {
        "behaviour": [k.value for k in Kind],
        "coverage": [v.value for v in Verdict],
        "store": [v.value for v in StoreVerdict],
    }
    for end in ends.get(kind, []):
        problems.unless(
            end in found.get(kind, set()),
            where,
            f"has no vector that ends in {end!r}",
        )


def check_vectors(problems: Problems) -> int:
    """Check the property engine's vector files, and return the number of vectors.

    The outputs of each vector are the executable reference's. `make
    render` writes them from the YAML inputs, and the stale check fails
    when the reference computes other outputs. This check covers what the
    renderer copies from the YAML: each file's kind, the ids, the typed
    literals, and that the vectors cover the vocabulary.
    """
    folder = ROOT / "corpus" / "prop"
    files = {path.stem: path for path in sorted(folder.glob("*.json"))}
    for kind in KINDS:
        problems.unless(kind in files, "corpus/prop/", f"has no {kind} vectors")

    total = 0
    for stem, path in files.items():
        where = str(path.relative_to(ROOT))
        document = _load(path, problems)
        if document is None:
            continue
        kind = document.get("kind")
        problems.unless(
            kind == stem, where, f"is named {stem!r} but states kind {kind!r}"
        )
        if not problems.unless(
            kind in KINDS, where, f"states kind {kind!r}, which no vector has"
        ):
            continue
        cases = document.get("cases")
        if not problems.unless(
            isinstance(cases, list) and bool(cases), where, "states no cases"
        ):
            continue
        total += len(cases)
        check_vector_cases(str(kind), cases, where, problems)
    return total


@dataclass(frozen=True)
class Relaxations:
    """What the definition and the naming table state about the relaxations.

    declared is the ids the definition states, named is the ids each
    language names, and implementing is the languages that name at least
    one assertion.
    """

    declared: frozenset[str]
    named: dict[str, set[str]]
    implementing: frozenset[str]


def check_relaxations(spec: Any, naming: Any, problems: Problems) -> Relaxations:
    """Check that every relaxation is named, and every reference to one is defined.

    A relaxation widens what counts as equal for one call. The definition
    states the set, so every language offers the same relaxations.

    Returns the relaxations the overlay check applies to each language.
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

    # A declared language that names no assertion is not checked, so a
    # language can be declared before its implementation exists.
    implementing: set[str] = set()
    for per_language in naming.get("names", {}).values():
        implementing.update(per_language)

    return Relaxations(
        declared=frozenset(declared),
        named=by_language,
        implementing=frozenset(implementing),
    )


SURFACE_SECTIONS = ("types", "members", "helpers")

#: A detail field name, as an assertion declares it and a corpus case
#: states it: lowercase words, hyphenated.
FIELD = re.compile(r"^[a-z][a-z0-9-]*$")

#: A surface id: hyphenated lowercase words, with one dot between a member
#: and its owner or a helper and its package, as in
#: `recorder-seat.message`. `a.b.c` is not a surface id.
SURFACE_ID = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)?$")


def check_surface(naming: Any, languages: set[str], problems: Problems) -> None:
    """Check the surface table: what a caller uses beside the assertions.

    Every entry is well formed, every member names an owner that the
    types section declares, and every name is in a declared language.
    The overlay check applies the rule that every implementing language
    names or declines every row.
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
    """What the overlay check reads from the naming table.

    The relaxations, the surface ids, the surface ids each language
    names, and the declared languages.
    """

    relaxations: Relaxations
    surface_ids: frozenset[str]
    surface_named: dict[str, set[str]]
    languages: frozenset[str]


def surface_names_by_language(naming: Any) -> dict[str, set[str]]:
    """Return the surface ids each language names, across all three sections."""
    out: dict[str, set[str]] = {}
    for section in SURFACE_SECTIONS:
        for sid, per_language in naming.get("surface", {}).get(section, {}).items():
            for language in per_language:
                out.setdefault(language, set()).add(sid)
    return out


def surface_ids(naming: Any) -> frozenset[str]:
    """Return every id the surface table states."""
    found: set[str] = set()
    for section in SURFACE_SECTIONS:
        found.update(naming.get("surface", {}).get(section, {}))
    return frozenset(found)


def check_overlay_surface(
    overlay: Any, where: str, language: Any, tables: Tables, problems: Problems
) -> None:
    """Check that one implementing language names or declines every surface id.

    A decline states a reason, and a language may not both name and
    decline one id.
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
    """Check that one implementing language names or declines every relaxation.

    A decline states a reason and a defined relaxation, and a language
    may not both name and decline one relaxation.
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
            "an implementing language names or declines every relaxation",
        )
        problems.unless(
            not (rid in named_here and rid in declined),
            where,
            f"both names and declines relaxation {rid!r}, which is a contradiction",
        )


def check_overlays(
    assertions: set[str], tables: Tables, version: str, problems: Problems
) -> None:
    """Check that every overlay extends this version and names only defined ids.

    A divergence states an id, a stance and a reason. Without the reason,
    a gap that cannot be closed and a gap nobody has worked on look the
    same, so an entry without one fails.

    A limit is the third state: the assertion is implemented, and there
    is a case it cannot see. It states an id, what it misses and why. An
    assertion cannot be both, because a divergence is absent and a limit
    is present.
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
                # A limit names an assertion or a row of the surface table.
                # A seat without a lock is a limit on the seat, not on one
                # assertion.
                problems.unless(
                    aid in assertions or aid in tables.surface_ids,
                    where,
                    f"limits {aid!r}, which the standard does not state",
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
    """Run every check over the published files, and print every problem once."""
    problems = Problems()

    version = (ROOT / "VERSION").read_text().strip()
    spec = _load(ROOT / "spec" / "assertions.json", problems)
    naming = _load(ROOT / "spec" / "naming.json", problems)
    if spec is None or naming is None:
        return problems.report()

    check_version(spec, naming, version, problems)
    assertions = check_assertions(spec, problems)
    relaxations = check_relaxations(spec, naming, problems)
    check_naming(naming, spec, set(assertions), problems)
    cases = check_corpus(assertions, check_subjects(spec, problems), problems)
    vectors = check_vectors(problems)
    check_surface(naming, set(naming.get("languages", [])), problems)
    check_overlays(
        set(assertions),
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
            f"{cases} corpus cases, {vectors} vectors, all consistent"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
