"""The machine subjects: their models, and the minimal steps a run shrinks to."""

from __future__ import annotations

import unittest
from typing import final

from history.model import Op
from prop.case import Step
from prop.execution import Status, execute
from prop.runner import Kind, Settings, run
from prop.trace import Draw, Entry, Tracing, entries

from .machine import CHECK
from .subjects import (
    CORRECT_COUNTER,
    CORRECT_QUEUE,
    COUNTER_OVERFLOWS,
    LOST,
    QUEUE_LOSES_ON_WRAP,
    RACY_COUNTER,
    STORE_LOSES_ON_CRASH,
    Ring,
    body,
    bounded_queue,
    counter,
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
}


@final
class RingTest(unittest.TestCase):
    """The ring under the two queues."""

    def test_a_correct_ring_returns_its_values_in_order_across_the_wrap(self) -> None:
        """Three puts, a get, a fourth put at slot 0, then the rest in order."""
        ring = Ring(3, loses_on_wrap=False)
        self.assertEqual([ring.put(v) for v in (1, 2, 3, 4)], [True, True, True, False])
        self.assertEqual(ring.get(), 1)
        self.assertTrue(ring.put(4))
        self.assertEqual([ring.get() for _ in range(4)], [2, 3, 4, None])

    def test_a_ring_that_loses_on_wrap_writes_the_last_slot_into_the_first(
        self,
    ) -> None:
        """The second put of a ring of 2 overwrites the first value."""
        ring = Ring(2, loses_on_wrap=True)
        ring.put(1)
        ring.put(2)
        self.assertEqual([ring.get(), ring.get()], [2, None])


@final
class ModelTest(unittest.TestCase):
    """The models the subjects are checked against."""

    def test_a_bounded_queue_refuses_a_put_when_full(self) -> None:
        """A put that returns true into a full queue is rejected."""
        model = bounded_queue(1)
        state = model.init()
        (state,) = model.step(state, Op("put", (5,), True, True))
        self.assertEqual(state, [5])
        self.assertEqual(model.step(state, Op("put", (6,), True, True)), [])
        self.assertEqual(model.step(state, Op("put", (6,), True, False)), [[5]])

    def test_a_bounded_queue_gets_its_oldest_value_or_null(self) -> None:
        """A get of another value is rejected."""
        model = bounded_queue(2)
        self.assertEqual(model.step([], Op("get", (), True, None)), [[]])
        self.assertEqual(model.step([5, 6], Op("get", (), True, 5)), [[6]])
        self.assertEqual(model.step([5, 6], Op("get", (), True, 6)), [])
        self.assertEqual(model.step([5, 6], Op("get", (), False)), [[6]])

    def test_a_counter_returns_the_new_count_and_resets_to_0(self) -> None:
        """An increment of 3 returns 4."""
        model = counter()
        self.assertEqual(model.step(3, Op("increment", (), True, 4)), [4])
        self.assertEqual(model.step(3, Op("increment", (), True, 3)), [])
        self.assertEqual(model.step(3, Op("reset", (), True, None)), [0])


@final
class SubjectTest(unittest.TestCase):
    """Each subject's run: the minimal steps of a failure, or a pass."""

    def test_each_failing_subject_shrinks_to_its_minimal_steps(self) -> None:
        """The same minimal trace from every seed."""
        for name, (identity, minimal) in MINIMAL.items():
            for seed in SEEDS:
                outcome = run(body(name), Settings(seed=seed))
                self.assertEqual(outcome.kind, Kind.COUNTEREXAMPLE, (name, seed))
                assert outcome.failing is not None
                self.assertEqual(outcome.failing.identity, identity, (name, seed))
                self.assertEqual(entries(outcome.failing.case), minimal, (name, seed))

    def test_the_correct_subjects_pass(self) -> None:
        """A hundred cases of each."""
        for name in (CORRECT_QUEUE, CORRECT_COUNTER):
            outcome = run(body(name), Settings(seed=1))
            self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, 100), name)

    def test_the_minimal_steps_replay_as_a_trace(self) -> None:
        """Each trace fails with its failure, and records itself again."""
        for name, (identity, minimal) in MINIMAL.items():
            execution = execute(body(name), Tracing(minimal), 8192)
            self.assertEqual(execution.status, Status.FAILED, name)
            self.assertEqual(execution.identity, identity, name)
            self.assertEqual(entries(execution.case), minimal, name)

    def test_a_trace_of_the_wrapping_queue_without_its_get_passes(self) -> None:
        """Two puts alone fill the queue and show nothing."""
        minimal = MINIMAL[QUEUE_LOSES_ON_WRAP][1]
        execution = execute(body(QUEUE_LOSES_ON_WRAP), Tracing(minimal[:-1]), 8192)
        self.assertEqual(execution.status, Status.PASSED)
