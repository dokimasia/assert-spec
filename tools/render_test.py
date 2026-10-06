"""The renderer: what is on disk is what it renders, and a clash is refused."""

from __future__ import annotations

import json
import unittest
from typing import Any, final

from render import (
    CORPUS,
    FAMILIES,
    ROOT,
    TABLES,
    RenderError,
    load,
    published,
    series,
    vector,
    vectors_text,
)


def _tables() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return both tables as rendering publishes them."""
    return published(load("assertions"), load("naming"))


@final
class FormsTest(unittest.TestCase):
    """The rule that adds an entry and a name for each property form."""

    def test_the_tables_on_disk_are_what_render_publishes(self) -> None:
        """A table the YAML no longer renders fails here, tracked or not."""
        for name, document in zip(TABLES, _tables(), strict=True):
            with self.subTest(table=name):
                on_disk = json.loads((ROOT / "spec" / f"{name}.json").read_text())
                self.assertEqual(on_disk, document, "run make render")

    def test_a_relation_form_loses_the_arguments_it_generates(self) -> None:
        """The relation associative takes five arguments, and its form makes three."""
        assertions = _tables()[0]["assertions"]
        self.assertEqual(assertions["prop-associative"]["arity"], 2)
        self.assertEqual(assertions["prop-commutative"]["arity"], 2)
        self.assertEqual(assertions["prop-idempotent"]["arity"], 3)
        self.assertEqual(
            assertions["prop-associative"]["form"],
            {"of": "associative", "kind": "relation", "generates": ["a", "b", "c"]},
        )

    def test_a_form_over_a_function_keeps_its_assertions_arity(self) -> None:
        """The function takes the place of the value."""
        entry = _tables()[0]["assertions"]["prop-equal"]
        self.assertEqual(entry["arity"], 3)
        self.assertEqual(entry["package"], "prop")
        self.assertEqual(
            entry["relaxations"], ["equate-empty", "equate-nans", "by-identity"]
        )
        self.assertEqual(
            entry["form"], {"of": "equal", "kind": "function", "generates": ["input"]}
        )

    def test_a_form_without_relaxations_states_none(self) -> None:
        """The assertion true accepts no relaxation, so its form accepts none."""
        self.assertNotIn("relaxations", _tables()[0]["assertions"]["prop-true"])

    def test_a_form_reports_the_detail_of_prop_for_all(self) -> None:
        """A form is a run of prop-for-all."""
        assertions = _tables()[0]["assertions"]
        self.assertEqual(
            assertions["prop-max-allocs"]["detail_fields"],
            assertions["prop-for-all"]["detail_fields"],
        )

    def test_a_summary_names_what_the_form_generates(self) -> None:
        """Two generated arguments read as a series."""
        self.assertEqual(
            _tables()[0]["assertions"]["prop-commutative"]["summary"],
            "The property form of commutative. Each case of a run generates a "
            "and b, and commutative runs on them as prop-for-all runs a body.\n",
        )

    def test_a_series_reads_as_english(self) -> None:
        """One label, two, and three."""
        self.assertEqual(series(["a"]), "a")
        self.assertEqual(series(["a", "b"]), "a and b")
        self.assertEqual(series(["a", "b", "c"]), "a, b and c")

    def test_a_form_takes_its_assertions_name_in_the_prop_package(self) -> None:
        """Each language qualifies the assertion's own name."""
        self.assertEqual(
            _tables()[1]["names"]["prop-equal"],
            {
                "go": "prop.Equal",
                "python": "prop.equal",
                "rust": "prop::equal",
                "typescript": "prop.equal",
                "java": "Prop.equal",
                "kotlin": "Prop.equal",
            },
        )

    def test_the_go_form_of_permutation_is_is_permutation(self) -> None:
        """Go's prop package already declares the generator prop.Permutation."""
        names = _tables()[1]["names"]["prop-permutation"]
        self.assertEqual(names["go"], "prop.IsPermutation")
        self.assertEqual(names["python"], "prop.is_permutation")

    def test_an_authored_form_is_refused(self) -> None:
        """The rule renders every form, so an authored one would be overwritten."""
        spec = load("assertions")
        spec["assertions"]["prop-equal"] = {"arity": 3}
        with self.assertRaisesRegex(RenderError, "prop-equal is authored"):
            published(spec, load("naming"))

    def test_a_relation_that_generates_nothing_is_refused(self) -> None:
        """A relation's form generates the arguments the relation takes."""
        spec = load("assertions")
        spec["forms"]["relations"]["commutative"] = []
        with self.assertRaisesRegex(RenderError, "commutative generates no argument"):
            published(spec, load("naming"))

    def test_a_form_of_an_undefined_assertion_is_refused(self) -> None:
        """A form runs an assertion of the table."""
        spec = load("assertions")
        spec["forms"]["functions"].append("invented")
        with self.assertRaisesRegex(RenderError, "invented runs an assertion nobody"):
            published(spec, load("naming"))

    def test_a_definition_without_prop_for_all_is_refused(self) -> None:
        """Every form reports the detail of prop-for-all."""
        spec = load("assertions")
        del spec["assertions"]["prop-for-all"]
        with self.assertRaisesRegex(RenderError, "prop-for-all, which is not defined"):
            published(spec, load("naming"))

    def test_an_assertion_without_a_name_to_qualify_is_refused(self) -> None:
        """A form's name is built from its assertion's name."""
        naming = load("naming")
        del naming["names"]["equal"]["rust"]
        with self.assertRaisesRegex(RenderError, "equal has no rust name"):
            published(load("assertions"), naming)

    def test_a_definition_without_the_forms_rule_is_refused(self) -> None:
        """Rendering needs the rule to add the forms."""
        spec = load("assertions")
        del spec["forms"]
        with self.assertRaisesRegex(RenderError, "states no rule for the forms"):
            published(spec, load("naming"))

    def test_a_rule_without_relations_is_refused(self) -> None:
        """The rule states the functions and the relations."""
        spec = load("assertions")
        del spec["forms"]["relations"]
        with self.assertRaisesRegex(RenderError, "needs functions and relations"):
            published(spec, load("naming"))

    def test_a_naming_table_without_qualifiers_is_refused(self) -> None:
        """Rendering needs the qualifiers to name the forms."""
        naming = load("naming")
        del naming["forms"]["qualifiers"]
        with self.assertRaisesRegex(RenderError, "states no qualifiers"):
            published(load("assertions"), naming)


@final
class VectorsTest(unittest.TestCase):
    """The vector files and the function that renders one case."""

    def test_every_vector_file_is_what_the_reference_renders(self) -> None:
        """A vector the reference no longer computes fails here, tracked or not."""
        for family, (kinds, _) in FAMILIES.items():
            for kind in kinds:
                with self.subTest(family=family, kind=kind):
                    on_disk = (CORPUS / family / f"{kind}.json").read_text()
                    self.assertEqual(
                        on_disk, vectors_text(family, kind), "run make render"
                    )

    def test_a_case_keeps_its_inputs_and_gains_the_outputs(self) -> None:
        """The inputs first, in their order, then the outputs."""
        case = {"id": "coverage/met", "counted": 27, "valid": 100, "share": 0.1}
        rendered = vector("prop", "coverage", {**case, "last": False, "exact": False})
        self.assertEqual(
            list(rendered),
            ["id", "counted", "valid", "share", "last", "exact", "verdict"],
        )
        self.assertEqual(rendered["verdict"], "met")

    def test_a_family_computes_its_own_kinds(self) -> None:
        """A seam vector is the history's, and gains its events."""
        rendered = vector("history", "seam", {"id": "history/empty", "script": []})
        self.assertEqual(
            rendered,
            {"id": "history/empty", "script": [], "events": [], "refused": None},
        )

    def test_an_input_named_as_an_output_is_refused(self) -> None:
        """An output never replaces what the YAML states."""
        case = {"id": "token/encodes", "choices": [], "token": "prop1:AAA"}
        with self.assertRaisesRegex(RenderError, "token"):
            vector("prop", "token", case)

    def test_a_case_that_is_not_an_object_is_refused(self) -> None:
        """A YAML list item that is a scalar names no inputs."""
        with self.assertRaises(RenderError):
            vector("prop", "token", "token/encodes")
