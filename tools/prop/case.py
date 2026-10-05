"""A case: the choices one call of a body makes, recorded with their spans.

A generator never reads the random source itself. It asks the case for a
choice with bounds, and the case's provider supplies the value: drawn from
the source while generating, read back from recorded choices while
replaying, given by the edge phase, or decoded from a fuzzer's bytes by
the bridge. The case records every value with its request and the spans of
the generators that asked for it. The shrinker edits that record.

A body receives the case and uses draw(), assume(), classify(), note(),
observe(), random() and fail(), and records the calls it makes to a
subject in the case's history. The signals those members raise, Rejected
and Failed, and the signals of the case tree end the body, which must let
them pass.
"""

from __future__ import annotations

import collections.abc
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Protocol, final, runtime_checkable

from history.seam import History

from . import draw
from .choice import UINT64_MAX, Bounds, Choice, IntegerBounds, SequenceBounds, Value
from .source import Source

#: The most choices one case may make. A sequence counts as one choice
#: plus one for each element.
MAX_CHOICES: Final = 8192

#: A draw takes the case's source and returns a value inside the bounds
#: of the request that carries it.
Draw = Callable[[Source], Value]


class Rejected(Exception):
    """The signal that ends a case without a verdict, as StopIteration ends a loop.

    A rejected case is not counted and not shrunk. It is not an error.
    """


class Overrun(Rejected):
    """A case asked for more choices than its cap allows."""


@final
class Failed(Exception):
    """A body's failure, with the identity the shrinker keeps it by.

    Two failures are the same failure when their identities are equal. The
    message is not part of the identity.
    """

    def __init__(self, identity: str, message: str = "") -> None:
        """Fail with identity, and describe the failure with message."""
        super().__init__(f"{identity}: {message}" if message else identity)
        self.identity = identity
        self.message = message


@dataclass(frozen=True)
class Request:
    """One choice a generator asks for.

    draw generates the value from a source. A choice that decides the
    structure of what its generator returns, such as a collection's
    continue flag or a one-of's index, states edge: the value the edge
    phase gives it. A value choice has no edge.

    reuse marks a value of the integer and duration generators. While a
    case is generated, such a choice may take the value of an earlier one
    with the same bounds, as Generating states.
    """

    bounds: Bounds
    draw: Draw
    edge: int | None = None
    reuse: bool = False


class Provider(Protocol):
    """Where a case's values come from."""

    def value(self, request: Request, index: int) -> Value:
        """Return the value for the request at this index of the case."""
        ...


class Observer(Protocol):
    """What watches each choice as the case records it: the case tree."""

    def step(self, index: int, request: Request, value: Value) -> None:
        """Take the choice at index, or raise a signal that ends the body."""
        ...


class Generator(Protocol):
    """A domain, and how to decode one of its values from a case."""

    def decode(self, case: Case) -> object:
        """Ask the case for choices and return the value they decode to.

        Raises:
            Rejected: the choices decode to no value of the domain.
        """
        ...


@runtime_checkable
class Tracer(Protocol):
    """A provider that serves a trace, which each draw consults before it decodes."""

    def drawing(self, generator: Generator, label: str) -> None:
        """Prepare the values of the draw of generator under label."""
        ...


@dataclass(frozen=True)
class Step:
    """One step a machine took: its action's name, and where it ran.

    client is set for a step of a concurrent section, and drain for a step
    of the drain.
    """

    action: str
    client: int | None = None
    drain: bool = False


@dataclass(frozen=True)
class Place:
    """The part of a machine's steps that was running, and its step.

    part is swarm, setup, sequential, concurrent, drain or settle. position
    is the step's position in its part, from 0, and in the swarm the
    position of the action whose keep choice it is. It is None in setup,
    in settle, and while a concurrent section runs the steps it listed.
    action is the swarm choice's action or the step's action, and None
    before the step has chosen its action and where position is None.
    """

    part: str
    position: int | None = None
    action: str | None = None


@dataclass(frozen=True)
class Where:
    """Where a case made a request or observed a fingerprint.

    label is the label of the innermost draw that was running, and None
    outside a draw. place is the machine's part and step, and None outside
    a machine's steps.
    """

    label: str | None = None
    place: Place | None = None


@final
class Generating:
    """A provider that draws every value from a random source.

    A request marked reuse, whose bounds admit more than one value and
    match the bounds of an earlier reuse request of the same case, first
    takes coin(1, REUSE_ODDS). When it comes up, the value is one of the
    earlier values with those bounds, chosen with below(their count).
    Otherwise the request draws as usual. The second of two keys or two
    identifiers then equals the first in at least one case in four.

    The earlier values are those of the choices the case's record still
    contains, in record order. A choice that Case.rewind() removed offers
    no value, so a filter's next attempt never reuses a rejected one.
    """

    def __init__(self, source: Source) -> None:
        """Draw from source."""
        self._source = source
        self._earlier: dict[Bounds, list[tuple[int, Value]]] = {}

    def value(self, request: Request, index: int) -> Value:
        """Return the request's draw from the source, or an earlier value."""
        bounds = request.bounds
        forced = isinstance(bounds, IntegerBounds) and bounds.lo == bounds.hi
        if not request.reuse or forced:
            return request.draw(self._source)
        earlier = self._earlier.setdefault(request.bounds, [])
        while earlier and earlier[-1][0] >= index:
            earlier.pop()
        if earlier and self._source.coin(1, draw.REUSE_ODDS):
            _, value = earlier[self._source.below(len(earlier))]
        else:
            value = request.draw(self._source)
        earlier.append((index, value))
        return value


@final
class Replaying:
    """A provider that reads recorded choices back, in order.

    A recorded choice that does not fit the request is coerced by the
    request's bounds. A request past the last recorded choice takes the
    target of its bounds.
    """

    def __init__(self, choices: Sequence[Choice]) -> None:
        """Replay choices."""
        self._choices = choices

    def value(self, request: Request, index: int) -> Value:
        """Return the recorded value at index, fitted to the request."""
        if index >= len(self._choices):
            return request.bounds.target
        return request.bounds.coerce(self._choices[index])


@dataclass
class Span:
    """The choices one generator, element or entry made: [start, end)."""

    label: str
    start: int
    end: int
    depth: int
    parent: int | None


@dataclass(frozen=True)
class Drawn:
    """One value a body drew: its label, its generator and that generator's span."""

    label: str
    value: object
    span: int
    generator: Generator


@dataclass(frozen=True)
class Mark:
    """A point of a case's record that Case.rewind() returns to.

    choices, spans and draws are the lengths of the record at the point.
    """

    choices: int
    spans: int
    draws: int


def _cost(value: Value) -> int:
    """Return what a value counts towards the cap: one, plus each element."""
    return 1 + len(value) if isinstance(value, tuple) else 1


@final
class Case:
    """The record of one call of a body.

    wheres states where the case made each recorded request, and observed
    where it observed each fingerprint. A machine's steps set place while
    they run.

    A case is not safe for concurrent use.
    """

    def __init__(
        self,
        provider: Provider,
        max_choices: int = MAX_CHOICES,
        observer: Observer | None = None,
    ) -> None:
        """Start an empty case whose values come from provider.

        observer, when given, sees every choice after the case records it.
        A provider that is a Tracer is the case's tracer.
        """
        self._provider = provider
        self._max_choices = max_choices
        self._observer = observer
        self._cost = 0
        self.tracer: Tracer | None = provider if isinstance(provider, Tracer) else None
        self.choices: list[Choice] = []
        self.requests: list[Request] = []
        self.spans: list[Span] = []
        self._open: list[int] = []
        self.draws: list[Drawn] = []
        self.steps: list[tuple[int, Step]] = []
        self.labels: set[str] = set()
        self.notes: list[str] = []
        self.fingerprints: list[int] = []
        self.history = History()
        self.place: Place | None = None
        self.wheres: list[Where] = []
        self.observed: list[Where] = []
        self._drawing: list[str] = []

    def where(self) -> Where:
        """Return where the case is: the open draw's label and the machine's place."""
        return Where(self._drawing[-1] if self._drawing else None, self.place)

    def choose(self, request: Request) -> Value:
        """Return the value for request and record it.

        Raises:
            Overrun: the value takes the case past its cap.
        """
        value = self._provider.value(request, len(self.choices))
        self._cost += _cost(value)
        if self._cost > self._max_choices:
            raise Overrun
        self.choices.append(Choice(request.bounds.kind, value))
        self.requests.append(request)
        self.wheres.append(self.where())
        if self._observer is not None:
            self._observer.step(len(self.choices) - 1, request, value)
        return value

    def integer(
        self, bounds: IntegerBounds, *, edge: int | None = None, reuse: bool = False
    ) -> int:
        """Return an integer choice inside bounds, drawn as draw.integer draws.

        Raises:
            Overrun: the choice takes the case past its cap.
        """
        value = self.choose(
            Request(bounds, lambda source: draw.integer(source, bounds), edge, reuse)
        )
        assert isinstance(value, int)
        return value

    def sequence(self, bounds: SequenceBounds) -> tuple[int, ...]:
        """Return a sequence choice inside bounds, drawn as draw.sequence draws.

        Raises:
            Overrun: the sequence takes the case past its cap.
        """
        value = self.choose(
            Request(bounds, lambda source: draw.sequence(source, bounds))
        )
        assert isinstance(value, tuple)
        return value

    @contextmanager
    def span(
        self, label: str, start: int | None = None
    ) -> collections.abc.Generator[None, None, None]:
        """Record the choices made inside the block as one span.

        start moves the span's first choice back to an index the case
        recorded before the block, so that an element's span can include
        the continue flag decided before it. It is the current index when
        omitted.
        """
        parent = self._open[-1] if self._open else None
        index = len(self.spans)
        first = len(self.choices) if start is None else start
        self.spans.append(Span(label, first, first, len(self._open), parent))
        self._open.append(index)
        try:
            yield
        finally:
            self._open.pop()
            self.spans[index].end = len(self.choices)

    def mark(self) -> Mark:
        """Return the current point of the record, for rewind()."""
        return Mark(len(self.choices), len(self.spans), len(self.draws))

    def rewind(self, mark: Mark) -> None:
        """Remove every choice, span and draw recorded after mark.

        Every span opened after mark must have closed. The removed choices
        still count towards the cap, and an observer keeps them: the case
        tree walked them, and a removal cannot unwalk a step.
        """
        del self.choices[mark.choices :]
        del self.requests[mark.choices :]
        del self.wheres[mark.choices :]
        del self.spans[mark.spans :]
        del self.draws[mark.draws :]

    def draw(self, generator: Generator, label: str) -> object:
        """Return a value of generator and record it under label.

        The draw's span is the first span the generator opens. Two draws
        may share a label. A case with a tracer lets it prepare the draw's
        values first. Every request of the draw is made under its label.
        """
        if self.tracer is not None:
            self.tracer.drawing(generator, label)
        span = len(self.spans)
        self._drawing.append(label)
        try:
            value = generator.decode(self)
        finally:
            self._drawing.pop()
        self.draws.append(Drawn(label, value, span, generator))
        return value

    def step(self, taken: Step) -> None:
        """Record a step a machine took, after every draw recorded so far."""
        self.steps.append((len(self.draws), taken))

    def assume(self, condition: bool) -> None:
        """Reject the case when condition is false.

        Raises:
            Rejected: condition is false.
        """
        if not condition:
            raise Rejected

    def classify(self, label: str) -> None:
        """Count the case under label. A label counted twice counts once."""
        self.labels.add(label)

    def note(self, message: str) -> None:
        """Attach message to the case; only a failing case reports it."""
        self.notes.append(message)

    def observe(self, fingerprint: int) -> None:
        """Record a fingerprint of the subject's state, for a replay to compare."""
        self.fingerprints.append(fingerprint)
        self.observed.append(self.where())

    def random(self) -> int:
        """Return an integer choice over the whole unsigned 64-bit range.

        This is the value the language's random-source interface produces.
        """
        return self.integer(IntegerBounds(0, UINT64_MAX))

    def fail(self, identity: str, message: str = "") -> None:
        """Fail the case.

        Raises:
            Failed: always.
        """
        raise Failed(identity, message)
