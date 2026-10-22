# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""Decoded values: the equality uniqueness is decided by."""

from __future__ import annotations

import math
import unittest
from typing import final

import pytest

from .value import NO_PAYLOAD, Pairs, Record, Variant, as_type, canonical


@final
class AsTypeTest(unittest.TestCase):
    """as_type(): a decoded value of the type its caller states."""

    def test_a_value_of_the_type_is_returned(self) -> None:
        """The same object, and a subclass of the type too."""
        drawn = [1, 2]
        assert as_type(drawn, list) is drawn
        assert as_type(value=True, kind=int) is True

    def test_a_value_of_another_type_raises(self) -> None:
        """The error states the value and the type."""
        with pytest.raises(TypeError, match=r"^prop: 1\.5 is not of the type int$"):
            as_type(1.5, int)


@final
class CanonicalTest(unittest.TestCase):
    """canonical(): equal forms exactly for equal values."""

    def test_signed_zeros_differ_and_every_nan_is_one(self) -> None:
        """Floats compare by their bits, with one NaN."""
        assert canonical(0.0) != canonical(-0.0)
        assert canonical(math.nan) == canonical(-math.nan)

    def test_a_bool_differs_from_the_equal_int(self) -> None:
        """True is not 1, and None is not 0."""
        assert canonical(value=True) != canonical(1)
        assert canonical(None) != canonical(0)

    def test_containers_compare_element_by_element(self) -> None:
        """Lists, dicts, strings and bytes."""
        assert canonical([1, [0.0]]) == canonical([1, [0.0]])
        assert canonical([1, [0.0]]) != canonical([1, [-0.0]])
        assert canonical(Pairs(((1, "a"),))) == canonical(Pairs(((1, "a"),)))
        assert canonical(Pairs(((True, "a"),))) != canonical(Pairs(((1, "a"),)))
        assert canonical("a") != canonical(b"a")

    def test_a_dict_equals_one_with_its_entries_in_another_order(self) -> None:
        """Equality of maps ignores the order the entries were generated in."""
        assert canonical(Pairs(((1, "a"), (2, "b")))) == canonical(
            Pairs(((2, "b"), (1, "a")))
        )
        assert canonical(Pairs(((1, "a"), (2, "b")))) != canonical(
            Pairs(((1, "a"), (2, "c")))
        )

    def test_a_record_compares_by_its_fields_in_order(self) -> None:
        """Field order is part of a record."""
        assert canonical(Record((("a", 1), ("b", 0.0)))) == canonical(
            Record((("a", 1), ("b", 0.0)))
        )
        assert canonical(Record((("a", 1), ("b", 2)))) != canonical(
            Record((("b", 2), ("a", 1)))
        )
        assert canonical(Record((("a", 0.0),))) != canonical(Record((("a", -0.0),)))

    def test_a_variant_compares_by_its_name_and_its_payload(self) -> None:
        """No payload, a null payload and another name are three values."""
        assert canonical(Variant("x", [1])) == canonical(Variant("x", [1]))
        assert canonical(Variant("x")) != canonical(Variant("x", None))
        assert canonical(Variant("x")) != canonical(Variant("y"))
        assert canonical(Variant("x", 1)) != canonical(Variant("x", 2))

    def test_the_missing_payload_names_itself(self) -> None:
        """A variant without a payload reads as such in a failure message."""
        assert repr(Variant("x")) == "Variant(name='x', payload=NO_PAYLOAD)"
        assert repr(NO_PAYLOAD) == "NO_PAYLOAD"

    def test_a_value_no_generator_decodes_raises(self) -> None:
        """A tuple, a set or an object."""
        for value in ((1,), {1}, object()):
            with pytest.raises(TypeError):
                canonical(value)
