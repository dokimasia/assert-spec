"""The standard's equality over decoded values, and a key that agrees with it.

equal() is the equality of the ``equal`` assertion. It is structural and
coerces no type, so a bool, an int and a float of one value differ, and a
null list or map differs from an empty one. Floats compare by value: -0
equals +0, and a NaN equals nothing, itself included. A map compares by
its entries in any order.

key() returns a hashable form of a value. Two equal values have equal
keys, so a key finds every candidate for a match in a hash table, and
equal() decides the match.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Final

from prop.value import NO_PAYLOAD, Pairs, Record, Variant

#: The tags of the scalar types, which compare with Python's own equality.
_SCALARS: Final[dict[type, str]] = {
    type(None): "null",
    bool: "bool",
    int: "int",
    float: "float",
    str: "string",
    bytes: "bytes",
}


def equal(a: object, b: object) -> bool:
    """Report whether two decoded values are equal under the standard's equality.

    Raises:
        TypeError: a value is not one that a typed literal decodes to.
    """
    if type(a) is not type(b):
        _tag(a)
        _tag(b)
        return False
    composite = _composite(a, b)
    if composite is not None:
        return composite
    _tag(a)
    return a == b


def _composite(a: object, b: object) -> bool | None:
    """Report whether two composites of one type are equal, or None for scalars."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, Pairs) and isinstance(b, Pairs):
        return len(a.items) == len(b.items) and all(
            any(equal(k, k2) and equal(v, v2) for k2, v2 in b.items) for k, v in a.items
        )
    if isinstance(a, Record) and isinstance(b, Record):
        return [name for name, _ in a.fields] == [name for name, _ in b.fields] and all(
            equal(x, y) for (_, x), (_, y) in zip(a.fields, b.fields, strict=True)
        )
    if isinstance(a, Variant) and isinstance(b, Variant):
        if a.payload is NO_PAYLOAD or b.payload is NO_PAYLOAD:
            return a.name == b.name and a.payload is b.payload
        return a.name == b.name and equal(a.payload, b.payload)
    return None


def key(value: object) -> Hashable:
    """Return a hashable form of a decoded value that two equal values share.

    Raises:
        TypeError: value is not one that a typed literal decodes to.
    """
    if isinstance(value, list):
        return ("list", tuple(key(item) for item in value))
    if isinstance(value, Pairs):
        return ("map", frozenset((key(k), key(v)) for k, v in value.items))
    if isinstance(value, Record):
        return ("record", tuple((name, key(v)) for name, v in value.fields))
    if isinstance(value, Variant):
        if value.payload is NO_PAYLOAD:
            return ("variant", value.name)
        return ("variant", value.name, key(value.payload))
    return (_tag(value), value)


def _tag(value: object) -> str:
    """Return the tag of a scalar, or of a composite's type.

    Raises:
        TypeError: value is not one that a typed literal decodes to.
    """
    tag = _SCALARS.get(type(value))
    if tag is not None:
        return tag
    if isinstance(value, list | Pairs | Record | Variant):
        return type(value).__name__
    raise TypeError(f"history: {value!r} is not a decoded value")
