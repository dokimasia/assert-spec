"""Decoded values: the equality uniqueness is decided by."""

from __future__ import annotations

import math
import unittest
from typing import final

from .value import Pairs, canonical


@final
class CanonicalTest(unittest.TestCase):
    """canonical(): equal forms exactly for equal values."""

    def test_signed_zeros_differ_and_every_nan_is_one(self) -> None:
        """Floats compare by their bits, with one NaN."""
        self.assertNotEqual(canonical(0.0), canonical(-0.0))
        self.assertEqual(canonical(math.nan), canonical(-math.nan))

    def test_a_bool_differs_from_the_equal_int(self) -> None:
        """True is not 1, and None is not 0."""
        self.assertNotEqual(canonical(True), canonical(1))
        self.assertNotEqual(canonical(None), canonical(0))

    def test_containers_compare_element_by_element(self) -> None:
        """Lists, dicts, strings and bytes."""
        self.assertEqual(canonical([1, [0.0]]), canonical([1, [0.0]]))
        self.assertNotEqual(canonical([1, [0.0]]), canonical([1, [-0.0]]))
        self.assertEqual(canonical(Pairs(((1, "a"),))), canonical(Pairs(((1, "a"),))))
        self.assertNotEqual(
            canonical(Pairs(((True, "a"),))), canonical(Pairs(((1, "a"),)))
        )
        self.assertNotEqual(canonical("a"), canonical(b"a"))

    def test_a_dict_equals_one_with_its_entries_in_another_order(self) -> None:
        """Equality of maps ignores the order the entries were generated in."""
        self.assertEqual(
            canonical(Pairs(((1, "a"), (2, "b")))),
            canonical(Pairs(((2, "b"), (1, "a")))),
        )
        self.assertNotEqual(
            canonical(Pairs(((1, "a"), (2, "b")))),
            canonical(Pairs(((1, "a"), (2, "c")))),
        )

    def test_a_value_no_generator_decodes_raises(self) -> None:
        """A tuple, a set or an object."""
        for value in ((1,), {1}, object()):
            with self.assertRaises(TypeError):
                canonical(value)
