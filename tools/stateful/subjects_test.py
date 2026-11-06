# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""The machine subjects: their models, and the minimal steps a run shrinks to."""

from __future__ import annotations

import unittest
from typing import final

from history.model import Op
from prop.case import Place, Step
from prop.execution import Status, execute
from prop.runner import Kind, Settings, run
from prop.trace import Draw, Entry, Tracing, entries

from .machine import CHECK
from .scheduler import RELEASES, Pct
from .subjects import (
    CORRECT_COUNTER,
    CORRECT_QUEUE,
    COUNTER_OVERFLOWS,
    COUNTER_REFUSES_EVERY_THIRD,
    LOST,
    QUEUE_LOSES_ON_WRAP,
    RACY_COUNTER,
    REGISTER_FLUSHES,
    REGISTER_FLUSHES_IN_TWO_PARTS,
    SPINS_UNTIL_A_FLAG,
    STORE_LOSES_ON_CRASH,
    TICKER,
    TICKER_SKIPS_ITS_FIRST_TICK,
    Ring,
    Setup,
    body,
    bounded_queue,
    counter,
    reading_counter,
    register,
    ticks,
)

#: The seeds each failing subject is run with.
SEEDS = range(1, 6)

#: The minimal steps of each failing subject, as a trace, and its failure.
MINIMAL: dict[str, tuple[str, list[Entry]]] = {
    QUEUE_LOSES_ON_WRAP: (
        CHECK,
        [
            Draw("capacity", 2),
            Step("put"),
            Draw("v", 0),
            Step("put"),
            Draw("v", 1),
            Step("get"),
        ],
    ),
    COUNTER_OVERFLOWS: (CHECK, [Step("increment")] * 3),
    STORE_LOSES_ON_CRASH: (LOST, [Step("put"), Draw("key", 0), Step("crash")]),
    RACY_COUNTER: (
        CHECK,
        [Step("increment", client=1), Step("increment", client=2)],
    ),
    REGISTER_FLUSHES_IN_TWO_PARTS: (
        CHECK,
        [Step("write"), Draw("v", 0), Step("read", client=1)],
    ),
}

#: The limit of releases under which spins-until-a-flag runs.
SPIN_LIMIT = 50

#: The setup of the ticker. Under pct a release records no choice, so the
#: choices of a case do not depend on the deadlines that an advance passes.
TICKER_SETUP = Setup(strategy=Pct(1))


@final
class RingTest(unittest.TestCase):
    """The ring under the two queues."""

    def test_a_correct_ring_returns_its_values_in_order_across_the_wrap(self) -> None:
        """Three puts, a get, a fourth put at slot 0, then the rest in order."""
        ring = Ring(3, loses_on_wrap=False)
        assert [ring.put(v) for v in (1, 2, 3, 4)] == [True, True, True, False]
        assert ring.get() == 1
        assert ring.put(4)
        assert [ring.get() for _ in range(4)] == [2, 3, 4, None]

    def test_a_ring_that_loses_on_wrap_writes_the_last_slot_into_the_first(
        self,
    ) -> None:
        """The second put of a ring of 2 overwrites the first value."""
        ring = Ring(2, loses_on_wrap=True)
        ring.put(1)
        ring.put(2)
        assert [ring.get(), ring.get()] == [2, None]


@final
class ModelTest(unittest.TestCase):
    """The models the subjects are checked against."""

    def test_a_bounded_queue_refuses_a_put_when_full(self) -> None:
        """A put that returns true into a full queue is rejected."""
        model = bounded_queue(1)
        state = model.init()
        (state,) = model.step(state, Op("put", (5,), known=True, output=True))
        assert state == [5]
        assert model.step(state, Op("put", (6,), known=True, output=True)) == []
        assert model.step(state, Op("put", (6,), known=True, output=False)) == [[5]]

    def test_a_bounded_queue_gets_its_oldest_value_or_null(self) -> None:
        """A get of another value is rejected."""
        model = bounded_queue(2)
        assert model.step([], Op("get", (), known=True, output=None)) == [[]]
        assert model.step([5, 6], Op("get", (), known=True, output=5)) == [[6]]
        assert model.step([5, 6], Op("get", (), known=True, output=6)) == []
        assert model.step([5, 6], Op("get", (), known=False)) == [[6]]

    def test_a_counter_returns_the_new_count_and_resets_to_0(self) -> None:
        """An increment of 3 returns 4."""
        model = counter()
        assert model.step(3, Op("increment", (), known=True, output=4)) == [4]
        assert model.step(3, Op("increment", (), known=True, output=3)) == []
        assert model.step(3, Op("reset", (), known=True, output=None)) == [0]

    def test_a_reading_counter_reads_the_count_and_increments_it(self) -> None:
        """A read of 3 returns 3, and an increment of 3 returns 4."""
        model = reading_counter()
        assert model.init() == 0
        assert model.step(3, Op("read", (), known=True, output=3)) == [3]
        assert model.step(3, Op("read", (), known=True, output=4)) == []
        assert model.step(3, Op("read", (), known=False)) == [3]
        assert model.step(3, Op("increment", (), known=True, output=4)) == [4]
        assert model.step(3, Op("increment", (), known=True, output=3)) == []

    def test_a_register_reads_the_last_write_and_starts_at_null(self) -> None:
        """A read after a write of 5 returns 5, and before any write null."""
        model = register()
        assert model.init() is None
        assert model.step(None, Op("read", (), known=True, output=None)) == [None]
        assert model.step(None, Op("write", (5,), known=True, output=None)) == [5]
        assert model.step(5, Op("read", (), known=True, output=5)) == [5]
        assert model.step(5, Op("read", (), known=True, output=None)) == []
        assert model.step(5, Op("read", (), known=False)) == [5]

    def test_ticks_count_each_4_ms_of_the_advances_up_to_4(self) -> None:
        """9 ms read 2, and 20 ms read the 4 ticks of the ticker."""
        model = ticks()
        assert model.init() == 0
        assert model.step(0, Op("advance", (9,), known=True, output=None)) == [9]
        assert model.step(9, Op("read", (), known=True, output=2)) == [9]
        assert model.step(9, Op("read", (), known=True, output=3)) == []
        assert model.step(20, Op("read", (), known=True, output=4)) == [20]


@final
class SubjectTest(unittest.TestCase):
    """Each subject's run: the minimal steps of a failure, or a pass."""

    def test_each_failing_subject_shrinks_to_its_minimal_steps(self) -> None:
        """The same minimal trace from every seed."""
        for name, (identity, minimal) in MINIMAL.items():
            for seed in SEEDS:
                outcome = run(body(name), Settings(seed=seed))
                assert outcome.kind == Kind.COUNTEREXAMPLE, (name, seed)
                assert outcome.failing is not None
                assert outcome.failing.identity == identity, (name, seed)
                assert entries(outcome.failing.case) == minimal, (name, seed)

    def test_the_correct_subjects_pass(self) -> None:
        """A hundred cases of each, the ticker under both strategies."""
        for name, setup in (
            (CORRECT_QUEUE, Setup()),
            (CORRECT_COUNTER, Setup()),
            (REGISTER_FLUSHES, Setup()),
            (TICKER, Setup()),
            (TICKER, TICKER_SETUP),
        ):
            outcome = run(body(name, setup), Settings(seed=1))
            assert (outcome.kind, outcome.cases) == (Kind.PASSED, 100), name

    def test_a_ticker_that_skips_its_first_tick_shrinks_to_an_advance_of_4_ms(
        self,
    ) -> None:
        """The first deadline is the end time of the advance, and it reads 0 for 1."""
        minimal = [Step("advance"), Draw("ms", 4), Step("read")]
        for seed in SEEDS:
            outcome = run(
                body(TICKER_SKIPS_ITS_FIRST_TICK, TICKER_SETUP), Settings(seed=seed)
            )
            assert outcome.kind == Kind.COUNTEREXAMPLE, seed
            assert outcome.failing is not None
            assert outcome.failing.identity == CHECK, seed
            assert entries(outcome.failing.case) == minimal, seed

    def test_a_ticker_ticks_at_each_deadline_of_one_advance(self) -> None:
        """An advance of 10 ms and one of 2 ms read 3 ticks, at 4, 8 and 12 ms."""
        trace: list[Entry] = [
            Step("advance"),
            Draw("ms", 10),
            Step("advance"),
            Draw("ms", 2),
            Step("read"),
        ]
        execution = execute(body(TICKER, TICKER_SETUP), Tracing(trace), 8192)
        assert execution.status == Status.PASSED
        assert execution.case.history.events()[-1].output == 3

    def test_a_spinning_task_fails_its_case_at_the_release_limit(self) -> None:
        """The case shrinks to one spin, whose run keeps a task ready."""
        setup = Setup(max_releases=SPIN_LIMIT)
        for seed in SEEDS:
            outcome = run(body(SPINS_UNTIL_A_FLAG, setup), Settings(seed=seed))
            assert outcome.kind == Kind.COUNTEREXAMPLE, seed
            assert outcome.failing is not None
            assert outcome.failing.identity == RELEASES, seed
            assert entries(outcome.failing.case) == [Step("spin")], seed

    def test_the_minimal_steps_replay_as_a_trace(self) -> None:
        """Each trace fails with its failure, and records itself again."""
        for name, (identity, minimal) in MINIMAL.items():
            execution = execute(body(name), Tracing(minimal), 8192)
            assert execution.status == Status.FAILED, name
            assert execution.identity == identity, name
            assert entries(execution.case) == minimal, name

    def test_a_trace_of_the_wrapping_queue_without_its_get_passes(self) -> None:
        """Two puts alone fill the queue and show nothing."""
        minimal = MINIMAL[QUEUE_LOSES_ON_WRAP][1]
        execution = execute(body(QUEUE_LOSES_ON_WRAP), Tracing(minimal[:-1]), 8192)
        assert execution.status == Status.PASSED

    def test_a_refusing_counter_diverges_at_the_index_of_a_sequential_step(
        self,
    ) -> None:
        """A refusal changes the list of a step, and the run names that step."""
        for seed in SEEDS:
            setup = Setup(swarm=False)
            outcome = run(body(COUNTER_REFUSES_EVERY_THIRD, setup), Settings(seed=seed))
            assert outcome.kind == Kind.FLAKY, seed
            assert outcome.divergence is not None
            step = outcome.divergence.step
            assert step is not None
            assert (step.part, step.action) == ("sequential", None), seed

    def test_each_body_of_a_refusing_counter_counts_from_0(self) -> None:
        """Two runs of the same seed report the same divergence."""
        setup = Setup(swarm=False)
        first = run(body(COUNTER_REFUSES_EVERY_THIRD, setup), Settings(seed=1))
        second = run(body(COUNTER_REFUSES_EVERY_THIRD, setup), Settings(seed=1))
        assert first.divergence == second.divergence
        assert first.divergence is not None
        assert first.divergence.step == Place("sequential", 4)
