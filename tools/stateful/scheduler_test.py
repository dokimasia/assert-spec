"""The task scheduler: releases, yields, and the choices of its two strategies."""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from typing import final

from prop.case import Case, Failed, Generating, Replaying
from prop.choice import UINT64_MAX, Choice, IntegerBounds
from prop.source import Source

from .scheduler import Pct, Scheduler, Strategy, Uniform


def started(strategy: Strategy, *values: int) -> tuple[Case, Scheduler, list[str]]:
    """Return a case that replays integer values, its scheduler, and an empty log."""
    case = Case(Replaying([Choice("integer", v) for v in values]))
    return case, Scheduler(case, strategy), []


def task(log: list[str], name: str, parts: int) -> Iterator[None]:
    """Log name and its part, yielding between parts."""
    for part in range(1, parts + 1):
        log.append(f"{name}{part}")
        if part < parts:
            yield


@final
class UniformTest(unittest.TestCase):
    """Uniform: each release chooses an index into the ready tasks."""

    def test_a_task_that_yields_waits_behind_the_ready_tasks(self) -> None:
        """Releasing the first ready task each time alternates the two."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(task(log, "a", 3))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        self.assertEqual(log, ["a1", "b1", "a2", "b2", "a3"])

    def test_each_release_takes_the_task_at_its_index(self) -> None:
        """Index 1 releases b first, which then waits behind a."""
        _, scheduler, log = started(Uniform(), 1, 0, 0)
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        self.assertEqual(log, ["b1", "a1", "b2", "a2"])

    def test_a_release_with_one_ready_task_records_its_choice(self) -> None:
        """Bounds [0, 1] while two are ready, then [0, 0], with edge 0."""
        case, scheduler, log = started(Uniform())
        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        self.assertEqual(
            [request.bounds for request in case.requests],
            [IntegerBounds(0, 1), IntegerBounds(0, 0), IntegerBounds(0, 0)],
        )
        self.assertEqual([request.edge for request in case.requests], [0, 0, 0])

    def test_a_release_draws_below_the_number_of_ready_tasks(self) -> None:
        """A forced release consumes nothing."""
        for seed in range(20):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            scheduler = Scheduler(case, Uniform())
            log: list[str] = []
            for name in "abc":
                scheduler.spawn(task(log, name, 1))
            scheduler.run()
            want = [twin.below(3), twin.below(2), 0]
            self.assertEqual([c.value for c in case.choices], want, seed)

    def test_a_task_may_spawn_another_while_it_runs(self) -> None:
        """The new task is ready behind the tasks that were ready."""
        _, scheduler, log = started(Uniform())

        def parent() -> Iterator[None]:
            log.append("p1")
            scheduler.spawn(task(log, "c", 1))
            yield
            log.append("p2")

        scheduler.spawn(parent())
        scheduler.spawn(task(log, "b", 1))
        scheduler.run()
        self.assertEqual(log, ["p1", "b1", "c1", "p2"])

    def test_a_task_that_calls_run_raises(self) -> None:
        """A scheduler that is releasing a task refuses a call of run()."""
        _, scheduler, _ = started(Uniform())

        def nested() -> Iterator[None]:
            scheduler.run()
            yield

        scheduler.spawn(nested())
        with self.assertRaises(ValueError):
            scheduler.run()

    def test_a_failure_in_a_task_ends_run(self) -> None:
        """The failure passes through, and the scheduler runs again afterwards."""
        case, scheduler, log = started(Uniform())

        def failing() -> Iterator[None]:
            case.fail("broken")
            yield

        scheduler.spawn(failing())
        with self.assertRaises(Failed):
            scheduler.run()
        scheduler.spawn(task(log, "a", 1))
        scheduler.run()
        self.assertEqual(log, ["a1"])


@final
class PctTest(unittest.TestCase):
    """Pct: priorities at spawn, and change points at the start of a run."""

    def test_a_depth_below_1_raises(self) -> None:
        """Depth 1 has no change point, and depth 0 is no depth."""
        Pct(1)
        with self.assertRaises(ValueError):
            Pct(0)

    def test_the_task_with_the_highest_priority_runs_through_its_yields(self) -> None:
        """Task b has priority 5 and keeps it when it yields, so it ends first."""
        _, scheduler, log = started(Pct(1), 1, 5)
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 3))
        scheduler.run()
        self.assertEqual(log, ["b1", "b2", "b3", "a1", "a2"])

    def test_equal_priorities_run_the_earliest_ready_first(self) -> None:
        """A task that yields becomes ready after the other, so the two alternate."""
        _, scheduler, log = started(Pct(1))
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        self.assertEqual(log, ["a1", "b1", "a2", "b2"])

    def test_a_spawn_and_a_run_request_their_choices(self) -> None:
        """A priority per task, then per change point a presence and a count."""
        case, scheduler, log = started(Pct(3), 0, 0, 1, 9, 0)
        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(task(log, "b", 1))
        scheduler.run()
        wide, presence = IntegerBounds(0, UINT64_MAX), IntegerBounds(0, 1)
        self.assertEqual(
            [request.bounds for request in case.requests],
            [wide, wide, presence, wide, presence],
        )
        self.assertEqual(
            [request.edge for request in case.requests], [None, None, 1, None, 1]
        )

    def test_a_change_point_drops_the_task_it_releases_below_every_other(
        self,
    ) -> None:
        """Task a has the higher priority, and the change point at 0 drops it."""
        _, scheduler, log = started(Pct(2), 5, 1, 1, 0)
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        self.assertEqual(log, ["a1", "b1", "b2", "a2"])

    def test_a_later_change_point_drops_its_task_lower_still(self) -> None:
        """Task a falls at release 0 and b at release 1, so c, then a, then b."""
        _, scheduler, log = started(Pct(3), 9, 8, 7, 1, 0, 1, 1)
        for name in "abc":
            scheduler.spawn(task(log, name, 2))
        scheduler.run()
        self.assertEqual(log, ["a1", "b1", "c1", "c2", "a2", "b2"])

    def test_a_task_spawned_with_a_higher_priority_still_falls_lower(self) -> None:
        """Task a falls at release 0 and spawns d, which falls at release 1.

        d has the higher priority, and the later change point puts it below a.
        """
        _, scheduler, log = started(Pct(3), 5, 1, 1, 0, 1, 1, 9)

        def parent() -> Iterator[None]:
            log.append("a1")
            scheduler.spawn(task(log, "d", 2))
            yield
            log.append("a2")

        scheduler.spawn(parent())
        scheduler.spawn(task(log, "c", 1))
        scheduler.run()
        self.assertEqual(log, ["a1", "d1", "c1", "a2", "d2"])

    def test_a_release_makes_no_choice(self) -> None:
        """Two tasks of one part each request only their priorities."""
        case, scheduler, log = started(Pct(1))
        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(task(log, "b", 1))
        scheduler.run()
        self.assertEqual(len(case.requests), 2)
        self.assertEqual(log, ["a1", "b1"])
