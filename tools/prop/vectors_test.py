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

DIGITS: dict[str, Any] = {
    "gen": "list",
    "of": {"gen": "integer", "min": 0, "max": 9},
    "max_size": 3,
}


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

    def test_an_unknown_kind_or_missing_input_raises(self) -> None:
        """No such kind; a decoding vector without choices."""
        with self.assertRaises(VectorError):
            compute("haiku", {})
        with self.assertRaises(VectorError):
            compute("decoding", {"generator": DIGITS})
