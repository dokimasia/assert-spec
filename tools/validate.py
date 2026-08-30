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
            qualified = "." in str(name)
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


def check_overlays(
    assertions: set[str], languages: set[str], version: str, problems: Problems
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
            language in languages,
            where,
            f"declares {language!r}, which the naming table does not list",
        )

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
    check_naming(naming, spec, assertions, problems)
    cases = check_corpus(assertions, problems)
    check_overlays(assertions, set(naming.get("languages", [])), version, problems)

    status = problems.report()
    if status == 0:
        print(
            f"spec {version}: {len(assertions)} assertions, "
            f"{cases} corpus cases, all consistent"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
