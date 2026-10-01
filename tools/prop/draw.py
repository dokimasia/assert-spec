"""How a generated case draws each value from its random source.

Every draw consumes the source in a fixed order, and the order is part of
the definition. The same seed gives the same values in every language only
when every implementation consumes the stream exactly as these functions
do, including the draws they skip: equal bounds, a forced collection flag
and a one-element range consume nothing.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Final

from .choice import (
    NAN,
    WIDTH_32,
    WIDTH_64,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    from_bits,
    from_bits32,
    next_down,
    next_up,
    same_float,
)
from .source import Source

#: One integer draw in EDGE_ODDS takes an edge value.
EDGE_ODDS: Final = 8

#: A reusable integer draw takes an earlier value of its case with the
#: same bounds with odds 1 in REUSE_ODDS.
REUSE_ODDS: Final = 4

#: The caps an integer draw chooses its offset below, with even odds, so
#: that small offsets from the target are common and every value of the
#: bounds stays reachable.
OFFSET_CAPS: Final = (1 << 4, 1 << 8, 1 << 16, 1 << 64)

#: The average number of elements beyond its minimum that a collection
#: with no closer maximum gets.
DEFAULT_EXTRA: Final = 5

#: A float draw picks one of FLOAT_BRANCHES: branch 0 takes an edge value,
#: branches 1 to 3 an integral value, and the rest assemble the bits.
FLOAT_BRANCHES: Final = 8
FLOAT_EDGE_BRANCH: Final = 0
FLOAT_LAST_INTEGRAL_BRANCH: Final = 3

#: The magnitude below which every integer is a value of the width.
EXACT_INTEGERS: Final = {WIDTH_32: 1 << 24, WIDTH_64: 1 << 53}

#: The widths of a float's exponent and mantissa fields.
EXPONENT_BITS: Final = {WIDTH_32: 8, WIDTH_64: 11}
MANTISSA_BITS: Final = {WIDTH_32: 23, WIDTH_64: 52}


def integer_edges(bounds: IntegerBounds) -> list[int]:
    """Return the edge values of integer bounds.

    They are the target, lo, hi, one above the target and one below it,
    in that order, each once, and only those inside the bounds.
    """
    target = bounds.target
    values: list[int] = []
    for value in (target, bounds.lo, bounds.hi, target + 1, target - 1):
        if bounds.lo <= value <= bounds.hi and value not in values:
            values.append(value)
    return values


def integer(source: Source, bounds: IntegerBounds) -> int:
    """Draw an integer inside the bounds.

    Equal bounds return their value and consume nothing. Otherwise a coin
    of 1 in 8 decides whether the draw takes an edge value, chosen with
    below(number of edges). The rest move away from the target: upward
    when the target is lo, downward when it is hi, and by a coin of 1 in 2
    when it lies strictly between them. The offset is below(min(span,
    cap - 1) + 1), where span is the distance to the bound in that
    direction and cap is one of OFFSET_CAPS, chosen with below(4).
    """
    if bounds.lo == bounds.hi:
        return bounds.lo
    if source.coin(1, EDGE_ODDS):
        values = integer_edges(bounds)
        return values[source.below(len(values))]
    target = bounds.target
    if target == bounds.lo:
        up = True
    elif target == bounds.hi:
        up = False
    else:
        up = source.coin(1, 2)
    span = bounds.hi - target if up else target - bounds.lo
    cap = OFFSET_CAPS[source.below(len(OFFSET_CAPS))]
    offset = source.below(min(span, cap - 1) + 1)
    return target + offset if up else target - offset


def boolean(source: Source, probability: Fraction) -> int:
    """Draw 1 with the given probability and 0 otherwise, from one coin."""
    return 1 if source.coin(probability.numerator, probability.denominator) else 0


def average_length(min_size: int, max_size: int | None) -> int:
    """Return the average length of a collection.

    The average is min + min(max(min, 5), ceil((max - min) / 2)), and an
    unbounded maximum leaves min + max(min, 5). It is an integer, so the
    continue coin has integer odds.
    """
    extra = max(min_size, DEFAULT_EXTRA)
    if max_size is not None:
        extra = min(extra, -(-(max_size - min_size) // 2))
    return min_size + extra


def flag_bounds(count: int, min_size: int, max_size: int | None) -> IntegerBounds:
    """Return the bounds of the decision whether a collection gets another element.

    The decision is an integer choice, 1 to continue and 0 to stop. Its
    bounds are [1, 1] while count is below the minimum, [0, 0] once count
    is at the maximum, and [0, 1] otherwise.
    """
    if count < min_size:
        return IntegerBounds(1, 1)
    if max_size is not None and count >= max_size:
        return IntegerBounds(0, 0)
    return IntegerBounds(0, 1)


def flag(
    source: Source,
    count: int,
    min_size: int,
    max_size: int | None,
    average: int,
) -> int:
    """Decide whether a collection with count elements gets another.

    A forced decision returns the one value its bounds allow and consumes
    nothing. A free one continues by a coin of (average - min) in
    (average - min + 1).
    """
    bounds = flag_bounds(count, min_size, max_size)
    if bounds.lo == bounds.hi:
        return bounds.lo
    extra = average - min_size
    return 1 if source.coin(extra, extra + 1) else 0


def float_edges(bounds: FloatBounds) -> list[float]:
    """Return the edge values of float bounds.

    They are the target, lo, hi, the next value above the target and the
    next below it, in that order, each once, and only those the bounds
    admit, followed by NaN when the bounds allow it.
    """
    target = bounds.target
    values: list[float] = []
    for value in (
        target,
        bounds.lo,
        bounds.hi,
        next_up(target, bounds.width),
        next_down(target, bounds.width),
    ):
        if bounds.admits(value) and not any(same_float(value, v) for v in values):
            values.append(value)
    if bounds.allow_nan:
        values.append(NAN)
    return values


def _integral_bounds(bounds: FloatBounds) -> IntegerBounds | None:
    """Return the integers the bounds admit that are exact values of the width.

    None when there are none, as for bounds of one infinity.
    """
    if bounds.lo == math.inf or bounds.hi == -math.inf:
        return None
    limit = EXACT_INTEGERS[bounds.width] - 1
    lo = -limit if bounds.lo == -math.inf else max(math.ceil(bounds.lo), -limit)
    hi = limit if bounds.hi == math.inf else min(math.floor(bounds.hi), limit)
    if lo > hi:
        return None
    return IntegerBounds(lo, hi)


def _from_parts(source: Source, bounds: FloatBounds) -> float:
    """Assemble a float from a sign, an exponent and a mantissa.

    The draws are below(2), below(2^exponent bits) and below(2^mantissa
    bits), in that order. A NaN becomes the canonical NaN when the bounds
    allow it and the target otherwise. A value below lo becomes lo and one
    above hi becomes hi, compared numerically, so -0 stays -0 when lo is
    +0.
    """
    exponent_bits = EXPONENT_BITS[bounds.width]
    mantissa_bits = MANTISSA_BITS[bounds.width]
    sign = source.below(2)
    exponent = source.below(1 << exponent_bits)
    mantissa = source.below(1 << mantissa_bits)
    bits = (
        (sign << (exponent_bits + mantissa_bits))
        | (exponent << mantissa_bits)
        | mantissa
    )
    value = from_bits(bits) if bounds.width == WIDTH_64 else from_bits32(bits)
    if math.isnan(value):
        return NAN if bounds.allow_nan else bounds.target
    if value < bounds.lo:
        return bounds.lo
    if value > bounds.hi:
        return bounds.hi
    return value


def float_value(source: Source, bounds: FloatBounds) -> float:
    """Draw a float inside the bounds.

    below(8) picks the branch. Branch 0 takes an edge value, chosen with
    below(number of edges). Branches 1 to 3 draw an integer, as integer()
    does, over the integers the bounds admit that are exact values of the
    width. The other branches, and an integral branch whose bounds admit no
    such integer, assemble the value from its bits.
    """
    branch = source.below(FLOAT_BRANCHES)
    if branch == FLOAT_EDGE_BRANCH:
        values = float_edges(bounds)
        return values[source.below(len(values))]
    if branch <= FLOAT_LAST_INTEGRAL_BRANCH:
        integral = _integral_bounds(bounds)
        if integral is not None:
            return float(integer(source, integral))
    return _from_parts(source, bounds)


def sequence(source: Source, bounds: SequenceBounds) -> tuple[int, ...]:
    """Draw a sequence inside the bounds.

    Each position first takes the decision flag() makes for a collection,
    and when it continues, an element drawn as integer(0, k - 1). A byte
    string therefore consumes the stream exactly as a list of integers in
    [0, 255] with the same sizes does, and gets the same values.
    """
    average = average_length(bounds.min_size, bounds.max_size)
    element = IntegerBounds(0, bounds.k - 1)
    elements: list[int] = []
    while flag(source, len(elements), bounds.min_size, bounds.max_size, average):
        elements.append(integer(source, element))
    return tuple(elements)
