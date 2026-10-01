"""The case tree: repeats, divergences, exhaustion and its size limit."""

from __future__ import annotations

import math
import unittest
from typing import final

from .case import Request
from .choice import Bounds, FloatBounds, IntegerBounds, SequenceBounds, Value
from .tree import NODE_LIMIT, Diverged, Ending, Repeated, Tree, size

#: The tree's limit, pinned as the definition states it.
PINNED_LIMIT = 1 << 20

BIT = IntegerBounds(0, 1)
DIGIT = IntegerBounds(0, 9)
ONE_FLOAT = FloatBounds(1.0, 1.0)


def _request(bounds: Bounds) -> Request:
    """Return a request with bounds, whose draw the tree never calls."""

    def unused(source: object) -> Value:
        raise AssertionError(f"the tree drew from {source}")

    return Request(bounds, unused)


def walk(
    tree: Tree, *steps: tuple[Bounds, Value], ending: Ending = Ending.PASSED
) -> None:
    """Walk one case through tree and end it."""
    walker = tree.walker()
    for index, (bounds, value) in enumerate(steps):
        walker.step(index, _request(bounds), value)
    walker.end(ending)


@final
class SizeTest(unittest.TestCase):
    """size(): the values a choice's bounds allow."""

    def test_integer_and_bounded_sequence_bounds_are_counted(self) -> None:
        """Ten digits; 1 + 2 + 4 sequences of length up to 2 over two values."""
        self.assertEqual(size(DIGIT), 10)
        self.assertEqual(size(SequenceBounds(2, 0, 2)), 7)

    def test_floats_and_unbounded_sequences_are_not_counted(self) -> None:
        """Neither ever exhausts."""
        self.assertIsNone(size(ONE_FLOAT))
        self.assertIsNone(size(SequenceBounds(2)))


@final
class RepeatTest(unittest.TestCase):
    """A case that repeats a tested one stops, and does not count."""

    def test_a_choice_that_arrives_at_a_leaf_raises_repeated(self) -> None:
        """The second case of 7 stops at its first choice."""
        tree = Tree()
        walk(tree, (DIGIT, 7))
        with self.assertRaises(Repeated):
            walk(tree, (DIGIT, 7))

    def test_a_rejected_case_is_a_leaf_too(self) -> None:
        """A repeat of a rejected case stops as well."""
        tree = Tree()
        walk(tree, (DIGIT, 3), ending=Ending.REJECTED)
        with self.assertRaises(Repeated):
            walk(tree, (DIGIT, 3))

    def test_every_nan_is_one_edge_and_the_zeros_are_two(self) -> None:
        """A NaN of another sign repeats; -0 does not repeat +0."""
        tree = Tree()
        nan = FloatBounds(-math.inf, math.inf, allow_nan=True)
        walk(tree, (nan, math.nan))
        with self.assertRaises(Repeated):
            walk(tree, (nan, -math.nan))
        walk(tree, (nan, 0.0))
        walk(tree, (nan, -0.0))
        self.assertEqual(len(tree.root.children), 3)


@final
class DivergenceTest(unittest.TestCase):
    """A body that requests different choices after the same values."""

    def test_other_bounds_at_a_recorded_position_raise_diverged(self) -> None:
        """Both requests are reported, with the position."""
        tree = Tree()
        walk(tree, (DIGIT, 1), (DIGIT, 2))
        with self.assertRaises(Diverged) as caught:
            walk(tree, (DIGIT, 1), (BIT, 0))
        self.assertEqual(
            (
                caught.exception.index,
                caught.exception.recorded,
                caught.exception.requested,
            ),
            (1, DIGIT, BIT),
        )

    def test_a_request_where_an_earlier_case_ended_raises_diverged(self) -> None:
        """The recorded side is None, for an end."""
        tree = Tree()
        walk(tree)
        with self.assertRaises(Diverged) as caught:
            walk(tree, (DIGIT, 1))
        self.assertIsNone(caught.exception.recorded)

    def test_an_end_where_an_earlier_case_made_a_request_raises_diverged(
        self,
    ) -> None:
        """The requested side is None, for an end."""
        tree = Tree()
        walk(tree, (DIGIT, 1))
        with self.assertRaises(Diverged) as caught:
            walk(tree)
        self.assertEqual(caught.exception.index, 0)
        self.assertIsNone(caught.exception.requested)


@final
class ExhaustionTest(unittest.TestCase):
    """A tree whose root is exhausted has seen every input of its domain."""

    def test_a_domain_is_exhausted_when_every_value_reached_a_leaf(self) -> None:
        """Two booleans: exhausted after the fourth distinct case, not the third."""
        tree = Tree()
        for first, second in ((0, 0), (0, 1), (1, 0)):
            walk(tree, (BIT, first), (BIT, second))
            self.assertFalse(tree.exhausted)
        walk(tree, (BIT, 1), (BIT, 1))
        self.assertTrue(tree.exhausted)

    def test_a_shorter_branch_exhausts_by_its_leaf(self) -> None:
        """A 0 ends at once; a 1 needs both of its children."""
        tree = Tree()
        walk(tree, (BIT, 0))
        walk(tree, (BIT, 1), (BIT, 0))
        self.assertFalse(tree.exhausted)
        walk(tree, (BIT, 1), (BIT, 1))
        self.assertTrue(tree.exhausted)

    def test_a_case_without_choices_exhausts_the_domain(self) -> None:
        """The root itself is the leaf."""
        tree = Tree()
        walk(tree)
        self.assertTrue(tree.exhausted)

    def test_a_float_never_exhausts(self) -> None:
        """Even a float range of one value."""
        tree = Tree()
        walk(tree, (ONE_FLOAT, 1.0))
        self.assertFalse(tree.exhausted)


@final
class LimitTest(unittest.TestCase):
    """The tree stops growing at its limit."""

    def test_the_limit_is_2_to_the_20_nodes(self) -> None:
        """The fixed limit."""
        self.assertEqual(NODE_LIMIT, PINNED_LIMIT)

    def test_a_full_tree_stops_checking_and_reports_no_exhaustion(self) -> None:
        """Past the limit a walk adds nothing, finds nothing, and exhausts nothing."""
        tree = Tree(limit=3)
        walk(tree, (BIT, 0), (BIT, 0))
        self.assertEqual(tree.nodes, 3)
        walk(tree, (BIT, 0), (BIT, 1))
        self.assertTrue(tree.full)
        self.assertEqual(tree.nodes, 3)
        walk(tree, (BIT, 0), (BIT, 1))
        tree.root.exhausted = True
        self.assertFalse(tree.exhausted)
