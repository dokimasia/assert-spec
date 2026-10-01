"""Bodies as data: the properties the corpus states without code.

A body spec draws one value, labelled DRAWN, from its ``draw`` generator.
It then classifies the case under each ``classify`` label whose predicate
holds, rejects the case when ``rejects-when`` holds, and fails it with
the identity of the first ``fails`` entry whose predicate holds, in that
order. The predicate module states the predicates.

Three named bodies state what no predicate can:

- DRAWS_NOTHING requests no input.
- DIVERGES draws an integer in [0, 9] on its first call and a boolean on
  every later call.
- FAILS_ONCE draws an integer in [0, 10^9] and fails with identity
  ``once`` the first time it draws a value above 1,000.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .case import Case
from .execution import Body
from .generator import build
from .predicate import predicate

#: The label of a body's one draw.
DRAWN: Final = "value"

#: The named bodies.
DRAWS_NOTHING: Final = "draws-nothing"
DIVERGES: Final = "diverges"
FAILS_ONCE: Final = "fails-once"

#: The identity and the threshold of FAILS_ONCE.
ONCE: Final = "once"
ONCE_ABOVE: Final = 1000

#: The generators the named bodies draw from.
_DIGIT: Final = {"gen": "integer", "min": 0, "max": 9}
_BOOLEAN: Final = {"gen": "boolean"}
_WIDE: Final = {"gen": "integer", "min": 0, "max": 10**9}


class BodyError(ValueError):
    """A body spec the vocabulary does not define."""


def build_body(spec: Mapping[str, Any]) -> Body:
    """Return a fresh body for a spec; a named body keeps its own state.

    Raises:
        BodyError: the spec names no body, or misstates an entry.
        PredicateError: a predicate is malformed.
        SpecError: the draw names no generator of the vocabulary.
    """
    kind = spec.get("kind")
    if kind == DRAWS_NOTHING:
        return _nothing
    if kind == DIVERGES:
        return _diverging()
    if kind == FAILS_ONCE:
        return _failing_once()
    if kind is not None:
        raise BodyError(f"prop: {kind!r} names no body")
    return _drawing(spec)


def _nothing(case: Case) -> None:
    """Request no input."""
    del case


def _diverging() -> Body:
    """Return a body that requests other bounds after its first call."""
    calls: list[None] = []
    digit, boolean = build(_DIGIT), build(_BOOLEAN)

    def body(case: Case) -> None:
        case.draw(boolean if calls else digit, DRAWN)
        calls.append(None)

    return body


def _failing_once() -> Body:
    """Return a body that fails only the first time it draws above ONCE_ABOVE."""
    failed: list[None] = []
    wide = build(_WIDE)

    def body(case: Case) -> None:
        value = case.draw(wide, DRAWN)
        assert isinstance(value, int)
        if value > ONCE_ABOVE and not failed:
            failed.append(None)
            case.fail(ONCE)

    return body


def _drawing(spec: Mapping[str, Any]) -> Body:
    """Return a body that draws once, then classifies, rejects and fails."""
    generator = build(spec.get("draw"))
    classify = {
        _name(label): predicate(when)
        for label, when in _mapping(spec, "classify").items()
    }
    rejects = predicate(spec["rejects-when"]) if "rejects-when" in spec else None
    try:
        fails = [
            (_name(entry["identity"]), predicate(entry["when"]))
            for entry in _list(spec, "fails")
        ]
    except KeyError as missing:
        raise BodyError(f"prop: a fails entry lacks {missing}") from None

    def body(case: Case) -> None:
        value = case.draw(generator, DRAWN)
        for label, holds in classify.items():
            if holds(value):
                case.classify(label)
        if rejects is not None:
            case.assume(not rejects(value))
        for identity, holds in fails:
            if holds(value):
                case.fail(identity)

    return body


def _name(value: object) -> str:
    """Return a label or an identity, which a spec states as a string.

    Raises:
        BodyError: value is not a string, such as a YAML word read as a
            boolean.
    """
    if not isinstance(value, str):
        raise BodyError(f"prop: {value!r} is not a label or an identity")
    return value


def _mapping(spec: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Return an optional object parameter, empty when absent."""
    value = spec.get(key, {})
    if not isinstance(value, Mapping):
        raise BodyError(f"prop: {key} is {value!r}, not an object")
    return value


def _list(spec: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    """Return an optional list parameter of objects, empty when absent."""
    value = spec.get(key, [])
    if not isinstance(value, list) or not all(isinstance(e, Mapping) for e in value):
        raise BodyError(f"prop: {key} is {value!r}, not a list of objects")
    return value
