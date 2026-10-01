#!/usr/bin/env python3
"""The validator, run against the faults it must catch.

A validator that runs only on a clean tree passes with every rule
deleted. Each case copies the repository, breaks one rule, and requires
the validator to report it.

Run with:

    python3 -m unittest discover -s tools -p '*_test.py'
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, final, override

ROOT = Path(__file__).resolve().parent.parent

#: What each scratch tree copies. The validator reads these and nothing
#: else.
COPIED = ("spec", "corpus", "overlays", "VERSION", "tools")


def _edit(path: Path, change: Callable[[Any], Any]) -> None:
    """Read JSON, apply change to it, and write it back."""
    document = json.loads(path.read_text())
    path.write_text(json.dumps(change(document) or document, indent=2))


@final
class Validator(unittest.TestCase):
    """Each case breaks one rule and reads what the validator reports."""

    #: A scratch copy of the repository, broken one way per case.
    tree: Path

    @override
    def setUp(self) -> None:
        """Copy the repository to a scratch directory."""
        self.tree = Path(tempfile.mkdtemp(prefix="assert-spec-"))
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        for name in COPIED:
            source = ROOT / name
            target = self.tree / name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        """Run the validator over the scratch tree."""
        return subprocess.run(
            [sys.executable, str(self.tree / "tools" / "validate.py")],
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_caught(self, phrase: str) -> None:
        """Require the validator to fail and to report phrase."""
        result = self.run_validator()
        self.assertEqual(result.returncode, 1, f"validator passed; wanted {phrase!r}")
        self.assertIn(phrase, result.stderr)

    def test_an_unbroken_tree_passes(self) -> None:
        """The copy itself is clean, or every other case proves nothing."""
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("all consistent", result.stdout)

    def test_a_version_disagreement_is_caught(self) -> None:
        """The VERSION file and the tables state the same version."""
        (self.tree / "VERSION").write_text("9.9.9\n")
        self.assert_caught("VERSION states '9.9.9'")

    def test_an_assertion_with_no_summary_is_caught(self) -> None:
        """An assertion nobody described cannot be implemented."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["equal"].update(summary="  "),
        )
        self.assert_caught("states no summary")

    def test_an_unnamed_assertion_is_caught(self) -> None:
        """An assertion with no name is one no user can call."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"].pop("equal"),
        )
        self.assert_caught("equal has no entry")

    def test_an_unqualified_name_for_a_packaged_assertion_is_caught(self) -> None:
        """An assertion in a subpackage is reached through a qualifier.

        The qualifier is the language's choice: Python qualifies by module
        and Java by type. The two tables agree on whether a qualifier is
        present.
        """
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["golden-match"].update(python="match"),
        )
        self.assert_caught("is not qualified")

    def test_a_qualified_name_with_no_package_is_caught(self) -> None:
        """A root-namespace assertion has no package prefix."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["equal"].update(python="somewhere.equal"),
        )
        self.assert_caught("the assertion names no package")

    def test_a_name_in_an_undeclared_language_is_caught(self) -> None:
        """A language column nobody declared is a typo, not a language."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["equal"].update(cobol="EQUAL"),
        )
        self.assert_caught("cobol is not in the declared languages")

    def test_a_corpus_case_for_an_unknown_assertion_is_caught(self) -> None:
        """A corpus file tests an assertion the standard states."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d.update(assertion="invented"),
        )
        self.assert_caught("which the definition does not state")

    def test_a_repeated_case_id_is_caught(self) -> None:
        """Two cases sharing an id make one of them unreportable."""

        def repeat(document: Any) -> None:
            document["cases"].append(dict(document["cases"][0]))

        _edit(self.tree / "corpus" / "equal.json", repeat)
        self.assert_caught("repeats case id")

    def test_an_unknown_literal_type_is_caught(self) -> None:
        """A type the encoding does not define cannot be decoded."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0]["args"][0].update(type="decimal"),
        )
        self.assert_caught("which the encoding does not define")

    def test_a_named_float_that_is_not_finite_is_caught(self) -> None:
        """The encoding names only NaN, Inf and -Inf."""
        _edit(
            self.tree / "corpus" / "close-to.json",
            lambda d: d["cases"][0]["args"][0].update(type="float", value="huge"),
        )
        self.assert_caught("only ['-Inf', 'Inf', 'NaN'] are named")

    def test_a_list_with_no_element_type_is_caught(self) -> None:
        """A list whose elements have no type cannot be decoded."""

        def strip(document: Any) -> None:
            for case in document["cases"]:
                for arg in case["args"]:
                    arg.pop("of", None)

        _edit(self.tree / "corpus" / "contains.json", strip)
        self.assert_caught("needs 'of'")

    def test_an_unknown_outcome_is_caught(self) -> None:
        """A case expects pass or fail."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(expect="maybe"),
        )
        self.assert_caught("expects 'maybe'")

    def test_a_passing_case_that_wants_message_text_is_caught(self) -> None:
        """Only a failure has a message, so this case contradicts itself."""

        def contradict(document: Any) -> None:
            for case in document["cases"]:
                if case["expect"] == "pass":
                    case["detail"] = {"want": {"type": "int", "value": 1}}
                    return

        _edit(self.tree / "corpus" / "equal.json", contradict)
        self.assert_caught("expects a pass but states detail")

    def test_a_skip_with_no_reason_is_caught(self) -> None:
        """A skip is a claim, so it states a reason."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(skip={"go": "   "}),
        )
        self.assert_caught("states no reason")

    def test_a_case_id_under_the_wrong_assertion_is_caught(self) -> None:
        """An id names its assertion, so a mismatch misfiles the case."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(id="other/renamed"),
        )
        self.assert_caught("does not begin with 'equal'")

    def test_an_overlay_extending_another_version_is_caught(self) -> None:
        """An overlay that extends an earlier version is stale."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(extends="spec://assertions@0.1.0"),
        )
        self.assert_caught("extends 'spec://assertions@0.1.0'")

    def test_a_divergence_from_an_unknown_assertion_is_caught(self) -> None:
        """A language cannot diverge from something nobody defined."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(
                diverge=[{"id": "invented", "stance": "blocked", "why": "stated"}]
            ),
        )
        self.assert_caught("diverges on 'invented'")

    def test_a_limit_with_no_reason_is_caught(self) -> None:
        """A limit is a claim about what a check misses, so it states a reason."""
        _edit(
            self.tree / "overlays" / "java.json",
            lambda d: d.update(
                limits=[{"id": "no-task-leaks", "what": "misses things", "why": ""}]
            ),
        )
        self.assert_caught("with no why")

    def test_a_limit_on_an_unknown_assertion_is_caught(self) -> None:
        """A language cannot limit something nobody defined."""
        _edit(
            self.tree / "overlays" / "java.json",
            lambda d: d.update(
                limits=[{"id": "invented", "what": "misses things", "why": "stated"}]
            ),
        )
        self.assert_caught("which the standard does not state")

    def test_diverging_and_limiting_the_same_assertion_is_caught(self) -> None:
        """A divergence is absent and a limit is present."""
        _edit(
            self.tree / "overlays" / "java.json",
            lambda d: d.update(
                diverge=[{"id": "equal", "stance": "blocked", "why": "stated"}],
                limits=[{"id": "equal", "what": "misses things", "why": "stated"}],
            ),
        )
        self.assert_caught("is both diverged from and limited")

    def test_a_divergence_with_no_reason_is_caught(self) -> None:
        """A divergence states why the assertion is absent."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(
                diverge=[{"id": "equal", "stance": "blocked", "why": "  "}]
            ),
        )
        self.assert_caught("with no why")

    def test_a_divergence_with_no_stance_is_caught(self) -> None:
        """A divergence states whether its gap is blocked or open."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(diverge=[{"id": "equal", "why": "stated"}]),
        )
        self.assert_caught("with no stance")

    def test_the_same_assertion_diverged_twice_is_caught(self) -> None:
        """Two entries for one assertion make one of them unreachable."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(
                diverge=[
                    {"id": "equal", "stance": "blocked", "why": "first"},
                    {"id": "equal", "stance": "open", "why": "second"},
                ]
            ),
        )
        self.assert_caught("diverges on 'equal' twice")

    def test_an_overlay_for_an_undeclared_language_is_caught(self) -> None:
        """An overlay for a language nobody targets is a stray file."""
        stray = self.tree / "overlays" / "cobol.json"
        stray.write_text(
            json.dumps(
                {
                    "extends": "spec://assertions@1.0.0",
                    "language": "cobol",
                    "diverge": [],
                }
            )
        )
        self.assert_caught("which the naming table does not list")

    def test_every_named_language_has_an_overlay(self) -> None:
        """A language the naming table names has an overlay.

        Full compliance is then stated, and never read from a missing
        file.
        """
        naming = json.loads((self.tree / "spec" / "naming.json").read_text())
        named = {language for entry in naming["names"].values() for language in entry}
        overlays = {p.stem for p in (self.tree / "overlays").glob("*.json")}

        self.assertEqual(named - overlays, set(), "named with no overlay")

    def test_an_assertion_accepting_an_unknown_relaxation_is_caught(self) -> None:
        """A relaxation an assertion names is one the definition states."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["equal"].update(relaxations=["equate-invented"]),
        )
        self.assert_caught("unknown relaxation")

    def test_a_relaxation_with_no_summary_is_caught(self) -> None:
        """A relaxation nobody described is one nobody can implement."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["relaxations"]["equate-nans"].update(summary="  "),
        )
        self.assert_caught("has no summary")

    def test_a_relaxation_the_naming_table_misses_is_caught(self) -> None:
        """A relaxation with no name is one a caller cannot type."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["relaxations"].pop("equate-nans"),
        )
        self.assert_caught("names no relaxation")

    def test_a_name_for_an_undeclared_relaxation_is_caught(self) -> None:
        """The tables are edited separately, so each is checked against the other."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["relaxations"].update({"equate-invented": {"go": "Invented"}}),
        )
        self.assert_caught("which the definition does not state")

    def test_an_overlay_dropping_an_unknown_relaxation_is_caught(self) -> None:
        """A language cannot decline something nobody defined."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d.update(
                relaxations=[{"id": "equate-invented", "why": "stated"}]
            ),
        )
        self.assert_caught("which is not defined")

    def test_an_overlay_dropping_a_relaxation_with_no_reason_is_caught(self) -> None:
        """Declining a relaxation is a claim, so it states a reason."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d.update(relaxations=[{"id": "equate-nans", "why": ""}]),
        )
        self.assert_caught("with no why")

    def test_a_relaxation_neither_named_nor_declined_is_caught(self) -> None:
        """An implementing language names or declines every relaxation."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d.update(
                relaxations=[e for e in d["relaxations"] if e["id"] != "equate-nans"]
            ),
        )
        self.assert_caught("neither names nor declines")

    def test_a_relaxation_named_and_declined_is_caught(self) -> None:
        """Offering it and declining it cannot both be true."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(relaxations=[{"id": "equate-nans", "why": "stated"}]),
        )
        self.assert_caught("both names and declines")

    def test_a_case_stating_an_undeclared_detail_field_is_caught(self) -> None:
        """A case states only the detail fields its assertion declares."""

        def add_field(document: Any) -> None:
            for case in document["cases"]:
                if case["expect"] == "fail":
                    case["detail"]["bogus"] = {"type": "int", "value": 1}

        _edit(self.tree / "corpus" / "equal.json", add_field)
        self.assert_caught("which equal does not declare")

    def test_an_untyped_detail_value_is_caught(self) -> None:
        """Detail values are typed literals, so an int and a float differ."""

        def untype(document: Any) -> None:
            for case in document["cases"]:
                if case["expect"] == "fail":
                    case["detail"]["want"] = 2

        _edit(self.tree / "corpus" / "equal.json", untype)
        self.assert_caught("detail.want")

    def test_a_detail_field_that_is_not_a_name_is_caught(self) -> None:
        """A detail field is a hyphenated lowercase name."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["equal"].update(detail_fields=["Want Got"]),
        )
        self.assert_caught("which is not a field name")

    def test_a_repeated_detail_field_is_caught(self) -> None:
        """An assertion names each detail field once."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["equal"].update(detail_fields=["want", "want"]),
        )
        self.assert_caught("names the same detail field twice")

    def test_a_limit_may_name_a_surface_row(self) -> None:
        """A seat without a lock is a limit on the seat."""
        _edit(
            self.tree / "overlays" / "java.json",
            lambda d: d.setdefault("limits", []).append(
                {"id": "recorder-seat", "what": "has no lock", "why": "one thread"}
            ),
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_assertion_driven_only_one_way_is_caught(self) -> None:
        """A corpus that drives only the passing path proves nothing."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d.update(cases=[c for c in d["cases"] if c["expect"] == "pass"]),
        )
        self.assert_caught("states no case expecting 'fail'")

    def test_a_surface_id_neither_named_nor_declined_is_caught(self) -> None:
        """The surface table is under the same rule as the relaxations."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(
                surface=[e for e in d["surface"] if e["id"] != "standard-seat"]
            ),
        )
        self.assert_caught("neither names nor declines surface id")

    def test_a_surface_id_named_and_declined_is_caught(self) -> None:
        """Naming it and declining it cannot both be true."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d.update(surface=[{"id": "seat", "why": "stated"}]),
        )
        self.assert_caught("both names and declines surface id")

    def test_a_member_of_an_undeclared_type_is_caught(self) -> None:
        """A member row's owner is a type the table declares."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["surface"]["members"].update({"orphan.thing": {"go": "X"}}),
        )
        self.assert_caught("the types section does not declare")

    def test_an_integer_beyond_2_to_the_53_as_a_number_is_caught(self) -> None:
        """A JavaScript reader rounds such an integer, so it is a decimal string."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0]["args"][0].update(value=2**60),
        )
        self.assert_caught("beyond 2^53 - 1")

    def test_bytes_that_are_not_lowercase_hex_are_caught(self) -> None:
        """A byte string has one spelling."""
        _edit(
            self.tree / "corpus" / "prop" / "decoding.json",
            lambda d: d["cases"][0].update(value={"type": "bytes", "value": "FF"}),
        )
        self.assert_caught("is not lowercase hexadecimal")

    def test_a_malformed_literal_inside_items_is_caught(self) -> None:
        """Each of a list's items is checked as a literal."""

        def break_items(document: Any) -> None:
            document["cases"][0]["value"] = {"type": "list", "items": [{"type": "int"}]}

        _edit(self.tree / "corpus" / "prop" / "decoding.json", break_items)
        self.assert_caught("is not an integer")

    def test_a_vector_file_of_another_kind_is_caught(self) -> None:
        """A vector file's name is its kind."""
        _edit(
            self.tree / "corpus" / "prop" / "coverage.json",
            lambda d: d.update(kind="token"),
        )
        self.assert_caught("is named 'coverage' but states kind 'token'")

    def test_a_missing_vector_file_is_caught(self) -> None:
        """Every kind of vector has a file."""
        (self.tree / "corpus" / "prop" / "bridge.json").unlink()
        self.assert_caught("has no bridge vectors")

    def test_a_repeated_vector_id_is_caught(self) -> None:
        """Two vectors with one id make one of them unreportable."""

        def repeat(document: Any) -> None:
            document["cases"].append(dict(document["cases"][0]))

        _edit(self.tree / "corpus" / "prop" / "token.json", repeat)
        self.assert_caught("repeats case id 'token/")

    def test_a_vector_id_that_names_no_generator_is_caught(self) -> None:
        """A decoding vector's id begins with the generator it decodes."""
        _edit(
            self.tree / "corpus" / "prop" / "decoding.json",
            lambda d: d["cases"][0].update(id="integers/decodes"),
        )
        self.assert_caught("which names no generator")

    def test_a_generator_without_generation_vectors_is_caught(self) -> None:
        """Every generator of the vocabulary has its own vectors."""
        _edit(
            self.tree / "corpus" / "prop" / "generation.json",
            lambda d: d.update(
                cases=[c for c in d["cases"] if not c["id"].startswith("boolean/")]
            ),
        )
        self.assert_caught("has no vector for generator 'boolean'")

    def test_a_generator_shrunk_only_one_way_is_caught(self) -> None:
        """Each generator has a shrinking vector that fails and one that passes."""
        passing = "integer/passes-when-no-value-fails"
        _edit(
            self.tree / "corpus" / "prop" / "shrinking.json",
            lambda d: d.update(cases=[c for c in d["cases"] if c["id"] != passing]),
        )
        self.assert_caught("has no integer vector whose outcome is 'passed'")

    def test_an_outcome_without_a_behaviour_vector_is_caught(self) -> None:
        """Every outcome of a run has a vector."""
        _edit(
            self.tree / "corpus" / "prop" / "behaviour.json",
            lambda d: d.update(
                cases=[c for c in d["cases"] if c["detail"]["outcome"] != "vacuous"]
            ),
        )
        self.assert_caught("has no vector that ends in 'vacuous'")

    def test_a_verdict_without_a_coverage_vector_is_caught(self) -> None:
        """Every verdict of the coverage test has a vector."""
        _edit(
            self.tree / "corpus" / "prop" / "coverage.json",
            lambda d: d.update(
                cases=[c for c in d["cases"] if c["verdict"] != "undecided"]
            ),
        )
        self.assert_caught("has no vector that ends in 'undecided'")

    def test_unreadable_json_is_reported_not_raised(self) -> None:
        """A broken file is a finding, not a traceback."""
        (self.tree / "corpus" / "equal.json").write_text("{not json")
        self.assert_caught("cannot be read")

    def test_every_problem_is_reported_in_one_run(self) -> None:
        """One run reports every problem."""

        def drop_two(document: Any) -> None:
            document["names"].pop("equal")
            document["names"].pop("true")

        _edit(self.tree / "spec" / "naming.json", drop_two)
        result = self.run_validator()
        self.assertEqual(result.returncode, 1)
        self.assertIn("equal has no entry", result.stderr)
        self.assertIn("true has no entry", result.stderr)


if __name__ == "__main__":
    unittest.main()
