# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

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
- A draw of a composite takes no entry when it starts, and its own draws
  take theirs. Once it decodes, it takes the next entry by its label and
  does not read the value, as a case records a composite after its draws.
- A draw through a composite, whose generator has a composite inside a
  one-of, an optional, a list, a dict, a filter or a recursive, takes the
  first draw entry with its label up to the next step entry. When its
  value runs backwards through a composite, the draws of the composite
  take the entries before it, and the draw takes it once it decodes.
- The choices of a draw serve the requests of its own generator. A draw
  inside it serves its own, and the outer requests continue after it.
- A machine turns each step entry into the choices of one step, which
  Tracing serves as they are requested: the continue flag, the client and
  the index of the named action among the actions the step lists.
- Every other request takes its target.

A trace that the body cannot follow raises TraceError, which names the
entry: a draw entry with another label, a value that the generator cannot
produce, or a step entry that the machine cannot take at its position.
The error is not a failure of the case: it ends the run before any case
runs.

The counterexample of a stored case is a trace too. A draw entry of it
records UNSTATED where no typed literal states the value, and the body
refuses such an entry. states() reports whether a case decodes to the
entries of such a counterexample.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, NoReturn, final, override

from . import literal
from .case import Case, Generator, Request, Step
from .choice import Choice, Value
from .generator import Composite
from .inverse import CannotInvert, invert_through, through_composite

if TYPE_CHECKING:
    from collections.abc import Sequence


@final
class _Unstated:
    """The value of a recorded draw entry that no typed literal states."""

    @override
    def __repr__(self) -> str:
        """Name the value."""
        return "UNSTATED"


#: The value of a recorded draw entry that no typed literal states.
UNSTATED: Final = _Unstated()


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


def states(recorded: Sequence[Entry], case: Case) -> bool:
    """Report whether case decodes to the entries of recorded, in order.

    Each draw entry has the label of its recorded entry, and the value where
    the recorded entry states one, as two typed literals compare. Each step
    entry has the action, the client and the drain mark of its recorded
    entry. A recorded counterexample without a step entry records the draws
    alone, so the steps of case do not count against it.
    """
    replayed = entries(case)
    if not any(isinstance(entry, Step) for entry in recorded):
        replayed = [entry for entry in replayed if isinstance(entry, Draw)]
    return len(replayed) == len(recorded) and all(
        _same(r, p) for r, p in zip(recorded, replayed, strict=True)
    )


def _same(recorded: Entry, replayed: Entry) -> bool:
    """Report whether replayed is the entry that recorded records."""
    if isinstance(recorded, Step) or isinstance(replayed, Step):
        return recorded == replayed
    if recorded.label != replayed.label:
        return False
    return recorded.value is UNSTATED or literal.encode(
        recorded.value
    ) == literal.encode(replayed.value)


@dataclass
class _Open:
    """A draw in progress: the choices of its requests, and how it ends.

    end is the index of the entry that a draw through a composite takes once
    it decodes, and by_label marks a composite, which takes the next entry
    by its label alone then. Every other draw has taken its entry already.
    """

    queue: deque[Choice] = field(default_factory=deque)
    end: int | None = None
    by_label: bool = False


@final
class Tracing:
    """A provider that serves the values of a trace's entries."""

    def __init__(self, trace: Sequence[Entry]) -> None:
        """Serve the entries of trace, from the first.

        The first open draw stands for the requests outside every draw, such
        as the steps of a machine.
        """
        self._entries = list(trace)
        self._at = 0
        self._open: list[_Open] = [_Open()]

    def value(self, request: Request, index: int) -> Value:
        """Return the next value of the innermost open draw, or the request's target."""
        del index
        queue = self._open[-1].queue
        if queue:
            return request.bounds.coerce(queue.popleft())
        return request.bounds.target

    def drawing(self, generator: Generator, label: str) -> None:
        """Prepare the choices of the entry of a draw under label.

        A composite takes no entry here. Its draws take theirs, and it takes
        its own entry once it decodes. A draw through a composite takes the
        first entry with its label up to the next step entry. Every other
        draw takes the next entry.

        Raises:
            TraceError: the entry is not a draw entry with label, it states
                no value, or generator cannot produce its value.
        """
        if isinstance(generator, Composite):
            self._open.append(_Open(by_label=True))
            return
        if self._at == len(self._entries):
            self._open.append(_Open())
            return
        through = through_composite(generator)
        at = self._find(label) if through else self._at
        entry = self._entries[at]
        if not isinstance(entry, Draw) or entry.label != label:
            raise TraceError(self._at, label, "label")
        if entry.value is UNSTATED:
            raise TraceError(at, label, "value")
        try:
            choices, composite = invert_through(generator, entry.value)
        except CannotInvert as bad:
            raise TraceError(at, label, "value") from bad
        if composite:
            self._open.append(_Open(deque(choices), end=at))
            return
        if at != self._at:
            raise TraceError(self._at, label, "label")
        self._at += 1
        self._open.append(_Open(deque(choices)))

    def drawn(self, generator: Generator, label: str) -> None:
        """End the draw under label, and take its entry once it decodes.

        A composite takes the next entry by its label alone. A draw through a
        composite takes its entry, which must be the next one, once the draws
        of its composites have taken the entries before it.

        Raises:
            TraceError: the next entry is not a draw entry with label, or it
                is not the entry of the draw. When a draw inside took the
                entry of the draw, the error names that entry.
        """
        del generator
        ended = self._open.pop()
        if ended.by_label and self._at < len(self._entries):
            self._take(label)
        if ended.end is not None:
            if self._at != ended.end:
                raise TraceError(min(self._at, ended.end), label, "label")
            self._take(label)

    def _find(self, label: str) -> int:
        """Return the index of the first draw entry with label before a step entry.

        The next entry is returned when no such entry exists, so the draw
        refuses it.
        """
        for at in range(self._at, len(self._entries)):
            entry = self._entries[at]
            if isinstance(entry, Step):
                break
            if entry.label == label:
                return at
        return self._at

    def _take(self, label: str) -> Draw:
        """Take the next entry, a draw entry with label.

        Raises:
            TraceError: the next entry is not a draw entry with label.
        """
        entry = self._entries[self._at]
        if not isinstance(entry, Draw) or entry.label != label:
            raise TraceError(self._at, label, "label")
        self._at += 1
        return entry

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
        self._open[-1].queue.extend(Choice("integer", value) for value in values)

    def take(self, *values: int) -> None:
        """Take the next entry, a step entry, and serve the values of its choices."""
        self.prepare(*values)
        self._at += 1

    def finished(self) -> bool:
        """Report whether the draws and the steps took every entry."""
        return self._at == len(self._entries)

    def refuse(self) -> NoReturn:
        """Fail on the next entry, a step entry the machine cannot take.

        Raises:
            TraceError: the next entry is a step entry.
            ValueError: the next entry is not a step entry.
        """
        step = self.next_step()
        if step is None:
            msg = f"prop: trace entry {self._at} is not a step entry"
            raise ValueError(msg)
        raise TraceError(self._at, step.action, "step")
