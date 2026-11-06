# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""The task scheduler: releases, yields, and the choices of its two strategies."""

from __future__ import annotations

import datetime as dt
import unittest
from typing import TYPE_CHECKING, final

import pytest

from prop.case import Case, Failed, Generating, Replaying
from prop.choice import UINT64_MAX, Choice, IntegerBounds
from prop.source import Source

from .scheduler import (
    EPOCH,
    MAX_RELEASES,
    RELEASES,
    Pct,
    Scheduler,
    Strategy,
    Uniform,
    Yielded,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: A millisecond, in the nanoseconds of the clock of a scheduler.
MS = 1_000_000


def started(
    strategy: Strategy, *values: int, max_releases: int = MAX_RELEASES
) -> tuple[Case, Scheduler, list[str]]:
    """Return a case that replays integer values, its scheduler, and an empty log."""
    case = Case(Replaying([Choice("integer", v) for v in values]))
    return case, Scheduler(case, strategy, max_releases), []


def task(log: list[str], name: str, parts: int) -> Iterator[None]:
    """Log name and its part, yielding between parts."""
    for part in range(1, parts + 1):
        log.append(f"{name}{part}")
        if part < parts:
            yield


def elapsed(scheduler: Scheduler) -> int:
    """Return the milliseconds that the clock of scheduler has advanced."""
    return (scheduler.clock().now() - EPOCH) // MS


def waiting(
    scheduler: Scheduler, log: list[str], name: str, ready: Callable[[], bool]
) -> Iterator[Yielded]:
    """Log name, wait until ready returns true, and log name again."""
    log.append(f"{name}1")
    yield scheduler.wait(ready)
    log.append(f"{name}2")


def ticking(
    scheduler: Scheduler, log: list[str], name: str, period: int, ticks: int
) -> Iterator[Yielded]:
    """Sleep period milliseconds ticks times, and log the time of each wake."""
    for _ in range(ticks):
        yield scheduler.clock().sleep(period * MS)
        log.append(f"{name}@{elapsed(scheduler)}")


@final
class UniformTest(unittest.TestCase):
    """Uniform: each release chooses an index into the ready tasks."""

    def test_a_task_that_yields_waits_behind_the_ready_tasks(self) -> None:
        """Releasing the first ready task each time alternates the two."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(task(log, "a", 3))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        assert log == ["a1", "b1", "a2", "b2", "a3"]

    def test_each_release_takes_the_task_at_its_index(self) -> None:
        """Index 1 releases b first, which then waits behind a."""
        _, scheduler, log = started(Uniform(), 1, 0, 0)
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        assert log == ["b1", "a1", "b2", "a2"]

    def test_a_release_with_one_ready_task_records_its_choice(self) -> None:
        """Bounds [0, 1] while two are ready, then [0, 0], with edge 0."""
        case, scheduler, log = started(Uniform())
        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        assert [request.bounds for request in case.requests] == [
            IntegerBounds(0, 1),
            IntegerBounds(0, 0),
            IntegerBounds(0, 0),
        ]
        assert [request.edge for request in case.requests] == [0, 0, 0]

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
            assert [c.value for c in case.choices] == want, seed

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
        assert log == ["p1", "b1", "c1", "p2"]

    def test_a_task_that_calls_run_raises(self) -> None:
        """A scheduler that is releasing a task refuses a call of run()."""
        _, scheduler, _ = started(Uniform())

        def nested() -> Iterator[None]:
            scheduler.run()
            yield

        scheduler.spawn(nested())
        with pytest.raises(ValueError, match="called run"):
            scheduler.run()

    def test_a_failure_in_a_task_ends_run(self) -> None:
        """The failure passes through, and the scheduler runs again afterwards."""
        case, scheduler, log = started(Uniform())

        def failing() -> Iterator[None]:
            case.fail("broken")
            yield

        scheduler.spawn(failing())
        with pytest.raises(Failed):
            scheduler.run()
        scheduler.spawn(task(log, "a", 1))
        scheduler.run()
        assert log == ["a1"]


@final
class PctTest(unittest.TestCase):
    """Pct: priorities at spawn, and change points at the start of a run."""

    def test_a_depth_below_1_raises(self) -> None:
        """Depth 1 has no change point, and depth 0 is no depth."""
        Pct(1)
        with pytest.raises(ValueError, match="depth of 0 is below 1"):
            Pct(0)

    def test_the_task_with_the_highest_priority_runs_through_its_yields(self) -> None:
        """Task b has priority 5 and keeps it when it yields, so it ends first."""
        _, scheduler, log = started(Pct(1), 1, 5)
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 3))
        scheduler.run()
        assert log == ["b1", "b2", "b3", "a1", "a2"]

    def test_equal_priorities_run_the_earliest_ready_first(self) -> None:
        """A task that yields becomes ready after the other, so the two alternate."""
        _, scheduler, log = started(Pct(1))
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        assert log == ["a1", "b1", "a2", "b2"]

    def test_a_spawn_and_a_run_request_their_choices(self) -> None:
        """A priority per task, then per change point a presence and a count."""
        case, scheduler, log = started(Pct(3), 0, 0, 1, 9, 0)
        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(task(log, "b", 1))
        scheduler.run()
        wide, presence = IntegerBounds(0, UINT64_MAX), IntegerBounds(0, 1)
        assert [request.bounds for request in case.requests] == [
            wide,
            wide,
            presence,
            wide,
            presence,
        ]
        assert [request.edge for request in case.requests] == [None, None, 1, None, 1]

    def test_a_change_point_drops_the_task_it_releases_below_every_other(
        self,
    ) -> None:
        """Task a has the higher priority, and the change point at 0 drops it."""
        _, scheduler, log = started(Pct(2), 5, 1, 1, 0)
        scheduler.spawn(task(log, "a", 2))
        scheduler.spawn(task(log, "b", 2))
        scheduler.run()
        assert log == ["a1", "b1", "b2", "a2"]

    def test_a_later_change_point_drops_its_task_lower_still(self) -> None:
        """Task a falls at release 0 and b at release 1, so c, then a, then b."""
        _, scheduler, log = started(Pct(3), 9, 8, 7, 1, 0, 1, 1)
        for name in "abc":
            scheduler.spawn(task(log, name, 2))
        scheduler.run()
        assert log == ["a1", "b1", "c1", "c2", "a2", "b2"]

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
        assert log == ["a1", "d1", "c1", "a2", "d2"]

    def test_a_release_makes_no_choice(self) -> None:
        """Two tasks of one part each request only their priorities."""
        case, scheduler, log = started(Pct(1))
        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(task(log, "b", 1))
        scheduler.run()
        assert len(case.requests) == 2
        assert log == ["a1", "b1"]

    def test_a_task_keeps_its_priority_through_a_wait(self) -> None:
        """Task a has the higher priority, so it runs again once its wait ends.

        c then runs before b, because c became ready before b yielded.
        """
        _, scheduler, log = started(Pct(1), 9, 1, 1)
        flag = [False]

        def setter() -> Iterator[None]:
            log.append("b1")
            flag[0] = True
            yield
            log.append("b2")

        scheduler.spawn(waiting(scheduler, log, "a", lambda: flag[0]))
        scheduler.spawn(setter())
        scheduler.spawn(task(log, "c", 1))
        scheduler.run()
        assert log == ["a1", "b1", "a2", "c1", "b2"]


@final
class WaitTest(unittest.TestCase):
    """wait: a task that is not ready until its condition is true."""

    def test_a_waiting_task_is_ready_once_another_task_makes_its_condition_true(
        self,
    ) -> None:
        """Task a waits, b sets the flag, and a runs after b's turn."""
        _, scheduler, log = started(Uniform())
        flag = [False]

        def setter() -> Iterator[None]:
            log.append("b1")
            flag[0] = True
            yield

        scheduler.spawn(waiting(scheduler, log, "a", lambda: flag[0]))
        scheduler.spawn(setter())
        scheduler.run()
        assert log == ["a1", "b1", "a2"]

    def test_run_returns_while_a_task_waits(self) -> None:
        """No task sets the flag, so run returns, and the next run wakes the task."""
        _, scheduler, log = started(Uniform())
        flag = [False]
        scheduler.spawn(waiting(scheduler, log, "a", lambda: flag[0]))
        scheduler.run()
        assert log == ["a1"]
        flag[0] = True
        scheduler.run()
        assert log == ["a1", "a2"]

    def test_a_wait_whose_condition_is_true_returns_at_once(self) -> None:
        """The task continues within its turn, so one release records one choice."""
        case, scheduler, log = started(Uniform())
        scheduler.spawn(waiting(scheduler, log, "a", lambda: True))
        scheduler.run()
        assert log == ["a1", "a2"]
        assert len(case.requests) == 1

    def test_woken_tasks_join_after_the_ready_tasks_in_the_order_of_their_waits(
        self,
    ) -> None:
        """Task s yields after it sets the flag, so it runs before w1 and w2."""
        _, scheduler, log = started(Uniform())
        flag = [False]

        def setter() -> Iterator[None]:
            log.append("s1")
            flag[0] = True
            yield
            log.append("s2")

        scheduler.spawn(waiting(scheduler, log, "w", lambda: flag[0]))
        scheduler.spawn(waiting(scheduler, log, "v", lambda: flag[0]))
        scheduler.spawn(setter())
        scheduler.run()
        assert log == ["w1", "v1", "s1", "s2", "w2", "v2"]

    def test_a_condition_that_fails_the_case_ends_run(self) -> None:
        """The scheduler calls the condition between turns, and the failure passes."""
        case, scheduler, log = started(Uniform())

        def broken() -> bool:
            case.fail("broken")
            return False

        scheduler.spawn(task(log, "a", 1))
        scheduler.spawn(waiting(scheduler, log, "w", broken))
        with pytest.raises(Failed):
            scheduler.run()

    def test_a_wait_outside_a_task_returns_only_for_a_true_condition(self) -> None:
        """The body cannot park, so a false condition raises."""
        _, scheduler, _ = started(Uniform())
        scheduler.wait(lambda: True)
        with pytest.raises(ValueError, match="outside a task"):
            scheduler.wait(lambda: False)


@final
class ClockTest(unittest.TestCase):
    """The clock of a scheduler: its start, its sleeps, and what moves it."""

    def test_the_clock_starts_at_midnight_utc_2000_01_01(self) -> None:
        """EPOCH is that instant in nanoseconds since the Unix epoch."""
        midnight = int(dt.datetime(2000, 1, 1, tzinfo=dt.UTC).timestamp())
        assert midnight * 10**9 == EPOCH
        _, scheduler, _ = started(Uniform())
        assert scheduler.clock().now() == EPOCH

    def test_run_does_not_move_the_clock(self) -> None:
        """A sleeping task remains parked after run."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(ticking(scheduler, log, "t", 4, 1))
        scheduler.run()
        assert (log, elapsed(scheduler)) == ([], 0)

    def test_a_sleep_of_zero_returns_at_once(self) -> None:
        """The task continues within its turn, so one release records one choice."""
        case, scheduler, log = started(Uniform())
        scheduler.spawn(ticking(scheduler, log, "t", 0, 2))
        scheduler.run()
        assert log == ["t@0", "t@0"]
        assert len(case.requests) == 1

    def test_a_sleep_outside_a_task_returns_only_for_no_time(self) -> None:
        """The body cannot park, so a positive duration raises."""
        _, scheduler, _ = started(Uniform())
        scheduler.clock().sleep(0)
        with pytest.raises(ValueError, match="outside a task"):
            scheduler.clock().sleep(MS)


@final
class AdvanceTest(unittest.TestCase):
    """advance: the clock moves from deadline to deadline, and tasks run at each."""

    def test_each_tick_runs_at_its_own_deadline(self) -> None:
        """A ticker of 4 ms ticks at 4 and 8 within 10 ms, and at 12 in 2 ms more."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(ticking(scheduler, log, "t", 4, 3))
        scheduler.advance(10 * MS)
        assert (log, elapsed(scheduler)) == (["t@4", "t@8"], 10)
        scheduler.advance(2 * MS)
        assert (log, elapsed(scheduler)) == (["t@4", "t@8", "t@12"], 12)

    def test_a_sleep_whose_deadline_is_the_end_time_ends_within_the_advance(
        self,
    ) -> None:
        """A sleep of 4 ms ends within an advance of 4 ms."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(ticking(scheduler, log, "t", 4, 1))
        scheduler.advance(4 * MS)
        assert log == ["t@4"]

    def test_tasks_wake_in_the_order_of_their_deadlines_and_then_their_sleeps(
        self,
    ) -> None:
        """Tasks b and c share a deadline and wake in the order they slept, after a."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(ticking(scheduler, log, "c", 6, 1))
        scheduler.spawn(ticking(scheduler, log, "a", 2, 1))
        scheduler.spawn(ticking(scheduler, log, "b", 6, 1))
        scheduler.advance(6 * MS)
        assert log == ["a@2", "c@6", "b@6"]

    def test_an_advance_of_no_time_releases_as_run_does(self) -> None:
        """The ready task runs, and the clock does not move."""
        _, scheduler, log = started(Uniform())
        scheduler.spawn(task(log, "a", 2))
        scheduler.advance(0)
        assert (log, elapsed(scheduler)) == (["a1", "a2"], 0)

    def test_a_task_that_calls_advance_raises(self) -> None:
        """A scheduler that is releasing a task refuses a call of advance()."""
        _, scheduler, _ = started(Uniform())

        def nested() -> Iterator[None]:
            scheduler.advance(MS)
            yield

        scheduler.spawn(nested())
        with pytest.raises(ValueError, match="called advance"):
            scheduler.run()

    def test_an_advance_makes_the_change_points_of_one_run(self) -> None:
        """One priority, then one presence for the depth of 2, over two deadlines."""
        case, scheduler, log = started(Pct(2))
        scheduler.spawn(ticking(scheduler, log, "t", 4, 2))
        scheduler.advance(10 * MS)
        assert log == ["t@4", "t@8"]
        assert [request.bounds for request in case.requests] == [
            IntegerBounds(0, UINT64_MAX),
            IntegerBounds(0, 1),
        ]


@final
class ReleaseLimitTest(unittest.TestCase):
    """max-releases: a run that keeps a task ready fails the case at the limit."""

    def test_the_default_limit_is_a_million(self) -> None:
        """The default of the definition, pinned."""
        assert MAX_RELEASES == 1_000_000

    def test_a_run_that_releases_the_limit_with_a_task_ready_fails(self) -> None:
        """A task that yields forever fails the case after five releases."""
        case, scheduler, _ = started(Uniform(), max_releases=5)

        def spinning() -> Iterator[None]:
            while True:
                yield

        scheduler.spawn(spinning())
        with pytest.raises(Failed) as failed:
            scheduler.run()
        assert failed.value.identity == RELEASES
        want = (
            "the task scheduler released 5 tasks in one run, and a task is still ready"
        )
        assert failed.value.message == want
        assert len(case.requests) == 5

    def test_the_limit_counts_the_releases_of_one_run(self) -> None:
        """Two runs of three releases each pass a limit of three."""
        _, scheduler, log = started(Uniform(), max_releases=3)
        scheduler.spawn(task(log, "a", 3))
        scheduler.run()
        scheduler.spawn(task(log, "b", 3))
        scheduler.run()
        assert log == ["a1", "a2", "a3", "b1", "b2", "b3"]

    def test_an_advance_counts_its_releases_over_its_deadlines(self) -> None:
        """Three ticks of one advance are three releases, past a limit of two."""
        _, scheduler, log = started(Uniform(), max_releases=2)
        scheduler.spawn(ticking(scheduler, log, "t", 1, 3))
        with pytest.raises(Failed) as failed:
            scheduler.advance(5 * MS)
        assert failed.value.identity == RELEASES

    def test_a_limit_below_1_raises(self) -> None:
        """A run releases at least one task."""
        with pytest.raises(ValueError, match="releases"):
            Scheduler(Case(Replaying([])), Uniform(), 0)
