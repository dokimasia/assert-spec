"""The vector functions of the seam and the checker, and what they refuse."""

from __future__ import annotations

import unittest
from typing import Any, final

from prop.vectors import VectorError

from .vectors import compute

#: The keys of a call on the key x, as typed literals.
X: list[dict[str, Any]] = [{"type": "string", "value": "x"}]

#: The typed literal of null.
NULL: dict[str, Any] = {"type": "null"}

#: A write of 1 that completes, then a read that outputs null.
MISSED: list[dict[str, Any]] = [
    {
        "invoke": 0,
        "client": 0,
        "operation": "write",
        "args": [{"type": "int", "value": 1}],
        "keys": X,
    },
    {"ok": 0, "output": NULL},
    {"invoke": 1, "client": 1, "operation": "read", "args": [], "keys": X},
    {"ok": 1, "output": NULL},
]


def entry(client: int, start: int, end: int | None = None) -> dict[str, Any]:
    """Return an interval of a read of x, ok with null, or pending without an end."""
    stated: dict[str, Any] = {
        "client": client,
        "operation": "read",
        "args": [],
        "keys": X,
        "start": start,
    }
    if end is not None:
        stated.update(end=end, kind="ok", output=NULL)
    return stated


@final
class SeamTest(unittest.TestCase):
    """seam: the events of a script or of intervals, or the entry refused."""

    def test_a_script_records_its_events(self) -> None:
        """The events are in the history's JSON form, and nothing is refused."""
        got = compute("seam", {"script": MISSED[:2]})
        self.assertEqual(got["refused"], None)
        self.assertEqual(
            [(event["index"], event["kind"]) for event in got["events"]],
            [(0, "invoke"), (1, "ok")],
        )

    def test_a_script_names_the_entry_that_raises(self) -> None:
        """A second completion of call 0 is entry 2."""
        got = compute("seam", {"script": [*MISSED[:2], {"ok": 0, "output": NULL}]})
        self.assertEqual(got, {"events": None, "refused": 2})

    def test_intervals_record_their_events(self) -> None:
        """A failure states its error, and a pending entry has no completion."""
        failed = {**entry(0, 0), "end": 1, "kind": "fail", "error": "refused"}
        got = compute("seam", {"intervals": [failed, entry(1, 0)]})
        self.assertEqual(
            [(event["kind"], event.get("error")) for event in got["events"]],
            [("invoke", None), ("invoke", None), ("fail", "refused")],
        )

    def test_intervals_name_the_entry_that_from_intervals_refuses(self) -> None:
        """Entry 1 of client 0 shares the instant 3 with entry 0."""
        got = compute("seam", {"intervals": [entry(0, 3, 6), entry(0, 0, 3)]})
        self.assertEqual(got, {"events": None, "refused": 1})

    def test_a_vector_states_a_script_or_intervals(self) -> None:
        """Both, or neither, is refused."""
        cases: list[dict[str, Any]] = [{}, {"script": [], "intervals": []}]
        for case in cases:
            with self.assertRaisesRegex(VectorError, "a script or intervals"):
                compute("seam", case)

    def test_an_interval_states_an_end_and_a_kind_together(self) -> None:
        """An end without a kind, a kind without an end, and an invoke are refused."""
        for stated in (
            {**entry(0, 0), "end": 1},
            {**entry(0, 0), "kind": "ok", "output": NULL},
            {**entry(0, 0), "end": 1, "kind": "invoke"},
        ):
            with self.assertRaisesRegex(VectorError, "a completion kind and an end"):
                compute("seam", {"intervals": [stated]})


@final
class LinearizableTest(unittest.TestCase):
    """linearizable: the verdict and the detail of a check against a named model."""

    def test_a_violation_fails_with_the_detail_of_its_record(self) -> None:
        """The read misses the write, after two steps."""
        got = compute("linearizable", {"model": "register", "history": MISSED})
        self.assertEqual(got["expect"], "fail")
        self.assertEqual(
            (got["detail"]["outcome"], got["detail"]["steps"]), ("violated", 2)
        )

    def test_a_pass_states_its_steps(self) -> None:
        """A read of null before any write passes after one step."""
        got = compute("linearizable", {"model": "register", "history": MISSED[2:]})
        self.assertEqual(got["expect"], "pass")
        self.assertEqual(
            (got["detail"]["outcome"], got["detail"]["steps"]), ("passed", 1)
        )

    def test_reads_the_budget_and_the_memo_limit(self) -> None:
        """A budget of one step, and a memo below one configuration, each stop it."""
        for limit, case in (
            ("steps", {"budget": 1}),
            ("memo", {"memo-limit": 1}),
        ):
            got = compute(
                "linearizable", {"model": "register", "history": MISSED, **case}
            )
            self.assertEqual(got["detail"]["limit"], limit)

    def test_reports_on_four_workers_what_it_reports_on_one(self) -> None:
        """The workers are read, and change nothing."""
        one = compute("linearizable", {"model": "register", "history": MISSED})
        four = compute(
            "linearizable", {"model": "register", "history": MISSED, "workers": 4}
        )
        self.assertEqual(four, one)

    def test_refuses_a_limit_that_is_not_a_positive_integer(self) -> None:
        """A zero, a negative number, a bool and a string are no limit."""
        for name, value in (
            ("budget", 0),
            ("memo-limit", -1),
            ("workers", True),
            ("workers", "4"),
        ):
            with self.assertRaisesRegex(VectorError, f"{name} is .*not a positive"):
                compute(
                    "linearizable",
                    {"model": "register", "history": MISSED, name: value},
                )

    def test_refuses_a_model_that_is_not_named(self) -> None:
        """A stack is no named model."""
        with self.assertRaisesRegex(VectorError, "'stack' is no named model"):
            compute("linearizable", {"model": "stack", "history": MISSED})

    def test_refuses_a_history_whose_script_raises(self) -> None:
        """A history is a script that the seam accepts."""
        refused = [*MISSED[:2], {"ok": 0, "output": NULL}]
        with self.assertRaisesRegex(VectorError, "script entry 2"):
            compute("linearizable", {"model": "register", "history": refused})


@final
class ComputeTest(unittest.TestCase):
    """compute(): the kind and the inputs of a vector."""

    def test_refuses_an_unknown_kind(self) -> None:
        """A kind of the property engine is none of the history's."""
        with self.assertRaisesRegex(VectorError, "'token' is no vector kind"):
            compute("token", {})

    def test_names_an_input_a_vector_lacks(self) -> None:
        """A linearizable vector names its model."""
        with self.assertRaisesRegex(VectorError, "linearizable vector lacks 'model'"):
            compute("linearizable", {"history": MISSED})
