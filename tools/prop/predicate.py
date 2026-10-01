"""Predicates as data: the conditions that bodies and filters state.

A predicate is a JSON object with a ``kind`` and its parameters, and
``"not": true`` negates it:

- ``always`` and ``never``.
- ``equals`` value: a value equal to the typed literal value.
- ``at-least`` n: a number at least n.
- ``divisible-by`` n: an integer divisible by n.
- ``sum-above`` n: a list of numbers whose sum is above n.
- ``length-at-least`` n: a list, string, byte string or dict with at
  least n elements.
- ``contains`` value: a list with an element equal to the typed literal
  value, or a string or byte string that contains it.
- ``not-sorted``: a list that is not in ascending order.
- ``has-duplicate``: a list with two equal elements.

Equal means equal under value.canonical(). A body classifies, rejects
and fails by predicates, and a ``filter`` generator keeps the values for
which its predicate is true.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import pairwise
from typing import Any, Final

from . import literal
from .value import Pairs, canonical

Predicate = Callable[[object], bool]


class PredicateError(ValueError):
    """A predicate spec the vocabulary does not define, or that lacks a parameter."""


def predicate(spec: object) -> Predicate:
    """Return the predicate a spec states.

    Raises:
        PredicateError: the spec names no predicate, or lacks a parameter.
    """
    if not isinstance(spec, Mapping):
        raise PredicateError(f"prop: {spec!r} is not a predicate")
    kind = spec.get("kind")
    factory = _PREDICATES.get(str(kind))
    if factory is None:
        raise PredicateError(f"prop: {kind!r} names no predicate")
    try:
        holds = factory(spec)
    except KeyError as missing:
        raise PredicateError(f"prop: predicate {kind!r} lacks {missing}") from None
    if spec.get("not", False) is True:
        return lambda value: not holds(value)
    return holds


def _number(value: object) -> int | float:
    """Return a predicate's numeric parameter: an integer, or a float."""
    if isinstance(value, float):
        return value
    return literal.integer(value)


def _is_number(value: object) -> bool:
    """Report whether value is an int or a float, and not a bool."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _always(spec: Mapping[str, Any]) -> Predicate:
    """Hold for every value."""
    del spec
    return lambda value: True


def _never(spec: Mapping[str, Any]) -> Predicate:
    """Hold for no value."""
    del spec
    return lambda value: False


def _equals(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a value equal to the typed literal value."""
    key = canonical(literal.decode(spec["value"]))
    return lambda value: canonical(value) == key


def _at_least(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a number at least n."""
    n = _number(spec["n"])

    def holds(value: object) -> bool:
        return isinstance(value, int | float) and _is_number(value) and value >= n

    return holds


def _divisible_by(spec: Mapping[str, Any]) -> Predicate:
    """Hold for an integer divisible by n."""
    n = literal.integer(spec["n"])

    def holds(value: object) -> bool:
        return isinstance(value, int) and _is_number(value) and value % n == 0

    return holds


def _sum_above(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a list of numbers whose sum is above n."""
    n = _number(spec["n"])

    def holds(value: object) -> bool:
        if not isinstance(value, list):
            return False
        return sum(item for item in value if isinstance(item, int | float)) > n

    return holds


def _length_at_least(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a collection with at least n elements."""
    n = literal.integer(spec["n"])

    def holds(value: object) -> bool:
        if isinstance(value, Pairs):
            return len(value.items) >= n
        return isinstance(value, list | str | bytes) and len(value) >= n

    return holds


def _contains(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a list with an element equal to value, or text that contains it."""
    wanted = literal.decode(spec["value"])
    key = canonical(wanted)

    def holds(value: object) -> bool:
        if isinstance(value, list):
            return any(canonical(item) == key for item in value)
        if isinstance(value, str) and isinstance(wanted, str):
            return wanted in value
        if isinstance(value, bytes) and isinstance(wanted, bytes):
            return wanted in value
        return False

    return holds


def _not_sorted(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a list that is not in ascending order."""
    del spec

    def holds(value: object) -> bool:
        if not isinstance(value, list):
            return False
        return any(b < a for a, b in pairwise(value))

    return holds


def _has_duplicate(spec: Mapping[str, Any]) -> Predicate:
    """Hold for a list with two equal elements."""
    del spec

    def holds(value: object) -> bool:
        if not isinstance(value, list):
            return False
        return len({canonical(item) for item in value}) < len(value)

    return holds


#: The predicates of the vocabulary, keyed by kind.
_PREDICATES: Final[dict[str, Callable[[Mapping[str, Any]], Predicate]]] = {
    "always": _always,
    "never": _never,
    "equals": _equals,
    "at-least": _at_least,
    "divisible-by": _divisible_by,
    "sum-above": _sum_above,
    "length-at-least": _length_at_least,
    "contains": _contains,
    "not-sorted": _not_sorted,
    "has-duplicate": _has_duplicate,
}
