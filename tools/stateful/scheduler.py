# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""The task scheduler: which ready task runs next, decided by choices of the case.

A task is a generator. A released task runs until it yields, parks or
returns. A task that yields None becomes ready again, after every task
that is ready. A task parks by yielding what wait() or the sleep() of the
scheduler's clock returns: a Wait parks it until its condition returns
true, and a Sleep until the clock has passed its duration. A wait whose
condition is true, and a sleep of no time, continue the turn at once.
spawn() makes a task ready, and run() releases one ready task at a time
until none is ready. A task may spawn others while it runs.

The scheduler checks its parked tasks at the start of each run() and each
advance(), after each turn, and after each move of its clock. It makes
ready, after every ready task, each sleeping task whose deadline the clock
has passed, by deadline and then in the order of the sleeps, and then each
waiting task whose condition returns true, in the order of the waits. A
task that yields joins the ready tasks before the tasks that the end of
its turn wakes.

The clock of a scheduler starts at EPOCH, and only advance() moves it.
advance() releases tasks as run() does, then moves the clock to the
earliest deadline of a parked sleep, or to its end time when no deadline
is due before it, wakes the tasks that the move makes due, and continues
until the clock reads the end time and no task is ready.

Two strategies choose the task to release:

- Uniform: each release chooses an index into the ready tasks, in the
  order they became ready, uniformly and with target 0. A release with
  one ready task records its choice and consumes nothing.
- Pct(depth): each task receives a priority when it is spawned, an
  integer in [0, 2^64 - 1] drawn as draw.integer draws, with target 0,
  and keeps it when it yields or parks. Each run() and each advance()
  starts with depth - 1 change points, each an optional count: a presence
  choice with target absent and, when present, an integer in
  [0, 2^64 - 1]. The ready task with the highest priority runs, the
  earliest ready among equals, and a release makes no choice. At a change
  point, the task released at that count, counting the releases of the run
  from 0, falls below every other task, and a later change point puts its
  task lower still.

A run() or an advance() that has released max_releases tasks while a task
is still ready ends every task and fails the case with the identity
RELEASES.

Shrinking moves every choice towards its target: under Uniform, the
release of the task that became ready first; under Pct, no change points
and equal priorities. Both are the order in which the tasks became ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final

from prop.case import Case, Request
from prop.choice import UINT64_MAX, IntegerBounds
from prop.value import as_type

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: The bounds of a task's priority under Pct, and of a change point's count.
PRIORITIES: Final = IntegerBounds(0, UINT64_MAX)
COUNTS: Final = IntegerBounds(0, UINT64_MAX)

#: The bounds of a change point's presence choice.
PRESENCE: Final = IntegerBounds(0, 1)

#: The instant at which the clock of every scheduler starts, midnight UTC
#: 2000-01-01, in nanoseconds since the Unix epoch.
EPOCH: Final = 946_684_800 * 10**9

#: The most tasks that one run() or one advance() releases by default.
MAX_RELEASES: Final = 1_000_000

#: The identity of the failure of a run that keeps a task ready past its
#: limit of releases.
RELEASES: Final = "max-releases"


@dataclass(frozen=True)
class Uniform:
    """The strategy that chooses each release uniformly among the ready tasks."""


@dataclass(frozen=True)
class Pct:
    """Probabilistic concurrency testing: priorities, and depth - 1 change points."""

    depth: int

    def __post_init__(self) -> None:
        """Refuse a depth below 1.

        Raises:
            ValueError: depth is below 1.
        """
        if self.depth < 1:
            msg = f"stateful: a PCT depth of {self.depth} is below 1"
            raise ValueError(msg)


Strategy = Uniform | Pct


@dataclass(frozen=True)
class Wait:
    """What a task yields to park until condition returns true."""

    condition: Callable[[], bool]


@dataclass(frozen=True)
class Sleep:
    """What a task yields to park until the clock has passed nanoseconds."""

    nanoseconds: int


#: What a task yields: None to yield its turn, and a Wait or a Sleep to park.
Yielded = Wait | Sleep | None


@dataclass(eq=False)
class _Task:
    """A spawned task: its body, its priority, its rank and what it parks on.

    level is 0 until a change point lowers the task, and each lowering
    gives it a level below every level before. ready numbers the times a
    task became ready, in order. A sleeping task has its deadline and the
    number of its sleep, and a waiting task its condition.
    """

    body: Iterator[Yielded]
    priority: int
    level: int = 0
    ready: int = 0
    deadline: int = 0
    slept: int = 0
    condition: Callable[[], bool] | None = None


@final
class Clock:
    """The clock of a scheduler, as its tasks read it."""

    def __init__(self, scheduler: Scheduler) -> None:
        """Read the time of scheduler."""
        self._scheduler = scheduler

    def now(self) -> int:
        """Return the instant of the clock, in nanoseconds since the Unix epoch."""
        return self._scheduler.now

    def sleep(self, nanoseconds: int) -> Sleep:
        """Return what a task yields to park until the clock has passed nanoseconds.

        Raises:
            ValueError: the body, outside a task, sleeps for a positive
                duration, which nothing could end.
        """
        if nanoseconds > 0 and not self._scheduler.releasing:
            msg = (
                "stateful: a sleep outside a task waits for a clock"
                " that only the body moves"
            )
            raise ValueError(msg)
        return Sleep(nanoseconds)


@final
class Scheduler:
    """The tasks of one case, released in the order its choices decide."""

    def __init__(
        self, case: Case, strategy: Strategy, max_releases: int = MAX_RELEASES
    ) -> None:
        """Release tasks by strategy, with the choices of case.

        Raises:
            ValueError: max_releases is below 1.
        """
        if max_releases < 1:
            msg = f"stateful: max-releases({max_releases}) states no count of releases"
            raise ValueError(msg)
        self._case = case
        self._strategy = strategy
        self._max_releases = max_releases
        self._ready: list[_Task] = []
        self._waiting: list[_Task] = []
        self._sleeping: list[_Task] = []
        self._readied = 0
        self._sleeps = 0
        self._lowest = 0
        self._running = False
        self._current: _Task | None = None
        self.now = EPOCH

    @property
    def releasing(self) -> bool:
        """Report whether a task runs its turn."""
        return self._current is not None

    def spawn(self, task: Iterator[Yielded]) -> None:
        """Make task ready. Under Pct, it first receives its priority."""
        pct = isinstance(self._strategy, Pct)
        self._enqueue(_Task(task, self._case.integer(PRIORITIES) if pct else 0))

    def wait(self, condition: Callable[[], bool]) -> Wait:
        """Return what a task yields to park until condition returns true.

        Raises:
            ValueError: the body, outside a task, waits for a condition that
                is false, which no task can make true while the body waits.
        """
        if not self.releasing and not condition():
            msg = "stateful: a wait outside a task waits for a condition that is false"
            raise ValueError(msg)
        return Wait(condition)

    def clock(self) -> Clock:
        """Return the clock of the scheduler."""
        return Clock(self)

    def run(self) -> None:
        """Release one ready task at a time until none is ready.

        Raises:
            ValueError: a task called run() while the scheduler releases it.
            Failed: a task or a condition failed the case, or the run
                released max_releases tasks while a task was still ready.
        """
        self._refuse_nested("run")
        self._running = True
        try:
            self._wake()
            self._release_all(self._change_points(), 0)
        finally:
            self._running = False

    def advance(self, nanoseconds: int) -> None:
        """Release tasks, and move the clock up to nanoseconds, deadline by deadline.

        A duration of zero or less moves the clock by nothing.

        Raises:
            ValueError: a task called advance() while the scheduler releases it.
            Failed: a task or a condition failed the case, or the advance
                released max_releases tasks while a task was still ready.
        """
        self._refuse_nested("advance")
        self._running = True
        try:
            end = self.now + max(nanoseconds, 0)
            self._wake()
            points = self._change_points()
            release = 0
            while True:
                release = self._release_all(points, release)
                due = min((task.deadline for task in self._sleeping), default=end)
                self.now = min(due, end)
                self._wake()
                if not self._ready and self.now == end:
                    return
        finally:
            self._running = False

    def _refuse_nested(self, call: str) -> None:
        """Refuse a call of run() or advance() from a task of this scheduler.

        Raises:
            ValueError: the scheduler is releasing a task.
        """
        if self._running:
            msg = f"stateful: a task called {call}() of its own scheduler"
            raise ValueError(msg)

    def _release_all(self, points: list[int], release: int) -> int:
        """Release tasks until none is ready, counting from release.

        Return the count of the releases after the last one.

        Raises:
            Failed: max_releases tasks were released while a task was still
                ready.
        """
        while self._ready:
            if release == self._max_releases:
                self._end_all()
                self._case.fail(
                    RELEASES,
                    f"the task scheduler released {release} tasks in one run,"
                    " and a task is still ready",
                )
            task = self._ready.pop(self._next())
            for _ in range(points.count(release)):
                self._lowest -= 1
                task.level = self._lowest
            release += 1
            self._turn(task)
            self._wake()
        return release

    def _turn(self, task: _Task) -> None:
        """Run task until it yields, parks or returns, and keep it where it goes."""
        self._current = task
        try:
            while True:
                try:
                    yielded = next(task.body)
                except StopIteration:
                    return
                if yielded is None:
                    self._enqueue(task)
                    return
                if isinstance(yielded, Wait):
                    if yielded.condition():
                        continue
                    task.condition = yielded.condition
                    self._waiting.append(task)
                    return
                if yielded.nanoseconds > 0:
                    task.deadline = self.now + yielded.nanoseconds
                    task.slept = self._sleeps
                    self._sleeps += 1
                    self._sleeping.append(task)
                    return
        finally:
            self._current = None

    def _wake(self) -> None:
        """Make ready the sleeping tasks that are due, then the waiting tasks."""
        due = sorted(
            (task for task in self._sleeping if task.deadline <= self.now),
            key=lambda task: (task.deadline, task.slept),
        )
        for task in due:
            self._sleeping.remove(task)
            self._enqueue(task)
        for task in list(self._waiting):
            condition = task.condition
            if condition is not None and condition():
                self._waiting.remove(task)
                task.condition = None
                self._enqueue(task)

    def _end_all(self) -> None:
        """End every task that has not returned, ready or parked: none runs again."""
        self._ready.clear()
        self._waiting.clear()
        self._sleeping.clear()

    def _enqueue(self, task: _Task) -> None:
        """Add a task to the end of the ready tasks."""
        task.ready = self._readied
        self._readied += 1
        self._ready.append(task)

    def _change_points(self) -> list[int]:
        """Return the counts of the run's change points, which only Pct makes."""
        if not isinstance(self._strategy, Pct):
            return []
        return [
            self._case.integer(COUNTS)
            for _ in range(self._strategy.depth - 1)
            if self._case.integer(PRESENCE, edge=1)
        ]

    def _next(self) -> int:
        """Return the index of the ready task to release."""
        ready = self._ready
        if isinstance(self._strategy, Pct):
            return max(
                range(len(ready)),
                key=lambda i: (ready[i].level, ready[i].priority, -ready[i].ready),
            )
        count = len(ready)
        index = self._case.choose(
            Request(
                IntegerBounds(0, count - 1),
                lambda source: source.below(count),
                edge=0,
            )
        )
        return as_type(index, int)
