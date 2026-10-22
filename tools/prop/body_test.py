# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""Bodies as data: the drawing body and the named bodies."""

from __future__ import annotations

import unittest
from typing import Any, final

import pytest

from .body import BodyError, build_body
from .case import Case, Replaying
from .choice import Choice
from .execution import Status, execute

#: The generator the drawing bodies of these tests draw from.
DIGIT: dict[str, Any] = {"gen": "integer", "min": 0, "max": 9}


def call(body_spec: dict[str, Any], *values: int) -> Case:
    """Run a body once on recorded integer values and return its case."""
    execution = execute(
        build_body(body_spec), Replaying([Choice("integer", v) for v in values]), 8192
    )
    return execution.case


@final
class DrawingBodyTest(unittest.TestCase):
    """A body that draws one value and classifies, rejects and fails by it."""

    def test_the_draw_is_labelled_value(self) -> None:
        """One draw, under the label value."""
        case = call({"draw": DIGIT}, 4)
        assert [(d.label, d.value) for d in case.draws] == [("value", 4)]

    def test_the_first_failing_identity_wins(self) -> None:
        """A value that matches both entries fails with the first."""
        spec = {
            "draw": DIGIT,
            "fails": [
                {"identity": "big", "when": {"kind": "at-least", "n": 5}},
                {"identity": "seven", "when": {"kind": "divisible-by", "n": 7}},
            ],
        }
        execution = execute(build_body(spec), Replaying([Choice("integer", 7)]), 8192)
        assert execution.identity == "big"

    def test_a_rejecting_body_rejects_before_it_fails(self) -> None:
        """rejects-when holds, so the failure is never checked."""
        spec = {
            "draw": DIGIT,
            "rejects-when": {"kind": "always"},
            "fails": [{"identity": "any", "when": {"kind": "always"}}],
        }
        execution = execute(build_body(spec), Replaying([]), 8192)
        assert execution.status is Status.REJECTED

    def test_classification_counts_labels_whose_predicate_holds(self) -> None:
        """Even and small, not big."""
        spec = {
            "draw": DIGIT,
            "classify": {
                "even": {"kind": "divisible-by", "n": 2},
                "big": {"kind": "at-least", "n": 5},
            },
        }
        assert call(spec, 2).labels == {"even"}

    def test_a_malformed_body_raises(self) -> None:
        """An unknown named body, a fails entry without when, a bad classify."""
        malformed: list[dict[str, Any]] = [
            {"kind": "explodes"},
            {"draw": DIGIT, "fails": [{"identity": "x"}]},
            {"draw": DIGIT, "fails": {"identity": "x"}},
            {"draw": DIGIT, "classify": []},
            {"draw": DIGIT, "fails": [{"identity": False, "when": {"kind": "never"}}]},
            {"draw": DIGIT, "classify": {True: {"kind": "never"}}},
        ]
        for spec in malformed:
            with pytest.raises(BodyError):
                build_body(spec)


@final
class NamedBodyTest(unittest.TestCase):
    """The bodies no predicate can state."""

    def test_draws_nothing_makes_no_choice(self) -> None:
        """No draw and no choice."""
        case = call({"kind": "draws-nothing"})
        assert (case.draws, case.choices) == ([], [])

    def test_diverges_requests_a_boolean_after_its_first_call(self) -> None:
        """A digit's bounds first, a boolean's after."""
        body = build_body({"kind": "diverges"})
        first = execute(body, Replaying([]), 8192).case.requests[0].bounds
        second = execute(body, Replaying([]), 8192).case.requests[0].bounds
        assert (first.kind, second.kind) == ("integer", "integer")
        assert first != second

    def test_fails_once_fails_on_the_first_value_above_1000_only(self) -> None:
        """The same value passes the second time."""
        body = build_body({"kind": "fails-once"})
        recorded = [Choice("integer", 5000)]
        assert execute(body, Replaying(recorded), 8192).identity == "once"
        assert execute(body, Replaying(recorded), 8192).status is Status.PASSED

    def test_fails_once_passes_1000(self) -> None:
        """1000 is not above 1000."""
        body = build_body({"kind": "fails-once"})
        recorded = [Choice("integer", 1000)]
        assert execute(body, Replaying(recorded), 8192).status is Status.PASSED

    def test_each_build_starts_fresh(self) -> None:
        """A second body of fails-once fails again."""
        recorded = [Choice("integer", 5000)]
        for _ in range(2):
            execution = execute(
                build_body({"kind": "fails-once"}), Replaying(recorded), 8192
            )
            assert execution.identity == "once"
