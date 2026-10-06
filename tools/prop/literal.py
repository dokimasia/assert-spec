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
- An absent list or map of a stated type: the ``of`` form, or the ``key``
  and ``of`` form, with a ``value`` of null. It decodes to None, which is
  the only absent value Python has. encode() never writes this form,
  because no generator decodes an absent container.
- record: ``fields``, a list of name and value literal pairs in
  declaration order, with no name twice.
- variant: ``name``, and ``payload``, a literal, when the variant has
  one. A variant without a payload states no ``payload`` key, and one
  whose optional payload is absent states a null payload.
- reference: ``id``, a non-empty string, and ``value``, a literal that
  is not null. It decodes to its value. This codec makes no object of
  its own, and encode() writes the value's literal, as a record states a
  reference.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any, Final

from .value import NO_PAYLOAD, Pairs, Record, Variant

#: The largest integer magnitude a JSON number states exactly in every
#: target language.
SAFE_INTEGER: Final = (1 << 53) - 1

#: A map entry is a key literal and a value literal.
_ENTRY: Final = 2

#: The names a float takes for the values JSON cannot state.
NON_FINITE: Final = {"NaN": math.nan, "Inf": math.inf, "-Inf": -math.inf}

#: The scalar types a list's ``of`` and a map's ``key`` may name.
SCALARS: Final = frozenset({"bool", "int", "float", "string"})


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
    if isinstance(kind, str) and kind in _DECODERS:
        return _DECODERS[kind](literal)
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


def _absent(literal: Mapping[str, Any]) -> bool:
    """Report whether literal states an absent container of a scalar type.

    Raises:
        LiteralError: the value is null and of names no scalar type.
    """
    if "value" not in literal or literal["value"] is not None:
        return False
    if literal.get("of") not in SCALARS:
        raise LiteralError(f"prop: {literal!r} states no type for its absent value")
    return True


def _list(literal: Mapping[str, Any]) -> list[object] | None:
    """Return a list stated by of and value, or by items, or None for an absent one."""
    if "items" in literal:
        items = literal["items"]
        if not isinstance(items, list):
            raise LiteralError(f"prop: items is {items!r}, not a list")
        return [decode(item) for item in items]
    if _absent(literal):
        return None
    values = literal.get("value")
    if not isinstance(values, list):
        raise LiteralError(f"prop: {literal!r} states no list")
    return [scalar(literal.get("of"), v) for v in values]


def _map(literal: Mapping[str, Any]) -> Pairs | None:
    """Return a map stated by entries or by string keys, or None for an absent one."""
    if "entries" in literal:
        entries = literal["entries"]
        if not isinstance(entries, list) or not all(
            isinstance(e, list) and len(e) == _ENTRY for e in entries
        ):
            raise LiteralError(f"prop: entries is {entries!r}, not key and value pairs")
        return Pairs(tuple((decode(k), decode(v)) for k, v in entries))
    if literal.get("key") != "string":
        raise LiteralError(f"prop: {literal!r} is not a map with string keys")
    if _absent(literal):
        return None
    values = literal.get("value")
    if not isinstance(values, Mapping):
        raise LiteralError(f"prop: {literal!r} is not a map with string keys")
    return Pairs(tuple((k, scalar(literal.get("of"), v)) for k, v in values.items()))


def _record(fields: object) -> Record:
    """Return a record stated by its name and value pairs.

    Raises:
        LiteralError: fields is not a list of pairs of a non-empty name and
            a literal, or names a field twice.
    """
    if not isinstance(fields, list) or not all(
        isinstance(f, list) and len(f) == _ENTRY and isinstance(f[0], str) and f[0]
        for f in fields
    ):
        raise LiteralError(f"prop: fields is {fields!r}, not name and value pairs")
    names = [f[0] for f in fields]
    if len(set(names)) != len(names):
        raise LiteralError(f"prop: the record {names!r} names a field twice")
    return Record(tuple((str(name), decode(value)) for name, value in fields))


def _variant(literal: Mapping[str, Any]) -> Variant:
    """Return a variant stated by its name, and its payload when it has one.

    Raises:
        LiteralError: the name is not a non-empty string.
    """
    name = literal.get("name")
    if not isinstance(name, str) or not name:
        raise LiteralError(f"prop: {literal!r} names no variant")
    if "payload" in literal:
        return Variant(name, decode(literal["payload"]))
    return Variant(name)


def _reference(literal: Mapping[str, Any]) -> object:
    """Return the value that a reference refers to.

    Raises:
        LiteralError: the id is not a non-empty string, or the value is
            null, which is no object.
    """
    rid = literal.get("id")
    if not isinstance(rid, str) or not rid:
        raise LiteralError(f"prop: {literal!r} states no id")
    value = literal.get("value")
    if isinstance(value, Mapping) and value.get("type") == "null":
        raise LiteralError(f"prop: the reference {rid!r} refers to null, no object")
    return decode(value)


def encode(value: object) -> dict[str, Any]:
    """Return the canonical typed literal of a decoded value.

    Raises:
        TypeError: value is not one a generator decodes.
    """
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    composite = _composite(value)
    if composite is not None:
        return composite
    kind = _scalar_kind(value)
    if kind is None:
        raise TypeError(f"prop: {value!r} is not a decoded value")
    return {"type": kind, "value": plain(value)}


def _composite(value: object) -> dict[str, Any] | None:
    """Return the literal of a list, a map, a record or a variant, or None.

    Raises:
        TypeError: an element is not a value a generator decodes.
    """
    if isinstance(value, list):
        return _list_literal(value)
    if isinstance(value, Pairs):
        entries = [[encode(k), encode(v)] for k, v in value.items]
        return {"type": "map", "entries": entries}
    if isinstance(value, Record):
        fields = [[name, encode(v)] for name, v in value.fields]
        return {"type": "record", "fields": fields}
    if isinstance(value, Variant):
        literal: dict[str, Any] = {"type": "variant", "name": value.name}
        if value.payload is not NO_PAYLOAD:
            literal["payload"] = encode(value.payload)
        return literal
    return None


def _list_literal(value: list[object]) -> dict[str, Any]:
    """Return a list's literal: the of form for one scalar type, else items."""
    kinds = {_scalar_kind(item) for item in value}
    if value and len(kinds) == 1 and None not in kinds:
        kind = kinds.pop()
        assert kind is not None
        return {"type": "list", "of": kind, "value": [plain(item) for item in value]}
    return {"type": "list", "items": [encode(item) for item in value]}


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


#: The decoder of each type that is not a scalar, keyed by the type.
_DECODERS: Final[dict[str, Callable[[Mapping[str, Any]], object]]] = {
    "null": lambda _: None,
    "bytes": lambda literal: _bytes(literal.get("value")),
    "list": _list,
    "map": _map,
    "record": lambda literal: _record(literal.get("fields")),
    "variant": _variant,
    "reference": _reference,
}
