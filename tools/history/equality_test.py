"""The standard's equality, and the key that agrees with it."""

from __future__ import annotations

import math
import unittest
from typing import final

from prop.value import Pairs, Record, Variant

from .equality import equal, key

#: Pairs of values that the standard's equality relates, with its verdict.
CASES: list[tuple[str, object, object, bool]] = [
    ("equal ints", 1, 1, True),
    ("an int and a float of one value", 1, 1.0, False),
    ("a bool and an int of one value", True, 1, False),
    ("negative and positive zero", -0.0, 0.0, True),
    ("null and an empty list", None, [], False),
    ("lists of equal items", [1, "a"], [1, "a"], True),
    ("lists of other lengths", [1], [1, 1], False),
    ("lists in another order", [1, 2], [2, 1], False),
    ("strings", "a", "b", False),
    ("bytes", b"a", b"a", True),
    (
        "maps in another order",
        Pairs(((1, "a"), (2, "b"))),
        Pairs(((2, "b"), (1, "a"))),
        True,
    ),
    ("maps with another value", Pairs(((1, "a"),)), Pairs(((1, "b"),)), False),
    ("maps of other sizes", Pairs(((1, "a"),)), Pairs(()), False),
    ("records", Record((("a", 1), ("b", 2))), Record((("a", 1), ("b", 2))), True),
    (
        "records in another order",
        Record((("a", 1), ("b", 2))),
        Record((("b", 2), ("a", 1))),
        False,
    ),
    ("records with another value", Record((("a", 1),)), Record((("a", 2),)), False),
    ("records with other names", Record((("a", 1),)), Record((("b", 1),)), False),
    ("variants without a payload", Variant("none"), Variant("none"), True),
    ("variants with a payload", Variant("some", 1), Variant("some", 1), True),
    ("variants with another payload", Variant("some", 1), Variant("some", 2), False),
    ("variants with other names", Variant("a"), Variant("b"), False),
    ("no payload and a null payload", Variant("some"), Variant("some", None), False),
]


@final
class EqualTest(unittest.TestCase):
    """equal(): structural, without coercion, with floats compared by value."""

    def test_relates_each_pair_as_the_standard_does(self) -> None:
        """Every case has the standard's verdict, in both orders."""
        for name, a, b, want in CASES:
            with self.subTest(name):
                self.assertIs(equal(a, b), want)
                self.assertIs(equal(b, a), want)

    def test_a_nan_equals_nothing(self) -> None:
        """A NaN is unequal to itself, alone and inside a list."""
        nan = math.nan
        self.assertFalse(equal(nan, nan))
        self.assertFalse(equal([nan], [nan]))

    def test_refuses_a_value_that_no_literal_decodes_to(self) -> None:
        """A dict, a tuple or an object is no decoded value."""
        for value in ({}, (1,), object()):
            with self.subTest(type(value).__name__):
                with self.assertRaises(TypeError):
                    equal(value, value)
                with self.assertRaises(TypeError):
                    equal(value, 1)


@final
class KeyTest(unittest.TestCase):
    """key(): two equal values share a key."""

    def test_equal_values_share_a_key(self) -> None:
        """Every equal pair of the cases has one key."""
        for name, a, b, want in CASES:
            if want:
                with self.subTest(name):
                    self.assertEqual(key(a), key(b))

    def test_values_of_other_types_have_other_keys(self) -> None:
        """A bool, an int and a float of one value have three keys."""
        self.assertEqual(len({key(True), key(1), key(1.0)}), 3)

    def test_refuses_a_value_that_no_literal_decodes_to(self) -> None:
        """A dict has no key."""
        with self.assertRaises(TypeError):
            key({})
