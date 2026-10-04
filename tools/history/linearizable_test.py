"""check() over partitions, its search, its limits and the record it returns."""

from __future__ import annotations

import math
import unittest
from typing import Any, final

from .linearizable import Limit, Outcome, check
from .model import NAMED, Model, Op, Subject, model_from
from .seam import Call, History

REGISTER = NAMED["register"]

#: The typed literal of null.
NULL: dict[str, Any] = {"type": "null"}


def literal(value: int | str) -> dict[str, Any]:
    """Return the typed literal of an int or a string."""
    return {"type": "int" if isinstance(value, int) else "string", "value": value}


def write(history: History, client: int, value: object, *keys: object) -> Call:
    """Invoke a write of value, on the key x unless keys are given."""
    return history.invoke(client, "write", [value], list(keys or ("x",)))


def read(history: History, client: int, *keys: object) -> Call:
    """Invoke a read, on the key x unless keys are given."""
    return history.invoke(client, "read", [], list(keys or ("x",)))


def lock(state: object, op: Op) -> list[object]:
    """Step a lock: acquire(c) takes a free lock for c, and release(c) frees it."""
    (client,) = op.args
    if op.operation == "acquire":
        return [client] if state is None else []
    return [None] if state == client else []


@final
class OutcomeTest(unittest.TestCase):
    """check(): passed and violated, and the record of a violation."""

    def test_a_read_after_a_completed_write_that_misses_it_is_violated(self) -> None:
        """The frontier is the write, and the read is its one candidate."""
        history = History()
        write(history, 0, 1).ok(None)
        read(history, 1).ok(None)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(
            verdict.detail(),
            {
                "outcome": "violated",
                "partitions": 1,
                "steps": 2,
                "partition": [literal("x")],
                "calls": 2,
                "concurrency": 1,
                "linearized": [
                    {
                        "call": 0,
                        "completion": 1,
                        "process": 0,
                        "operation": "write",
                        "args": [literal(1)],
                        "output": NULL,
                    }
                ],
                "states": [literal(1)],
                "candidates": [
                    {
                        "call": 2,
                        "completion": 3,
                        "process": 1,
                        "operation": "read",
                        "args": [],
                        "output": NULL,
                    }
                ],
                "limit": None,
            },
        )

    def test_concurrent_writes_take_effect_in_the_order_a_read_needs(self) -> None:
        """The read of 1 needs the write of 2 first, which the sixth step finds."""
        history = History()
        first = write(history, 0, 1)
        second = write(history, 1, 2)
        first.ok(None)
        second.ok(None)
        read(history, 0).ok(1)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(
            (verdict.outcome, verdict.partitions, verdict.steps), (Outcome.PASSED, 1, 6)
        )

    def test_the_detail_of_a_pass_states_no_reported_partition(self) -> None:
        """A pass reports no record, so each field of a reported partition is null."""
        history = History()
        write(history, 0, 1).ok(None)
        read(history, 1).ok(1)
        self.assertEqual(
            check(history.events(), REGISTER).detail(),
            {
                "outcome": "passed",
                "partitions": 1,
                "steps": 2,
                "partition": None,
                "calls": None,
                "concurrency": None,
                "linearized": None,
                "states": None,
                "candidates": None,
                "limit": None,
            },
        )

    def test_a_history_without_calls_passes(self) -> None:
        """No events, or only failed calls, leave no partition."""
        history = History()
        self.assertEqual(check(history.events(), REGISTER).partitions, 0)
        write(history, 0, 1).fail("refused")
        verdict = check(history.events(), REGISTER)
        self.assertEqual(
            (verdict.outcome, verdict.partitions, verdict.steps), (Outcome.PASSED, 0, 0)
        )


@final
class CompletionTest(unittest.TestCase):
    """How the checker reads fail, unknown and pending calls."""

    def test_a_failed_call_takes_no_effect_and_joins_no_partition(self) -> None:
        """The failed write on x and y neither changes x nor joins it to y."""
        history = History()
        write(history, 0, 5, "x", "y").fail("refused")
        read(history, 1, "x").ok(None)
        read(history, 2, "y").ok(None)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(
            (verdict.outcome, verdict.partitions, verdict.steps), (Outcome.PASSED, 2, 2)
        )

    def test_a_write_whose_outcome_is_unknown_takes_effect_later(self) -> None:
        """The unknown write of 2 follows the read of 1 and precedes the read of 2."""
        history = History()
        write(history, 0, 1).ok(None)
        lost = write(history, 1, 2)
        read(history, 0).ok(1)
        lost.unknown("timed out")
        read(history, 0).ok(2)
        verdict = check(history.events(), REGISTER)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.PASSED, 6))

    def test_a_call_whose_outcome_is_unknown_may_never_take_effect(self) -> None:
        """A second acquire of a held lock never took effect, so the history passes."""
        model = Model(lambda: None, lock)
        history = History()
        history.invoke(0, "acquire", [0], ["lock"]).ok(None)
        history.invoke(1, "acquire", [1], ["lock"]).unknown("timed out")
        history.invoke(2, "acquire", [2], ["lock"])
        verdict = check(history.events(), model)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.PASSED, 1))

    def test_a_pending_call_takes_effect_when_a_later_read_needs_it(self) -> None:
        """A write that never completes is seen by a read after it."""
        history = History()
        write(history, 0, 1)
        read(history, 1).ok(1)
        verdict = check(history.events(), REGISTER)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.PASSED, 2))

    def test_a_record_states_no_completion_of_a_pending_call(self) -> None:
        """A pending call states no completion, and an unknown call no output."""
        history = History()
        write(history, 0, 1)
        write(history, 1, 2).unknown("timed out")
        read(history, 2).ok(9)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(verdict.outcome, Outcome.VIOLATED)
        self.assertEqual(verdict.steps, 9)
        self.assertEqual((verdict.calls, verdict.concurrency), (3, 3))
        self.assertEqual(
            [call.document() for call in verdict.linearized],
            [
                {"call": 0, "process": 0, "operation": "write", "args": [literal(1)]},
                {
                    "call": 1,
                    "completion": 2,
                    "process": 1,
                    "operation": "write",
                    "args": [literal(2)],
                },
            ],
        )
        self.assertEqual(verdict.states, (2,))
        self.assertEqual([call.index for call in verdict.candidates], [3])


@final
class PartitionTest(unittest.TestCase):
    """Partitions: their keys, their order and the one reported."""

    def test_reports_the_first_violated_partition_in_order_of_first_invocation(
        self,
    ) -> None:
        """Partition y is searched first and passes, then x fails at the start."""
        history = History()
        write(history, 0, 1, "y").ok(None)
        read(history, 1, "x").ok(5)
        read(history, 2, "y").ok(1)
        verdict = check(history.events(), REGISTER)
        detail = verdict.detail()
        self.assertEqual(
            {
                name: detail[name]
                for name in ("outcome", "partitions", "steps", "partition")
            },
            {
                "outcome": "violated",
                "partitions": 2,
                "steps": 3,
                "partition": [literal("x")],
            },
        )
        self.assertEqual((detail["linearized"], detail["states"]), ([], [NULL]))
        self.assertEqual([call["call"] for call in detail["candidates"]], [2])

    def test_a_call_on_two_keys_joins_their_partitions(self) -> None:
        """The keys are listed in the order the history first declares them."""
        history = History()
        read(history, 0, "x").ok(None)
        write(history, 1, 2, "y", "x").ok(None)
        read(history, 2, "y").ok(3)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(verdict.partition, ("x", "y"))
        self.assertEqual((verdict.partitions, verdict.calls, verdict.steps), (1, 3, 3))
        self.assertEqual([call.index for call in verdict.linearized], [0, 2])
        self.assertEqual(verdict.states, (2,))

    def test_a_call_that_declares_no_key_touches_every_key(self) -> None:
        """The whole history is one partition, which lists no key."""
        history = History()
        write(history, 0, 1, "x").ok(None)
        history.invoke(1, "read", [], []).ok(2)
        write(history, 2, 1, "y").ok(None)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(
            (verdict.partitions, verdict.partition, verdict.calls), (1, (), 3)
        )
        self.assertEqual(verdict.detail()["partition"], [])

    def test_a_key_is_its_typed_literal(self) -> None:
        """The int 1 and the float 1.0 are two keys, so two partitions."""
        history = History()
        write(history, 0, 1, 1).ok(None)
        read(history, 1, 1.0).ok(None)
        self.assertEqual(check(history.events(), REGISTER).partitions, 2)


@final
class LimitTest(unittest.TestCase):
    """The budget and the memo limit, and the partition they report."""

    def history(self) -> History:
        """Return a history whose partition x needs two steps and y one."""
        history = History()
        write(history, 0, 1).ok(None)
        read(history, 1).ok(1)
        read(history, 2, "y").ok(None)
        return history

    def test_a_budget_is_spent_exactly(self) -> None:
        """Two steps decide x, so a budget of two passes."""
        verdict = check(self.history().events(), REGISTER, budget=2)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.PASSED, 3))

    def test_the_search_stops_before_a_step_past_its_budget(self) -> None:
        """Partition x stops after one step, and the step of y is not counted."""
        verdict = check(self.history().events(), REGISTER, budget=1)
        detail = verdict.detail()
        self.assertEqual(
            {
                name: detail[name]
                for name in ("outcome", "partitions", "steps", "partition", "limit")
            },
            {
                "outcome": "undecided",
                "partitions": 2,
                "steps": 1,
                "partition": [literal("x")],
                "limit": "steps",
            },
        )
        self.assertEqual([call["call"] for call in detail["linearized"]], [0])
        self.assertEqual((detail["states"], detail["candidates"]), ([literal(1)], []))

    def test_a_violated_partition_after_an_undecided_one_is_reported(self) -> None:
        """The violation of y is reported, with the steps of x and y."""
        history = History()
        write(history, 0, 1).ok(None)
        read(history, 1).ok(1)
        read(history, 2, "y").ok(7)
        verdict = check(history.events(), REGISTER, budget=1)
        self.assertEqual(
            (verdict.outcome, verdict.partition, verdict.steps, verdict.limit),
            (Outcome.VIOLATED, ("y",), 2, None),
        )

    def test_the_first_of_two_undecided_partitions_is_reported(self) -> None:
        """Partitions x and y each stop after one step, and x is reported."""
        history = History()
        write(history, 0, 1).ok(None)
        read(history, 1).ok(1)
        write(history, 2, 2, "y").ok(None)
        read(history, 3, "y").ok(2)
        verdict = check(history.events(), REGISTER, budget=1)
        self.assertEqual(
            (verdict.outcome, verdict.partition, verdict.steps),
            (Outcome.UNDECIDED, ("x",), 1),
        )

    def test_the_memo_limit_counts_a_bit_per_call_for_each_configuration(self) -> None:
        """Partition x has two calls, so its second configuration needs four bits."""
        passed = check(self.history().events(), REGISTER, memo_limit=4)
        self.assertEqual(passed.outcome, Outcome.PASSED)
        stopped = check(self.history().events(), REGISTER, memo_limit=3)
        self.assertEqual(
            (stopped.outcome, stopped.limit, stopped.steps, stopped.partition),
            (Outcome.UNDECIDED, Limit.MEMO, 2, ("x",)),
        )
        self.assertEqual(
            ([call.index for call in stopped.linearized], stopped.candidates), ([0], ())
        )

    def test_a_step_of_a_model_from_a_subject_costs_its_depth_plus_one(self) -> None:
        """The second add replays the first, so it costs two steps."""

        def counter() -> Subject:
            total = [0]

            def apply(operation: str, args: tuple[object, ...]) -> object:
                del operation
                (amount,) = args
                assert isinstance(amount, int)
                total[0] += amount
                return total[0]

            return apply

        history = History()
        history.invoke(0, "add", [1], []).ok(1)
        history.invoke(1, "add", [2], []).ok(3)
        model = model_from(counter)
        self.assertEqual(check(history.events(), model).steps, 3)
        stopped = check(history.events(), model, budget=2)
        self.assertEqual(
            (stopped.outcome, stopped.limit, stopped.steps),
            (Outcome.UNDECIDED, Limit.STEPS, 1),
        )


@final
class ConfigurationTest(unittest.TestCase):
    """How configurations merge equal states, and how open calls are counted."""

    def test_a_configuration_keeps_one_of_each_group_of_equal_states(self) -> None:
        """Two lossy writes of 1 leave the states 1 and null, not four states."""
        history = History()
        write(history, 0, 1).ok(None)
        write(history, 0, 1).ok(None)
        read(history, 0).ok(7)
        verdict = check(history.events(), NAMED["lossy-register"])
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.VIOLATED, 5))
        self.assertEqual(verdict.detail()["states"], [literal(1), NULL])

    def test_the_memo_merges_a_configuration_reached_twice(self) -> None:
        """Two orders of two writes of 1 reach one configuration, searched once."""
        history = self.writes(1)
        verdict = check(history.events(), REGISTER)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.VIOLATED, 5))

    def test_the_memo_never_merges_a_state_that_contains_a_nan(self) -> None:
        """A NaN equals nothing, so the second order is searched again."""
        verdict = check(self.writes(math.nan).events(), REGISTER)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.VIOLATED, 6))

    def test_two_lists_of_states_are_one_configuration_only_at_one_length(self) -> None:
        """A key coarser than equality puts [1, 2] and [1] in one bucket.

        The orders a, b and b, a leave those two lists for the same calls.
        [1] is a new configuration, so c is stepped from it too.
        """

        def paths(state: object, op: Op) -> list[object]:
            if op.operation == "c":
                return []
            table: dict[tuple[str, object], list[object]] = {
                ("a", 0): [1, 2],
                ("a", 5): [1],
                ("b", 0): [5],
            }
            return table.get((op.operation, state), [state])

        model = Model(lambda: 0, paths, key=lambda state: 0)
        history = History()
        a = history.invoke(0, "a", [], ["x"])
        b = history.invoke(1, "b", [], ["x"])
        a.ok(None)
        b.ok(None)
        history.invoke(2, "c", [], ["x"]).ok(None)
        verdict = check(history.events(), model)
        self.assertEqual((verdict.outcome, verdict.steps), (Outcome.VIOLATED, 8))

    def writes(self, value: object) -> History:
        """Return two concurrent writes of value, then a read of 5."""
        history = History()
        first = write(history, 0, value)
        second = write(history, 1, value)
        first.ok(None)
        second.ok(None)
        read(history, 0).ok(5)
        return history

    def test_an_unknown_call_is_open_to_the_end_of_the_history(self) -> None:
        """The unknown write is open with the two reads after it."""
        history = History()
        first = write(history, 0, 1)
        lost = write(history, 1, 2)
        lost.unknown("timed out")
        first.ok(None)
        late = read(history, 2)
        read(history, 3).ok(9)
        late.ok(9)
        verdict = check(history.events(), REGISTER)
        self.assertEqual(
            (verdict.outcome, verdict.calls, verdict.concurrency),
            (Outcome.VIOLATED, 4, 3),
        )
