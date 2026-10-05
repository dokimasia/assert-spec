"""Collections: their sizes, their continue flags, and their discards."""

from __future__ import annotations

import unittest
from typing import final

from .case import Case, Generating, Rejected, Replaying, Span
from .choice import Choice, IntegerBounds
from .collection import ELEMENT, Sizes, collect, more
from .source import Source

#: The discards in a row that stop a collection, pinned here as the
#: definition states it rather than read from the code under test.
DISCARD_LIMIT = 10

#: The bounds of each element the tests decode.
DIGIT = IntegerBounds(0, 9)


def replay(*values: int) -> Case:
    """Return a case that replays integer values."""
    return Case(Replaying([Choice("integer", v) for v in values]))


def digits(case: Case, sizes: Sizes, *, unique: bool) -> list[int]:
    """Collect digits, each unique by its value when unique is set."""

    def element() -> tuple[int, object]:
        value = case.integer(DIGIT)
        return value, value if unique else None

    return collect(case, sizes, ELEMENT, element)


@final
class SizesTest(unittest.TestCase):
    """Sizes: the bounds on a length."""

    def test_sizes_that_admit_no_length_raise(self) -> None:
        """A negative minimum, or a maximum below the minimum."""
        for low, high in ((-1, None), (3, 2)):
            with self.assertRaises(ValueError):
                Sizes(low, high)

    def test_the_average_follows_the_length_rule(self) -> None:
        """The average is min + min(max(min, 5), ceil((max - min) / 2))."""
        self.assertEqual(Sizes(0, None).average, 5)
        self.assertEqual(Sizes(0, 1).average, 1)
        self.assertEqual(Sizes(10, None).average, 20)


@final
class MoreTest(unittest.TestCase):
    """more(): one continue flag, an integer choice that decides structure."""

    def test_the_flag_is_forced_below_the_minimum_and_at_the_maximum(self) -> None:
        """[1, 1] below min_size, [0, 1] between, [0, 0] at max_size."""
        case = replay(0, 0, 1)
        sizes = Sizes(1, 2)
        self.assertEqual(
            [more(case, n, sizes) for n in (0, 1, 2)], [True, False, False]
        )
        bounds = [r.bounds for r in case.requests]
        want = [IntegerBounds(1, 1), IntegerBounds(0, 1), IntegerBounds(0, 0)]
        self.assertEqual(bounds, want)
        self.assertEqual([r.edge for r in case.requests], [1, 0, 0])

    def test_a_stated_average_replaces_the_average_of_the_sizes(self) -> None:
        """An average of 30 continues on a coin of 30 in 31."""
        case = Case(Generating(Source(12)))
        twin = Source(12)
        for count in range(50):
            continues = more(case, count, Sizes(0, 100), average=30)
            self.assertEqual(continues, twin.coin(30, 31))


@final
class CollectTest(unittest.TestCase):
    """collect(): flags, elements, spans and discards."""

    def test_each_element_span_starts_at_its_flag(self) -> None:
        """Flag and element in one span, and the stop flag in none."""
        case = replay(1, 7, 1, 3, 0)
        self.assertEqual(digits(case, Sizes(), unique=False), [7, 3])
        self.assertEqual(
            case.spans, [Span(ELEMENT, 0, 2, 0, None), Span(ELEMENT, 2, 4, 0, None)]
        )

    def test_duplicates_stay_without_a_key(self) -> None:
        """No key, no discard."""
        self.assertEqual(digits(replay(1, 4, 1, 4, 0), Sizes(), unique=False), [4, 4])

    def test_a_repeated_key_is_discarded(self) -> None:
        """The second 4 is discarded, and the next flag continues."""
        self.assertEqual(
            digits(replay(1, 4, 1, 4, 1, 5, 0), Sizes(), unique=True), [4, 5]
        )

    def test_one_discard_fewer_than_the_limit_continues(self) -> None:
        """Nine duplicates in a row, then a new value."""
        values = (1, 4, *(1, 4) * (DISCARD_LIMIT - 1), 1, 5, 0)
        self.assertEqual(digits(replay(*values), Sizes(), unique=True), [4, 5])

    def test_the_limit_of_discards_stops_the_collection(self) -> None:
        """Ten duplicates in a row stop it without another flag."""
        case = replay(1, 4, *(1, 4) * DISCARD_LIMIT, 1, 5, 0)
        self.assertEqual(digits(case, Sizes(), unique=True), [4])
        self.assertEqual(len(case.choices), 2 + 2 * DISCARD_LIMIT)

    def test_a_new_element_restarts_the_count_of_discards(self) -> None:
        """Nine duplicates, a new 5, one more duplicate, then a new 6."""
        values = (1, 4, *(1, 4) * (DISCARD_LIMIT - 1), 1, 5, 1, 5, 1, 6, 0)
        self.assertEqual(digits(replay(*values), Sizes(), unique=True), [4, 5, 6])

    def test_a_collection_that_stops_at_its_minimum_is_kept(self) -> None:
        """A minimum of 1 and one element survive the limit."""
        case = replay(1, 4, *(1, 4) * DISCARD_LIMIT)
        self.assertEqual(digits(case, Sizes(1, None), unique=True), [4])

    def test_a_collection_that_stops_below_its_minimum_rejects_the_case(self) -> None:
        """The targets repeat, so a minimum of 2 cannot be met."""
        with self.assertRaises(Rejected):
            digits(replay(), Sizes(2, None), unique=True)
