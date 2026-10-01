"""The edge phase: the value each choice takes at each boundary."""

from __future__ import annotations

import unittest
from typing import Any, final

from .case import Case, Request
from .choice import Bounds, FloatBounds, IntegerBounds, SequenceBounds, Value
from .edge import BOUNDARIES, Boundary, Edge
from .generator import build

#: The smallest positive binary64.
TINY = 5e-324


def take(bounds: Bounds, edge: int | None = None) -> list[Value]:
    """Return the value a request with bounds takes at each boundary, in order."""

    def unused(source: object) -> Value:
        raise AssertionError(f"the edge phase drew from {source}")

    request = Request(bounds, unused, edge)
    return [Edge(b).value(request, 0) for b in BOUNDARIES]


def decode(spec: dict[str, Any], boundary: Boundary) -> object:
    """Decode spec at one boundary."""
    return build(spec).decode(Case(Edge(boundary)))


@final
class BoundaryTest(unittest.TestCase):
    """The order of the four edge cases."""

    def test_the_cases_are_min_max_above_and_below(self) -> None:
        """In that order."""
        self.assertEqual(
            BOUNDARIES, (Boundary.MIN, Boundary.MAX, Boundary.ABOVE, Boundary.BELOW)
        )


@final
class ValueTest(unittest.TestCase):
    """A value choice takes its boundary, or its target where none is allowed."""

    def test_an_integer_takes_lo_hi_and_the_targets_neighbours(self) -> None:
        """[-5, 5] around a target of 0."""
        self.assertEqual(take(IntegerBounds(-5, 5)), [-5, 5, 1, -1])

    def test_a_neighbour_outside_the_bounds_is_the_target(self) -> None:
        """Below 0 is outside [0, 10], and [3, 3] has one value."""
        self.assertEqual(take(IntegerBounds(0, 10)), [0, 10, 1, 0])
        self.assertEqual(take(IntegerBounds(3, 3)), [3, 3, 3, 3])

    def test_a_float_takes_the_next_floats_around_its_target(self) -> None:
        """The smallest subnormals on either side of 0."""
        self.assertEqual(take(FloatBounds(-1.0, 1.0)), [-1.0, 1.0, TINY, -TINY])

    def test_a_float_below_its_range_is_the_target(self) -> None:
        """The target of [0.5, 0.75] is its minimum."""
        values = take(FloatBounds(0.5, 0.75))
        self.assertEqual(values[3], 0.5)
        above = values[2]
        assert isinstance(above, float)
        self.assertGreater(above, 0.5)

    def test_a_sequence_takes_one_element_at_the_boundary(self) -> None:
        """0, k - 1, 1, and 0 for below, which is outside [0, k)."""
        self.assertEqual(take(SequenceBounds(256)), [(0,), (255,), (1,), (0,)])

    def test_a_sequence_takes_min_size_elements_or_none_at_a_max_of_0(self) -> None:
        """Three elements for a minimum of 3, none for a maximum of 0."""
        self.assertEqual(take(SequenceBounds(4, 3))[1], (3, 3, 3))
        self.assertEqual(take(SequenceBounds(4, 0, 0)), [(), (), (), ()])

    def test_one_element_value_above_is_zero(self) -> None:
        """A sequence with one element value has only 0."""
        self.assertEqual(take(SequenceBounds(1))[2], (0,))


@final
class StructureTest(unittest.TestCase):
    """A structure choice takes its edge at every boundary."""

    def test_the_edge_is_taken_when_the_bounds_allow_it(self) -> None:
        """Edge 1 on a free flag, and the target on a flag forced to 1."""
        self.assertEqual(take(IntegerBounds(0, 1), edge=1), [1, 1, 1, 1])
        self.assertEqual(take(IntegerBounds(1, 1), edge=0), [1, 1, 1, 1])

    def test_a_collection_gets_one_element_at_each_boundary(self) -> None:
        """A list of digits is [0], [9], [1] and [0]."""
        spec = {"gen": "list", "of": {"gen": "integer", "min": 0, "max": 9}}
        self.assertEqual([decode(spec, b) for b in BOUNDARIES], [[0], [9], [1], [0]])

    def test_an_optional_is_present_and_a_one_of_takes_its_first(self) -> None:
        """At the maximum: the optional's maximum, the first alternative's."""
        digit = {"gen": "integer", "min": 0, "max": 9}
        teen = {"gen": "integer", "min": 10, "max": 20}
        self.assertEqual(decode({"gen": "optional", "of": digit}, Boundary.MAX), 9)
        spec = {"gen": "one-of", "of": [digit, teen]}
        self.assertEqual(decode(spec, Boundary.MAX), 9)
