"""The choice kinds: their bounds, targets, sort keys and replay rules."""

from __future__ import annotations

import math
import unittest
from typing import final

from .choice import (
    GROUP_FRACTION,
    GROUP_INTEGRAL,
    INT64_MAX,
    INT64_MIN,
    NAN_BITS,
    UINT64_MAX,
    WIDTH_32,
    WIDTH_64,
    Choice,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    bits_of,
    float_key,
    from_bits32,
    next_down,
    next_up,
    same_float,
    simplest_float,
)

#: The largest finite binary32 value and the smallest positive one.
MAX_FLOAT32 = from_bits32(0x7F7FFFFF)
MIN_FLOAT32 = from_bits32(1)

#: The smallest positive binary64 subnormal.
MIN_FLOAT64 = 5e-324


@final
class IntegerBoundsTest(unittest.TestCase):
    """Integer bounds: inclusive, one of the two 64-bit ranges."""

    def test_the_target_is_the_value_closest_to_zero(self) -> None:
        """Zero when the bounds admit it, otherwise the bound nearer zero."""
        cases = {(-5, 5): 0, (0, 9): 0, (3, 9): 3, (-9, -3): -3, (7, 7): 7}
        for (lo, hi), target in cases.items():
            self.assertEqual(IntegerBounds(lo, hi).target, target, f"[{lo}, {hi}]")

    def test_the_key_orders_by_distance_then_above_before_below(self) -> None:
        """Around a target of zero: 0, 1, -1, 2, -2."""
        bounds = IntegerBounds(-2, 2)
        self.assertEqual(sorted(range(-2, 3), key=bounds.key), [0, 1, -1, 2, -2])

    def test_rank_numbers_the_values_in_key_order(self) -> None:
        """rank() and at_rank() are inverse, and follow key() over every value."""
        for lo, hi in ((-5, 10), (-10, 5), (3, 9), (-9, -3), (-4, 4), (7, 7), (-1, 0)):
            bounds = IntegerBounds(lo, hi)
            ordered = sorted(range(lo, hi + 1), key=bounds.key)
            ranks = range(hi - lo + 1)
            self.assertEqual([bounds.at_rank(r) for r in ranks], ordered)
            self.assertEqual([bounds.rank(v) for v in ordered], list(ranks))

    def test_rank_continues_on_the_longer_side(self) -> None:
        """In [-2, 9], after -2 come 3, 4 and 5, one per rank."""
        bounds = IntegerBounds(-2, 9)
        self.assertEqual([bounds.at_rank(r) for r in range(4, 8)], [-2, 3, 4, 5])

    def test_rank_reaches_the_ends_of_the_unsigned_range(self) -> None:
        """The largest unsigned value is the last of its bounds."""
        bounds = IntegerBounds(0, UINT64_MAX)
        self.assertEqual(bounds.rank(UINT64_MAX), UINT64_MAX)
        self.assertEqual(bounds.at_rank(UINT64_MAX), UINT64_MAX)

    def test_both_64_bit_ranges_are_accepted(self) -> None:
        """The whole signed range and the whole unsigned range are bounds."""
        IntegerBounds(INT64_MIN, INT64_MAX)
        IntegerBounds(0, UINT64_MAX)

    def test_empty_or_straddling_bounds_are_refused(self) -> None:
        """An empty range, or a span inside neither 64-bit range."""
        for lo, hi in ((5, 4), (-1, UINT64_MAX), (INT64_MIN - 1, 0)):
            with self.assertRaises(ValueError):
                IntegerBounds(lo, hi)

    def test_a_recorded_value_inside_the_bounds_replays(self) -> None:
        """A fitting integer comes back unchanged."""
        self.assertEqual(IntegerBounds(0, 9).coerce(Choice("integer", 4)), 4)

    def test_a_recorded_value_that_does_not_fit_becomes_the_target(self) -> None:
        """Out of bounds, another kind, or a bool all replay as the target."""
        bounds = IntegerBounds(3, 9)
        for recorded in (
            Choice("integer", 10),
            Choice("float", 4.0),
            Choice("sequence", (4,)),
            Choice("integer", True),
        ):
            self.assertEqual(bounds.coerce(recorded), 3, recorded)


@final
class FloatBoundsTest(unittest.TestCase):
    """Float bounds: an inclusive range, NaN on request, and a width."""

    def test_the_target_is_the_simplest_value_in_range(self) -> None:
        """The value with the smallest sort key, per range and width."""
        cases = [
            ((-1.0, 1.0, WIDTH_64), 0.0),
            ((2.5, 7.0, WIDTH_64), 3.0),
            ((-7.0, -2.5, WIDTH_64), -3.0),
            ((0.1, 0.9, WIDTH_64), 0.5),
            ((0.6, 0.7, WIDTH_64), 0.625),
            ((0.5625, 0.6875, WIDTH_32), 0.625),
            ((float(2**53 + 2), float(2**60), WIDTH_64), float(2**53 + 2)),
            ((1e300, math.inf, WIDTH_64), 1e300),
            ((math.inf, math.inf, WIDTH_64), math.inf),
            ((-math.inf, -math.inf, WIDTH_64), -math.inf),
        ]
        for (lo, hi, width), target in cases:
            got = FloatBounds(lo, hi, width=width).target
            self.assertTrue(same_float(got, target), f"[{lo}, {hi}]: {got}")

    def test_a_range_with_no_value_of_the_width_is_refused(self) -> None:
        """No binary32 value lies between 2^30 + 0.25 and 2^30 + 0.75."""
        with self.assertRaises(ValueError):
            simplest_float(2.0**30 + 0.25, 2.0**30 + 0.75, WIDTH_32)

    def test_malformed_bounds_are_refused(self) -> None:
        """A bad width, a NaN bound, an empty range, or a bound off its width."""
        for lo, hi, width in (
            (0.0, 1.0, 16),
            (math.nan, 1.0, WIDTH_64),
            (1.0, 0.0, WIDTH_64),
            (0.1, 1.0, WIDTH_32),
        ):
            with self.assertRaises(ValueError):
                FloatBounds(lo, hi, width=width)

    def test_the_key_orders_integral_then_fractional_then_infinite_then_nan(
        self,
    ) -> None:
        """Integral below 2^53, then by fractional bits, then inf, then NaN."""
        ordered = [
            0.0,
            -0.0,
            1.0,
            -1.0,
            2.0,
            float(2**53),
            0.5,
            -0.5,
            1.5,
            0.25,
            math.inf,
            -math.inf,
            math.nan,
        ]
        shuffled = list(reversed(ordered))
        result = sorted(shuffled, key=float_key)
        for got, want in zip(result, ordered, strict=True):
            self.assertTrue(same_float(got, want), f"{got} != {want}")

    def test_the_integral_group_ends_below_2_to_the_53(self) -> None:
        """2^52 + 1 sorts by magnitude, and 2^53 as a fraction without bits."""
        self.assertEqual(float_key(float(2**52 + 1)), (GROUP_INTEGRAL, 2**52 + 1, 0))
        self.assertEqual(float_key(float(2**53)), (GROUP_FRACTION, 0, 2**53, 0))
        self.assertEqual(float_key(-0.5), (GROUP_FRACTION, 1, 1, 1))

    def test_signed_zeros_and_nan_compare_by_value(self) -> None:
        """-0 is not +0, and any NaN is NaN."""
        self.assertFalse(same_float(0.0, -0.0))
        self.assertTrue(same_float(math.nan, -math.nan))
        self.assertFalse(same_float(math.nan, 0.0))

    def test_the_next_value_of_a_width_steps_one_unit(self) -> None:
        """Steps of one unit in the last place, through zero and to inf."""
        self.assertEqual(next_up(1.0, WIDTH_32), 1.0 + 2.0**-23)
        self.assertEqual(next_up(0.0, WIDTH_32), MIN_FLOAT32)
        self.assertEqual(next_up(-0.0, WIDTH_32), MIN_FLOAT32)
        self.assertEqual(next_down(0.0, WIDTH_32), -MIN_FLOAT32)
        self.assertEqual(next_up(-MIN_FLOAT32, WIDTH_32), -0.0)
        self.assertEqual(next_up(MAX_FLOAT32, WIDTH_32), math.inf)
        self.assertEqual(next_up(-math.inf, WIDTH_32), -MAX_FLOAT32)
        self.assertEqual(next_up(math.inf, WIDTH_32), math.inf)
        self.assertEqual(next_up(0.0, WIDTH_64), MIN_FLOAT64)
        self.assertEqual(next_down(1.0, WIDTH_64), 1.0 - 2.0**-53)

    def test_a_recorded_nan_replays_as_the_canonical_nan_when_allowed(
        self,
    ) -> None:
        """Any NaN payload comes back with the canonical bits."""
        bounds = FloatBounds(0.0, 1.0, allow_nan=True)
        got = bounds.coerce(Choice("float", -math.nan))
        self.assertEqual(bits_of(got), NAN_BITS)

    def test_a_recorded_value_that_does_not_fit_becomes_the_target(self) -> None:
        """Out of range, NaN not allowed, wrong width, or another kind."""
        bounds = FloatBounds(1.0, 2.0, width=WIDTH_32)
        for recorded in (
            Choice("float", 3.0),
            Choice("float", math.nan),
            Choice("float", 1.1),
            Choice("integer", 1),
        ):
            self.assertEqual(bounds.coerce(recorded), 1.0, recorded)

    def test_a_recorded_value_inside_the_bounds_replays(self) -> None:
        """A fitting float comes back unchanged, signed zero included."""
        bounds = FloatBounds(-1.0, 1.0)
        self.assertTrue(same_float(bounds.coerce(Choice("float", -0.0)), -0.0))


@final
class SequenceBoundsTest(unittest.TestCase):
    """Sequence bounds: elements in [0, k) and a length range."""

    def test_the_target_is_min_size_zeros(self) -> None:
        """The simplest sequence is as short as allowed and all zeros."""
        self.assertEqual(SequenceBounds(256, 3, 8).target, (0, 0, 0))

    def test_the_key_orders_shorter_first_then_element_by_element(self) -> None:
        """(1,) before (0, 0), and (0, 1) before (1, 0)."""
        bounds = SequenceBounds(4)
        values = [(1, 0), (0, 0), (1,), (0, 1)]
        self.assertEqual(sorted(values, key=bounds.key), [(1,), (0, 0), (0, 1), (1, 0)])

    def test_a_recorded_sequence_is_fitted_to_the_bounds(self) -> None:
        """Cut to max_size, extended to min_size, out-of-range elements zeroed."""
        bounds = SequenceBounds(10, 2, 4)
        self.assertEqual(
            bounds.coerce(Choice("sequence", (1, 2, 3, 4, 5))), (1, 2, 3, 4)
        )
        self.assertEqual(bounds.coerce(Choice("sequence", (7,))), (7, 0))
        self.assertEqual(bounds.coerce(Choice("sequence", (11, -1, 3))), (0, 0, 3))

    def test_another_kind_replays_as_the_target(self) -> None:
        """An integer recorded where a sequence is requested is the target."""
        self.assertEqual(SequenceBounds(10, 1).coerce(Choice("integer", 5)), (0,))

    def test_bounds_that_admit_no_sequence_are_refused(self) -> None:
        """No element value, a negative minimum, or a maximum below the minimum."""
        for k, min_size, max_size in ((0, 0, None), (2, -1, None), (2, 3, 2)):
            with self.assertRaises(ValueError):
                SequenceBounds(k, min_size, max_size)

    def test_admits_checks_length_and_elements(self) -> None:
        """Length inside [min, max] and every element inside [0, k)."""
        bounds = SequenceBounds(3, 1, 2)
        self.assertTrue(bounds.admits((2,)))
        self.assertFalse(bounds.admits(()))
        self.assertFalse(bounds.admits((0, 0, 0)))
        self.assertFalse(bounds.admits((3,)))
        self.assertFalse(bounds.admits([1]))
