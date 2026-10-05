"""One call of a body: each way it can end."""

from __future__ import annotations

import unittest
from typing import final

from .case import Case, Place, Replaying
from .choice import Choice
from .execution import Status, execute
from .generator import build
from .tree import Ending, Tree

DIGIT = build({"gen": "integer", "min": 0, "max": 9})
BOOLEAN = build({"gen": "boolean"})

#: A cap of choices that two draws exceed.
ONE_CHOICE = 1


def draws(case: Case) -> None:
    """Draw a digit and pass."""
    case.draw(DIGIT, "n")


@final
class ExecuteTest(unittest.TestCase):
    """execute(): the status of one case."""

    def test_a_body_that_returns_passes(self) -> None:
        """The case and its draws come back."""
        execution = execute(draws, Replaying([Choice("integer", 4)]), 8192)
        self.assertIs(execution.status, Status.PASSED)
        self.assertEqual(execution.case.draws[0].value, 4)
        self.assertIsNone(execution.identity)

    def test_a_body_that_fails_reports_its_identity(self) -> None:
        """The failure and its identity."""
        execution = execute(
            lambda case: case.fail("broken", "why"), Replaying([]), 8192
        )
        self.assertIs(execution.status, Status.FAILED)
        self.assertEqual(execution.identity, "broken")
        assert execution.failure is not None
        self.assertEqual(execution.failure.message, "why")

    def test_a_body_that_assumes_false_is_rejected(self) -> None:
        """assume(False) rejects the case."""
        execution = execute(lambda case: case.assume(False), Replaying([]), 8192)
        self.assertIs(execution.status, Status.REJECTED)

    def test_a_case_past_its_cap_is_rejected(self) -> None:
        """Two draws exceed a cap of one choice."""

        def two(case: Case) -> None:
            case.draw(DIGIT, "a")
            case.draw(DIGIT, "b")

        self.assertIs(execute(two, Replaying([]), ONE_CHOICE).status, Status.REJECTED)

    def test_a_case_that_repeats_a_leaf_is_repeated(self) -> None:
        """The second identical case stops at its draw."""
        tree = Tree()
        execute(draws, Replaying([Choice("integer", 4)]), 8192, tree)
        again = execute(draws, Replaying([Choice("integer", 4)]), 8192, tree)
        self.assertIs(again.status, Status.REPEATED)

    def test_a_case_that_requests_other_bounds_diverges(self) -> None:
        """The divergence names the request, the position and the draw's label."""
        tree = Tree()
        execute(draws, Replaying([]), 8192, tree)
        other = execute(lambda case: case.draw(BOOLEAN, "b"), Replaying([]), 8192, tree)
        self.assertIs(other.status, Status.DIVERGED)
        assert other.divergence is not None
        got = (
            other.divergence.what,
            other.divergence.index,
            other.divergence.label,
            other.divergence.step,
        )
        self.assertEqual(got, ("request", 0, "b", None))

    def test_a_divergence_states_the_place_of_its_request(self) -> None:
        """A request that a machine's step made names the step."""
        tree = Tree()
        execute(draws, Replaying([]), 8192, tree)

        def stepping(case: Case) -> None:
            case.place = Place("sequential", 3)
            case.draw(BOOLEAN, "b")

        other = execute(stepping, Replaying([]), 8192, tree)
        assert other.divergence is not None
        self.assertEqual(other.divergence.step, Place("sequential", 3))

    def test_a_case_that_ends_where_another_drew_diverges(self) -> None:
        """An end where the tree recorded a request is a divergence too."""
        tree = Tree()
        execute(draws, Replaying([]), 8192, tree)
        other = execute(lambda case: None, Replaying([]), 8192, tree)
        self.assertIs(other.status, Status.DIVERGED)
        assert other.divergence is not None
        got = (other.divergence.replayed, other.divergence.label, other.divergence.step)
        self.assertEqual(got, (None, None, None))

    def test_a_case_marks_its_leaf_with_how_it_ended(self) -> None:
        """A rejected case leaves a rejected leaf."""
        tree = Tree()

        def reject(case: Case) -> None:
            case.draw(DIGIT, "n")
            case.assume(False)

        execute(reject, Replaying([Choice("integer", 3)]), 8192, tree)
        bounds_node = tree.root.children[3]
        self.assertIs(bounds_node.ending, Ending.REJECTED)
