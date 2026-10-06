"""The functions of the subject kinds that take one input."""

from __future__ import annotations

import unittest
from typing import final

from .function import FUNCTIONS


@final
class FunctionTest(unittest.TestCase):
    """What each function returns for its input."""

    def test_each_function_returns_what_its_summary_states(self) -> None:
        """One input each, with the result the subject's summary gives it."""
        cases: list[tuple[str, object, object]] = [
            ("identity", [1, 2], [1, 2]),
            ("is-non-negative", 0, True),
            ("returns-null", 3, None),
            ("drops-the-first", [1, 2], [2]),
            ("prepends-zero", [1], [0, 1]),
            ("sorts", [2, 1, 2], [1, 2, 2]),
            ("wraps-in-a-and-b", "x", "axb"),
        ]
        for kind, given, result in cases:
            with self.subTest(kind=kind):
                self.assertEqual(FUNCTIONS[kind](given), result)
