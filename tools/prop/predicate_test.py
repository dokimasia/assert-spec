"""Predicates as data: each kind of the vocabulary, its negation and its refusals."""

from __future__ import annotations

import unittest
from typing import Any, final

from .predicate import PredicateError, predicate
from .value import Pairs


def holds(spec: dict[str, Any], value: object) -> bool:
    """Report whether the predicate spec holds of value."""
    return predicate(spec)(value)


@final
class PredicateTest(unittest.TestCase):
    """Each predicate of the vocabulary, and its negation."""

    def test_each_predicate_holds_where_it_should(self) -> None:
        """One holding and one failing value per predicate."""
        cases: list[tuple[dict[str, Any], object, object]] = [
            ({"kind": "always"}, 0, None),
            ({"kind": "equals", "value": {"type": "bool", "value": True}}, True, 1),
            (
                {
                    "kind": "equals",
                    "value": {"type": "list", "of": "int", "value": [1]},
                },
                [1],
                [1.0],
            ),
            ({"kind": "at-least", "n": 5}, 5, 4),
            ({"kind": "at-least", "n": 2.5}, 3.0, 2.0),
            ({"kind": "divisible-by", "n": 3}, 9, 10),
            ({"kind": "sum-above", "n": 10}, [6, 5], [6, 4]),
            ({"kind": "length-at-least", "n": 2}, "ab", b"a"),
            ({"kind": "length-at-least", "n": 1}, Pairs(((1, 2),)), []),
            ({"kind": "contains", "value": {"type": "int", "value": 3}}, [1, 3], [1]),
            (
                {"kind": "contains", "value": {"type": "string", "value": "ab"}},
                "cab",
                "ba",
            ),
            (
                {"kind": "contains", "value": {"type": "bytes", "value": "01"}},
                b"\x00\x01",
                b"",
            ),
            ({"kind": "not-sorted"}, [2, 1], [1, 2]),
            ({"kind": "has-duplicate"}, [1, 1], [1, 2]),
            ({"kind": "indexed-above", "n": 100}, [0, 200, 1], [0, 200, 0]),
            ({"kind": "indexed-above", "n": 100}, [200, 0], [100, 0]),
        ]
        for spec, yes, no in cases:
            self.assertTrue(holds(spec, yes), (spec, yes))
            if no is not None:
                self.assertFalse(holds(spec, no), (spec, no))

    def test_never_holds_for_nothing(self) -> None:
        """Whatever the value."""
        self.assertFalse(holds({"kind": "never"}, [1]))

    def test_not_negates_a_predicate(self) -> None:
        """An odd number is not divisible by 2."""
        odd = {"kind": "divisible-by", "n": 2, "not": True}
        self.assertTrue(holds(odd, 3))
        self.assertFalse(holds(odd, 4))

    def test_a_bool_is_not_a_number(self) -> None:
        """True is not at least 1."""
        self.assertFalse(holds({"kind": "at-least", "n": 1}, True))

    def test_equal_neighbours_are_sorted(self) -> None:
        """[1, 1] is in ascending order."""
        self.assertFalse(holds({"kind": "not-sorted"}, [1, 1]))

    def test_indexed_above_holds_only_inside_the_earlier_elements(self) -> None:
        """An index past them, a negative index or an empty list holds for nothing."""
        above = {"kind": "indexed-above", "n": 100}
        for value in ([200, 1], [200, -1], [], [200]):
            self.assertFalse(holds(above, value), value)

    def test_indexed_above_reads_no_bool_as_an_index_or_an_element(self) -> None:
        """False is no index 0, and True at the index is no number above 0."""
        above_zero = {"kind": "indexed-above", "n": 0}
        self.assertFalse(holds(above_zero, [5, False]))
        self.assertFalse(holds(above_zero, [True, 0]))

    def test_contains_compares_as_uniqueness_does(self) -> None:
        """True is no element equal to the int 1."""
        one = {"kind": "contains", "value": {"type": "int", "value": 1}}
        self.assertFalse(holds(one, [True]))

    def test_an_unknown_or_incomplete_predicate_raises(self) -> None:
        """No kind, an unknown kind, or a missing n."""
        for spec in ([1], {"kind": "odd"}, {"kind": "at-least"}):
            with self.assertRaises(PredicateError, msg=str(spec)):
                predicate(spec)
