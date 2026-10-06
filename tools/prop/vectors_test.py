"""The vector functions: the notation and one computed vector of each kind."""

from __future__ import annotations

import math
import unittest
from typing import Any, final

from .choice import Choice, FloatBounds, IntegerBounds, SequenceBounds
from .vectors import (
    VectorError,
    bounds_literal,
    choice_literal,
    compute,
    parse_choice,
)

DIGIT: dict[str, Any] = {"gen": "integer", "min": 0, "max": 9}
DIGITS: dict[str, Any] = {"gen": "list", "of": DIGIT, "max_size": 3}


@final
class NotationTest(unittest.TestCase):
    """Choices in corpus form."""

    def test_each_kind_of_choice_round_trips(self) -> None:
        """An integer, a large integer, floats and a sequence."""
        choices = [
            Choice("integer", -3),
            Choice("integer", 2**64 - 1),
            Choice("float", 1.5),
            Choice("float", -0.0),
            Choice("float", math.inf),
            Choice("sequence", (1, 200)),
        ]
        for choice in choices:
            written = choice_literal(choice)
            again = parse_choice(written)
            self.assertEqual(again.kind, choice.kind)
            self.assertEqual(repr(again.value), repr(choice.value))

    def test_the_forms_are_as_stated(self) -> None:
        """A JSON integer, a string past 2^53, a float object, a sequence object."""
        self.assertEqual(choice_literal(Choice("integer", 7)), 7)
        self.assertEqual(choice_literal(Choice("integer", 2**60)), str(2**60))
        self.assertEqual(choice_literal(Choice("float", math.nan)), {"float": "NaN"})
        self.assertEqual(choice_literal(Choice("sequence", (1,))), {"sequence": [1]})

    def test_a_form_that_is_no_choice_raises(self) -> None:
        """A bool, a list, an object with two keys."""
        for written in (True, [1], {"float": 1.0, "sequence": []}):
            with self.assertRaises(VectorError, msg=str(written)):
                parse_choice(written)


@final
class ComputeTest(unittest.TestCase):
    """One vector of each kind."""

    def test_decoding_records_the_choices_and_the_value(self) -> None:
        """The RFC's example: 1, 7, 1, 3, 0 is [7, 3]."""
        got = compute("decoding", {"generator": DIGITS, "choices": [1, 7, 1, 3, 0]})
        self.assertEqual(got["recorded"], [1, 7, 1, 3, 0])
        self.assertEqual(got["value"], {"type": "list", "of": "int", "value": [7, 3]})

    def test_decoding_reports_a_rejected_case(self) -> None:
        """A unique list of two from the targets."""
        unique = {**DIGITS, "unique": True, "min_size": 2}
        got = compute("decoding", {"generator": unique, "choices": []})
        self.assertEqual((got["value"], got["rejected"]), (None, True))

    def test_generation_states_each_cases_choices_and_value(self) -> None:
        """Three cases of seed 42, each from its own source."""
        spec = {"gen": "integer", "min": -100, "max": 100}
        got = compute("generation", {"generator": spec, "seed": "42", "count": 3})
        self.assertEqual([c["choices"] for c in got["cases"]], [[11], [0], [76]])
        self.assertEqual(got["cases"][0]["value"], {"type": "int", "value": 11})

    def test_a_seed_that_is_no_decimal_string_raises(self) -> None:
        """A seed is digits only."""
        spec = {"gen": "integer", "min": 0, "max": 9}
        for seed in ("7.5", "-1", 7):
            with self.assertRaises(VectorError, msg=str(seed)):
                compute("generation", {"generator": spec, "seed": seed, "count": 1})

    def test_shrinking_stops_at_the_stated_budget(self) -> None:
        """Five runs, and a case larger than the minimum."""
        integers = {"gen": "list", "of": {"gen": "integer", "min": 0, "max": 100}}
        case = {
            "generator": integers,
            "fails-when": {"kind": "sum-above", "n": 150},
            "seed": "7",
            "budget": 5,
        }
        self.assertEqual(compute("shrinking", case)["runs"], 5)

    def test_shrinking_reports_the_minimal_case(self) -> None:
        """A sum above 10 shrinks to [11]."""
        integers = {"gen": "list", "of": {"gen": "integer", "min": 0, "max": 100}}
        got = compute(
            "shrinking",
            {
                "generator": integers,
                "fails-when": {"kind": "sum-above", "n": 10},
                "seed": "7",
            },
        )
        self.assertEqual(got["value"], {"type": "list", "of": "int", "value": [11]})
        self.assertEqual(got["outcome"], "counterexample")

    def test_coverage_bridge_and_token_vectors(self) -> None:
        """A verdict, bytes decoded, and a token."""
        verdict = compute(
            "coverage",
            {"counted": 40, "valid": 100, "share": 0.1, "last": False, "exact": False},
        )
        self.assertEqual(verdict, {"verdict": "met"})
        bridged = compute("bridge", {"generator": {"gen": "bytes"}, "bytes": "0100ff"})
        self.assertEqual(bridged["value"], {"type": "bytes", "value": "ff"})
        self.assertEqual(compute("token", {"choices": []}), {"token": "prop1:"})
        self.assertEqual(
            compute("token", {"token": "prop1:AAA="}), {"decoded": None, "error": True}
        )

    def test_behaviour_states_every_detail_field(self) -> None:
        """A vacuous run fills only its own fields."""
        got = compute(
            "behaviour",
            {"body": {"kind": "draws-nothing"}, "settings": {"seed": "7"}},
        )
        detail = got["detail"]
        self.assertEqual(
            sorted(detail),
            sorted(
                [
                    "outcome",
                    "cases",
                    "rejected",
                    "seed",
                    "counterexample",
                    "failure",
                    "choices",
                    "others",
                    "divergence",
                    "coverage",
                ]
            ),
        )
        self.assertEqual((detail["outcome"], detail["cases"]), ("vacuous", 1))
        self.assertIsNone(detail["counterexample"])

    def test_a_divergence_states_the_label_and_the_step_of_its_request(self) -> None:
        """The diverging body's draw is labelled value, and it runs no machine."""
        got = compute(
            "behaviour", {"body": {"kind": "diverges"}, "settings": {"seed": "7"}}
        )
        divergence = got["detail"]["divergence"]
        self.assertEqual((divergence["label"], divergence["step"]), ("value", None))

    def test_a_counterexample_states_the_nearest_passing_value(self) -> None:
        """Above 1000 fails, so 1001 fails and 1000 passes."""
        body = {
            "draw": {"gen": "integer", "min": 0, "max": 10000},
            "fails": [{"identity": "big", "when": {"kind": "at-least", "n": 1001}}],
        }
        got = compute("behaviour", {"body": body, "settings": {"seed": "7"}})
        self.assertEqual(
            got["detail"]["counterexample"],
            [
                {
                    "label": "value",
                    "value": {"type": "int", "value": 1001},
                    "any-value-fails": False,
                    "nearest-passing": {"type": "int", "value": 1000},
                }
            ],
        )

    def test_bounds_are_stated_with_every_parameter(self) -> None:
        """A float's width and NaN, a sequence's element count and sizes."""
        self.assertEqual(
            bounds_literal(FloatBounds(-math.inf, 1.5, True, 32)),
            {
                "kind": "float",
                "min": "-Inf",
                "max": 1.5,
                "allow_nan": True,
                "width": 32,
            },
        )
        self.assertEqual(
            bounds_literal(SequenceBounds(256, 1, None)),
            {"kind": "sequence", "k": 256, "min_size": 1, "max_size": None},
        )
        self.assertEqual(
            bounds_literal(IntegerBounds(0, 2**64 - 1)),
            {"kind": "integer", "min": 0, "max": str(2**64 - 1)},
        )

    def test_a_stored_case_runs_before_the_simplest(self) -> None:
        """The stored case fails before any case passes."""
        body = {
            "draw": {"gen": "integer", "min": 0, "max": 1000},
            "fails": [{"identity": "big", "when": {"kind": "at-least", "n": 900}}],
        }
        stored = {"seed": "7", "stored": [[950]]}
        got = compute("behaviour", {"body": body, "settings": stored})
        self.assertEqual(got["detail"]["cases"], 0)

    def test_max_choices_rejects_a_larger_case(self) -> None:
        """A list of at least three digits needs seven choices."""
        body = {"draw": {**DIGITS, "min_size": 3, "max_size": None}}
        capped = {"seed": "7", "max-choices": 4}
        got = compute("behaviour", {"body": body, "settings": capped})
        self.assertEqual(got["detail"]["outcome"], "rejected")

    def test_a_replayed_token_runs_one_case(self) -> None:
        """A failing token is reported as found."""
        body = {
            "draw": {"gen": "integer", "min": 0, "max": 9},
            "fails": [{"identity": "big", "when": {"kind": "at-least", "n": 5}}],
        }
        got = compute(
            "behaviour",
            {"body": body, "settings": {"seed": "7", "replay": "prop1:AAc"}},
        )
        self.assertEqual(got["detail"]["outcome"], "counterexample")
        self.assertEqual(got["detail"]["choices"], "prop1:AAc")

    def test_a_shape_vector_states_each_cases_choices_and_value(self) -> None:
        """Three cases of a bool shape, each from its own source."""
        got = compute("shapes", {"shape": {"shape": "bool"}, "seed": "7", "count": 3})
        self.assertEqual(len(got["cases"]), 3)
        for case in got["cases"]:
            self.assertEqual(len(case["choices"]), 1)
            self.assertEqual(case["value"]["type"], "bool")

    def test_an_inverse_vector_states_the_choices_or_an_error(self) -> None:
        """A value of the shape, and one outside a generator's bounds."""
        shape = {"shape": "int", "width": 8, "signed": False}
        self.assertEqual(
            compute("inverse", {"shape": shape, "value": {"type": "int", "value": 9}}),
            {"choices": [9], "error": False},
        )
        digit = {"gen": "integer", "min": 0, "max": 9}
        self.assertEqual(
            compute(
                "inverse", {"generator": digit, "value": {"type": "int", "value": 12}}
            ),
            {"choices": None, "error": True},
        )

    def test_an_inverse_vector_states_a_shape_or_a_generator(self) -> None:
        """Both, or neither, names nothing to run backwards."""
        value = {"type": "int", "value": 1}
        both = {
            "shape": {"shape": "bool"},
            "generator": {"gen": "boolean"},
            "value": value,
        }
        for case in (both, {"value": value}):
            with self.assertRaisesRegex(VectorError, "a shape or a generator"):
                compute("inverse", case)

    def test_a_shape_that_does_not_read_raises(self) -> None:
        """The reader's failure, as a vector error."""
        with self.assertRaisesRegex(VectorError, "no shape"):
            compute("shapes", {"shape": {"shape": "widget"}, "seed": "1", "count": 1})

    def test_a_fixture_vector_computes_nothing(self) -> None:
        """A fixture states its shape, its name, its summary and what it covers."""
        fixture = {
            "fixture": "flag",
            "summary": "A record of one boolean field.",
            "covers": "bool",
            "shape": {"shape": "record", "fields": [["enabled", {"shape": "bool"}]]},
        }
        self.assertEqual(compute("fixtures", fixture), {})
        with self.assertRaisesRegex(VectorError, "states no summary"):
            compute("fixtures", {**fixture, "summary": " "})
        with self.assertRaisesRegex(VectorError, "which is no shape"):
            compute("fixtures", {**fixture, "shape": {"shape": "widget"}})

    def test_a_draws_vector_matches_runs_out_or_names_the_draw(self) -> None:
        """Each end: matched, ran out, a label that differs, a value out of bounds."""
        draws = [
            {"label": "count", "generator": {"gen": "integer", "min": 0, "max": 9}},
            {"label": "flag", "generator": {"gen": "boolean"}},
        ]
        four = {"label": "count", "value": {"type": "int", "value": 4}}
        matched = compute(
            "draws",
            {
                "draws": draws,
                "entries": [
                    four,
                    {"label": "flag", "value": {"type": "bool", "value": True}},
                ],
            },
        )
        self.assertEqual((matched["choices"], matched["error"]), ([4, 1], None))
        short = compute("draws", {"draws": draws, "entries": [four]})
        self.assertEqual(
            short["values"][1],
            {"label": "flag", "value": {"type": "bool", "value": False}},
        )
        mislabelled = compute(
            "draws", {"draws": draws, "entries": [{**four, "label": "flag"}]}
        )
        self.assertEqual(mislabelled["error"], {"label": "count", "reason": "label"})
        large = {"label": "count", "value": {"type": "int", "value": 12}}
        bounded = compute("draws", {"draws": draws, "entries": [large]})
        self.assertEqual(bounded["error"], {"label": "count", "reason": "value"})

    def test_a_form_vector_states_the_record_of_the_minimal_case(self) -> None:
        """The minimal input of true over -9 to 9 is -1, and 0 passes."""
        case = {
            "form": "prop-true",
            "subjects": ["is-non-negative"],
            "shape": {"shape": "int", "width": 8, "signed": True, "min": -9, "max": 9},
            "seed": "7",
        }
        detail = compute("forms", case)["detail"]
        self.assertEqual(detail["outcome"], "counterexample")
        self.assertEqual(detail["failure"], {"assertion": "true", "detail": {}})
        self.assertEqual(
            detail["counterexample"],
            [
                {
                    "label": "input",
                    "value": {"type": "int", "value": -1},
                    "any-value-fails": False,
                    "nearest-passing": {"type": "int", "value": 0},
                }
            ],
        )

    def test_a_passing_form_vector_states_no_failure(self) -> None:
        """Every input from 0 to 9 is non-negative."""
        case = {
            "form": "prop-true",
            "subjects": ["is-non-negative"],
            "shape": {"shape": "int", "width": 8, "signed": True, "min": 0, "max": 9},
            "seed": "7",
        }
        detail = compute("forms", case)["detail"]
        self.assertEqual((detail["outcome"], detail["cases"]), ("passed", 10))
        self.assertIsNone(detail["failure"])

    def test_a_form_vector_whose_run_depends_on_earlier_cases_raises(self) -> None:
        """A cell that one case sets to 1 is not changed by the next that sets 1."""
        case = {
            "id": "prop-pure/sets-a-bit",
            "form": "prop-pure",
            "subjects": ["sets-value"],
            "shape": {"shape": "int", "width": 8, "signed": False, "max": 1},
            "seed": "7",
        }
        with self.assertRaisesRegex(VectorError, "depends on what earlier cases leave"):
            compute("forms", case)

    def test_a_form_vector_that_names_no_form_raises(self) -> None:
        """The form's error, as a vector error."""
        case = {"form": "prop-invented", "shape": {"shape": "bool"}, "seed": "7"}
        with self.assertRaisesRegex(VectorError, "is no form of the definition"):
            compute("forms", case)

    def test_a_form_vector_over_a_map_fails_at_its_example_as_found(self) -> None:
        """-5 is no digit, and the run states it with no choices to replay."""
        case = {
            "form": "prop-true",
            "subjects": ["is-non-negative"],
            "generator": {"gen": "map", "of": DIGIT, "subject": "identity"},
            "examples": [{"type": "int", "value": -5}],
            "seed": "7",
        }
        detail = compute("forms", case)["detail"]
        self.assertEqual(
            (detail["outcome"], detail["cases"], detail["choices"], detail["others"]),
            ("counterexample", 0, None, []),
        )
        self.assertEqual(
            detail["counterexample"],
            [
                {
                    "label": "input",
                    "value": {"type": "int", "value": -5},
                    "any-value-fails": None,
                    "nearest-passing": None,
                }
            ],
        )

    def test_a_form_vector_states_one_of_a_shape_and_a_generator(self) -> None:
        """Both, and neither."""
        shape = {"shape": "int", "width": 8, "signed": True, "min": 0, "max": 9}
        base = {"form": "prop-true", "subjects": ["is-non-negative"], "seed": "7"}
        refusal = "states one of shape and generator"
        for case in ({**base, "shape": shape, "generator": DIGIT}, base):
            with (
                self.subTest(keys=sorted(case)),
                self.assertRaisesRegex(VectorError, refusal),
            ):
                compute("forms", case)

    def test_a_recording_vector_states_each_call_with_its_run_and_phase(self) -> None:
        """A failing token: one call of true, in the one call of the body."""
        body = {
            "draw": {"gen": "integer", "min": 0, "max": 9},
            "fails": [{"identity": "big", "when": {"kind": "at-least", "n": 5}}],
        }
        settings = {"seed": "7", "replay": "prop1:AAc"}
        got = compute("recording", {"body": body, "settings": settings})
        call = {"run": 1, "phase": "token", "verdict": "fail"}
        self.assertEqual(got, {"verdict": "fail", "calls": [call]})

    def test_a_recording_vector_numbers_each_call_of_the_body(self) -> None:
        """An example and a stored case pass, and the second stored case fails."""
        body = {
            "draw": {"gen": "integer", "min": 0, "max": 1000},
            "fails": [{"identity": "big", "when": {"kind": "at-least", "n": 900}}],
        }
        settings = {"seed": "7", "examples": [[5]], "stored": [[3], [950]], "shrink": 0}
        got = compute("recording", {"body": body, "settings": settings})
        self.assertEqual(
            got["calls"],
            [
                {"run": 1, "phase": "example", "verdict": "pass"},
                {"run": 2, "phase": "stored", "verdict": "pass"},
                {"run": 3, "phase": "stored", "verdict": "fail"},
            ],
        )

    def test_a_body_that_ends_before_true_makes_no_call(self) -> None:
        """Every case is rejected, so the run fails and true is never called."""
        body = {
            "draw": {"gen": "integer", "min": 0, "max": 9},
            "rejects-when": {"kind": "always"},
        }
        got = compute("recording", {"body": body, "settings": {"seed": "7"}})
        self.assertEqual(got, {"verdict": "fail", "calls": []})

    def test_an_unknown_kind_or_missing_input_raises(self) -> None:
        """No such kind; a decoding vector without choices."""
        with self.assertRaises(VectorError):
            compute("haiku", {})
        with self.assertRaises(VectorError):
            compute("decoding", {"generator": DIGITS})
