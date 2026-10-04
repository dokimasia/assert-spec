"""The corpus vectors of the history seam and the checker, computed from their inputs.

Each vector kind has a function that takes a case's inputs, as the corpus
states them, and returns the outputs this reference computes for them. The
renderer writes inputs and outputs together, as it does for the property
engine's vectors.

A seam vector states its calls as a script or as intervals. Its outputs are
the events in the history's JSON form, and the entry that the seam refuses:
the script entry whose call raises a usage error, or the entry that
from-intervals names in its error. An interval entry states a completion
kind and an end together, or neither for a pending call.

A linearizable vector names a model and states its history as a script,
with an optional budget, memo limit and number of workers. Its outputs are
whether the check passes and the detail of its record.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from prop.literal import decode
from prop.vectors import Vector, VectorError

from .linearizable import BUDGET, MEMO_LIMIT, Outcome, check
from .model import NAMED
from .seam import (
    Interval,
    IntervalError,
    Kind,
    ScriptError,
    document,
    from_intervals,
    record,
)

#: The completion kinds an interval entry may state.
COMPLETIONS: Final = frozenset({Kind.OK, Kind.FAIL, Kind.UNKNOWN})


def seam(case: Mapping[str, Any]) -> Vector:
    """Record a script or intervals, and return the events or the refused entry.

    Raises:
        VectorError: the vector states both a script and intervals, or
            neither, or an entry's end and completion kind disagree.
    """
    if ("script" in case) == ("intervals" in case):
        raise VectorError("history: a seam vector states a script or intervals")
    try:
        if "script" in case:
            events = record(case["script"])
        else:
            events = from_intervals([_interval(e) for e in case["intervals"]]).events()
    except (ScriptError, IntervalError) as refused:
        return {"events": None, "refused": refused.entry}
    return {"events": [document(event) for event in events], "refused": None}


def _interval(entry: Mapping[str, Any]) -> Interval:
    """Return the interval that one entry states.

    Raises:
        VectorError: the entry states an end without a completion kind, or
            a kind without an end, or a kind that completes no call.
    """
    end, kind = entry.get("end"), entry.get("kind")
    if (end is None) != (kind is None) or kind not in {None, *COMPLETIONS}:
        raise VectorError(
            f"history: an interval states a completion kind and an end, or "
            f"neither, not {entry!r}"
        )
    completion = None if kind is None else Kind(kind)
    return Interval(
        entry["client"],
        entry["operation"],
        tuple(decode(arg) for arg in entry["args"]),
        tuple(decode(key) for key in entry["keys"]),
        entry["start"],
        end,
        completion,
        decode(entry["output"]) if completion is Kind.OK else None,
        entry["error"] if completion in {Kind.FAIL, Kind.UNKNOWN} else "",
    )


def linearizable(case: Mapping[str, Any]) -> Vector:
    """Check a history against a named model, and return the verdict and its detail.

    workers is read and ignored: a check on more workers reports what a
    check on one reports.

    Raises:
        VectorError: the model is not a named one, the history's script is
            refused, or a limit or the workers is not a positive integer.
    """
    model = NAMED.get(str(case["model"]))
    if model is None:
        raise VectorError(f"history: {case['model']!r} is no named model")
    try:
        events = record(case["history"])
    except ScriptError as refused:
        raise VectorError(str(refused)) from refused
    _positive(case, "workers", 1)
    verdict = check(
        events,
        model,
        _positive(case, "budget", BUDGET),
        _positive(case, "memo-limit", MEMO_LIMIT),
    )
    expect = "pass" if verdict.outcome is Outcome.PASSED else "fail"
    return {"expect": expect, "detail": verdict.detail()}


def _positive(case: Mapping[str, Any], name: str, default: int) -> int:
    """Return a positive integer that a vector states, or default when it states none.

    Raises:
        VectorError: the value is not a positive integer.
    """
    value = case.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VectorError(f"history: {name} is {value!r}, not a positive integer")
    return value


#: The function that computes each kind's outputs.
KINDS: Final[dict[str, Callable[[Mapping[str, Any]], Vector]]] = {
    "seam": seam,
    "linearizable": linearizable,
}


def compute(kind: str, case: Mapping[str, Any]) -> Vector:
    """Return the outputs of one case of a kind.

    Raises:
        VectorError: the kind is unknown, or the case's inputs are malformed.
    """
    function = KINDS.get(kind)
    if function is None:
        raise VectorError(f"history: {kind!r} is no vector kind")
    try:
        return function(case)
    except KeyError as missing:
        raise VectorError(f"history: a {kind} vector lacks {missing}") from None
