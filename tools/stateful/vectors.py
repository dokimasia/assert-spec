"""The corpus vectors of machines, computed from their inputs.

The machines kind has a function that takes a case's inputs, as the
corpus states them, and returns the outputs this reference computes for
them. The renderer writes inputs and outputs together, as it does for the
property engine's vectors.

A machines vector names a machine subject, and may state the options of
its steps as its setup, the settings of the run, and a trace. A trace
entry is written as the property engine's counterexample writes it: a
draw entry, ``{"label": …, "value": …}``, or a step entry, ``{"step": …}``
with ``"client"`` in a concurrent section and ``"drain": true`` in the
drain.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Final

from prop import literal
from prop.case import Step
from prop.runner import run
from prop.trace import Draw, Entry, TraceError
from prop.vectors import Vector, VectorError, detail, run_settings

from . import subjects
from .scheduler import Pct, Strategy, Uniform


def machines(case: Mapping[str, Any]) -> Vector:
    """Run a named machine subject, and return the detail of the run.

    setup states the options of the subject's steps, and settings those of
    the run. A vector with a trace runs it first, as the Draws option does.
    A trace that the body cannot follow ends the run before any case runs,
    and the vector states the entry, the name and the reason as its error.

    Raises:
        VectorError: the subject is not named, the strategy is neither
            uniform nor a pct depth, or the trace is no list of entries.
    """
    name = str(case["subject"])
    if name not in subjects.SUBJECTS:
        raise VectorError(f"stateful: {name!r} names no machine subject")
    settings = run_settings(case.get("settings", {}))
    if "trace" in case:
        settings = replace(settings, traces=(_trace(case["trace"]),))
    body = subjects.body(name, _setup(case.get("setup", {})))
    try:
        outcome = run(body, settings)
    except TraceError as refused:
        error = {"entry": refused.entry, "name": refused.name, "reason": refused.reason}
        return {"detail": None, "error": error}
    return {"detail": detail(outcome), "error": None}


def _setup(written: Mapping[str, Any]) -> subjects.Setup:
    """Return the options a machines vector states, with the defaults for the rest.

    Raises:
        VectorError: the strategy is neither uniform nor a pct depth.
    """
    default = subjects.Setup()
    return subjects.Setup(
        mean=int(written.get("mean", default.mean)),
        max=int(written.get("max", default.max)),
        swarm=bool(written.get("swarm", default.swarm)),
        clients=int(written.get("clients", default.clients)),
        concurrent=int(written.get("concurrent", default.concurrent)),
        strategy=_strategy(written.get("strategy", "uniform")),
    )


def _strategy(written: object) -> Strategy:
    """Return the strategy a setup states: uniform, or {"pct": depth}.

    Raises:
        VectorError: the strategy is neither.
    """
    if written == "uniform":
        return Uniform()
    if isinstance(written, Mapping) and set(written) == {"pct"}:
        return Pct(literal.integer(written["pct"]))
    raise VectorError(f"stateful: {written!r} is no strategy")


def _trace(written: object) -> tuple[Entry, ...]:
    """Return the trace a vector states, as entries.

    Raises:
        VectorError: the trace is no list of draw and step entries.
    """
    if not isinstance(written, list):
        raise VectorError(f"stateful: a trace is {written!r}, not a list")
    trace: list[Entry] = []
    for entry in written:
        if isinstance(entry, Mapping) and set(entry) == {"label", "value"}:
            trace.append(Draw(str(entry["label"]), literal.decode(entry["value"])))
        elif isinstance(entry, Mapping) and "step" in entry:
            client = entry.get("client")
            trace.append(
                Step(
                    str(entry["step"]),
                    None if client is None else literal.integer(client),
                    entry.get("drain") is True,
                )
            )
        else:
            raise VectorError(f"stateful: {entry!r} is no trace entry")
    return tuple(trace)


#: The function that computes each kind's outputs.
KINDS: Final[dict[str, Callable[[Mapping[str, Any]], Vector]]] = {
    "machines": machines,
}


def compute(kind: str, case: Mapping[str, Any]) -> Vector:
    """Return the outputs of one case of a kind.

    Raises:
        VectorError: the kind is unknown, or the case's inputs are malformed.
    """
    function = KINDS.get(kind)
    if function is None:
        raise VectorError(f"stateful: {kind!r} is no vector kind")
    try:
        return function(case)
    except KeyError as missing:
        raise VectorError(f"stateful: a {kind} vector lacks {missing}") from None
