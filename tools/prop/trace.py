"""Traces: a case stated as the draws it makes and the machine steps it takes.

A trace lists entries in request order. A draw entry states a label and a
value. A step entry names an action, and states its client in a
concurrent section and the drain mark in the drain. entries() returns the
trace of a case, which is how a machine's counterexample lists it.

A body runs on a trace through Tracing, a provider whose values come from
the entries:

- A draw takes the next entry, which must be a draw entry with the draw's
  label. Its value runs backwards through the draw's generator, and the
  draw decodes the choices that result. A draw past the last entry takes
  its targets.
- A machine turns each step entry into the choices of one step, which
  Tracing serves as they are requested: the continue flag, the client and
  the index of the named action among the actions the step lists.
- Every other request takes its target.

A trace that the body cannot follow raises TraceError, which names the
entry: a draw entry with another label, a value that the generator cannot
produce, or a step entry that the machine cannot take at its position.
The error is not a failure of the case: it ends the run before any case
runs.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn, final

from .case import Case, Generator, Request, Step
from .choice import Choice, Value
from .inverse import CannotInvert, invert


@dataclass(frozen=True)
class Draw:
    """A draw entry: the label of a draw and the value it decoded."""

    label: str
    value: object


#: One entry of a trace.
Entry = Draw | Step


@final
class TraceError(ValueError):
    """An entry that the body cannot follow, named by its position.

    name is the draw's label for a reason of "label" or "value", and the
    step's action for a reason of "step".
    """

    def __init__(self, entry: int, name: str, reason: str) -> None:
        """Name the entry, the draw or the step, and the reason."""
        super().__init__(f"prop: trace entry {entry} ({name}): {reason}")
        self.entry = entry
        self.name = name
        self.reason = reason


def entries(case: Case) -> list[Entry]:
    """Return a case's draws and steps as a trace, in request order.

    A step comes before the draws the case recorded after it.
    """
    trace: list[Entry] = []
    steps = iter(case.steps)
    pending = next(steps, None)
    for number, drawn in enumerate(case.draws):
        while pending is not None and pending[0] <= number:
            trace.append(pending[1])
            pending = next(steps, None)
        trace.append(Draw(drawn.label, drawn.value))
    while pending is not None:
        trace.append(pending[1])
        pending = next(steps, None)
    return trace


@final
class Tracing:
    """A provider that serves the values of a trace's entries."""

    def __init__(self, trace: Sequence[Entry]) -> None:
        """Serve the entries of trace, from the first."""
        self._entries = list(trace)
        self._at = 0
        self._queue: deque[Choice] = deque()

    def value(self, request: Request, index: int) -> Value:
        """Return the next prepared value fitted to the request, or its target."""
        del index
        if self._queue:
            return request.bounds.coerce(self._queue.popleft())
        return request.bounds.target

    def drawing(self, generator: Generator, label: str) -> None:
        """Prepare the choices of the next entry for a draw under label.

        Raises:
            TraceError: the next entry is not a draw entry with label, or
                generator cannot produce its value.
        """
        if self._at == len(self._entries):
            return
        entry = self._entries[self._at]
        if not isinstance(entry, Draw) or entry.label != label:
            raise TraceError(self._at, label, "label")
        try:
            self._queue.extend(invert(generator, entry.value))
        except CannotInvert as bad:
            raise TraceError(self._at, label, "value") from bad
        self._at += 1

    def next_step(self) -> Step | None:
        """Return the next entry when it is a step entry."""
        if self._at == len(self._entries):
            return None
        entry = self._entries[self._at]
        return entry if isinstance(entry, Step) else None

    def actions(self) -> frozenset[str]:
        """Return the actions that the step entries from the next one on name."""
        rest = self._entries[self._at :]
        return frozenset(entry.action for entry in rest if isinstance(entry, Step))

    def prepare(self, *values: int) -> None:
        """Serve integer values to the next requests, before any target."""
        self._queue.extend(Choice("integer", value) for value in values)

    def take(self, *values: int) -> None:
        """Take the next entry, a step entry, and serve the values of its choices."""
        self.prepare(*values)
        self._at += 1

    def refuse(self) -> NoReturn:
        """Fail on the next entry, a step entry the machine cannot take.

        Raises:
            TraceError: always.
        """
        step = self.next_step()
        assert step is not None
        raise TraceError(self._at, step.action, "step")
