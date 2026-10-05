"""The task scheduler: which ready task runs next, decided by choices of the case.

A task is a generator. A released task runs until it yields or returns,
and a task that yields becomes ready again, after every task that is
ready. spawn() makes a task ready, and run() releases one ready task at a
time until none is ready. A task may spawn others while it runs.

Two strategies choose the task to release:

- Uniform: each release chooses an index into the ready tasks, in the
  order they became ready, uniformly and with target 0. A release with
  one ready task records its choice and consumes nothing.
- Pct(depth): each task receives a priority when it is spawned, an
  integer in [0, 2^64 - 1] drawn as draw.integer draws, with target 0,
  and keeps it when it yields. Each run() starts with depth - 1 change
  points, each an optional count: a presence choice with target absent
  and, when present, an integer in [0, 2^64 - 1]. The ready task with
  the highest priority runs, the earliest ready among equals, and a
  release makes no choice. At a change point, the task released at that
  count, counting the releases of the run from 0, falls below every other
  task, and a later change point puts its task lower still.

Shrinking moves every choice towards its target: under Uniform, the
release of the task that became ready first; under Pct, no change points
and equal priorities. Both are the order in which the tasks became ready.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, final

from prop.case import Case, Request
from prop.choice import UINT64_MAX, IntegerBounds

#: The bounds of a task's priority under Pct, and of a change point's count.
PRIORITIES: Final = IntegerBounds(0, UINT64_MAX)
COUNTS: Final = IntegerBounds(0, UINT64_MAX)

#: The bounds of a change point's presence choice.
PRESENCE: Final = IntegerBounds(0, 1)


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
            raise ValueError(f"stateful: a PCT depth of {self.depth} is below 1")


Strategy = Uniform | Pct


@dataclass(eq=False)
class _Task:
    """A spawned task: its body, its priority and its rank among lowered tasks.

    level is 0 until a change point lowers the task, and each lowering
    gives it a level below every level before. ready numbers the times a
    task became ready, in order.
    """

    body: Iterator[None]
    priority: int
    level: int = 0
    ready: int = 0


@final
class Scheduler:
    """The tasks of one case, released in the order its choices decide."""

    def __init__(self, case: Case, strategy: Strategy) -> None:
        """Release tasks by strategy, with the choices of case."""
        self._case = case
        self._strategy = strategy
        self._ready: list[_Task] = []
        self._readied = 0
        self._lowest = 0
        self._running = False

    def spawn(self, task: Iterator[None]) -> None:
        """Make task ready. Under Pct, it first receives its priority."""
        pct = isinstance(self._strategy, Pct)
        self._enqueue(_Task(task, self._case.integer(PRIORITIES) if pct else 0))

    def run(self) -> None:
        """Release one ready task at a time until none is ready.

        Raises:
            ValueError: a task called run() while the scheduler releases it.
        """
        if self._running:
            raise ValueError("stateful: a task called run() of its own scheduler")
        self._running = True
        try:
            self._release_all()
        finally:
            self._running = False

    def _release_all(self) -> None:
        """Make the run's change points, then release tasks until none is ready."""
        points = self._change_points()
        release = 0
        while self._ready:
            task = self._ready.pop(self._next())
            for _ in range(points.count(release)):
                self._lowest -= 1
                task.level = self._lowest
            release += 1
            try:
                next(task.body)
            except StopIteration:
                continue
            self._enqueue(task)

    def _enqueue(self, task: _Task) -> None:
        """Add a task to the end of the ready tasks."""
        task.ready = self._readied
        self._readied += 1
        self._ready.append(task)

    def _change_points(self) -> list[int]:
        """Return the counts of the run's change points, which only Pct makes."""
        if not isinstance(self._strategy, Pct):
            return []
        points: list[int] = []
        for _ in range(self._strategy.depth - 1):
            if self._case.integer(PRESENCE, edge=1):
                points.append(self._case.integer(COUNTS))
        return points

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
        assert isinstance(index, int)
        return index
