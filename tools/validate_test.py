#!/usr/bin/env python3
"""The validator, driven against faults it must catch.

A validator only ever run on a clean tree is untested: it would pass
just as readily if every rule were deleted. Each case here copies the
repository, breaks one thing, and requires the validator to say so.

Standard library only, and run with:

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
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: What gets copied into each scratch tree. The validator reads these
#: and nothing else.
COPIED = ("spec", "corpus", "overlays", "VERSION", "tools")


def _edit(path: Path, change: Callable[[Any], Any]) -> None:
    """Read JSON, apply change to it, and write it back."""
    document = json.loads(path.read_text())
    path.write_text(json.dumps(change(document) or document, indent=2))


class Validator(unittest.TestCase):
    """Each case breaks one rule and reads what the validator says."""

    def setUp(self) -> None:
        """Copy the repository somewhere it can be broken safely."""
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
        """The validator must fail, and say why."""
        result = self.run_validator()
        self.assertEqual(result.returncode, 1, f"validator passed; wanted {phrase!r}")
        self.assertIn(phrase, result.stderr)

    def test_an_unbroken_tree_passes(self) -> None:
        """The copy itself is clean, or every other case proves nothing."""
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("all consistent", result.stdout)

    def test_a_version_disagreement_is_caught(self) -> None:
        """The VERSION file and the tables must say the same thing."""
        (self.tree / "VERSION").write_text("9.9.9\n")
        self.assert_caught("VERSION says '9.9.9'")

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

    def test_a_name_outside_its_package_is_caught(self) -> None:
        """A qualified name must sit in the package the definition gives."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: d["names"]["golden-match"].update(python="wrong.match"),
        )
        self.assert_caught("does not sit in package 'golden'")

    def test_a_qualified_name_with_no_package_is_caught(self) -> None:
        """A root-namespace assertion may not carry a package prefix."""
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
        """A corpus file must test something the standard states."""
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
        """JSON names only NaN, Inf and -Inf; anything else is a typo."""
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
        """A case must say pass or fail; anything else states nothing."""
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
                    case["message_contains"] = ["something"]
                    return

        _edit(self.tree / "corpus" / "equal.json", contradict)
        self.assert_caught("expects a pass but states message_contains")

    def test_a_skip_with_no_reason_is_caught(self) -> None:
        """A skip is a claim, and a claim with no reason cannot be read."""
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
        """An overlay pinned to a version that moved on is stale."""
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

    def test_a_divergence_with_no_reason_is_caught(self) -> None:
        """A divergence is the one thing that most needs explaining."""
        _edit(
            self.tree / "overlays" / "go.json",
            lambda d: d.update(
                diverge=[{"id": "equal", "stance": "blocked", "why": "  "}]
            ),
        )
        self.assert_caught("with no why")

    def test_a_divergence_with_no_stance_is_caught(self) -> None:
        """Whether a gap is blocked or merely open is the useful part."""
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

    def test_every_implementing_language_carries_an_overlay(self) -> None:
        """Full compliance is stated, not assumed from a missing file."""
        declared = {
            p.stem for p in (self.tree / "overlays").glob("*.json")
        }
        self.assertEqual(declared, {"go", "python"})

    def test_unreadable_json_is_reported_not_raised(self) -> None:
        """A broken file is a finding, not a traceback."""
        (self.tree / "corpus" / "equal.json").write_text("{not json")
        self.assert_caught("cannot be read")

    def test_every_problem_is_reported_in_one_run(self) -> None:
        """Fixing one problem at a time per run would be unusable."""
        _edit(
            self.tree / "spec" / "naming.json",
            lambda d: [d["names"].pop("equal"), d["names"].pop("true")] and None,
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 1)
        self.assertIn("equal has no entry", result.stderr)
        self.assertIn("true has no entry", result.stderr)


if __name__ == "__main__":
    unittest.main()
