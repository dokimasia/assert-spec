"""Decoded values: the dict type, and the equality uniqueness is decided by.

Generators decode to Python values: None, bool, int, float, str, bytes, a
list, and Pairs for a dict. canonical() gives each one a hashable form
that is equal exactly when the values are, with floats compared by their
bits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from .choice import NAN_BITS, bits_of

#: The tags canonical() gives the decoded values it compares as they are.
_TAGS: Final[dict[type, str]] = {
    type(None): "null",
    bool: "bool",
    int: "int",
    str: "string",
    bytes: "bytes",
}


@dataclass(frozen=True)
class Pairs:
    """A decoded dict: its entries in the order they were generated.

    No two entries have keys that are equal under canonical().
    """

    items: tuple[tuple[object, object], ...]


def canonical(value: object) -> object:
    """Return a hashable form of a decoded value, equal exactly when the values are.

    A float compares by its bits, so -0 differs from +0, and every NaN is
    one value. A bool differs from the int of the same value. A dict
    compares by its entries in any order, as every language's map does.

    Raises:
        TypeError: value is not one a generator decodes.
    """
    if isinstance(value, float):
        return ("float", NAN_BITS if math.isnan(value) else bits_of(value))
    if isinstance(value, list):
        return ("list", tuple(canonical(e) for e in value))
    if isinstance(value, Pairs):
        return ("map", frozenset((canonical(k), canonical(v)) for k, v in value.items))
    tag = _TAGS.get(type(value))
    if tag is None:
        raise TypeError(f"prop: {value!r} is not a decoded value")
    return (tag, value)
