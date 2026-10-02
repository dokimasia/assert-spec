"""Decoded values, and the equality that uniqueness is decided by.

Generators decode to Python values: None, bool, int, float, str, bytes, a
list, Pairs for a dict, and Record and Variant for the record and enum
shapes. canonical() gives each one a hashable form that is equal exactly
when the values are, with floats compared by their bits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, final, override

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


@dataclass(frozen=True)
class Record:
    """A decoded record: each field's name and value, in declaration order.

    No two fields share a name.
    """

    fields: tuple[tuple[str, object], ...]


@final
class _NoPayload:
    """The payload of a variant that has none, which differs from a null payload."""

    @override
    def __repr__(self) -> str:
        """Return the sentinel's name."""
        return "NO_PAYLOAD"


#: The payload of a variant that has none.
NO_PAYLOAD: Final = _NoPayload()


@dataclass(frozen=True)
class Variant:
    """A decoded variant of an enum: its name, and its payload when it has one.

    A variant with an optional payload that is absent has a payload of
    None. A variant without a payload has NO_PAYLOAD.
    """

    name: str
    payload: object = NO_PAYLOAD


def canonical(value: object) -> object:
    """Return a hashable form of a decoded value, equal exactly when the values are.

    A float compares by its bits, so -0 differs from +0, and every NaN is
    one value. A bool differs from the int of the same value. A dict
    compares by its entries in any order, as every language's map does. A
    record compares by its fields in order, and a variant by its name and
    its payload.

    Raises:
        TypeError: value is not one a generator decodes.
    """
    if isinstance(value, float):
        return ("float", NAN_BITS if math.isnan(value) else bits_of(value))
    composite = _composite(value)
    if composite is not None:
        return composite
    tag = _TAGS.get(type(value))
    if tag is None:
        raise TypeError(f"prop: {value!r} is not a decoded value")
    return (tag, value)


def _composite(value: object) -> tuple[object, ...] | None:
    """Return the canonical form of a list, a dict, a record or a variant, or None.

    Raises:
        TypeError: an element is not a value a generator decodes.
    """
    if isinstance(value, list):
        return ("list", tuple(canonical(e) for e in value))
    if isinstance(value, Pairs):
        return ("map", frozenset((canonical(k), canonical(v)) for k, v in value.items))
    if isinstance(value, Record):
        return ("record", tuple((name, canonical(v)) for name, v in value.fields))
    if isinstance(value, Variant):
        if value.payload is NO_PAYLOAD:
            return ("variant", value.name)
        return ("variant", value.name, canonical(value.payload))
    return None
