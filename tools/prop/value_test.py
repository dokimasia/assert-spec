"""Decoded values: the equality uniqueness is decided by."""

from __future__ import annotations

import math
import unittest
from typing import final

from .value import NO_PAYLOAD, Pairs, Record, Variant, canonical


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

    def test_a_record_compares_by_its_fields_in_order(self) -> None:
        """Field order is part of a record."""
        self.assertEqual(
            canonical(Record((("a", 1), ("b", 0.0)))),
            canonical(Record((("a", 1), ("b", 0.0)))),
        )
        self.assertNotEqual(
            canonical(Record((("a", 1), ("b", 2)))),
            canonical(Record((("b", 2), ("a", 1)))),
        )
        self.assertNotEqual(
            canonical(Record((("a", 0.0),))), canonical(Record((("a", -0.0),)))
        )

    def test_a_variant_compares_by_its_name_and_its_payload(self) -> None:
        """No payload, a null payload and another name are three values."""
        self.assertEqual(canonical(Variant("x", [1])), canonical(Variant("x", [1])))
        self.assertNotEqual(canonical(Variant("x")), canonical(Variant("x", None)))
        self.assertNotEqual(canonical(Variant("x")), canonical(Variant("y")))
        self.assertNotEqual(canonical(Variant("x", 1)), canonical(Variant("x", 2)))

    def test_the_missing_payload_names_itself(self) -> None:
        """A variant without a payload reads as such in a failure message."""
        self.assertEqual(repr(Variant("x")), "Variant(name='x', payload=NO_PAYLOAD)")
        self.assertEqual(repr(NO_PAYLOAD), "NO_PAYLOAD")

    def test_a_value_no_generator_decodes_raises(self) -> None:
        """A tuple, a set or an object."""
        for value in ((1,), {1}, object()):
            with self.assertRaises(TypeError):
                canonical(value)
