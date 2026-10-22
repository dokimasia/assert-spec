# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""Traces: the entries of a case, and the provider that serves a trace's values."""

from __future__ import annotations

import unittest
from typing import final

import pytest

from .case import Case, Replaying, Step
from .choice import Choice, IntegerBounds
from .generator import Integer, Optional
from .trace import Draw, TraceError, Tracing, entries

#: The generator most draws here use.
DIGIT = Integer(IntegerBounds(0, 9))


@final
class EntriesTest(unittest.TestCase):
    """entries(): a case's draws and steps, in request order."""

    def test_a_step_comes_before_the_draws_recorded_after_it(self) -> None:
        """Steps before the first draw, between draws and after the last."""
        case = Case(Replaying([Choice("integer", v) for v in (3, 4)]))
        case.step(Step("put"))
        case.draw(DIGIT, "v")
        case.step(Step("get", client=1))
        case.step(Step("put", drain=True))
        case.draw(DIGIT, "w")
        case.step(Step("get"))
        assert entries(case) == [
            Step("put"),
            Draw("v", 3),
            Step("get", client=1),
            Step("put", drain=True),
            Draw("w", 4),
            Step("get"),
        ]


@final
class TracingTest(unittest.TestCase):
    """Tracing: draws take their entries, and other requests their targets."""

    def test_a_draw_decodes_the_value_of_its_entry(self) -> None:
        """The case records the choices that run backwards from the value."""
        case = Case(Tracing([Draw("x", 7), Draw("y", None)]))
        assert case.draw(DIGIT, "x") == 7
        assert case.draw(Optional(DIGIT), "y") is None
        assert case.choices == [Choice("integer", 7), Choice("integer", 0)]

    def test_a_draw_past_the_last_entry_takes_its_targets(self) -> None:
        """The second draw finds no entry."""
        case = Case(Tracing([Draw("x", 7)]))
        case.draw(DIGIT, "x")
        assert case.draw(Integer(IntegerBounds(3, 9)), "y") == 3

    def test_a_request_outside_a_draw_takes_its_target(self) -> None:
        """Nothing is prepared for it."""
        case = Case(Tracing([Draw("x", 7)]))
        assert case.integer(IntegerBounds(2, 5)) == 2

    def test_a_draw_with_another_label_than_its_entry_raises(self) -> None:
        """The error names the entry, the draw's label and the reason."""
        case = Case(Tracing([Draw("y", 7)]))
        with pytest.raises(TraceError) as caught:
            case.draw(DIGIT, "x")
        error = caught.value
        assert (error.entry, error.name, error.reason) == (0, "x", "label")

    def test_a_draw_where_a_step_entry_is_next_raises(self) -> None:
        """A step entry has no label."""
        case = Case(Tracing([Step("put")]))
        with pytest.raises(TraceError) as caught:
            case.draw(DIGIT, "v")
        assert caught.value.reason == "label"

    def test_a_value_the_generator_cannot_produce_raises(self) -> None:
        """12 is no digit."""
        case = Case(Tracing([Draw("x", 7), Draw("x", 12)]))
        case.draw(DIGIT, "x")
        with pytest.raises(TraceError) as caught:
            case.draw(DIGIT, "x")
        error = caught.value
        assert (error.entry, error.name, error.reason) == (1, "x", "value")

    def test_a_step_entry_is_served_as_the_values_a_machine_takes(self) -> None:
        """take() moves past the entry and serves its values in order."""
        trace = Tracing([Step("put"), Step("get", client=1), Draw("v", 2)])
        case = Case(trace)
        assert trace.next_step() == Step("put")
        assert trace.actions() == frozenset({"put", "get"})
        trace.take(1, 4)
        assert trace.next_step() == Step("get", client=1)
        assert trace.actions() == frozenset({"get"})
        bounds = IntegerBounds(0, 9)
        assert [case.integer(bounds) for _ in range(3)] == [1, 4, 0]
        trace.take()
        assert trace.next_step() is None

    def test_prepared_values_are_fitted_to_their_requests(self) -> None:
        """A value outside the bounds takes the target."""
        trace = Tracing([])
        case = Case(trace)
        trace.prepare(0)
        assert case.integer(IntegerBounds(1, 1)) == 1

    def test_refuse_names_the_step_entry(self) -> None:
        """The reason is step, and the name the step's action."""
        trace = Tracing([Draw("v", 1), Step("get")])
        case = Case(trace)
        case.draw(DIGIT, "v")
        with pytest.raises(TraceError) as caught:
            trace.refuse()
        error = caught.value
        assert (error.entry, error.name, error.reason) == (1, "get", "step")
        assert str(error) == "prop: trace entry 1 (get): step"

    def test_refuse_where_no_step_entry_is_next_raises(self) -> None:
        """A draw entry is next, and refuse names step entries alone."""
        trace = Tracing([Draw("v", 1)])
        with pytest.raises(ValueError, match="trace entry 0 is not a step entry"):
            trace.refuse()
