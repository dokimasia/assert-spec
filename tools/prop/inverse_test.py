"""Running generators backwards: a generated value's choices replay to that value."""

from __future__ import annotations

import unittest
from typing import Any, final

from .case import Case, Generating, Rejected, Replaying
from .choice import Choice
from .generator import build
from .generator_test import DIGIT, EVERY
from .inverse import CannotInvert, NoInverse, invert, no_draw
from .shape import BUDGET, read
from .shape_test import TREE, UINT8
from .source import case_source
from .value import Pairs, Record, Variant, canonical
from .zone import zones

#: Cases per generator in the round-trip check.
CASES = 60

#: A map of a digit, which returns the digit and has no inverse.
IDENTITY: dict[str, Any] = {"gen": "map", "of": DIGIT, "subject": "identity"}

#: One shape of each id, for the round trip.
SHAPES: dict[str, dict[str, Any]] = {
    "bool": {"shape": "bool"},
    "int": {"shape": "int", "width": 16, "signed": True},
    "int-128": {"shape": "int", "width": 128, "signed": True},
    "float": {"shape": "float", "width": 32, "allow_nan": True},
    "char": {"shape": "char"},
    "string": {"shape": "string", "max_size": 6},
    "pattern": {"shape": "string", "pattern": "[a-c]{2,4}(x|yz)?"},
    "bytes": {"shape": "bytes", "max_size": 4},
    "list": {"shape": "list", "of": UINT8, "max_size": 4},
    "fixed-list": {"shape": "fixed-list", "of": UINT8, "size": 3},
    "set": {"shape": "set", "of": {"shape": "int", "width": 8, "signed": True}},
    "map": {"shape": "map", "key": UINT8, "of": {"shape": "bool"}},
    "optional": {"shape": "optional", "of": UINT8},
    "record": {"shape": "record", "fields": [["id", UINT8], ["ok", {"shape": "bool"}]]},
    "enum": {"shape": "enum", "variants": [["none", None], ["some", UINT8]]},
    "literal": {
        "shape": "literal",
        "values": [{"type": "string", "value": v} for v in ("a", "b", "a")],
    },
    "ref": TREE,
    "uuid": {"shape": "uuid"},
    "ip-address": {"shape": "ip-address"},
    "decimal": {"shape": "decimal", "scale": 2, "min": "-5.00", "max": "5.00"},
    "instant": {"shape": "instant", "unit": "ms", "min": "2020-01-01T00:00:00.5Z"},
    "date": {"shape": "date"},
    "time-of-day": {"shape": "time-of-day", "unit": "us"},
    "local-date-time": {"shape": "local-date-time", "unit": "s"},
    "duration": {"shape": "duration", "unit": "ns"},
    "offset": {"shape": "offset"},
    "zone": {"shape": "zone"},
    "zoned-date-time": {"shape": "zoned-date-time", "unit": "ns"},
    "wall-time": {"shape": "wall-time", "unit": "ms"},
}


def _replayed(generator: Any, choices: tuple[Choice, ...]) -> object:
    """Return the value that choices decode to."""
    return generator.decode(Case(Replaying(list(choices))))


def _elements(value: object) -> frozenset[object]:
    """Return a set's elements, in no order."""
    assert isinstance(value, list)
    return frozenset(canonical(element) for element in value)


@final
class RoundTripTest(unittest.TestCase):
    """Every generated value runs backwards to choices that decode to it."""

    def check(self, name: str, generator: Any, *, unordered: bool = False) -> None:
        """Generate values from one seed, and replay each one's inverse."""
        inverted = 0
        for index in range(CASES):
            case = Case(Generating(case_source(17, index)))
            try:
                value = generator.decode(case)
            except Rejected:
                continue
            replayed = _replayed(generator, invert(generator, value))
            if unordered:
                self.assertEqual(_elements(replayed), _elements(value), name)
            else:
                self.assertEqual(canonical(replayed), canonical(value), name)
            inverted += 1
        self.assertGreater(inverted, CASES // 2, name)

    def test_every_generator_but_map_runs_backwards(self) -> None:
        """The vocabulary, with a filter through its source. map has no inverse."""
        for name, spec in EVERY.items():
            if spec["gen"] == "map":
                continue
            with self.subTest(generator=name):
                self.check(name, build(spec))

    def test_every_shape_runs_backwards(self) -> None:
        """A set comes back with its elements in shortlex order."""
        for name, shape in SHAPES.items():
            with self.subTest(shape=name):
                self.check(name, read(shape), unordered=name == "set")


@final
class OrderTest(unittest.TestCase):
    """The first sequence of choices, where more than one decodes to a value."""

    def test_one_of_takes_its_first_alternative_that_produces_the_value(self) -> None:
        """7 is in both ranges, so the first."""
        spec = {
            "gen": "one-of",
            "of": [
                {"gen": "integer", "min": 0, "max": 9},
                {"gen": "integer", "min": 5, "max": 15},
            ],
        }
        self.assertEqual(
            invert(build(spec), 7), (Choice("integer", 0), Choice("integer", 7))
        )
        self.assertEqual(
            invert(build(spec), 12), (Choice("integer", 1), Choice("integer", 12))
        )

    def test_sampled_from_takes_the_first_equal_value(self) -> None:
        """The value a is at 0 and at 2."""
        values = [{"type": "string", "value": v} for v in ("a", "b", "a")]
        generator = build({"gen": "sampled-from", "values": values})
        self.assertEqual(invert(generator, "a"), (Choice("integer", 0),))

    def test_a_permutation_takes_the_smallest_index_at_each_swap(self) -> None:
        """Two equal values: the first one stays where it is."""
        values = [{"type": "int", "value": v} for v in (1, 1, 2)]
        generator = build({"gen": "permutation", "values": values})
        self.assertEqual(
            invert(generator, [1, 2, 1]), (Choice("integer", 0), Choice("integer", 2))
        )

    def test_a_pattern_takes_the_greedy_match(self) -> None:
        """The first a* takes both a's, and the second none."""
        generator = build({"gen": "string-matching", "pattern": "a*a*"})
        self.assertEqual(
            [choice.value for choice in invert(generator, "aa")], [1, 1, 0, 0]
        )

    def test_a_pattern_takes_its_first_alternative_that_matches(self) -> None:
        """Both alternatives match x, so the first."""
        generator = build({"gen": "string-matching", "pattern": "x|x"})
        self.assertEqual([choice.value for choice in invert(generator, "x")], [0])

    def test_a_pattern_backtracks_when_the_rest_does_not_match(self) -> None:
        """a* gives back one a, so that ab can match after it."""
        generator = build({"gen": "string-matching", "pattern": "a*ab"})
        self.assertEqual([choice.value for choice in invert(generator, "aab")], [1, 0])

    def test_a_pattern_tries_the_next_alternative_after_a_short_match(self) -> None:
        """The alternative a ends before the string does, so ab follows."""
        generator = build({"gen": "string-matching", "pattern": "a|ab"})
        self.assertEqual([choice.value for choice in invert(generator, "ab")], [1])

    def test_a_sequence_resumes_its_search_after_a_short_match(self) -> None:
        """(a|ab)c* first matches a and no c, which ends short of the b."""
        generator = build({"gen": "string-matching", "pattern": "(a|ab)c*"})
        self.assertEqual([choice.value for choice in invert(generator, "ab")], [1, 0])

    def test_a_repetition_that_matches_nothing_is_not_repeated(self) -> None:
        """(a?)* takes the a once, then stops instead of repeating an empty match."""
        generator = build({"gen": "string-matching", "pattern": "(a?)*"})
        self.assertEqual(
            [choice.value for choice in invert(generator, "a")], [1, 1, 0, 0]
        )

    def test_an_absent_optional_of_an_optional_is_absent_outside(self) -> None:
        """Absent before present."""
        inner = {"gen": "optional", "of": {"gen": "integer", "min": 0, "max": 9}}
        generator = build({"gen": "optional", "of": inner})
        self.assertEqual(invert(generator, None), (Choice("integer", 0),))

    def test_a_set_takes_its_elements_in_shortlex_order(self) -> None:
        """2 is simpler than 5, so it comes first."""
        generator = read({"shape": "set", "of": UINT8})
        self.assertEqual(
            [choice.value for choice in invert(generator, [5, 2])], [1, 2, 1, 5, 0]
        )

    def test_a_map_takes_its_entries_in_shortlex_order(self) -> None:
        """The entry of key 1 comes before the entry of key 4."""
        generator = read({"shape": "map", "key": UINT8, "of": UINT8})
        choices = invert(generator, Pairs(((4, 0), (1, 9))))
        self.assertEqual([choice.value for choice in choices], [1, 1, 9, 1, 4, 0, 0])

    def test_an_instant_at_a_change_takes_the_whole_range(self) -> None:
        """A value at Amsterdam's first change is the zone, 0, then the instant."""
        change = zones()[1].changes[0]
        value = Record(
            (
                ("instant", Record((("seconds", change.at), ("units", 0)))),
                ("zone", "Europe/Amsterdam"),
            )
        )
        choices = invert(read({"shape": "zoned-date-time", "unit": "s"}), value)
        self.assertEqual([c.value for c in choices], [1, 0, change.at])

    def test_a_recursive_value_takes_the_base_first(self) -> None:
        """An empty list is both a base and an extension, so the base."""
        spec = {
            "gen": "recursive",
            "base": {"gen": "list", "of": {"gen": "integer", "min": 0, "max": 9}},
            "extend": {"gen": "list", "of": {"gen": "self"}, "max_size": 3},
        }
        self.assertEqual(
            invert(build(spec), []), (Choice("integer", 0), Choice("integer", 0))
        )


@final
class CannotInvertTest(unittest.TestCase):
    """A value the generator cannot produce from any choices."""

    def test_each_value_that_no_choices_produce_raises(self) -> None:
        """A wrong type, a value out of bounds, and each structural mismatch."""
        digit = {"gen": "integer", "min": 0, "max": 9}
        one = [{"type": "int", "value": 1}]
        even = {"gen": "filter", "of": digit, "keep": {"kind": "divisible-by", "n": 2}}
        instant = read({"shape": "instant", "unit": "s"})
        bare = read({"shape": "enum", "variants": [["a", None]]})
        wide = read({"shape": "int", "width": 128, "signed": False})
        table = build({"gen": "dict", "keys": digit, "values": digit})
        faults: list[tuple[Any, object, str]] = [
            (build(digit), 10, "is outside"),
            (build(digit), True, "is outside"),
            (build({"gen": "boolean"}), 1, "is not a boolean"),
            (build({"gen": "just", "value": {"type": "int", "value": 4}}), 5, "not 4"),
            (build({"gen": "list", "of": digit, "max_size": 1}), [1, 2], "sizes"),
            (build({"gen": "list", "of": digit, "unique": True}), [1, 1], "repeats"),
            (build({"gen": "list", "of": digit}), (1,), "is not a list"),
            (table, {1: 2}, "is not a map"),
            (table, Pairs(((1, 2), (1, 3))), "repeats a value"),
            (build({"gen": "string", "alphabet": "ab"}), "c", "outside the alphabet"),
            (build({"gen": "string"}), b"x", "is not a string"),
            (build({"gen": "bytes", "max_size": 1}), b"xy", "is outside"),
            (build({"gen": "bytes"}), "x", "is not bytes"),
            (build({"gen": "string-matching", "pattern": "a+"}), "b", "not match"),
            (build({"gen": "string-matching", "pattern": "a+"}), 1, "not a string"),
            (build({"gen": "one-of", "of": [digit]}), 11, "no alternative produces"),
            (build(even), 3, "the filter rejects 3"),
            (build({"gen": "permutation", "values": one}), [2], "not a permutation"),
            (build({"gen": "permutation", "values": one}), [1, 1], "not a permutation"),
            (
                read({"shape": "record", "fields": [["id", UINT8]]}),
                Record((("x", 1),)),
                "is not a record of",
            ),
            (bare, Variant("b"), "is no variant of"),
            (bare, Variant("a", 1), "has no payload"),
            (bare, "a", "is no variant of"),
            (instant, Record((("seconds", 0), ("units", 1))), "has no units"),
            (instant, 0, "is not a record of"),
            (read({"shape": "ip-address"}), b"\x00" * 5, "neither 4 nor 16"),
            (read({"shape": "ip-address"}), "127.0.0.1", "is not an address"),
            (read({"shape": "zone"}), "Mars/Olympus", "none of the values"),
            (wide, -1, "is outside"),
            (wide, 1.5, "is not an integer"),
        ]
        for generator, value, message in faults:
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(CannotInvert, message),
            ):
                invert(generator, value)

    def test_one_of_passes_over_an_alternative_that_cannot_produce_the_value(
        self,
    ) -> None:
        """A list too long, a list with a repeat, and a value a filter rejects."""
        digit = {"gen": "integer", "min": 0, "max": 9}
        even = {"gen": "filter", "of": digit, "keep": {"kind": "divisible-by", "n": 2}}
        cases: list[tuple[list[Any], object]] = [
            (
                [
                    {"gen": "list", "of": digit, "max_size": 1},
                    {"gen": "list", "of": digit, "max_size": 3},
                ],
                [1, 2],
            ),
            (
                [
                    {"gen": "list", "of": digit, "unique": True},
                    {"gen": "list", "of": digit},
                ],
                [1, 1],
            ),
            ([even, digit], 3),
        ]
        for alternatives, value in cases:
            with self.subTest(value=value):
                choices = invert(build({"gen": "one-of", "of": alternatives}), value)
                self.assertEqual(choices[0], Choice("integer", 1))

    def test_a_value_beyond_its_budget_raises(self) -> None:
        """A chain of more nodes than the budget allows."""
        value: object = Record((("value", 0), ("children", [])))
        for _ in range(BUDGET):
            value = Record((("value", 0), ("children", [value])))
        with self.assertRaises(CannotInvert):
            invert(read(TREE), value)

    def test_a_value_of_more_choices_than_a_case_may_make_raises(self) -> None:
        """9,000 digits take more than 8,192 choices to state."""
        generator = build({"gen": "list", "of": {"gen": "integer", "min": 0, "max": 9}})
        with self.assertRaisesRegex(CannotInvert, "decodes to no value"):
            invert(generator, [0] * 9000)

    def test_a_recursive_value_that_neither_branch_produces_raises(self) -> None:
        """A string is neither a digit nor a list."""
        spec = {
            "gen": "recursive",
            "base": {"gen": "integer", "min": 0, "max": 9},
            "extend": {"gen": "list", "of": {"gen": "self"}, "max_size": 3},
        }
        with self.assertRaisesRegex(CannotInvert, "neither the base nor the extension"):
            invert(build(spec), "x")

    def test_a_step_never_draws(self) -> None:
        """An inverse's request is read for its bounds, and drawing from it fails."""
        with self.assertRaises(AssertionError):
            no_draw(None)


@final
class NoInverseTest(unittest.TestCase):
    """A generator that applies a function, which the engine cannot run backwards."""

    def test_map_and_a_generator_without_an_emitter_have_no_inverse(self) -> None:
        """map, and a language's generator that applies a function."""

        class Mapped:
            def decode(self, case: Case) -> object:
                del case
                return 0

        with self.assertRaisesRegex(NoInverse, "Mapped does not run backwards"):
            invert(Mapped(), 0)
        with self.assertRaisesRegex(NoInverse, "Map does not run backwards"):
            invert(build(EVERY["map"]), [1, 2])

    def test_a_generator_around_one_without_an_inverse_has_none(self) -> None:
        """A list, an optional and a filter pass on the refusal inside them."""
        mapped = EVERY["map"]
        keep = {"kind": "length-at-least", "n": 1}
        for spec in (
            {"gen": "list", "of": mapped},
            {"gen": "optional", "of": mapped},
            {"gen": "filter", "of": mapped, "keep": keep},
        ):
            with self.subTest(gen=spec["gen"]), self.assertRaises(NoInverse):
                invert(build(spec), [[1]] if spec["gen"] == "list" else [1])

    def test_one_of_runs_back_through_an_alternative_with_an_inverse(self) -> None:
        """The map has none, so the digit after it produces 3."""
        spec = {"gen": "one-of", "of": [IDENTITY, DIGIT]}
        self.assertEqual(
            invert(build(spec), 3), (Choice("integer", 1), Choice("integer", 3))
        )

    def test_one_of_and_recursive_have_no_inverse_where_a_branch_has_none(
        self,
    ) -> None:
        """No branch produces the value, and the map might."""
        one_of = build({"gen": "one-of", "of": [DIGIT, IDENTITY]})
        with self.assertRaisesRegex(NoInverse, "and one of them has no inverse"):
            invert(one_of, 11)
        tree = build(
            {
                "gen": "recursive",
                "base": IDENTITY,
                "extend": {"gen": "list", "of": {"gen": "self"}, "max_size": 3},
            }
        )
        with self.assertRaisesRegex(NoInverse, "neither the base nor the extension"):
            invert(tree, "x")

    def test_a_value_outside_every_invertible_branch_is_outside_the_domain(
        self,
    ) -> None:
        """Every alternative has an inverse, so 11 is no value of the one-of."""
        with self.assertRaises(CannotInvert) as raised:
            invert(build({"gen": "one-of", "of": [DIGIT]}), 11)
        self.assertNotIsInstance(raised.exception, NoInverse)
