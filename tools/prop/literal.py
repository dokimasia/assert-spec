"""Typed literals: the language-neutral form of a value in the corpus.

A typed literal is a JSON object with a ``type`` key. decode() turns one
into the Python value a generator decodes, and encode() turns a decoded
value into its one canonical literal:

- null, bool, string, and float, which names NaN, Inf and -Inf.
- int, as a JSON integer up to SAFE_INTEGER in magnitude and as a
  decimal string beyond it, because a JavaScript reader would round it.
- bytes, as lowercase hexadecimal.
- list: ``of`` and ``value`` for a non-empty list of one scalar type,
  and ``items``, a list of literals, for any other list.
- map: ``entries``, a list of key and value literal pairs in order. The
  older form, ``key``, ``of`` and a JSON object ``value``, decodes when
  its keys are strings.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from .value import Pairs

#: The largest integer magnitude a JSON number states exactly in every
#: target language.
SAFE_INTEGER: Final = (1 << 53) - 1

#: A map entry is a key literal and a value literal.
_ENTRY: Final = 2

#: The names a float takes for the values JSON cannot state.
NON_FINITE: Final = {"NaN": math.nan, "Inf": math.inf, "-Inf": -math.inf}


class LiteralError(ValueError):
    """A literal the encoding does not define, or one whose value lacks its type."""


def decode(literal: object) -> object:
    """Return the value a typed literal states.

    Raises:
        LiteralError: the literal is not one the encoding defines.
    """
    if not isinstance(literal, Mapping):
        raise LiteralError(f"prop: {literal!r} is not a typed literal")
    kind = literal.get("type")
    if kind == "null":
        return None
    if kind == "bytes":
        return _bytes(literal.get("value"))
    if kind == "list":
        return _list(literal)
    if kind == "map":
        return _map(literal)
    return scalar(kind, literal.get("value"))


def scalar(kind: object, value: object) -> object:
    """Return value as a scalar of the named type.

    Raises:
        LiteralError: value is not a scalar of that type.
    """
    if kind == "bool" and isinstance(value, bool):
        return value
    if kind == "int":
        return integer(value)
    if kind == "float":
        return number(value)
    if kind == "string" and isinstance(value, str):
        return value
    raise LiteralError(f"prop: {value!r} is not a literal of type {kind!r}")


def integer(value: object) -> int:
    """Return an int stated as a JSON integer, or beyond SAFE_INTEGER as a string.

    Raises:
        LiteralError: value is neither, or states a safe integer as a string.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > SAFE_INTEGER:
            raise LiteralError(
                f"prop: {value} is beyond 2^53 - 1; state it as a string"
            )
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit() and value.isascii():
        parsed = int(value)
        if abs(parsed) <= SAFE_INTEGER or str(parsed) != value:
            raise LiteralError(f"prop: {value!r} is not a canonical large integer")
        return parsed
    raise LiteralError(f"prop: {value!r} is not an integer")


def number(value: object) -> float:
    """Return a float stated as a JSON number or as NaN, Inf or -Inf.

    Raises:
        LiteralError: value is neither.
    """
    if isinstance(value, str) and value in NON_FINITE:
        return NON_FINITE[value]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise LiteralError(f"prop: {value!r} is not a float")


def _bytes(value: object) -> bytes:
    """Return bytes stated as lowercase hexadecimal."""
    if not isinstance(value, str) or value != value.lower():
        raise LiteralError(f"prop: {value!r} is not lowercase hexadecimal")
    try:
        return bytes.fromhex(value)
    except ValueError as bad:
        raise LiteralError(f"prop: {value!r} is not hexadecimal") from bad


def _list(literal: Mapping[str, Any]) -> list[object]:
    """Return a list stated by of and value, or by items."""
    if "items" in literal:
        items = literal["items"]
        if not isinstance(items, list):
            raise LiteralError(f"prop: items is {items!r}, not a list")
        return [decode(item) for item in items]
    values = literal.get("value")
    if not isinstance(values, list):
        raise LiteralError(f"prop: {literal!r} states no list")
    return [scalar(literal.get("of"), v) for v in values]


def _map(literal: Mapping[str, Any]) -> Pairs:
    """Return a map stated by entries, or by string keys in a JSON object."""
    if "entries" in literal:
        entries = literal["entries"]
        if not isinstance(entries, list) or not all(
            isinstance(e, list) and len(e) == _ENTRY for e in entries
        ):
            raise LiteralError(f"prop: entries is {entries!r}, not key and value pairs")
        return Pairs(tuple((decode(k), decode(v)) for k, v in entries))
    values = literal.get("value")
    if literal.get("key") != "string" or not isinstance(values, Mapping):
        raise LiteralError(f"prop: {literal!r} is not a map with string keys")
    return Pairs(tuple((k, scalar(literal.get("of"), v)) for k, v in values.items()))


def encode(value: object) -> dict[str, Any]:
    """Return the canonical typed literal of a decoded value.

    Raises:
        TypeError: value is not one a generator decodes.
    """
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, list):
        kinds = {_scalar_kind(item) for item in value}
        if value and len(kinds) == 1 and None not in kinds:
            kind = kinds.pop()
            assert kind is not None
            return {
                "type": "list",
                "of": kind,
                "value": [plain(item) for item in value],
            }
        return {"type": "list", "items": [encode(item) for item in value]}
    if isinstance(value, Pairs):
        entries = [[encode(k), encode(v)] for k, v in value.items]
        return {"type": "map", "entries": entries}
    kind = _scalar_kind(value)
    if kind is None:
        raise TypeError(f"prop: {value!r} is not a decoded value")
    return {"type": kind, "value": plain(value)}


def _scalar_kind(value: object) -> str | None:
    """Return the scalar type a value encodes as, or None for any other value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return None


def plain(value: object) -> object:
    """Return a scalar's JSON form: non-finite floats named, large ints quoted."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
        return value
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and abs(value) > SAFE_INTEGER
    ):
        return str(value)
    return value
