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


def _edit(path: Path, change: Callable[[Any], object]) -> None:
    """Read JSON, let change edit it in place, and write it back.

    The return value of change is ignored, so an edit written as a lambda
    over dict.pop removes the key and nothing else.
    """
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document, indent=2))


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

    def test_an_overlay_without_records_is_caught(self) -> None:
        """An overlay states the artifact that contains its call records."""
        _edit(self.tree / "overlays" / "go.json", lambda d: d.pop("records"))
        self.assert_caught("overlays/go.json: states no records")

    def test_records_that_are_not_an_object_are_caught(self) -> None:
        """The records entry is an object of three sentences."""
        _edit(self.tree / "overlays" / "go.json", lambda d: d.update(records=[]))
        self.assert_caught("overlays/go.json: records is not an object")

    def test_a_records_entry_with_an_empty_key_is_caught(self) -> None:
        """Each key of the records entry states something."""
        _edit(
            self.tree / "overlays" / "python.json",
            lambda d: d["records"].update(location="  "),
        )
        self.assert_caught("overlays/python.json: records states no location")

    def test_a_records_entry_with_a_missing_key_is_caught(self) -> None:
        """A reader of the artifact needs where each test's status is."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d["records"].pop("status"),
        )
        self.assert_caught("overlays/rust.json: records states no status")

    def test_an_overlay_without_sections_is_caught(self) -> None:
        """An overlay states how its language runs a concurrent section."""
        _edit(self.tree / "overlays" / "go.json", lambda d: d.pop("sections"))
        self.assert_caught("overlays/go.json: states no sections")

    def test_sections_that_name_no_way_are_caught(self) -> None:
        """An overlay's sections list at least one way to run a section."""
        _edit(self.tree / "overlays" / "go.json", lambda d: d.update(sections=[]))
        self.assert_caught("overlays/go.json: sections is [], not a list")

    def test_an_unknown_way_to_run_a_section_is_caught(self) -> None:
        """A section runs as tasks of the scheduler or on threads."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d.update(sections=["fibers"]),
        )
        self.assert_caught(
            "runs a section as 'fibers', which is none of ['tasks', 'threads']"
        )

    def test_a_way_to_run_a_section_named_twice_is_caught(self) -> None:
        """Each way is named once."""
        _edit(
            self.tree / "overlays" / "typescript.json",
            lambda d: d.update(sections=["tasks", "tasks"]),
        )
        self.assert_caught("typescript.json: names a way to run a section twice")

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
                    case.setdefault("detail", {})["bogus"] = {"type": "int", "value": 1}

        _edit(self.tree / "corpus" / "equal.json", add_field)
        self.assert_caught("which equal does not declare")

    def test_an_untyped_detail_value_is_caught(self) -> None:
        """Detail values are typed literals, so an int and a float differ."""

        def untype(document: Any) -> None:
            for case in document["cases"]:
                if case["expect"] == "fail":
                    case.setdefault("detail", {})["want"] = 2

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

    def test_a_record_that_names_a_field_twice_is_caught(self) -> None:
        """A record's field names are distinct, so each field is reachable."""

        def repeat(document: Any) -> None:
            field = ["id", {"type": "int", "value": 1}]
            document["cases"][0]["value"] = {"type": "record", "fields": [field, field]}

        _edit(self.tree / "corpus" / "prop" / "decoding.json", repeat)
        self.assert_caught("names a field twice")

    def test_a_variant_with_a_key_it_does_not_take_is_caught(self) -> None:
        """A variant states a name and an optional payload, and nothing else."""

        def widen(document: Any) -> None:
            document["cases"][0]["value"] = {"type": "variant", "name": "x", "of": "y"}

        _edit(self.tree / "corpus" / "prop" / "decoding.json", widen)
        self.assert_caught("states 'of', which type 'variant' does not take")

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

    def test_a_definition_table_of_another_version_is_caught(self) -> None:
        """The assertion table states the version VERSION states."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d.update(version="9.9.9"),
        )
        self.assert_caught("spec/assertions.json: states version '9.9.9'")

    def test_a_naming_table_of_another_version_is_caught(self) -> None:
        """The naming table states the version VERSION states."""
        _edit(self.tree / "spec" / "naming.json", lambda d: d.update(version="9.9.9"))
        self.assert_caught("spec/naming.json: states version '9.9.9'")

    def test_a_definition_with_no_assertions_is_caught(self) -> None:
        """A definition that states nothing defines nothing."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d.update(assertions={}),
        )
        self.assert_caught("spec/assertions.json: states no assertions")

    def test_an_assertion_id_that_is_not_hyphenated_lowercase_is_caught(self) -> None:
        """An id is lowercase words joined by hyphens."""

        def rename(document: Any) -> None:
            document["assertions"]["True"] = document["assertions"].pop("true")

        _edit(self.tree / "spec" / "assertions.json", rename)
        self.assert_caught("assertions.json: True: is not a hyphenated lowercase id")

    def test_an_assertion_of_no_arguments_is_caught(self) -> None:
        """An assertion takes at least the message."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["equal"].update(arity=0),
        )
        self.assert_caught("equal: states arity 0")

    def test_detail_fields_that_are_not_a_list_are_caught(self) -> None:
        """The detail fields are a list of names."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["equal"].update(detail_fields="want"),
        )
        self.assert_caught("equal: detail_fields is not a list")

    def test_a_package_that_is_not_an_id_is_caught(self) -> None:
        """A package name is an id."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["golden-match"].update(package="Golden"),
        )
        self.assert_caught("names package 'Golden', which is not an id")

    def test_a_definition_with_no_subjects_is_caught(self) -> None:
        """The subject vocabulary is what the subject cases name."""
        _edit(self.tree / "spec" / "assertions.json", lambda d: d.update(subjects={}))
        self.assert_caught("spec/assertions.json: states no subject vocabulary")

    def test_a_subject_kind_that_is_not_hyphenated_lowercase_is_caught(self) -> None:
        """A subject kind is an id."""

        def rename(document: Any) -> None:
            document["subjects"]["Raises"] = document["subjects"].pop("raises")

        _edit(self.tree / "spec" / "assertions.json", rename)
        self.assert_caught("subject Raises: is not a hyphenated lowercase id")

    def test_a_subject_with_no_summary_is_caught(self) -> None:
        """Each implementation builds a subject from its summary."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["subjects"]["raises"].update(summary="  "),
        )
        self.assert_caught("subject raises: states no summary")

    def test_a_naming_table_with_no_languages_is_caught(self) -> None:
        """The table declares the languages its columns may name."""
        _edit(self.tree / "spec" / "naming.json", lambda d: d.update(languages=[]))
        self.assert_caught("spec/naming.json: declares no languages")

    def test_a_name_for_an_undefined_assertion_is_caught(self) -> None:
        """The tables are edited separately, so each is checked against the other."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"].update({"invented": {"go": "Invented"}}),
        )
        self.assert_caught("invented is named but not defined")

    def test_an_empty_name_is_caught(self) -> None:
        """A name a user types has characters."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["equal"].update(go="  "),
        )
        self.assert_caught("spec/naming.json: equal.go: is empty")

    def test_a_language_that_names_only_some_assertions_is_caught(self) -> None:
        """A language that names one assertion names every one."""

        def drop(document: Any) -> None:
            del document["names"]["equal"]["go"]

        _edit(self.tree / "spec" / "naming.json", drop)
        self.assert_caught("equal has no go name, and go names other assertions")

    def test_a_literal_with_a_key_its_type_does_not_take_is_caught(self) -> None:
        """An int has a value and nothing else."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0]["args"][0].update(of="int"),
        )
        self.assert_caught("states 'of', which type 'int' does not take")

    def test_a_list_of_a_type_that_is_not_a_scalar_is_caught(self) -> None:
        """A list's of names a scalar type, as an absent list's of does."""
        _edit(
            self.tree / "corpus" / "contains.json",
            lambda d: d["cases"][1]["args"][0].update(of="widget"),
        )
        self.assert_caught("of is 'widget', which is not a scalar type")

    def test_a_case_that_is_not_an_object_is_caught(self) -> None:
        """A case is an object."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"].append("equal/a-string"),
        )
        self.assert_caught("corpus/equal.json: is not an object")

    def test_a_case_id_that_is_not_hyphenated_lowercase_is_caught(self) -> None:
        """A case id is <assertion>/<case> in hyphenated lowercase."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(id="equal/Identical Ints"),
        )
        self.assert_caught("states id 'equal/Identical Ints', want <assertion>/<case>")

    def test_a_case_with_neither_args_nor_a_subject_is_caught(self) -> None:
        """A case states what the assertion is given."""

        def drop(document: Any) -> None:
            del document["cases"][0]["args"]

        _edit(self.tree / "corpus" / "equal.json", drop)
        self.assert_caught("states neither args nor a subject")

    def test_a_file_that_is_no_json_object_is_reported_not_raised(self) -> None:
        """Every file the validator reads is one JSON object."""
        (self.tree / "corpus" / "equal.json").write_text("[]")
        self.assert_caught("corpus/equal.json: is not a JSON object")

    def test_a_case_with_both_args_and_a_subject_is_caught(self) -> None:
        """A case states values or names a behaviour, not both."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(subject={"kind": "raises"}),
        )
        self.assert_caught("states both args and a subject")

    def test_args_that_are_not_a_list_are_caught(self) -> None:
        """The arguments are a list, in call order."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(args={"type": "int", "value": 1}),
        )
        self.assert_caught("states args that are not a list")

    def test_a_subject_that_is_not_an_object_is_caught(self) -> None:
        """A subject is an object that names its kind."""
        _edit(
            self.tree / "corpus" / "throws.json",
            lambda d: d["cases"][0].update(subject="raises"),
        )
        self.assert_caught("subject is not an object")

    def test_an_unknown_subject_kind_is_caught(self) -> None:
        """A case names a kind of the definition's vocabulary."""
        _edit(
            self.tree / "corpus" / "throws.json",
            lambda d: d["cases"][0].update(subject={"kind": "sleeps"}),
        )
        self.assert_caught("names subject kind 'sleeps', which the definition does not")

    def test_detail_that_is_not_an_object_is_caught(self) -> None:
        """The detail maps field names to literals."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][1].update(detail=[]),
        )
        self.assert_caught("detail is not an object")

    def test_a_skip_that_is_not_an_object_is_caught(self) -> None:
        """A skip maps each language to its reason."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(skip="go"),
        )
        self.assert_caught("skip is not an object")

    def test_options_that_are_not_a_list_are_caught(self) -> None:
        """A case's options are a list of relaxation ids."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(options="equate-nans"),
        )
        self.assert_caught("options is not a list")

    def test_an_option_the_assertion_does_not_accept_is_caught(self) -> None:
        """A case relaxes only what its assertion accepts."""
        _edit(
            self.tree / "corpus" / "true.json",
            lambda d: d["cases"][0].update(options=["equate-nans"]),
        )
        self.assert_caught("names option 'equate-nans', which true does not accept")

    def test_an_option_named_twice_is_caught(self) -> None:
        """A relaxation applies once."""
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0].update(options=["equate-nans", "equate-nans"]),
        )
        self.assert_caught("names an option twice")

    def test_a_reference_to_null_is_caught(self) -> None:
        """A reference refers to an object, and null is none."""
        null = {"type": "reference", "id": "a", "value": {"type": "null"}}
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][0]["args"].__setitem__(0, null),
        )
        self.assert_caught("the reference 'a' refers to null, no object")

    def test_two_values_for_one_reference_are_caught(self) -> None:
        """Every reference of one id in a case is one object, of one value."""

        def differ(document: Any) -> None:
            document["cases"][0]["args"] = [
                {"type": "reference", "id": "a", "value": {"type": "int", "value": n}}
                for n in (1, 2)
            ]

        _edit(self.tree / "corpus" / "equal.json", differ)
        self.assert_caught(
            "states two values for the reference 'a', which is one object"
        )

    def test_a_reference_in_a_record_is_caught(self) -> None:
        """A record states the value that a reference refers to."""
        inner = {"type": "reference", "id": "a", "value": {"type": "int", "value": 1}}
        _edit(
            self.tree / "corpus" / "equal.json",
            lambda d: d["cases"][1]["detail"].update(
                got={"type": "list", "items": [inner]}
            ),
        )
        self.assert_caught("states a reference; a record states the value it refers to")

    def test_a_corpus_with_no_files_is_caught(self) -> None:
        """A corpus without a file checks no meaning at all."""
        for path in (self.tree / "corpus").glob("*.json"):
            path.unlink()
        self.assert_caught("corpus/: holds no cases")

    def test_a_corpus_file_named_for_another_assertion_is_caught(self) -> None:
        """A corpus file is named for the assertion it states."""
        corpus = self.tree / "corpus"
        (corpus / "equal.json").rename(corpus / "equal-again.json")
        self.assert_caught("is named 'equal-again' but states 'equal'")

    def test_a_corpus_file_with_no_cases_is_caught(self) -> None:
        """A corpus file states at least one case."""
        _edit(self.tree / "corpus" / "equal.json", lambda d: d.update(cases=[]))
        self.assert_caught("corpus/equal.json: states no cases")

    def test_a_vector_that_is_not_an_object_is_caught(self) -> None:
        """A vector is an object."""
        _edit(
            self.tree / "corpus" / "prop" / "token.json",
            lambda d: d["cases"].append("token/a-string"),
        )
        self.assert_caught("corpus/prop/token.json: a case is not an object")

    def test_a_vector_id_that_is_not_hyphenated_lowercase_is_caught(self) -> None:
        """A vector id is <subject>/<case> in hyphenated lowercase."""
        _edit(
            self.tree / "corpus" / "prop" / "token.json",
            lambda d: d["cases"][0].update(id="token/Encodes Nothing"),
        )
        self.assert_caught("states id 'token/Encodes Nothing', want <subject>/<case>")

    def test_a_vector_file_of_an_unknown_kind_is_caught(self) -> None:
        """A vector file states one of the definition's kinds."""
        (self.tree / "corpus" / "prop" / "fuzzing.json").write_text(
            json.dumps({"kind": "fuzzing", "cases": [{"id": "fuzzing/one"}]})
        )
        self.assert_caught("states kind 'fuzzing', which no vector has")

    def test_a_vector_file_with_no_cases_is_caught(self) -> None:
        """A vector file states at least one vector."""
        _edit(
            self.tree / "corpus" / "prop" / "token.json",
            lambda d: d.update(cases=[]),
        )
        self.assert_caught("corpus/prop/token.json: states no cases")

    def test_a_definition_with_no_relaxations_is_caught(self) -> None:
        """The definition states the relaxations a caller may apply."""

        def drop(document: Any) -> None:
            document["relaxations"] = {}
            for body in document["assertions"].values():
                body.pop("relaxations", None)

        _edit(self.tree / "spec" / "assertions.json", drop)
        self.assert_caught("spec/assertions.json: states no relaxations")

    def test_a_relaxation_id_that_is_not_hyphenated_lowercase_is_caught(self) -> None:
        """A relaxation id is an id."""

        def rename(document: Any) -> None:
            relaxations = document["relaxations"]
            relaxations["Equate-NaNs"] = relaxations.pop("equate-nans")

        _edit(self.tree / "spec" / "assertions.json", rename)
        self.assert_caught("Equate-NaNs: is not a hyphenated lowercase id")

    def test_a_naming_table_with_no_surface_is_caught(self) -> None:
        """The table names what a caller types beside the assertions."""
        _edit(self.tree / "spec" / "naming.json", lambda d: d.update(surface={}))
        self.assert_caught("spec/naming.json: states no surface table")

    def test_a_surface_id_that_is_not_well_formed_is_caught(self) -> None:
        """A surface id is an id with at most one dot."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["surface"]["helpers"].update({"golden.a.b": {"go": "X"}}),
        )
        self.assert_caught("surface.helpers.golden.a.b: is not a well-formed id")

    def test_a_surface_name_in_an_undeclared_language_is_caught(self) -> None:
        """A surface column names a declared language."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["surface"]["types"]["seat"].update(cobol="SEAT"),
        )
        self.assert_caught("surface.types.seat: cobol is not in the declared languages")

    def test_an_empty_surface_name_is_caught(self) -> None:
        """A surface name a user types has characters."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["surface"]["types"]["seat"].update(go="  "),
        )
        self.assert_caught("surface.types.seat: go is empty")

    def test_an_overlay_surface_that_is_not_a_list_is_caught(self) -> None:
        """An overlay's surface is a list of declines."""
        _edit(self.tree / "overlays" / "go.json", lambda d: d.update(surface={}))
        self.assert_caught("overlays/go.json: surface is not a list")

    def test_a_surface_decline_that_is_not_an_object_is_caught(self) -> None:
        """A decline states an id and a reason."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d["surface"].append("standard-seat"),
        )
        self.assert_caught("surface entry 'standard-seat' is not an object")

    def test_a_decline_of_an_unknown_surface_id_is_caught(self) -> None:
        """A language declines only what the table states."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d["surface"].append({"id": "invented", "why": "stated"}),
        )
        self.assert_caught("declines surface id 'invented', which the table does not")

    def test_a_surface_decline_with_no_reason_is_caught(self) -> None:
        """Declining a surface id is a claim, so it states a reason."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d["surface"][0].update(why="  "),
        )
        self.assert_caught("declines surface id 'standard-seat' with no why")

    def test_overlay_relaxations_that_are_not_a_list_are_caught(self) -> None:
        """An overlay's relaxations are a list of declines."""
        _edit(self.tree / "overlays" / "rust.json", lambda d: d.update(relaxations={}))
        self.assert_caught("overlays/rust.json: relaxations is not a list")

    def test_a_relaxation_decline_that_is_not_an_object_is_caught(self) -> None:
        """A decline states an id and a reason."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d["relaxations"].append("equate-nans"),
        )
        self.assert_caught("relaxation 'equate-nans' is not an object")

    def test_an_overlay_named_for_another_language_is_caught(self) -> None:
        """An overlay's file name is its language."""
        _edit(self.tree / "overlays" / "go.json", lambda d: d.update(language="rust"))
        self.assert_caught("overlays/go.json: is named 'go' but declares 'rust'")

    def test_limits_that_are_not_a_list_are_caught(self) -> None:
        """An overlay's limits are a list."""
        _edit(self.tree / "overlays" / "java.json", lambda d: d.update(limits={}))
        self.assert_caught("overlays/java.json: limits is not a list")

    def test_a_limit_that_is_not_an_object_is_caught(self) -> None:
        """A limit states an id, what it misses and why."""
        _edit(
            self.tree / "overlays" / "java.json",
            lambda d: d.setdefault("limits", []).append("no-task-leaks"),
        )
        self.assert_caught("limit 'no-task-leaks' is not an object")

    def test_divergences_that_are_not_a_list_are_caught(self) -> None:
        """An overlay's divergences are a list."""
        _edit(self.tree / "overlays" / "java.json", lambda d: d.update(diverge={}))
        self.assert_caught("overlays/java.json: diverge is not a list")

    def test_a_divergence_that_is_not_an_object_is_caught(self) -> None:
        """A divergence states an id, a stance and a reason."""
        _edit(
            self.tree / "overlays" / "java.json",
            lambda d: d["diverge"].append("max-allocs"),
        )
        self.assert_caught("divergence 'max-allocs' is not an object")

    def _vectors(self, kind: str, keep: Callable[[Any], bool]) -> None:
        """Keep only the vectors of one kind that keep accepts."""
        _edit(
            self.tree / "corpus" / "prop" / f"{kind}.json",
            lambda d: d.update(cases=[c for c in d["cases"] if keep(c)]),
        )

    def test_a_shape_with_one_vector_is_caught(self) -> None:
        """Every shape has two shape vectors."""
        self._vectors("shapes", lambda c: c["id"] != "bool/one-coin-each")
        self.assert_caught("has fewer than 2 vectors for shape 'bool'")

    def test_a_shape_vector_named_for_no_shape_is_caught(self) -> None:
        """A shape vector's id begins with the shape it decodes."""
        _edit(
            self.tree / "corpus" / "prop" / "shapes.json",
            lambda d: d["cases"][0].update(id="boolean/renamed"),
        )
        self.assert_caught("begins with 'boolean', which names no shape")

    def test_a_shape_that_no_inverse_runs_back_is_caught(self) -> None:
        """Every shape runs backwards in a vector."""
        self._vectors("inverse", lambda c: not c["id"].startswith("bool/"))
        self.assert_caught("runs no shape 'bool' back")

    def test_a_generator_that_no_inverse_runs_back_is_caught(self) -> None:
        """Every generator runs backwards in a vector."""
        self._vectors("inverse", lambda c: not c["id"].startswith("integer/"))
        self.assert_caught("runs no generator 'integer' back")

    def test_a_constraint_without_a_fixture_is_caught(self) -> None:
        """The fixtures cover every row of the constraint table."""
        self._vectors("fixtures", lambda c: c.get("covers") != "scale")
        self.assert_caught("has no fixture that covers 'scale'")

    def test_a_draws_end_without_a_vector_is_caught(self) -> None:
        """A label that differs from its entry has a vector."""

        def other_ends(case: Any) -> bool:
            error: dict[str, Any] = case.get("error") or {}
            return error.get("reason") != "label"

        self._vectors("draws", other_ends)
        self.assert_caught("has no vector that ends in 'label'")

    def test_a_phase_that_no_recording_vector_records_is_caught(self) -> None:
        """Every phase but fuzz has a recorded call."""
        token = "recording/records-the-one-case-of-a-replay-token"
        self._vectors("recording", lambda c: c["id"] != token)
        self.assert_caught("has no vector that records a call of phase 'token'")

    def _history(self, kind: str, keep: Callable[[Any], bool]) -> None:
        """Keep only the history vectors of one kind that keep accepts."""
        _edit(
            self.tree / "corpus" / "history" / f"{kind}.json",
            lambda d: d.update(cases=[c for c in d["cases"] if keep(c)]),
        )

    def test_a_definition_with_no_specs_is_caught(self) -> None:
        """The specs are what the checker's vectors name."""
        _edit(self.tree / "spec" / "assertions.json", lambda d: d.update(specs={}))
        self.assert_caught("spec/assertions.json: states no spec vocabulary")

    def test_a_spec_with_no_summary_is_caught(self) -> None:
        """Each implementation builds a named spec from its summary."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["specs"]["queue"].update(summary="  "),
        )
        self.assert_caught("spec queue: states no summary")

    def test_a_history_vector_of_an_unknown_spec_is_caught(self) -> None:
        """A vector of the checker names a spec of the definition."""
        _edit(
            self.tree / "corpus" / "history" / "linearizable.json",
            lambda d: d["cases"][0].update(spec="stack"),
        )
        self.assert_caught("names spec 'stack', which the definition does not state")

    def test_a_missing_history_vector_file_is_caught(self) -> None:
        """Every kind of history vector has a file."""
        (self.tree / "corpus" / "history" / "seam.json").unlink()
        self.assert_caught("corpus/history/: has no seam vectors")

    def test_a_history_vector_file_of_another_kind_is_caught(self) -> None:
        """A history vector file's name is its kind."""
        _edit(
            self.tree / "corpus" / "history" / "seam.json",
            lambda d: d.update(kind="linearizable"),
        )
        self.assert_caught("is named 'seam' but states kind 'linearizable'")

    def test_a_seam_vector_named_for_another_subject_is_caught(self) -> None:
        """A seam vector's id begins with history."""
        _edit(
            self.tree / "corpus" / "history" / "seam.json",
            lambda d: d["cases"][0].update(id="seam/renamed"),
        )
        self.assert_caught("begins with 'seam', which names no seam vector")

    def test_a_repeated_history_vector_id_is_caught(self) -> None:
        """Two vectors with one id make one of them unreportable."""

        def repeat(document: Any) -> None:
            document["cases"].append(dict(document["cases"][0]))

        _edit(self.tree / "corpus" / "history" / "linearizable.json", repeat)
        self.assert_caught("repeats case id 'linearizable/")

    def test_a_malformed_literal_in_a_history_vector_is_caught(self) -> None:
        """Every typed literal of a history vector is checked."""
        _edit(
            self.tree / "corpus" / "history" / "seam.json",
            lambda d: d["cases"][0]["script"][0]["args"][0].update(type="decimal"),
        )
        self.assert_caught("script[0].args[0]: states type 'decimal'")

    def test_intervals_that_refuse_no_entry_are_caught(self) -> None:
        """from-intervals has a vector that names the entry it refuses."""
        self._history("seam", lambda c: "intervals" not in c or c["refused"] is None)
        self.assert_caught("has no vector that covers 'intervals:refused'")

    def test_a_script_without_a_pending_call_is_caught(self) -> None:
        """A script records a call without a completion."""
        pending = "history/a-pending-call-has-no-completion"
        self._history("seam", lambda c: c["id"] != pending)
        self.assert_caught("has no vector that covers 'script:pending'")

    def test_a_spec_driven_only_one_way_is_caught(self) -> None:
        """Each named spec has a vector that passes and one that is violated."""
        self._history(
            "linearizable",
            lambda c: c["spec"] != "queue" or c["detail"]["outcome"] != "passed",
        )
        self.assert_caught("has no vector that covers 'queue:passed'")

    def test_a_limit_that_no_vector_reaches_is_caught(self) -> None:
        """The memo limit stops a search in a vector."""
        self._history("linearizable", lambda c: c["detail"]["limit"] != "memo")
        self.assert_caught("has no vector that covers 'limit:memo'")

    def test_a_forbidden_kind_that_no_vector_reports_is_caught(self) -> None:
        """Each kind that serializability forbids is the anomaly of a vector."""
        self._history("serializable", lambda c: c["detail"]["anomaly"] != "G0")
        self.assert_caught("has no vector that covers 'anomaly:G0'")

    def test_an_isolation_level_without_a_pass_is_caught(self) -> None:
        """Each level has a vector that passes."""
        self._history(
            "snapshot-isolation", lambda c: c["detail"]["anomaly"] is not None
        )
        self.assert_caught("has no vector that covers 'passed'")

    def test_an_isolation_vector_named_for_another_level_is_caught(self) -> None:
        """A vector's id begins with the assertion of its file."""
        _edit(
            self.tree / "corpus" / "history" / "snapshot-isolation.json",
            lambda d: d["cases"][0].update(id="serializable/renamed"),
        )
        self.assert_caught(
            "begins with 'serializable', which names no snapshot-isolation vector"
        )

    def _machines(self, keep: Callable[[Any], bool]) -> None:
        """Keep only the machines vectors that keep accepts."""
        _edit(
            self.tree / "corpus" / "stateful" / "machines.json",
            lambda d: d.update(cases=[c for c in d["cases"] if keep(c)]),
        )

    def test_a_definition_with_no_machine_subjects_is_caught(self) -> None:
        """The machine subjects are what the machines vectors name."""
        _edit(self.tree / "spec" / "assertions.json", lambda d: d.update(machines={}))
        self.assert_caught("spec/assertions.json: states no machine vocabulary")

    def test_a_machine_subject_with_no_summary_is_caught(self) -> None:
        """Each implementation builds a machine subject from its summary."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["machines"]["racy-counter"].update(summary="  "),
        )
        self.assert_caught("machine racy-counter: states no summary")

    def test_a_missing_machines_vector_file_is_caught(self) -> None:
        """The machines vectors have a file."""
        (self.tree / "corpus" / "stateful" / "machines.json").unlink()
        self.assert_caught("corpus/stateful/: has no machines vectors")

    def test_a_machines_vector_named_for_no_subject_is_caught(self) -> None:
        """A machines vector's id begins with a machine subject."""
        _edit(
            self.tree / "corpus" / "stateful" / "machines.json",
            lambda d: d["cases"][0].update(id="stack/renamed"),
        )
        self.assert_caught("begins with 'stack', which names no machine subject")

    def test_a_machines_vector_that_runs_another_subject_is_caught(self) -> None:
        """A machines vector runs the subject its id names."""
        _edit(
            self.tree / "corpus" / "stateful" / "machines.json",
            lambda d: d["cases"][0].update(subject="correct-queue"),
        )
        self.assert_caught(
            "runs 'correct-queue', and its id names 'queue-loses-on-wrap'"
        )

    def test_a_machine_subject_without_a_vector_is_caught(self) -> None:
        """Every machine subject runs in a vector."""
        self._machines(lambda c: c["subject"] != "correct-counter")
        self.assert_caught("has no vector that covers 'subject:correct-counter'")

    def test_machines_without_a_pass_are_caught(self) -> None:
        """A run of a machine passes in a vector."""
        self._machines(
            lambda c: c["detail"] is None or c["detail"]["outcome"] != "passed"
        )
        self.assert_caught("has no vector that covers 'passed'")

    def test_traces_that_never_fail_are_caught(self) -> None:
        """A trace that a run follows fails in a vector."""
        self._machines(lambda c: "trace" not in c or c["error"] is not None)
        self.assert_caught("has no vector that covers 'trace:counterexample'")

    def test_a_trace_without_a_client_is_caught(self) -> None:
        """A concurrent step entry states its client in a vector."""
        self._machines(lambda c: c["subject"] != "racy-counter" or "trace" not in c)
        self.assert_caught("has no vector that covers 'trace:client'")

    def test_a_refused_trace_that_no_vector_states_is_caught(self) -> None:
        """A step entry that a run cannot take is the error of a vector."""
        self._machines(lambda c: c["error"] is None)
        self.assert_caught("has no vector that covers 'refused:step'")

    def _files(self, kind: str, change: Callable[[Any], object]) -> None:
        """Edit the vectors of one file assertion in the scratch tree."""
        _edit(self.tree / "corpus" / "files" / f"{kind}.json", change)

    def test_a_missing_files_vector_file_is_caught(self) -> None:
        """Every file assertion has a vector file."""
        (self.tree / "corpus" / "files" / "is-dir.json").unlink()
        self.assert_caught("corpus/files/: has no is-dir vectors")

    def test_a_file_assertion_driven_one_way_is_caught(self) -> None:
        """A file assertion has a vector that passes and one that fails."""
        self._files(
            "has-mode",
            lambda d: d.update(cases=[c for c in d["cases"] if c["expect"] == "fail"]),
        )
        self.assert_caught("has-mode.json: states no case expecting 'pass'")

    def test_a_files_vector_under_another_assertion_is_caught(self) -> None:
        """A vector's id begins with the assertion of its file."""
        self._files("is-file", lambda d: d["cases"][0].update(id="is-dir/renamed"))
        self.assert_caught("id 'is-dir/renamed' does not begin with 'is-file'")

    def test_a_repeated_files_vector_id_is_caught(self) -> None:
        """Two vectors with one id make one of them unreportable."""
        self._files("is-dir", lambda d: d["cases"].append(dict(d["cases"][0])))
        self.assert_caught("repeats case id 'is-dir/a-directory-passes'")

    def test_a_files_vector_with_an_undeclared_detail_field_is_caught(self) -> None:
        """A failure states only the fields its assertion declares."""
        self._files(
            "is-file",
            lambda d: d["cases"][1]["detail"].update(kind={"type": "null"}),
        )
        self.assert_caught("states detail 'kind', which is-file does not declare")

    def test_a_subject_that_the_definition_does_not_state_is_caught(self) -> None:
        """tree-unchanged names a subject of the definition."""
        self._files(
            "tree-unchanged",
            lambda d: d["cases"][0].update(subject={"kind": "sleeps"}),
        )
        self.assert_caught("names subject kind 'sleeps', which the definition does")

    def test_a_workspace_that_breaks_a_rule_of_the_tree_is_caught(self) -> None:
        """A workspace states its entries in path order."""
        self._files(
            "tree-equal",
            lambda d: d["cases"][2]["workspace"]["entries"].reverse(),
        )
        self.assert_caught("workspace: 'a.txt' is not after the entry before it")

    def test_a_workspace_that_states_a_digest_is_caught(self) -> None:
        """A workspace writes content, which a digest does not state."""

        def digest(document: Any) -> None:
            entry = document["cases"][0]["workspace"]["entries"][0]
            del entry["text"]
            entry.update(digest="sha256:" + "0" * 64, size=70_000)

        self._files("is-file", digest)
        self.assert_caught("workspace: 'docs/a.md' states a digest")

    def test_an_argument_that_states_a_digest_is_caught(self) -> None:
        """Only a record states a file by its digest."""

        def digest(document: Any) -> None:
            entry = document["cases"][1]["args"][0]["entries"][0]
            del entry["text"]
            entry.update(digest="sha256:" + "0" * 64, size=70_000)

        self._files("tree-equal", digest)
        self.assert_caught("arg 0: 'a.txt' states a digest, which only a record")

    def test_a_tree_literal_with_a_key_it_does_not_take_is_caught(self) -> None:
        """A tree states its entries and nothing else."""
        self._files("tree-equal", lambda d: d["cases"][0]["args"][0].update(of="x"))
        self.assert_caught("states 'of', which type 'tree' does not take")

    def test_a_golden_case_without_its_golden_tree_is_caught(self) -> None:
        """A case of golden-match-tree states a golden tree, or null for none."""
        self._files("golden-match-tree", lambda d: d["cases"][0].pop("golden"))
        self.assert_caught("states no golden, a tree or null")

    def test_a_golden_tree_that_breaks_a_rule_of_the_tree_is_caught(self) -> None:
        """A golden tree states no entry below a file."""
        self._files(
            "golden-match-tree",
            lambda d: d["cases"][0]["golden"]["entries"].insert(
                1, {"path": "api.go/x", "text": ""}
            ),
        )
        self.assert_caught("golden: 'api.go/x' is below 'api.go', no directory")

    def test_a_parallel_language_without_the_recorder_limit_is_caught(self) -> None:
        """The counter can hide a missing barrier where threads run on many cores."""
        _edit(
            self.tree / "overlays" / "rust.json",
            lambda d: d.update(limits=[e for e in d["limits"] if e["id"] != "history"]),
        )
        self.assert_caught("overlays/rust.json: states no limit on 'history'")

    def _forms(self, change: Callable[[Any], object]) -> None:
        """Edit the form vectors of the scratch tree."""
        _edit(self.tree / "corpus" / "prop" / "forms.json", change)

    def test_a_form_without_a_failing_vector_is_caught(self) -> None:
        """Each form has a vector that fails and one that passes."""
        failing = "prop-equal/fails-when-a-sort-reorders-the-input"
        self._vectors("forms", lambda c: c["id"] != failing)
        self.assert_caught("has no prop-equal vector whose outcome is 'counterexample'")

    def test_a_vector_of_a_form_no_case_can_state_is_caught(self) -> None:
        """No case can state an allocation count, so max-allocs has no vector."""
        self._forms(
            lambda d: d["cases"][0].update(
                id="prop-max-allocs/allocates", form="prop-max-allocs"
            )
        )
        self.assert_caught(
            "begins with 'prop-max-allocs', which names no form a vector runs"
        )

    def test_a_form_vector_that_runs_another_form_is_caught(self) -> None:
        """A form vector runs the form its id names."""
        self._forms(lambda d: d["cases"][0].update(form="prop-nil"))
        self.assert_caught("runs 'prop-nil', and its id names 'prop-equal'")

    def test_a_form_vector_with_an_unknown_subject_is_caught(self) -> None:
        """A form vector names subject kinds of the definition's vocabulary."""
        self._forms(lambda d: d["cases"][0].update(subjects=["identity", "sleeps"]))
        self.assert_caught("names subject kind 'sleeps', which the definition does not")

    def test_form_vector_subjects_that_are_not_a_list_are_caught(self) -> None:
        """The subjects are a list, in the order the assertion takes them."""
        self._forms(lambda d: d["cases"][0].update(subjects="identity"))
        self.assert_caught("subjects is not a list")

    def test_a_form_that_fails_with_another_assertions_record_is_caught(self) -> None:
        """A form's failure is the record of the assertion it runs."""
        self._forms(
            lambda d: d["cases"][1]["detail"]["failure"].update(assertion="nil")
        )
        self.assert_caught(
            "fails with the record of 'nil', and prop-equal runs 'equal'"
        )

    def test_a_form_failure_with_an_undeclared_detail_field_is_caught(self) -> None:
        """A failure states only the detail fields its assertion declares."""
        self._forms(
            lambda d: d["cases"][1]["detail"]["failure"]["detail"].update(
                bogus={"type": "int", "value": 1}
            )
        )
        self.assert_caught("states detail 'bogus', which equal does not declare")

    def _zones(self, change: Callable[[Any], object]) -> None:
        """Edit the zone table of the scratch tree."""
        _edit(self.tree / "spec" / "zones.json", change)

    def test_a_zone_list_that_does_not_start_with_utc_is_caught(self) -> None:
        """The first zone is the simplest, and UTC has no change."""
        self._zones(lambda d: d["zones"].reverse())
        self.assert_caught("lists 'Antarctica/Troll' first")

    def test_a_zone_listed_twice_is_caught(self) -> None:
        """A zone listed twice is sampled twice as often."""
        self._zones(lambda d: d["zones"].append(d["zones"][1]))
        self.assert_caught("spec/zones.json: lists a zone twice")

    def test_utc_with_a_change_is_caught(self) -> None:
        """UTC has no offset and no change."""
        self._zones(lambda d: d["zones"][0]["changes"].append([0, 0, 3600]))
        self.assert_caught("UTC: changes, and UTC has none")

    def test_changes_out_of_order_are_caught(self) -> None:
        """A zone's changes are in time order."""
        self._zones(lambda d: d["zones"][1]["changes"].reverse())
        self.assert_caught("is not after the change before it")

    def test_a_change_that_keeps_its_offset_is_caught(self) -> None:
        """A transition of the abbreviation alone is no offset change."""

        def flat(document: Any) -> None:
            change = document["zones"][1]["changes"][0]
            change[2] = change[1]

        self._zones(flat)
        self.assert_caught("Europe/Amsterdam: change 0 keeps its offset")

    def test_a_change_that_does_not_connect_is_caught(self) -> None:
        """Each change starts from the offset the change before it left."""
        self._zones(lambda d: d["zones"][1]["changes"][1].__setitem__(1, 1234))
        self.assert_caught("change 1 starts from 1234")

    def test_an_offset_beyond_18_hours_is_caught(self) -> None:
        """No zone is more than 18 hours from UTC."""
        self._zones(lambda d: d["zones"][1]["changes"][0].__setitem__(1, -64801))
        self.assert_caught("change 0 states an offset beyond 18 hours")

    def test_a_change_outside_the_years_is_caught(self) -> None:
        """The table covers its stated years and no more."""
        self._zones(lambda d: d["zones"][1]["changes"][0].__setitem__(0, -(2**40)))
        self.assert_caught("Europe/Amsterdam: change 0 is outside the years")

    def test_a_change_that_is_not_three_integers_is_caught(self) -> None:
        """A change is an instant and two offsets."""
        self._zones(lambda d: d["zones"][1]["changes"].append([1, 2]))
        self.assert_caught("is [1, 2], not an instant and two offsets")

    def test_a_zone_without_changes_is_caught(self) -> None:
        """Every zone states its changes, UTC's empty list included."""
        self._zones(lambda d: d["zones"][1].pop("changes"))
        self.assert_caught("Europe/Amsterdam: states no changes")

    def test_a_table_without_a_release_is_caught(self) -> None:
        """The table names the tzdata release it was computed from."""
        self._zones(lambda d: d.update(release=""))
        self.assert_caught("spec/zones.json: names no tzdata release")

    def test_a_table_whose_years_run_backwards_is_caught(self) -> None:
        """The table's first year is before its last."""
        self._zones(lambda d: d.update({"from": 2100, "until": 1900}))
        self.assert_caught("states the years 2100 to 1900")

    def test_an_unreadable_zone_table_is_reported_not_raised(self) -> None:
        """A broken table is a finding, not a traceback."""
        (self.tree / "spec" / "zones.json").write_text("{not json")
        self.assert_caught("spec/zones.json: cannot be read")

    def test_a_table_without_zones_is_caught(self) -> None:
        """The zone shape samples from a list that is not empty."""
        self._zones(lambda d: d.update(zones=[]))
        self.assert_caught("spec/zones.json: lists no zones")

    def test_a_relation_form_that_keeps_a_generated_argument_is_caught(self) -> None:
        """A relation's form loses the arguments it generates from its arity."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["prop-commutative"].update(arity=4),
        )
        self.assert_caught("prop-commutative: states arity 4; the rule gives 2")

    def test_a_form_over_a_function_that_loses_an_argument_is_caught(self) -> None:
        """The function takes the place of the value, so the arity stays."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["prop-equal"].update(arity=2),
        )
        self.assert_caught("prop-equal: states arity 2; the rule gives 3")

    def test_a_form_with_its_assertions_detail_fields_is_caught(self) -> None:
        """A form reports the detail of the run that it is."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["prop-equal"].update(detail_fields=["want"]),
        )
        self.assert_caught("prop-equal: states detail_fields ['want']")

    def test_a_form_without_its_assertions_relaxations_is_caught(self) -> None:
        """A relaxation applies to the assertion's comparison in every case."""

        def drop(document: Any) -> None:
            del document["assertions"]["prop-equal"]["relaxations"]

        _edit(self.tree / "spec" / "assertions.json", drop)
        self.assert_caught("prop-equal: states relaxations []")

    def test_a_form_in_another_package_is_caught(self) -> None:
        """Every form is in the prop package."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["assertions"]["prop-equal"].update(package="golden"),
        )
        self.assert_caught("prop-equal: states package 'golden'; the rule gives 'prop'")

    def test_a_form_of_another_assertion_is_caught(self) -> None:
        """A form's entry states the assertion that its id names."""

        def swap(document: Any) -> None:
            document["assertions"]["prop-equal"]["form"]["of"] = "not-equal"

        _edit(self.tree / "spec" / "assertions.json", swap)
        self.assert_caught("prop-equal: is a form that the rule does not list")

    def test_a_form_that_the_rule_lists_and_nobody_defined_is_caught(self) -> None:
        """Each listed assertion has its form's entry."""

        def drop(document: Any) -> None:
            del document["assertions"]["prop-equal"]

        _edit(self.tree / "spec" / "assertions.json", drop)
        self.assert_caught("prop-equal: is not defined, and the rule lists it")

    def test_a_form_that_the_rule_does_not_list_is_caught(self) -> None:
        """Every entry with a form is one the rule lists."""

        def add(document: Any) -> None:
            entry = json.loads(json.dumps(document["assertions"]["prop-equal"]))
            entry["form"]["of"] = "total"
            document["assertions"]["prop-total"] = entry

        _edit(self.tree / "spec" / "assertions.json", add)
        self.assert_caught("prop-total: is a form that the rule does not list")

    def test_a_form_of_prop_for_all_is_caught(self) -> None:
        """prop-for-all is the run that every form is, so it has no form."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["forms"]["functions"].append("prop-for-all"),
        )
        self.assert_caught("which is no assertion that can have a form")

    def test_an_assertion_that_the_rule_lists_twice_is_caught(self) -> None:
        """An assertion has one form."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["forms"]["relations"].update(equal=["input"]),
        )
        self.assert_caught("forms: lists 'equal' twice")

    def test_a_relation_form_that_generates_nothing_is_caught(self) -> None:
        """A relation's form generates the arguments the relation takes."""
        _edit(
            self.tree / "spec" / "assertions.json",
            lambda d: d["forms"]["relations"].update(commutative=[]),
        )
        self.assert_caught("generates [], not arguments")

    def test_a_forms_rule_without_relations_is_caught(self) -> None:
        """The rule states the functions and the relations."""

        def drop(document: Any) -> None:
            del document["forms"]["relations"]

        _edit(self.tree / "spec" / "assertions.json", drop)
        self.assert_caught("needs a list of functions and a map of relations")

    def test_a_definition_without_a_forms_rule_is_caught(self) -> None:
        """The entries of the forms are read against the rule."""

        def drop(document: Any) -> None:
            del document["forms"]

        _edit(self.tree / "spec" / "assertions.json", drop)
        self.assert_caught("spec/assertions.json: forms: is not a rule")

    def test_a_form_name_off_the_rule_is_caught(self) -> None:
        """A form's name is the qualifier followed by its assertion's name."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["prop-equal"].update(python="prop.eq"),
        )
        self.assert_caught(
            "prop-equal.python: is 'prop.eq'; the rule gives 'prop.equal'"
        )

    def test_a_go_form_of_permutation_without_its_exception_is_caught(self) -> None:
        """Go's prop package already declares the generator prop.Permutation."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["prop-permutation"].update(go="prop.Permutation"),
        )
        self.assert_caught(
            "prop-permutation.go: is 'prop.Permutation'; the rule gives "
            "'prop.IsPermutation'"
        )

    def test_a_name_exception_for_an_assertion_without_a_form_is_caught(self) -> None:
        """An exception renames a form that exists."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["forms"]["exceptions"].update(total={"go": "prop.Total"}),
        )
        self.assert_caught("names a form of 'total', which has none")

    def test_a_name_exception_in_an_unqualified_language_is_caught(self) -> None:
        """An exception applies only where the rule names forms at all."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["forms"]["exceptions"]["permutation"].update(cobol="X"),
        )
        self.assert_caught("names cobol, which the rule does not qualify")

    def test_a_naming_table_without_qualifiers_is_caught(self) -> None:
        """The names of the forms are read against the qualifiers."""

        def drop(document: Any) -> None:
            del document["forms"]["qualifiers"]

        _edit(self.tree / "spec" / "naming.json", drop)
        self.assert_caught("spec/naming.json: forms: states no qualifiers")


if __name__ == "__main__":
    unittest.main()
