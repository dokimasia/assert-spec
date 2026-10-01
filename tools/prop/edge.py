"""The edge phase: four cases, each with every value at one boundary.

A choice that decides structure takes the edge its request states, so a
collection gets one element, a one-of its first alternative and an
optional its value. A value choice takes the boundary of its case:

- MIN: lo. A sequence's elements are 0.
- MAX: hi. A sequence's elements are k - 1.
- ABOVE: one above the target, the next float of the width for a float,
  and 1 for a sequence's elements.
- BELOW: one below the target, and the next float below it.

A value the bounds do not admit takes the target instead. A sequence has
one element, or min_size elements when that is more, and none when its
max_size is 0.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, final

from .case import Request
from .choice import (
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    Value,
    next_down,
    next_up,
)


class Boundary(StrEnum):
    """The boundary every value choice of one edge case takes."""

    MIN = "min"
    MAX = "max"
    ABOVE = "above"
    BELOW = "below"


#: The edge cases, in the order a run tries them.
BOUNDARIES: Final = (Boundary.MIN, Boundary.MAX, Boundary.ABOVE, Boundary.BELOW)


def _integer(bounds: IntegerBounds, boundary: Boundary) -> int:
    """Return an integer choice's value at the boundary."""
    target = bounds.target
    value = {
        Boundary.MIN: bounds.lo,
        Boundary.MAX: bounds.hi,
        Boundary.ABOVE: target + 1,
        Boundary.BELOW: target - 1,
    }[boundary]
    return value if bounds.admits(value) else target


def _float(bounds: FloatBounds, boundary: Boundary) -> float:
    """Return a float choice's value at the boundary."""
    target = bounds.target
    value = {
        Boundary.MIN: bounds.lo,
        Boundary.MAX: bounds.hi,
        Boundary.ABOVE: next_up(target, bounds.width),
        Boundary.BELOW: next_down(target, bounds.width),
    }[boundary]
    return value if bounds.admits(value) else target


def _sequence(bounds: SequenceBounds, boundary: Boundary) -> tuple[int, ...]:
    """Return a sequence choice's value at the boundary."""
    length = max(bounds.min_size, 1)
    if bounds.max_size is not None:
        length = min(length, bounds.max_size)
    element = {
        Boundary.MIN: 0,
        Boundary.MAX: bounds.k - 1,
        Boundary.ABOVE: 1,
        Boundary.BELOW: -1,
    }[boundary]
    if not 0 <= element < bounds.k:
        element = 0
    return (element,) * length


@final
class Edge:
    """A provider that gives every choice its value at one boundary."""

    def __init__(self, boundary: Boundary) -> None:
        """Give each value choice its value at boundary."""
        self._boundary = boundary

    def value(self, request: Request, index: int) -> Value:
        """Return the request's edge, or its value at the boundary."""
        del index
        bounds = request.bounds
        if request.edge is not None:
            return request.edge if bounds.admits(request.edge) else bounds.target
        if isinstance(bounds, IntegerBounds):
            return _integer(bounds, self._boundary)
        if isinstance(bounds, FloatBounds):
            return _float(bounds, self._boundary)
        return _sequence(bounds, self._boundary)
