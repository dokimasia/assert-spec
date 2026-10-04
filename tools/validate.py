#!/usr/bin/env python3
"""Check the definition, the corpus and the overlays against their rules.

The validator reads the published files, the rendered JSON an
implementation reads, and not the YAML behind them. It reports every
problem it finds in one run.

It needs the standard library and this repository's executable
reference, which needs nothing else, so a bare Python runs it.
"""

from __future__ import annotations

import calendar
import json
import re
import sys
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import history.linearizable
import history.seam
import history.vectors
from prop import literal
from prop.coverage import Verdict
from prop.execution import Phase
from prop.generator import IDS
from prop.runner import Kind
from prop.shape import SHAPES
from prop.store import Verdict as StoreVerdict
from prop.vectors import KINDS

ROOT = Path(__file__).resolve().parent.parent

#: The scalar types a list's ``of`` and a map's ``key`` may name, as the
#: reference's codec states them.
SCALARS = literal.SCALARS

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
    "record": (frozenset({"fields"}),),
    "variant": (frozenset({"name"}), frozenset({"name", "payload"})),
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

#: The shape vectors each shape has.
SHAPE_VECTORS = 2

#: What the fixture types cover between them: every shape a native type
#: reads as, and every row of the constraint table.
FIXTURE_COVERS = (SHAPES - {"wall-time"}) | frozenset(
    {
        "min-max",
        "sizes",
        "pattern",
        "alphabet",
        "nan-and-infinity",
        "unit",
        "scale",
        "version",
    }
)

#: The ends the draws vectors reach between them: every draw matched, the
#: entries ran out first, a label differed, and a value no choices produce.
DRAWS_ENDS = ("matched", "ran-out", "label", "value")

#: The form that no vector runs, because no case can state an allocation
#: count.
UNSTATED_FORMS = frozenset({"prop-max-allocs"})

#: The phase that no recording vector records, because a run of the phases
#: decodes no fuzzer's input.
UNRECORDED_PHASES = frozenset({Phase.FUZZ.value})

#: What an overlay's records entry states: the artifact that the language's
#: runner writes for a run, where each call record is in it, and where it
#: states each test's status.
RECORDS_KEYS = ("artifact", "location", "status")

#: What the ids of each kind of history vector begin with: the seam's
#: vectors are named for the history, and the checker's for its assertion.
HISTORY_PREFIXES = {"seam": "history", "linearizable": "linearizable"}

#: What the seam vectors cover between them, through a script and through
#: intervals: an event of every kind, a pending call, and a refused entry.
SEAM_ENDS = tuple(
    f"{form}:{end}"
    for form in ("script", "intervals")
    for end in (*(kind.value for kind in history.seam.Kind), "pending", "refused")
)

#: What the checker's vectors cover between them: every outcome and every
#: limit that a vector can state.
CHECK_ENDS = (
    *(outcome.value for outcome in history.linearizable.Outcome),
    *(f"limit:{limit.value}" for limit in history.linearizable.Limit),
)

#: The languages whose threads run on more than one core. The history's
#: counter synchronizes the clients of such a language, which can hide a
#: missing barrier in the subject, so the overlay of each limits RECORDER.
PARALLEL = frozenset({"go", "java", "kotlin", "rust"})

#: The surface id of the history, which records through that counter.
RECORDER = "history"


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
    """Return a JSON file's object, or record a problem and return None.

    Every file the validator reads is one JSON object, so any other
    document is reported here rather than raised by the first check that
    reads a key.
    """
    where = str(path.relative_to(ROOT))
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as err:
        problems.at(where, f"cannot be read: {err}")
        return None
    if not problems.unless(isinstance(document, dict), where, "is not a JSON object"):
        return None
    return document


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


def check_vocabulary(
    spec: Any, section: str, label: str, problems: Problems
) -> set[str]:
    """Check one vocabulary of names that a case states in place of a value.

    A case that cannot state a callable names a subject instead, and a
    history vector names a model. Each implementation builds every subject
    and every model natively, so each vocabulary is small, and each name
    has a summary to build it from. Returns the names.
    """
    entries = spec.get(section, {})
    problems.unless(
        bool(entries), "spec/assertions.json", f"states no {label} vocabulary"
    )
    for name, body in sorted(entries.items()):
        where = f"spec/assertions.json: {label} {name}"
        problems.unless(bool(ID.match(name)), where, "is not a hyphenated lowercase id")
        stated = isinstance(body, dict) and bool(str(body.get("summary", "")).strip())
        problems.unless(stated, where, "states no summary")
    return set(entries)


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

    A language that names one assertion names every assertion. One that
    its overlay declares absent keeps its name, so the implementation that
    later supplies it does not choose another.
    """
    defined = spec.get("assertions", {})
    languages = naming.get("languages", [])
    names = naming.get("names", {})

    problems.unless(bool(languages), "spec/naming.json", "declares no languages")

    for missing in sorted(assertions - set(names)):
        problems.at("spec/naming.json", f"{missing} has no entry")
    for extra in sorted(set(names) - assertions):
        problems.at("spec/naming.json", f"{extra} is named but not defined")

    implementing = {language for named in names.values() for language in named}
    for aid in sorted(assertions & set(names)):
        for language in sorted(implementing - set(names[aid])):
            problems.at(
                "spec/naming.json",
                f"{aid} has no {language} name, and {language} names other assertions",
            )

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


#: The start of a property form's id, and the assertion whose run every
#: form is.
FORM_PREFIX = "prop-"
FOR_ALL = "prop-for-all"


def _form_rule(spec: Any, problems: Problems) -> dict[str, tuple[str, list[Any]]]:
    """Return each assertion the forms rule lists, with its kind and what it generates.

    A form over a function generates input. A relation's form generates
    the arguments the rule states for it. An assertion listed twice is a
    problem, and its first listing counts.
    """
    rule = spec.get("forms")
    where = "spec/assertions.json: forms"
    if not problems.unless(isinstance(rule, dict), where, "is not a rule"):
        return {}
    functions = rule.get("functions")
    relations = rule.get("relations")
    if not problems.unless(
        isinstance(functions, list) and isinstance(relations, dict),
        where,
        "needs a list of functions and a map of relations",
    ):
        return {}
    stated: list[tuple[Any, str, Any]] = [(f, "function", ["input"]) for f in functions]
    stated += [(r, "relation", g) for r, g in relations.items()]
    listed: dict[str, tuple[str, list[Any]]] = {}
    for of, kind, generates in stated:
        if not problems.unless(of not in listed, where, f"lists {of!r} twice"):
            continue
        problems.unless(
            isinstance(generates, list) and bool(generates),
            where,
            f"states that the form of {of!r} generates {generates!r}, not arguments",
        )
        listed[str(of)] = (kind, generates if isinstance(generates, list) else [])
    return listed


def check_forms(spec: Any, naming: Any, problems: Problems) -> None:
    """Check every property form against the rules the two tables state.

    The assertion table's rule lists the assertions that have a property
    form, and the naming table's rule qualifies each form's name.
    Rendering adds an entry and a name for each form, and this check reads
    them back against the rules:

    - Each listed assertion is defined, is not itself a form, and is not
      prop-for-all, and its form's entry exists. Every entry with a form
      is one the rule lists.
    - A form's package is prop, its detail fields are prop-for-all's, and
      its relaxations are its assertion's.
    - A form over a function generates input and keeps its assertion's
      arity, because the function takes the place of the value. A
      relation's form generates the arguments the rule states, and its
      arity is less by their number.
    - A form's name in each qualified language is the qualifier followed
      by its assertion's name, unless the naming rule states an exception
      for that language.
    """
    listed = _form_rule(spec, problems)
    _check_form_entries(spec.get("assertions", {}), listed, problems)
    _check_form_names(naming, listed, problems)


def _check_form_entries(
    defined: Any, listed: dict[str, tuple[str, list[Any]]], problems: Problems
) -> None:
    """Check each listed form's entry, and that every entry with a form is listed."""
    for_all = defined.get(FOR_ALL, {})
    for of, (kind, generates) in sorted(listed.items()):
        where = f"spec/assertions.json: {FORM_PREFIX}{of}"
        base = defined.get(of)
        if not problems.unless(
            isinstance(base, dict) and "form" not in base and of != FOR_ALL,
            where,
            f"is the form of {of!r}, which is no assertion that can have a form",
        ):
            continue
        entry = defined.get(FORM_PREFIX + of)
        if not problems.unless(
            isinstance(entry, dict), where, "is not defined, and the rule lists it"
        ):
            continue
        removed = len(generates) if kind == "relation" else 0
        arity = base.get("arity")
        wanted = {
            "arity": arity - removed if isinstance(arity, int) else None,
            "package": "prop",
            "detail_fields": for_all.get("detail_fields"),
            "relaxations": base.get("relaxations") or [],
            "form": {"of": of, "kind": kind, "generates": generates},
        }
        for key, want in wanted.items():
            got = entry.get(key)
            if key == "relaxations":
                got = got or []
            problems.unless(
                got == want, where, f"states {key} {got!r}; the rule gives {want!r}"
            )

    for aid, entry in sorted(defined.items()):
        form = entry.get("form") if isinstance(entry, dict) else None
        if form is None:
            continue
        runs = form.get("of") if isinstance(form, dict) else None
        problems.unless(
            runs in listed and aid == f"{FORM_PREFIX}{runs}",
            f"spec/assertions.json: {aid}",
            "is a form that the rule does not list",
        )


def _check_form_names(
    naming: Any, listed: dict[str, tuple[str, list[Any]]], problems: Problems
) -> None:
    """Check each listed form's names against the naming table's rule."""
    rule = naming.get("forms")
    if not problems.unless(
        isinstance(rule, dict) and isinstance(rule.get("qualifiers"), dict),
        "spec/naming.json: forms",
        "states no qualifiers",
    ):
        return
    qualifiers = rule["qualifiers"]
    exceptions = rule.get("exceptions", {})
    for of, per_language in sorted(exceptions.items()):
        where = f"spec/naming.json: forms.exceptions.{of}"
        problems.unless(of in listed, where, f"names a form of {of!r}, which has none")
        for language in sorted(set(per_language) - set(qualifiers)):
            problems.at(where, f"names {language}, which the rule does not qualify")

    names = naming.get("names", {})
    for of in sorted(listed):
        stated = names.get(FORM_PREFIX + of, {})
        for language, qualifier in sorted(qualifiers.items()):
            want = exceptions.get(of, {}).get(language)
            if want is None:
                want = f"{qualifier}{names.get(of, {}).get(language)}"
            got = stated.get(language)
            problems.unless(
                got == want,
                f"spec/naming.json: {FORM_PREFIX}{of}.{language}",
                f"is {got!r}; the rule gives {want!r}",
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

    The detail fields and the relaxations of the assertion under test and
    the subject kinds of the definition are checked together, because a
    case names any of them.
    """

    detail: set[str]
    subjects: set[str]
    relaxations: set[str]


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

    options = case.get("options", [])
    if problems.unless(
        isinstance(options, list), f"{where} [{cid}]", "options is not a list"
    ):
        for option in options:
            problems.unless(
                option in vocabulary.relaxations,
                f"{where} [{cid}]",
                f"names option {option!r}, which {assertion} does not accept",
            )
        problems.unless(
            len({str(option) for option in options}) == len(options),
            f"{where} [{cid}]",
            "names an option twice",
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
    assertions: dict[str, set[str]],
    subjects: set[str],
    accepted: dict[str, set[str]],
    problems: Problems,
) -> int:
    """Check every corpus file and case, and return the number of cases.

    Each file names a defined assertion, and each case id is unique.
    assertions maps each assertion to its detail fields, and accepted to
    the relaxations it accepts.
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
                    detail=assertions.get(str(assertion), set()),
                    subjects=subjects,
                    relaxations=accepted.get(str(assertion), set()),
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


@dataclass(frozen=True)
class FormVocabulary:
    """What a form vector may name.

    runs maps each form's id to the assertion it runs, detail maps each
    assertion to the detail fields it declares, and subjects is the
    definition's subject kinds.
    """

    runs: dict[str, str]
    detail: dict[str, set[str]]
    subjects: set[str]

    @property
    def stated(self) -> frozenset[str]:
        """Return the forms that vectors run."""
        return frozenset(self.runs) - UNSTATED_FORMS


def form_runs(spec: Any) -> dict[str, str]:
    """Return the assertion each form runs, by the form's id."""
    return {
        aid: str(body["form"].get("of"))
        for aid, body in spec.get("assertions", {}).items()
        if isinstance(body, dict) and isinstance(body.get("form"), dict)
    }


def _prefixes(kind: str, forms: FormVocabulary) -> frozenset[str]:
    """Return what the ids of one kind's vectors may begin with."""
    if kind in GENERATOR_KINDS:
        return IDS
    if kind == "shapes":
        return SHAPES
    if kind == "inverse":
        return SHAPES | IDS
    if kind == "forms":
        return forms.stated
    return frozenset({kind})


def _named(kind: str) -> str:
    """Return what the ids of one kind's vectors name."""
    if kind in GENERATOR_KINDS:
        return "generator"
    if kind == "shapes":
        return "shape"
    if kind == "inverse":
        return "shape or generator"
    if kind == "forms":
        return "form a vector runs"
    return f"{kind} vector"


def _reached(kind: str, case: dict[str, Any]) -> str:
    """Return what one vector reaches: an outcome, a verdict, an error or a cover.

    An inverse vector reaches the kind of what it runs backwards, a shape
    or a generator. A draws vector reaches its error's reason, or a match
    of every draw, or a match whose entries run out first.
    """
    if kind == "inverse":
        return "shape" if "shape" in case else "generator"
    if kind == "fixtures":
        return str(case.get("covers"))
    if kind == "draws":
        error = case.get("error")
        if isinstance(error, dict):
            return str(error.get("reason"))
        short = len(case.get("entries", [])) < len(case.get("draws", []))
        return "ran-out" if short else "matched"
    detail = case.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("outcome"))
    return str(case.get("outcome") or case.get("verdict"))


def _phases(case: dict[str, Any]) -> list[str]:
    """Return the phase of each call that a recording vector records."""
    calls = case.get("calls")
    if not isinstance(calls, list):
        return []
    return [str(call.get("phase")) for call in calls if isinstance(call, dict)]


def _check_form_vector(
    case: dict[str, Any],
    prefix: str,
    forms: FormVocabulary,
    where: str,
    problems: Problems,
) -> None:
    """Check a form vector's form, its subjects and its failure.

    The vector runs the form that its id names, and names subject kinds of
    the definition. A failure is the record of the form's assertion, and
    states only detail fields that the assertion declares.
    """
    form = case.get("form")
    problems.unless(
        form == prefix, where, f"runs {form!r}, and its id names {prefix!r}"
    )
    subjects = case.get("subjects")
    if not isinstance(subjects, list):
        problems.at(where, "subjects is not a list")
        subjects = []
    for kind in subjects:
        problems.unless(
            isinstance(kind, str) and kind in forms.subjects,
            where,
            f"names subject kind {kind!r}, which the definition does not state",
        )
    detail = case.get("detail")
    failure = detail.get("failure") if isinstance(detail, dict) else None
    if not isinstance(failure, dict):
        return
    assertion = forms.runs.get(prefix)
    problems.unless(
        failure.get("assertion") == assertion,
        where,
        f"fails with the record of {failure.get('assertion')!r}, and "
        f"{prefix} runs {assertion!r}",
    )
    stated = failure.get("detail")
    for name in sorted(stated) if isinstance(stated, dict) else []:
        problems.unless(
            name in forms.detail.get(str(assertion), set()),
            where,
            f"states detail {name!r}, which {assertion} does not declare",
        )


def check_vector_cases(
    kind: str,
    cases: list[Any],
    where: str,
    forms: FormVocabulary,
    problems: Problems,
) -> None:
    """Check one kind's vectors: their ids, their literals and what they cover.

    Every generator has decoding, generation and shrinking vectors, and a
    shrinking vector that fails and one that passes. The behaviour
    vectors end in every outcome, and the coverage and store vectors
    reach every verdict of their kind. Every shape has two shape vectors,
    every shape and every generator runs backwards in an inverse vector,
    the fixture types cover every shape a type reads as and every row of
    the constraint table, and the draws vectors reach every end. Every
    form but those in UNSTATED_FORMS has a vector that fails and one that
    passes. The recording vectors record a call of every phase but those
    in UNRECORDED_PHASES.
    """
    found: dict[str, list[str]] = {}
    named = (_prefixes(kind, forms), _named(kind))
    for cid, prefix, case in _vector_cases(cases, named, where, problems):
        if kind == "forms":
            _check_form_vector(case, prefix, forms, f"{where} [{cid}]", problems)
        reached = _phases(case) if kind == "recording" else [_reached(kind, case)]
        found.setdefault(prefix, []).extend(reached)
    _check_vector_coverage(kind, found, forms, where, problems)


def _vector_cases(
    cases: list[Any],
    named: tuple[Collection[str], str],
    where: str,
    problems: Problems,
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield each vector that is an object, with its id and the start of its id.

    Each id is <subject>/<case> in hyphenated lowercase, appears once, and
    begins with one of the prefixes, which name what named states. The
    typed literals of each vector are checked.
    """
    prefixes, what = named
    seen: set[str] = set()
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
            f"id {cid!r} begins with {prefix!r}, which names no {what}",
        )
        for path, value in literals(case):
            check_literal(value, f"{where} [{cid}] {path}", problems)
        yield cid, prefix, case


def _both_ways(
    names: Iterable[str],
    found: dict[str, list[str]],
    what: str,
    where: str,
    problems: Problems,
) -> None:
    """Check that each name has a vector that fails and one that passes."""
    for name in sorted(names):
        for outcome in SHRUNK_BOTH_WAYS:
            problems.unless(
                outcome in found.get(name, []),
                where,
                f"has no {name} vector whose outcome is {outcome!r}; {what} "
                "both ways or the corpus proves nothing",
            )


def _check_vector_coverage(
    kind: str,
    found: dict[str, list[str]],
    forms: FormVocabulary,
    where: str,
    problems: Problems,
) -> None:
    """Check that one kind's vectors cover what that kind must cover."""
    if kind in GENERATOR_KINDS:
        for gen in sorted(IDS - set(found)):
            problems.at(where, f"has no vector for generator {gen!r}")
    if kind == "shrinking":
        _both_ways(IDS & set(found), found, "a generator is shrunk", where, problems)
    if kind == "forms":
        _both_ways(forms.stated, found, "a form is run", where, problems)
    if kind == "shapes":
        for shape in sorted(SHAPES):
            problems.unless(
                len(found.get(shape, [])) >= SHAPE_VECTORS,
                where,
                f"has fewer than {SHAPE_VECTORS} vectors for shape {shape!r}",
            )
    if kind == "inverse":
        for shape in sorted(SHAPES):
            problems.unless(
                "shape" in found.get(shape, []), where, f"runs no shape {shape!r} back"
            )
        for gen in sorted(IDS):
            problems.unless(
                "generator" in found.get(gen, []),
                where,
                f"runs no generator {gen!r} back",
            )
    ends = {
        "behaviour": [k.value for k in Kind],
        "coverage": [v.value for v in Verdict],
        "store": [v.value for v in StoreVerdict],
        "draws": list(DRAWS_ENDS),
        "fixtures": sorted(FIXTURE_COVERS),
        "recording": [p.value for p in Phase if p.value not in UNRECORDED_PHASES],
    }
    what = {
        "fixtures": "fixture that covers",
        "recording": "vector that records a call of phase",
    }.get(kind, "vector that ends in")
    for end in ends.get(kind, []):
        problems.unless(end in found.get(kind, []), where, f"has no {what} {end!r}")


def check_vectors(forms: FormVocabulary, problems: Problems) -> int:
    """Check the property engine's vector files, and return the number of vectors.

    The outputs of each vector are the executable reference's. `make
    render` writes them from the YAML inputs, and the stale check fails
    when the reference computes other outputs. This check covers what the
    renderer copies from the YAML: each file's kind, the ids, the typed
    literals, the forms and subjects that form vectors name, and that the
    vectors cover the vocabulary. It also reads each form vector's failure
    against the definition.
    """
    total = 0
    for kind, where, cases in _vector_files("prop", KINDS, problems):
        total += len(cases)
        check_vector_cases(kind, cases, where, forms, problems)
    return total


def check_history(models: set[str], problems: Problems) -> int:
    """Check the history's vector files, and return the number of vectors.

    `make render` writes the outputs of these vectors as it writes the
    property engine's, so this check covers what the renderer copies from
    the YAML: each file's kind, the ids, the typed literals, and the models
    that the checker's vectors name. It also checks what the vectors cover.
    Through a script and through intervals, the seam vectors record an
    event of every kind and a pending call, and refuse an entry. The
    checker's vectors end in every outcome, stop at every limit, and
    include a pass and a violation of every named model.
    """
    total = 0
    for kind, where, cases in _vector_files("history", history.vectors.KINDS, problems):
        total += len(cases)
        prefix = HISTORY_PREFIXES[kind]
        named = (frozenset({prefix}), f"{kind} vector")
        covered: set[str] = set()
        for cid, _, case in _vector_cases(cases, named, where, problems):
            if kind == "seam":
                covered.update(_seam_covers(case))
                continue
            model = case.get("model")
            problems.unless(
                model in models,
                f"{where} [{cid}]",
                f"names model {model!r}, which the definition does not state",
            )
            covered.update(_check_covers(case))
        ends = SEAM_ENDS
        if kind == "linearizable":
            both = (f"{m}:{o}" for m in sorted(models) for o in ("passed", "violated"))
            ends = (*CHECK_ENDS, *both)
        for end in ends:
            problems.unless(end in covered, where, f"has no vector that covers {end!r}")
    return total


def _seam_covers(case: dict[str, Any]) -> list[str]:
    """Return what one seam vector covers, each under the form of its calls.

    A vector covers the kind of each event it records, pending when one of
    its calls has no completion, and refused when the seam refuses an
    entry.
    """
    form = "script" if "script" in case else "intervals"
    events = case.get("events")
    if not isinstance(events, list):
        return [f"{form}:refused"]
    recorded = [event for event in events if isinstance(event, dict)]
    completed = {e.get("call") for e in recorded if e.get("kind") != "invoke"}
    covered = [f"{form}:{event.get('kind')}" for event in recorded]
    if any(
        e.get("kind") == "invoke" and e.get("call") not in completed for e in recorded
    ):
        covered.append(f"{form}:pending")
    return covered


def _check_covers(case: dict[str, Any]) -> list[str]:
    """Return what one vector of the checker covers.

    A vector covers its outcome, its limit, and its model under its outcome.
    """
    detail = case.get("detail")
    stated = detail if isinstance(detail, dict) else {}
    outcome = stated.get("outcome")
    return [
        str(outcome),
        f"limit:{stated.get('limit')}",
        f"{case.get('model')}:{outcome}",
    ]


def _vector_files(
    folder: str, kinds: Collection[str], problems: Problems
) -> Iterator[tuple[str, str, list[Any]]]:
    """Yield the kind, the path and the cases of each vector file in a corpus folder.

    Every kind has a file, a file's name is its kind, and a file states at
    least one case. A file that breaks a rule is reported and not yielded.
    """
    files = {
        path.stem: path for path in sorted((ROOT / "corpus" / folder).glob("*.json"))
    }
    for kind in kinds:
        problems.unless(kind in files, f"corpus/{folder}/", f"has no {kind} vectors")
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
            kind in kinds, where, f"states kind {kind!r}, which no vector has"
        ):
            continue
        cases = document.get("cases")
        if problems.unless(
            isinstance(cases, list) and bool(cases), where, "states no cases"
        ):
            yield str(kind), where, cases


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


#: The largest offset from UTC a zone may state: 18 hours, in seconds.
MAX_OFFSET = 64800

#: A change of the zone table: its instant and the offsets before and after.
CHANGE_PARTS = 3


def check_zones(path: Path, problems: Problems) -> int:
    """Check the zone list and its offset changes, and return the number of changes.

    The list names each zone once, and starts with UTC, which has no
    change. Each change states the first second of a new offset, in
    seconds since the epoch, the offset before it and the offset after
    it, in seconds east of UTC.
    """
    where = str(path.relative_to(ROOT))
    document = _load(path, problems)
    if document is None:
        return 0
    release = document.get("release")
    problems.unless(
        isinstance(release, str) and bool(release), where, "names no tzdata release"
    )
    first, until = document.get("from"), document.get("until")
    if not problems.unless(
        isinstance(first, int) and isinstance(until, int) and first < until,
        where,
        f"states the years {first!r} to {until!r}",
    ):
        return 0
    zones = document.get("zones")
    if not problems.unless(
        isinstance(zones, list) and bool(zones), where, "lists no zones"
    ):
        return 0
    names = [zone.get("name") if isinstance(zone, dict) else None for zone in zones]
    problems.unless(
        names[0] == "UTC",
        where,
        f"lists {names[0]!r} first, and the list starts with UTC",
    )
    problems.unless(len(set(names)) == len(names), where, "lists a zone twice")
    bounds = (
        calendar.timegm((first, 1, 1, 0, 0, 0)),
        calendar.timegm((until, 1, 1, 0, 0, 0)),
    )
    return sum(_check_zone(zone, bounds, where, problems) for zone in zones)


def _check_zone(
    zone: Any, bounds: tuple[int, int], where: str, problems: Problems
) -> int:
    """Check one zone's changes, and return how many it states.

    The changes are in time order inside the table's years, each changes
    the offset by no more than MAX_OFFSET either side, and each starts
    from the offset the change before it left.
    """
    name = zone.get("name") if isinstance(zone, dict) else None
    changes = zone.get("changes") if isinstance(zone, dict) else None
    here = f"{where}: {name}"
    if not problems.unless(
        isinstance(name, str) and isinstance(changes, list), here, "states no changes"
    ):
        return 0
    assert isinstance(changes, list)
    problems.unless(name != "UTC" or not changes, here, "changes, and UTC has none")
    last: tuple[int, int] | None = None
    for index, change in enumerate(changes):
        if not problems.unless(
            isinstance(change, list)
            and len(change) == CHANGE_PARTS
            and all(isinstance(p, int) and not isinstance(p, bool) for p in change),
            here,
            f"change {index} is {change!r}, not an instant and two offsets",
        ):
            continue
        at, before, after = change
        problems.unless(
            bounds[0] <= at < bounds[1], here, f"change {index} is outside the years"
        )
        problems.unless(
            all(-MAX_OFFSET <= o <= MAX_OFFSET for o in (before, after)),
            here,
            f"change {index} states an offset beyond 18 hours",
        )
        problems.unless(before != after, here, f"change {index} keeps its offset")
        if last is not None:
            problems.unless(
                at > last[0], here, f"change {index} is not after the change before it"
            )
            problems.unless(
                before == last[1],
                here,
                f"change {index} starts from {before}, and the change before it "
                f"left {last[1]}",
            )
        last = (at, after)
    return len(changes)


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


def check_overlay_records(overlay: Any, where: str, problems: Problems) -> None:
    """Check that one overlay states where its language writes the call records.

    The records entry states each of RECORDS_KEYS, and none of them is
    empty.
    """
    records = overlay.get("records")
    if not problems.unless(records is not None, where, "states no records"):
        return
    if not problems.unless(
        isinstance(records, dict), where, "records is not an object"
    ):
        return
    for key in RECORDS_KEYS:
        problems.unless(
            bool(str(records.get(key, "")).strip()),
            where,
            f"records states no {key}",
        )


def check_overlay_limits(
    overlay: Any,
    where: str,
    language: Any,
    known: Collection[str],
    problems: Problems,
) -> set[Any]:
    """Check one overlay's limits, and return the ids it limits.

    A limit names an assertion or a row of the surface table, because a
    seat without a lock is a limit on the seat and not on one assertion. It
    states what it misses and why. A language in PARALLEL limits RECORDER.
    """
    limits = overlay.get("limits", [])
    if not problems.unless(isinstance(limits, list), where, "limits is not a list"):
        return set()
    for entry in limits:
        if not problems.unless(
            isinstance(entry, dict), where, f"limit {entry!r} is not an object"
        ):
            continue
        aid = entry.get("id")
        problems.unless(
            aid in known, where, f"limits {aid!r}, which the standard does not state"
        )
        for field in ("what", "why"):
            problems.unless(
                bool(str(entry.get(field, "")).strip()),
                where,
                f"limits {aid!r} with no {field}",
            )
    limited = {entry.get("id") for entry in limits if isinstance(entry, dict)}
    problems.unless(
        language not in PARALLEL or RECORDER in limited,
        where,
        f"states no limit on {RECORDER!r}; its threads run on more than one "
        "core, where the history's counter can hide a missing barrier",
    )
    return limited


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
    is present. A language whose threads run on more than one core limits
    the history.

    Every overlay states the artifact that contains its language's call
    records.
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
        check_overlay_records(overlay, where, problems)
        known = assertions | tables.surface_ids
        limited = check_overlay_limits(overlay, where, language, known, problems)

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
                aid not in limited,
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
    check_forms(spec, naming, problems)
    accepted = {
        aid: set(body.get("relaxations", []) or [])
        for aid, body in spec.get("assertions", {}).items()
        if isinstance(body, dict)
    }
    subjects = check_vocabulary(spec, "subjects", "subject", problems)
    models = check_vocabulary(spec, "models", "model", problems)
    cases = check_corpus(assertions, subjects, accepted, problems)
    vectors = check_vectors(
        FormVocabulary(form_runs(spec), assertions, subjects), problems
    )
    vectors += check_history(models, problems)
    changes = check_zones(ROOT / "spec" / "zones.json", problems)
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
            f"{cases} corpus cases, {vectors} vectors, "
            f"{changes} offset changes, all consistent"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
