"""The fuzz bridge: a fuzzer's bytes decoded into the choices of one case.

Bridging is a provider that reads each value from the bytes, in request
order:

- An integer in [lo, hi] reads ceil(bit_length(hi - lo) / 8) bytes as a
  little-endian unsigned u, and takes lo + u mod (hi - lo + 1). Bounds
  with one value read no byte.
- A float reads 8 bytes, or 4 for width 32, little-endian, as the bits of
  a float of its width. A value its bounds do not admit takes the target,
  and an allowed NaN becomes the canonical NaN. Bounds that admit one
  value read no byte.
- A sequence reads its length as an integer in [min_size, max_size], or
  in [min_size, min_size + UNBOUNDED_LENGTHS] when it has no maximum.
  Then it reads each element as an integer in [0, k - 1]. A byte string
  therefore takes one fuzzer byte per byte, after its length.
- A value that needs more bytes than remain takes its target, and the
  bytes that remain are spent, so every later value takes its target
  too. An element cut short ends its sequence, which zeros extend to
  min_size.

Every byte string decodes to a valid case, so a failure a fuzzer finds is
a choice sequence the shrinker can minimise and the store can keep.
"""

from __future__ import annotations

from typing import Final, final

from .case import Request
from .choice import (
    WIDTH_64,
    Choice,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    Value,
    from_bits,
    from_bits32,
)

#: The lengths a sequence without a maximum may take beyond its minimum,
#: read from two bytes.
UNBOUNDED_LENGTHS: Final = 0xFFFF

#: The bits of one byte.
BYTE_BITS: Final = 8


def width(span: int) -> int:
    """Return the bytes that cover an integer range of span + 1 values."""
    return (span.bit_length() + BYTE_BITS - 1) // BYTE_BITS


def _single(bounds: FloatBounds) -> bool:
    """Report whether float bounds admit exactly one value.

    Both zeros lie inside any range that contains either, so only a
    nonzero range of one value, without NaN, has one.
    """
    return bounds.lo == bounds.hi and bounds.lo != 0.0 and not bounds.allow_nan


@final
class Bridging:
    """A provider that decodes every value from a fuzzer's bytes."""

    def __init__(self, data: bytes) -> None:
        """Decode from data's first byte."""
        self._data = data
        self._at = 0

    def value(self, request: Request, index: int) -> Value:
        """Return the value the next bytes decode to under the request's bounds."""
        del index
        bounds = request.bounds
        if isinstance(bounds, IntegerBounds):
            return self._integer(bounds)
        if isinstance(bounds, FloatBounds):
            return self._float(bounds)
        return self._sequence(bounds)

    def _take(self, count: int) -> int | None:
        """Return the next count bytes as a little-endian unsigned integer.

        None when fewer than count bytes remain. The bytes that remain are
        then spent.
        """
        if count > len(self._data) - self._at:
            self._at = len(self._data)
            return None
        taken = self._data[self._at : self._at + count]
        self._at += count
        return int.from_bytes(taken, "little")

    def _below(self, span: int) -> int | None:
        """Return an integer in [0, span] read from width(span) bytes, or None."""
        u = self._take(width(span))
        return None if u is None else u % (span + 1)

    def _integer(self, bounds: IntegerBounds) -> int:
        """Return lo plus the offset the bytes state, or the target."""
        offset = self._below(bounds.hi - bounds.lo)
        return bounds.target if offset is None else bounds.lo + offset

    def _float(self, bounds: FloatBounds) -> float:
        """Return the float whose bits the bytes state, fitted to the bounds."""
        if _single(bounds):
            return bounds.target
        bits = self._take(bounds.width // BYTE_BITS)
        if bits is None:
            return bounds.target
        value = from_bits(bits) if bounds.width == WIDTH_64 else from_bits32(bits)
        return bounds.coerce(Choice("float", value))

    def _sequence(self, bounds: SequenceBounds) -> tuple[int, ...]:
        """Return the length the bytes state, then as many elements as they hold."""
        spread = (
            UNBOUNDED_LENGTHS
            if bounds.max_size is None
            else bounds.max_size - bounds.min_size
        )
        extra = self._below(spread)
        if extra is None:
            return bounds.target
        elements: list[int] = []
        for _ in range(bounds.min_size + extra):
            element = self._below(bounds.k - 1)
            if element is None:
                break
            elements.append(element)
        elements.extend([0] * (bounds.min_size - len(elements)))
        return tuple(elements)
