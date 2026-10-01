"""The draws: what each consumes from the stream, and what it can return."""

from __future__ import annotations

import math
import unittest
from fractions import Fraction
from typing import final

from .choice import (
    INT64_MAX,
    INT64_MIN,
    UINT64_MAX,
    WIDTH_32,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    representable,
    same_float,
)
from .draw import (
    OFFSET_CAPS,
    average_length,
    boolean,
    flag,
    flag_bounds,
    float_edges,
    float_value,
    integer,
    integer_edges,
    sequence,
)
from .source import Source

#: Draws per property check: enough to visit every branch of every draw.
DRAWS = 2000

#: The first ten draws of integer(-100, 100) from seed 42, pinned so that
#: any change to the draw fails here before a corpus vector moves.
PINNED_SEED = 42
PINNED_INTEGERS = [11, 24, 14, 62, -71, -5, 8, -21, -29, -69]

#: The first ten draws over the whole signed 64-bit range from seed 42,
#: pinned because only a wide range reaches the larger offset caps.
PINNED_WIDE = [
    11,
    49,
    14,
    31993,
    -207,
    -49792,
    -10,
    -9223372036854775808,
    3534659902462096457,
    51818,
]


@final
class IntegerDrawTest(unittest.TestCase):
    """integer(): edges one time in eight, otherwise an offset from the target."""

    def test_equal_bounds_return_their_value_and_consume_nothing(self) -> None:
        """A range of one value draws nothing from the stream."""
        source, twin = Source(1), Source(1)
        self.assertEqual(integer(source, IntegerBounds(7, 7)), 7)
        self.assertEqual(source.next(), twin.next())

    def test_every_draw_stays_inside_its_bounds(self) -> None:
        """Small, one-sided, negative and full 64-bit ranges."""
        for lo, hi in (
            (-100, 100),
            (0, 1),
            (5, 9),
            (-9, -5),
            (INT64_MIN, INT64_MAX),
            (0, UINT64_MAX),
        ):
            bounds = IntegerBounds(lo, hi)
            source = Source(lo & UINT64_MAX)
            for _ in range(DRAWS):
                value = integer(source, bounds)
                self.assertTrue(lo <= value <= hi, f"[{lo}, {hi}]: {value}")

    def test_edges_are_target_lo_hi_and_the_target_neighbours_once_each(
        self,
    ) -> None:
        """In that order, and only those inside the bounds."""
        cases = {
            (0, 10): [0, 10, 1],
            (-5, 5): [0, -5, 5, 1, -1],
            (1, 2): [1, 2],
            (3, 3): [3],
        }
        for (lo, hi), edges in cases.items():
            self.assertEqual(integer_edges(IntegerBounds(lo, hi)), edges)

    def test_a_target_at_lo_moves_upward_without_the_direction_coin(self) -> None:
        """The draws are the edge coin, the cap and the offset, in that order."""
        bounds = IntegerBounds(0, 1000)
        for seed in range(50):
            source, twin = Source(seed), Source(seed)
            got = integer(source, bounds)
            if twin.coin(1, 8):
                edges = integer_edges(bounds)
                want = edges[twin.below(len(edges))]
            else:
                cap = OFFSET_CAPS[twin.below(len(OFFSET_CAPS))]
                want = twin.below(min(1000, cap - 1) + 1)
            self.assertEqual(got, want, f"seed {seed}")
            self.assertEqual(source.next(), twin.next(), f"seed {seed}")

    def test_the_first_draws_from_seed_42_are_pinned(self) -> None:
        """Ten draws of integer(-100, 100)."""
        source = Source(PINNED_SEED)
        bounds = IntegerBounds(-100, 100)
        self.assertEqual([integer(source, bounds) for _ in range(10)], PINNED_INTEGERS)

    def test_the_first_wide_draws_from_seed_42_are_pinned(self) -> None:
        """Ten draws over the whole signed 64-bit range."""
        source = Source(PINNED_SEED)
        bounds = IntegerBounds(INT64_MIN, INT64_MAX)
        self.assertEqual([integer(source, bounds) for _ in range(10)], PINNED_WIDE)


@final
class CollectionDrawTest(unittest.TestCase):
    """The length decisions of collections and sequences."""

    def test_the_average_length_follows_the_rule(self) -> None:
        """The average is min + min(max(min, 5), ceil((max - min) / 2))."""
        cases = {
            (0, None): 5,
            (0, 16): 5,
            (0, 3): 2,
            (0, 1): 1,
            (2, 4): 3,
            (3, 3): 3,
            (10, None): 20,
        }
        for (min_size, max_size), average in cases.items():
            self.assertEqual(
                average_length(min_size, max_size), average, (min_size, max_size)
            )

    def test_a_flag_below_the_minimum_continues_without_consuming(self) -> None:
        """Forced to 1 with bounds [1, 1]."""
        source, twin = Source(5), Source(5)
        self.assertEqual(flag_bounds(1, 2, 9), IntegerBounds(1, 1))
        self.assertEqual(flag(source, 1, 2, 9, 7), 1)
        self.assertEqual(source.next(), twin.next())

    def test_a_flag_at_the_maximum_stops_without_consuming(self) -> None:
        """Forced to 0 with bounds [0, 0]."""
        source, twin = Source(5), Source(5)
        self.assertEqual(flag_bounds(9, 2, 9), IntegerBounds(0, 0))
        self.assertEqual(flag(source, 9, 2, 9, 7), 0)
        self.assertEqual(source.next(), twin.next())

    def test_a_free_flag_continues_by_its_coin(self) -> None:
        """Bounds [0, 1], continuing on a coin of 5 in 6 for an average of 5."""
        self.assertEqual(flag_bounds(3, 0, None), IntegerBounds(0, 1))
        self.assertEqual(flag_bounds(2, 2, 3), IntegerBounds(0, 1))
        source, twin = Source(5), Source(5)
        for _ in range(100):
            self.assertEqual(flag(source, 3, 0, None, 5), 1 if twin.coin(5, 6) else 0)

    def test_a_sequence_draws_as_a_list_of_integers_does(self) -> None:
        """Flag, element, flag, element: a byte string equals the list draw."""
        bounds = SequenceBounds(256, 0, 16)
        average = average_length(0, 16)
        element = IntegerBounds(0, 255)
        for seed in range(100):
            source, twin = Source(seed), Source(seed)
            want: list[int] = []
            while flag(twin, len(want), 0, 16, average):
                want.append(integer(twin, element))
            self.assertEqual(sequence(source, bounds), tuple(want), f"seed {seed}")

    def test_every_sequence_stays_inside_its_bounds(self) -> None:
        """Length inside [min, max] and every element inside [0, k)."""
        bounds = SequenceBounds(3, 2, 6)
        source = Source(11)
        for _ in range(DRAWS):
            self.assertTrue(bounds.admits(sequence(source, bounds)))


@final
class BooleanDrawTest(unittest.TestCase):
    """boolean(): one coin with the stated probability."""

    def test_probability_zero_and_one_are_certain(self) -> None:
        """Never 1 at 0, always 1 at 1."""
        source = Source(2)
        for _ in range(100):
            self.assertEqual(boolean(source, Fraction(0)), 0)
            self.assertEqual(boolean(source, Fraction(1)), 1)

    def test_a_draw_is_one_coin(self) -> None:
        """1 exactly when coin(num, den) is true."""
        source, twin = Source(3), Source(3)
        for _ in range(100):
            self.assertEqual(
                boolean(source, Fraction(1, 3)), 1 if twin.coin(1, 3) else 0
            )


@final
class FloatDrawTest(unittest.TestCase):
    """float_value(): edges, integral values or assembled bits."""

    def test_every_draw_is_admitted_by_its_bounds(self) -> None:
        """Finite, half-infinite, infinite, one-infinity and binary32 bounds."""
        for bounds in (
            FloatBounds(-1.0, 1.0),
            FloatBounds(0.5, 0.75),
            FloatBounds(-math.inf, math.inf),
            FloatBounds(1e300, math.inf),
            FloatBounds(math.inf, math.inf),
            FloatBounds(-math.inf, -math.inf),
            FloatBounds(-10.0, 10.0, width=WIDTH_32),
            FloatBounds(-math.inf, math.inf, allow_nan=True),
        ):
            source = Source(17)
            for _ in range(DRAWS):
                value = float_value(source, bounds)
                self.assertTrue(bounds.admits(value), f"{bounds}: {value}")
                self.assertTrue(representable(value, bounds.width))

    def test_nan_appears_only_when_allowed(self) -> None:
        """Allowed bounds produce NaN within the draws; others never do."""
        allowed = FloatBounds(-math.inf, math.inf, allow_nan=True)
        refused = FloatBounds(-math.inf, math.inf)
        source = Source(23)
        self.assertTrue(
            any(math.isnan(float_value(source, allowed)) for _ in range(DRAWS))
        )
        self.assertFalse(
            any(math.isnan(float_value(source, refused)) for _ in range(DRAWS))
        )

    def test_edges_are_target_lo_hi_and_the_target_neighbours(self) -> None:
        """Each once, inside the bounds, then NaN when allowed."""
        edges = float_edges(FloatBounds(-1.0, 1.0, allow_nan=True))
        want = [0.0, -1.0, 1.0, 5e-324, -5e-324, math.nan]
        self.assertEqual(len(edges), len(want))
        for got, expected in zip(edges, want, strict=True):
            self.assertTrue(same_float(got, expected), f"{got} != {expected}")
