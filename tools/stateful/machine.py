"""Machines: a model of a subject, actions over it, and the steps a case takes.

A machine has actions in a fixed order, and optionally a model, an
invariant and a settle check. steps() runs a machine inside a body in six
parts, in order, and records every decision as a choice of the case:

1. Swarm. With swarm on, one choice per action, in order, decides whether
   the case keeps the action, drawn as draw.keep draws with probability
   SWARM: 1 keeps it and 0 disables it, with target 0 and edge 1. While
   no earlier action is kept, the last choice has the bounds [1, 1]. A
   disabled action takes no step of the case outside the drain.
2. Setup. A machine with a model checks the history the case recorded,
   as after every step. Its state is the first of the model states after
   the order the check found. A machine without a model has the absent
   state, None. The invariant runs.
3. Sequential steps, on client 0. Before each step the machine lists the
   kept actions that are enabled in every state the last check left,
   calling enabled once per state. With none, the steps end and record no
   flag. Otherwise a continue flag decides, by the collection rule with
   minimum 0, max as the maximum and mean as the average. An index into
   the list then chooses the action, drawn as draw.weighted draws with the
   actions' weights, with target 0 and edge 0. The step is a span
   labelled with the action's name, from its flag to the end of its run.
   Inside it, input requests the step's input from the state, and run
   calls the subject. After the span the machine checks the history, and
   the invariant runs.
4. A concurrent section, with two clients or more. The section lists its
   steps before any of them runs. Each step is a continue flag by the
   collection rule with the maximum concurrent, a client uniform over 0
   to clients with target 0 and edge 0, and an index into the kept actions
   that state no enabled. Its span covers these and its input, requested
   from the state after the sequential steps. Client 0 then runs its
   steps in order. The scheduler then runs one task for each other client
   that has a step, spawned in client order, which runs that client's
   steps in order. The machine checks the history once every task ends.
5. The drain. The actions with drain set, whether or not swarm kept them,
   take steps until none is enabled or max steps have run. A drain step
   is a sequential step without its flag: an index, its span, its input
   and its run on client 0, then the check and the invariant.
6. Settling. settle runs on the state of the last check, and the
   invariant runs a last time.

A check that the history fails, violated or undecided, fails the case
with the identity CHECK and the checker's record as its message. The
check treats the whole history as one partition. Every part that records
a call ends with a check, so the last check has read the whole history
when settle runs.

An action's run returns None, or a generator when the subject yields to
the task scheduler. On client 0 the machine runs the generator to its
end, and each yield continues at once. In a concurrent section the
client's task yields where the generator yields.

A case whose provider is a Tracing follows its trace: the swarm keeps the
actions that the step entries name, and each step entry becomes the
choices of one step. A step entry that the machine cannot take at its
position raises TraceError: an action that the step's list lacks, a step
past the section's maximum, a client outside the clients, a concurrent
step for a machine with one client, and a drain step after the drain.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, final

from history.linearizable import Outcome, whole
from history.model import Model
from prop import draw
from prop.case import Case, Request, Step
from prop.choice import IntegerBounds
from prop.collection import Sizes, more
from prop.trace import Tracing

from .scheduler import Scheduler

#: The identity of a failure of the check after a step.
CHECK: Final = "linearizable"

#: The probability with which swarm keeps an action, before draw.keep
#: conditions the choices on keeping one.
SWARM: Final = Fraction(1, 2)

#: What an action's run returns when its subject yields to the scheduler.
Task = Iterator[None]


@dataclass(frozen=True)
class Action:
    """A named action: how often it runs, when, with what input, and what it does.

    run calls the subject with the case, the client and the input, and
    records each call in the case's history. enabled, when stated, removes
    the action from a sequential step's list in a state where it is false.
    A drain action also takes the steps of the drain.
    """

    name: str
    run: Callable[[Case, int, object], Task | None]
    weight: int = 1
    enabled: Callable[[object], bool] | None = None
    drain: bool = False
    input: Callable[[Case, object], object] | None = None

    def __post_init__(self) -> None:
        """Refuse a weight below 1.

        Raises:
            ValueError: the weight is below 1.
        """
        if self.weight < 1:
            raise ValueError(f"stateful: action {self.name!r} has weight {self.weight}")


@dataclass(frozen=True)
class Machine:
    """A subject's actions, in the order that makes the earlier one simpler.

    model, when stated, is the model that the history is checked against
    after every step. invariant runs after setup and after every
    sequential and drain step, and settle once after the drain.
    """

    actions: tuple[Action, ...]
    model: Model | None = None
    invariant: Callable[[Case, object], None] | None = None
    settle: Callable[[Case, object], None] | None = None

    def __post_init__(self) -> None:
        """Refuse two actions with one name, which a trace could not tell apart.

        Raises:
            ValueError: two actions share a name.
        """
        names = [action.name for action in self.actions]
        if len(set(names)) != len(names):
            raise ValueError(f"stateful: the actions {names} repeat a name")


@dataclass(frozen=True)
class Options:
    """How many steps a case takes, and on how many clients.

    clients counts the clients of the concurrent section besides client 0,
    so 1 runs no section. The reference runs a section only as tasks of
    scheduler, which a machine with two clients or more must state.
    """

    mean: int = 30
    max: int = 100
    swarm: bool = True
    clients: int = 1
    concurrent: int = 16
    scheduler: Scheduler | None = None

    def __post_init__(self) -> None:
        """Refuse negative counts, no client, and a section without a scheduler.

        Raises:
            ValueError: a count is negative, clients is below 1, or a
                concurrent section has no scheduler.
        """
        if min(self.mean, self.max, self.concurrent) < 0 or self.clients < 1:
            raise ValueError(f"stateful: {self} states a count below its minimum")
        if self.clients > 1 and self.scheduler is None:
            raise ValueError("stateful: a concurrent section needs a scheduler")


def steps(case: Case, machine: Machine, options: Options | None = None) -> None:
    """Run a machine's steps in case, with options or the defaults.

    Raises:
        Failed: a check, the invariant, settle or an action failed the case.
        TraceError: the case follows a trace that the machine cannot.
    """
    _Run(case, machine, options or Options()).run()


def _finish(task: Task | None) -> None:
    """Run a step's generator to its end on client 0, where a yield continues."""
    if task is not None:
        for _ in task:
            pass


def _keep(kept: bool, remaining: int) -> Request:
    """Return the swarm choice of an action, given the choices before it."""
    bounds = IntegerBounds(1, 1) if not kept and remaining == 1 else IntegerBounds(0, 1)
    return Request(
        bounds, lambda source: draw.keep(source, SWARM, kept, remaining), edge=1
    )


@final
class _Run:
    """One run of a machine's steps in one case."""

    def __init__(self, case: Case, machine: Machine, options: Options) -> None:
        """Start at the absent state, before the swarm."""
        self._case = case
        self._machine = machine
        self._options = options
        self._trace = case.tracer if isinstance(case.tracer, Tracing) else None
        self._states: tuple[object, ...] = (None,)

    def run(self) -> None:
        """Run the six parts in order."""
        kept = self._swarm()
        self._check()
        self._invariant()
        self._sequential(kept)
        self._concurrent(kept)
        self._drain()
        if self._machine.settle is not None:
            self._machine.settle(self._case, self._states[0])
        self._invariant()

    def _swarm(self) -> list[Action]:
        """Return the actions the case keeps, in order."""
        actions = self._machine.actions
        if not self._options.swarm:
            return list(actions)
        trace = self._trace
        named = frozenset[str]() if trace is None else trace.actions()
        kept: list[Action] = []
        for position, action in enumerate(actions):
            if trace is not None:
                trace.prepare(1 if action.name in named else 0)
            if self._case.choose(_keep(bool(kept), len(actions) - position)):
                kept.append(action)
        return kept

    def _sequential(self, kept: list[Action]) -> None:
        """Take sequential steps until the list is empty or a flag stops them."""
        case, options = self._case, self._options
        count = 0
        while True:
            available = self._available(kept)
            start = len(case.choices)
            if self._trace is not None:
                self._follow_sequential(self._trace, available, count)
            if not available:
                return
            if not more(case, count, Sizes(0, options.max), average=options.mean):
                return
            action = available[self._index(available)]
            with case.span(action.name, start):
                case.step(Step(action.name))
                _finish(action.run(case, 0, self._input(action)))
            self._check()
            self._invariant()
            count += 1

    def _concurrent(self, kept: list[Action]) -> None:
        """List the concurrent section's steps, run them, and check the history."""
        case, options = self._case, self._options
        if options.clients == 1:
            if self._trace is not None:
                self._refuse_concurrent(self._trace)
            return
        eligible = [action for action in kept if action.enabled is None]
        planned: list[list[tuple[Action, object]]] = [
            [] for _ in range(options.clients + 1)
        ]
        count = 0
        while True:
            start = len(case.choices)
            if self._trace is not None:
                self._follow_concurrent(self._trace, eligible, count)
            if not eligible or not more(case, count, Sizes(0, options.concurrent)):
                break
            client = self._client()
            action = eligible[self._index(eligible)]
            with case.span(action.name, start):
                case.step(Step(action.name, client=client))
                planned[client].append((action, self._input(action)))
            count += 1
        for action, value in planned[0]:
            _finish(action.run(case, 0, value))
        scheduler = options.scheduler
        assert scheduler is not None
        for client in range(1, options.clients + 1):
            if planned[client]:
                scheduler.spawn(self._task(client, planned[client]))
        scheduler.run()
        self._check()

    def _task(self, client: int, planned: list[tuple[Action, object]]) -> Task:
        """Run one client's steps in order, yielding where their subject yields."""
        for action, value in planned:
            task = action.run(self._case, client, value)
            if task is not None:
                yield from task

    def _drain(self) -> None:
        """Take drain steps until no drain action is enabled or max steps ran."""
        case = self._case
        drains = [action for action in self._machine.actions if action.drain]
        count = 0
        while True:
            available = self._available(drains) if count < self._options.max else []
            if self._trace is not None:
                self._follow_drain(self._trace, available)
            if not available:
                return
            start = len(case.choices)
            action = available[self._index(available)]
            with case.span(action.name, start):
                case.step(Step(action.name, drain=True))
                _finish(action.run(case, 0, self._input(action)))
            self._check()
            self._invariant()
            count += 1

    def _available(self, actions: Iterable[Action]) -> list[Action]:
        """Return the actions enabled in every state, calling enabled once per state."""
        available: list[Action] = []
        for action in actions:
            enabled = action.enabled
            if enabled is None or all([enabled(state) for state in self._states]):
                available.append(action)
        return available

    def _index(self, actions: Sequence[Action]) -> int:
        """Return the case's choice of an action, by weight, from a list."""
        weights = [action.weight for action in actions]
        index = self._case.choose(
            Request(
                IntegerBounds(0, len(actions) - 1),
                lambda source: draw.weighted(source, weights),
                edge=0,
            )
        )
        assert isinstance(index, int)
        return index

    def _client(self) -> int:
        """Return the case's choice of a concurrent step's client."""
        clients = self._options.clients
        client = self._case.choose(
            Request(
                IntegerBounds(0, clients),
                lambda source: source.below(clients + 1),
                edge=0,
            )
        )
        assert isinstance(client, int)
        return client

    def _input(self, action: Action) -> object:
        """Return the input that action requests from the state, or None."""
        if action.input is None:
            return None
        return action.input(self._case, self._states[0])

    def _check(self) -> None:
        """Check the history with the model, and keep the states the check left.

        Raises:
            Failed: the check is violated or undecided.
        """
        model = self._machine.model
        if model is None:
            return
        verdict, states = whole(self._case.history.events(), model)
        if verdict.outcome is not Outcome.PASSED:
            self._case.fail(CHECK, json.dumps(verdict.detail()))
        self._states = states

    def _invariant(self) -> None:
        """Run the invariant on the state, when the machine has one."""
        if self._machine.invariant is not None:
            self._machine.invariant(self._case, self._states[0])

    def _follow_sequential(
        self, trace: Tracing, available: list[Action], count: int
    ) -> None:
        """Serve the flag and index of a sequential step entry, if one is next.

        Raises:
            TraceError: the step's action is not in the list, or the steps
                are at their maximum.
        """
        step = trace.next_step()
        if step is None or step.client is not None or step.drain:
            return
        names = [action.name for action in available]
        if count == self._options.max or step.action not in names:
            trace.refuse()
        trace.take(1, names.index(step.action))

    def _refuse_concurrent(self, trace: Tracing) -> None:
        """Refuse a concurrent step entry where the machine runs no section.

        Raises:
            TraceError: the next entry is a concurrent step.
        """
        step = trace.next_step()
        if step is not None and step.client is not None and not step.drain:
            trace.refuse()

    def _follow_concurrent(
        self, trace: Tracing, eligible: list[Action], count: int
    ) -> None:
        """Serve the flag, client and index of a concurrent step entry, if one is next.

        Raises:
            TraceError: the step's action is not among the eligible
                actions, its client is outside the clients, or the section
                is at its maximum.
        """
        step = trace.next_step()
        if step is None or step.client is None or step.drain:
            return
        names = [action.name for action in eligible]
        clients = self._options.clients
        full = count == self._options.concurrent
        if full or not 0 <= step.client <= clients or step.action not in names:
            trace.refuse()
        trace.take(1, step.client, names.index(step.action))

    def _follow_drain(self, trace: Tracing, available: list[Action]) -> None:
        """Serve the index of a drain step entry, if one is next.

        Raises:
            TraceError: the step's action is not in the list, which is
                empty once the drain has ended.
        """
        step = trace.next_step()
        if step is None or not step.drain:
            return
        names = [action.name for action in available]
        if step.action not in names:
            trace.refuse()
        trace.take(names.index(step.action))
