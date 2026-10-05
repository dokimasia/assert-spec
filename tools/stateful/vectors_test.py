"""The vector function of machines, and what it refuses."""

from __future__ import annotations

import unittest
from typing import Any, final

from prop import replay
from prop.vectors import VectorError

from .vectors import compute

#: The settings every vector here runs with.
SEED: dict[str, Any] = {"seed": "1"}

#: The steps of counter-overflows that make its third increment return 0.
THREE_INCREMENTS: list[dict[str, Any]] = [{"step": "increment"}] * 3


def machines(subject: str, **inputs: Any) -> dict[str, Any]:
    """Return the outputs of a machines vector of subject, run at SEED."""
    return compute("machines", {"subject": subject, "settings": SEED, **inputs})


def outcome(subject: str, **inputs: Any) -> str:
    """Return the outcome of a machines vector of subject."""
    return str(machines(subject, **inputs)["detail"]["outcome"])


def key(value: int) -> dict[str, Any]:
    """Return the draw entry of the key that a put of the store draws."""
    return {"label": "key", "value": {"type": "int", "value": value}}


@final
class MachinesTest(unittest.TestCase):
    """machines: the detail of a run of a named subject, or the trace's error."""

    def test_a_failing_subject_states_its_minimal_steps(self) -> None:
        """Three increments, with no draw between them, fail the check."""
        got = machines("counter-overflows")
        self.assertIsNone(got["error"])
        detail = got["detail"]
        self.assertEqual(
            (detail["outcome"], detail["failure"]), ("counterexample", "linearizable")
        )
        self.assertEqual(detail["counterexample"], THREE_INCREMENTS)

    def test_a_correct_subject_passes(self) -> None:
        """A hundred cases of two clients under the task scheduler."""
        detail = machines("correct-counter")["detail"]
        self.assertEqual((detail["outcome"], detail["cases"]), ("passed", 100))

    def test_the_setup_states_the_options_of_the_steps(self) -> None:
        """Each option stops the fault that the subject fails with by default."""
        for subject, setup in (
            ("counter-overflows", {"max": 2}),
            ("counter-overflows", {"mean": 0}),
            ("racy-counter", {"clients": 1}),
            ("racy-counter", {"concurrent": 0}),
        ):
            with self.subTest(subject=subject, setup=setup):
                self.assertEqual(outcome(subject, setup=setup), "passed")

    def test_swarm_adds_one_choice_per_action(self) -> None:
        """The minimal case of counter-overflows keeps increment and drops reset."""
        tokens = [
            machines("counter-overflows", setup={"swarm": swarm})["detail"]["choices"]
            for swarm in (True, False)
        ]
        on, off = (len(replay.decode(token)) for token in tokens)
        self.assertEqual(on - off, 2)

    def test_a_strategy_is_uniform_or_a_pct_depth(self) -> None:
        """PCT finds the race too, refuses a depth of 0, and nothing else reads."""
        self.assertEqual(
            outcome("racy-counter", setup={"strategy": {"pct": 2}}), "counterexample"
        )
        with self.assertRaisesRegex(ValueError, "PCT depth of 0"):
            machines("racy-counter", setup={"strategy": {"pct": 0}})
        with self.assertRaisesRegex(VectorError, "'random' is no strategy"):
            machines("racy-counter", setup={"strategy": "random"})

    def test_a_trace_runs_as_the_first_case(self) -> None:
        """The minimal steps of the wrapping queue fail, and shrink to themselves."""
        trace = [
            {"label": "capacity", "value": {"type": "int", "value": 2}},
            {"step": "put"},
            {"label": "v", "value": {"type": "int", "value": 0}},
            {"step": "put"},
            {"label": "v", "value": {"type": "int", "value": 1}},
            {"step": "get"},
        ]
        detail = machines("queue-loses-on-wrap", trace=trace)["detail"]
        self.assertEqual(detail["failure"], "linearizable")
        named = [e.get("step", e.get("label")) for e in detail["counterexample"]]
        self.assertEqual(named, ["capacity", "put", "v", "put", "v", "get"])

    def test_a_trace_the_body_cannot_follow_is_the_vectors_error(self) -> None:
        """A flush of an empty buffer is not enabled, at entry 1."""
        trace = [{"step": "crash"}, {"step": "flush"}]
        got = machines("store-loses-on-crash", trace=trace)
        refused = {"entry": 1, "name": "flush", "reason": "step"}
        self.assertEqual(got, {"detail": None, "error": refused})

    def test_a_concurrent_step_states_its_client(self) -> None:
        """Client 3 of two clients is refused, and client 1 is taken."""
        refused = machines("racy-counter", trace=[{"step": "increment", "client": 3}])
        want = {"entry": 0, "name": "increment", "reason": "step"}
        self.assertEqual(refused["error"], want)
        taken = machines("racy-counter", trace=[{"step": "increment", "client": 1}])
        self.assertIsNone(taken["error"])

    def test_a_drain_step_states_the_drain_mark(self) -> None:
        """With max 1, a flush after a put is a drain step, not a second step."""
        trace = [{"step": "put"}, key(0), {"step": "flush", "drain": True}]
        got = machines("store-loses-on-crash", setup={"max": 1}, trace=trace)
        self.assertIsNone(got["error"])
        self.assertEqual(got["detail"]["outcome"], "passed")

    def test_a_trace_is_a_list_of_draw_and_step_entries(self) -> None:
        """A map is no trace, and a draw entry states a label and a value."""
        with self.assertRaisesRegex(VectorError, "not a list"):
            machines("correct-queue", trace={"step": "put"})
        with self.assertRaisesRegex(VectorError, "is no trace entry"):
            machines("correct-queue", trace=[{"label": "v"}])

    def test_refuses_a_subject_that_is_not_named(self) -> None:
        """A stack is no machine subject."""
        with self.assertRaisesRegex(VectorError, "'stack' names no machine subject"):
            machines("stack")


@final
class ComputeTest(unittest.TestCase):
    """compute(): the kind and the inputs of a vector."""

    def test_refuses_an_unknown_kind(self) -> None:
        """A kind of the property engine is none of the machines'."""
        with self.assertRaisesRegex(VectorError, "'token' is no vector kind"):
            compute("token", {})

    def test_names_an_input_a_vector_lacks(self) -> None:
        """A machines vector names its subject."""
        with self.assertRaisesRegex(VectorError, "machines vector lacks 'subject'"):
            compute("machines", {"settings": SEED})
