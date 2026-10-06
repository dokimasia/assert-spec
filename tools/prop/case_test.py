"""The case: where its values come from, what it records, and its cap."""

from __future__ import annotations

import unittest
from typing import final

from . import draw
from .case import (
    MAX_CHOICES,
    Case,
    Generating,
    Generator,
    Overrun,
    Place,
    Rejected,
    Replaying,
    Request,
    Span,
    Step,
    Valuing,
    Where,
)
from .choice import INT64_MAX, INT64_MIN, Choice, IntegerBounds, SequenceBounds, Value
from .source import Source

#: The bounds most cases here request.
DIGIT = IntegerBounds(0, 9)

#: The first twelve reuse requests over the whole signed 64-bit range from
#: seed 42, pinned so that any change to reuse fails here before a corpus
#: vector moves.
PINNED_REUSE = [
    11,
    13,
    9223372036854775807,
    9223372036854775807,
    -207,
    -781715023583996500,
    -9223372036854775808,
    -43,
    -12,
    -2609675888663766267,
    -2609675888663766267,
    229,
]


def _digit() -> Request:
    """Return a request for one digit, drawn as integer() draws."""
    return Request(DIGIT, lambda source: draw.integer(source, DIGIT))


def _sequence(bounds: SequenceBounds) -> Request:
    """Return a request for one sequence inside bounds."""
    return Request(bounds, lambda source: draw.sequence(source, bounds))


@final
class _Digit:
    """A generator of one digit that opens no span."""

    def decode(self, case: Case) -> object:
        """Return the case's next digit."""
        return case.choose(_digit())


@final
class _Outer:
    """A generator that requests a digit and then draws a digit under inner."""

    def decode(self, case: Case) -> object:
        """Return the two digits."""
        return (case.choose(_digit()), case.draw(_Digit(), "inner"))


@final
class _Refusing:
    """A generator that requests a digit and then rejects the case."""

    def decode(self, case: Case) -> object:
        """Request a digit, then reject.

        Raises:
            Rejected: always.
        """
        case.choose(_digit())
        raise Rejected


@final
class _Announced:
    """A provider that replays digits and keeps the label of every draw it hears of."""

    def __init__(self) -> None:
        """Replay 4, 5, 6, and hear of no draw yet."""
        self._replay = Replaying([Choice("integer", v) for v in (4, 5, 6)])
        self.served = 0
        self.heard: list[tuple[str, int]] = []

    def value(self, request: Request, index: int) -> Value:
        """Return the replayed value, and count it."""
        self.served += 1
        return self._replay.value(request, index)

    def drawing(self, generator: Generator, label: str) -> None:
        """Keep the label, and the number of values served before it."""
        del generator
        self.heard.append((label, self.served))


@final
class _Steps:
    """An observer that keeps the value of every step."""

    def __init__(self) -> None:
        """Start with no step."""
        self.values: list[Value] = []

    def step(self, index: int, request: Request, value: Value) -> None:
        """Keep value."""
        del index, request
        self.values.append(value)


@final
class GeneratingTest(unittest.TestCase):
    """A generated case draws each value with its request's draw."""

    def test_each_value_is_the_draw_of_its_request(self) -> None:
        """The case consumes the source as the draws alone would."""
        case, twin = Case(Generating(Source(3))), Source(3)
        got = [case.choose(_digit()) for _ in range(20)]
        self.assertEqual(got, [draw.integer(twin, DIGIT) for _ in range(20)])

    def test_the_case_records_each_choice_and_its_request(self) -> None:
        """Kind and value, in request order, beside the request itself."""
        case = Case(Generating(Source(3)))
        request = _digit()
        value = case.choose(request)
        self.assertEqual(case.choices, [Choice("integer", value)])
        self.assertEqual(case.requests, [request])

    def test_a_reuse_request_draws_a_coin_then_an_earlier_value(self) -> None:
        """The first draws as usual; later ones take the coin, then reuse or draw."""
        twin = Source(5)
        case = Case(Generating(Source(5)))
        wide = IntegerBounds(0, 10**9)
        first = case.integer(wide, reuse=True)
        self.assertEqual(first, draw.integer(twin, wide))
        earlier = [first]
        for _ in range(40):
            got = case.integer(wide, reuse=True)
            if twin.coin(1, draw.REUSE_ODDS):
                self.assertEqual(got, earlier[twin.below(len(earlier))])
            else:
                self.assertEqual(got, draw.integer(twin, wide))
            earlier.append(got)

    def test_the_first_reuse_requests_from_seed_42_are_pinned(self) -> None:
        """Twelve requests over the whole signed 64-bit range."""
        case = Case(Generating(Source(42)))
        wide = IntegerBounds(INT64_MIN, INT64_MAX)
        got = [case.integer(wide, reuse=True) for _ in range(12)]
        self.assertEqual(got, PINNED_REUSE)

    def test_a_reuse_request_with_equal_bounds_consumes_nothing(self) -> None:
        """Equal bounds take no coin, so later draws match a fresh source's."""
        case, twin = Case(Generating(Source(7))), Source(7)
        seven = IntegerBounds(7, 7)
        self.assertEqual([case.integer(seven, reuse=True) for _ in range(3)], [7, 7, 7])
        wide = IntegerBounds(0, 10**9)
        self.assertEqual(
            [case.integer(wide) for _ in range(5)],
            [draw.integer(twin, wide) for _ in range(5)],
        )

    def test_reuse_keeps_to_the_bounds_of_the_request(self) -> None:
        """A request takes no value drawn under other bounds."""
        case = Case(Generating(Source(5)))
        for _ in range(30):
            case.integer(IntegerBounds(500, 600), reuse=True)
        values = [case.integer(DIGIT, reuse=True) for _ in range(30)]
        self.assertTrue(all(DIGIT.lo <= v <= DIGIT.hi for v in values))

    def test_a_request_without_reuse_takes_no_coin(self) -> None:
        """After a reuse request, a plain request with its bounds draws as usual."""
        case, twin = Case(Generating(Source(9))), Source(9)
        case.integer(DIGIT, reuse=True)
        draw.integer(twin, DIGIT)
        self.assertEqual(case.integer(DIGIT, edge=0), draw.integer(twin, DIGIT))

    def test_a_reuse_request_takes_no_value_of_a_removed_choice(self) -> None:
        """After a rewind to the start, no earlier value remains, so no coin."""
        wide = IntegerBounds(0, 10**9)
        for seed in range(50):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            start = case.mark()
            case.integer(wide, reuse=True)
            case.rewind(start)
            draw.integer(twin, wide)
            got = case.integer(wide, reuse=True)
            self.assertEqual(got, draw.integer(twin, wide), seed)

    def test_a_reuse_request_takes_no_removed_value_of_other_bounds(self) -> None:
        """A request after a rewind forgets the removed values of every bounds.

        The second attempt requests other bounds first, at the index where
        the rejected value was, and the wide request after it finds no
        earlier value, so no coin.
        """
        wide, narrow = IntegerBounds(0, 10**9), IntegerBounds(0, 10**9 - 1)
        for seed in range(50):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            start = case.mark()
            case.integer(wide, reuse=True)
            case.rewind(start)
            draw.integer(twin, wide)
            case.integer(narrow, reuse=True)
            draw.integer(twin, narrow)
            got = case.integer(wide, reuse=True)
            self.assertEqual(got, draw.integer(twin, wide), seed)


@final
class ReplayingTest(unittest.TestCase):
    """A replayed case reads recorded values back and fits them to its bounds."""

    def test_a_value_that_fits_comes_back(self) -> None:
        """Recorded digits replay in order."""
        case = Case(Replaying([Choice("integer", 7), Choice("integer", 3)]))
        self.assertEqual([case.choose(_digit()), case.choose(_digit())], [7, 3])

    def test_a_value_outside_the_bounds_takes_the_target(self) -> None:
        """12 is no digit, so the request gets 0."""
        case = Case(Replaying([Choice("integer", 12)]))
        self.assertEqual(case.choose(_digit()), 0)

    def test_a_value_of_another_kind_takes_the_target(self) -> None:
        """A recorded sequence where a digit is requested replays as 0."""
        case = Case(Replaying([Choice("sequence", (5,))]))
        self.assertEqual(case.choose(_digit()), 0)

    def test_a_request_past_the_recorded_choices_takes_the_target(self) -> None:
        """Every request after the last recorded choice gets its target."""
        bounds = IntegerBounds(3, 9)
        case = Case(Replaying([Choice("integer", 5)]))
        request = Request(bounds, lambda source: draw.integer(source, bounds))
        self.assertEqual([case.choose(request) for _ in range(3)], [5, 3, 3])

    def test_the_case_records_the_fitted_value(self) -> None:
        """The record contains what the body received, not what was replayed."""
        case = Case(Replaying([Choice("integer", 12)]))
        case.choose(_digit())
        self.assertEqual(case.choices, [Choice("integer", 0)])


@final
class ValuingTest(unittest.TestCase):
    """A case whose draws take stated values, which no choice decodes."""

    def test_each_draw_takes_the_next_value_without_a_choice(self) -> None:
        """A value outside the generator's domain too, and no span opens."""
        case = Case(Valuing([5, "x"]))
        drawn = [case.draw(_Digit(), label) for label in ("a", "b")]
        self.assertEqual(drawn, [5, "x"])
        self.assertEqual((case.choices, case.spans), ([], []))
        recorded = [(d.label, d.value) for d in case.draws]
        self.assertEqual(recorded, [("a", 5), ("b", "x")])

    def test_a_draw_past_the_last_value_decodes_the_targets(self) -> None:
        """The second draw decodes, and its request takes the target."""
        case = Case(Valuing([5]))
        case.draw(_Digit(), "a")
        self.assertEqual(case.draw(_Digit(), "b"), 0)
        self.assertEqual(case.choices, [Choice("integer", 0)])

    def test_a_provider_that_states_values_is_the_valuer(self) -> None:
        """A replay states no value."""
        self.assertIsNotNone(Case(Valuing([])).valuer)
        self.assertIsNone(Case(Replaying([])).valuer)


@final
class CapTest(unittest.TestCase):
    """A case may make at most MAX_CHOICES choices."""

    def test_the_default_cap_is_8192(self) -> None:
        """The fixed limit."""
        self.assertEqual(MAX_CHOICES, 8192)

    def test_a_case_at_its_cap_continues(self) -> None:
        """Exactly max_choices choices are allowed."""
        case = Case(Replaying([]), max_choices=3)
        for _ in range(3):
            case.choose(_digit())
        self.assertEqual(len(case.choices), 3)

    def test_a_choice_past_the_cap_rejects_the_case_as_an_overrun(self) -> None:
        """One more than max_choices raises Overrun, which is a rejection."""
        case = Case(Replaying([]), max_choices=3)
        for _ in range(3):
            case.choose(_digit())
        with self.assertRaises(Rejected) as caught:
            case.choose(_digit())
        self.assertIsInstance(caught.exception, Overrun)

    def test_a_sequence_counts_one_plus_each_element(self) -> None:
        """A sequence of three costs four, so a cap of 4 holds it and 3 does not."""
        bounds = SequenceBounds(10, 3, 3)
        recorded = [Choice("sequence", (1, 2, 3))]
        Case(Replaying(recorded), max_choices=4).choose(_sequence(bounds))
        with self.assertRaises(Overrun):
            Case(Replaying(recorded), max_choices=3).choose(_sequence(bounds))

    def test_a_sequence_whose_minimum_passes_the_cap_draws_nothing(self) -> None:
        """The overrun comes before the draw, so the source stays where it was."""
        source, twin = Source(7), Source(7)
        case = Case(Generating(source), max_choices=3)
        with self.assertRaises(Overrun):
            case.choose(_sequence(SequenceBounds(10, 3)))
        self.assertEqual(source.next(), twin.next())


@final
class SpanTest(unittest.TestCase):
    """Spans: the choices of one generator, element or entry."""

    def test_a_span_covers_the_choices_made_inside_it(self) -> None:
        """[start, end) over the case's choices."""
        case = Case(Replaying([]))
        case.choose(_digit())
        with case.span("pair"):
            case.choose(_digit())
            case.choose(_digit())
        self.assertEqual(case.spans, [Span("pair", 1, 3, 0, None)])

    def test_nested_spans_record_their_depth_and_parent(self) -> None:
        """The parent is the index of the enclosing span in the list."""
        case = Case(Replaying([]))
        with case.span("outer"):
            with case.span("first"):
                case.choose(_digit())
            with case.span("second"):
                case.choose(_digit())
        self.assertEqual(
            case.spans,
            [
                Span("outer", 0, 2, 0, None),
                Span("first", 0, 1, 1, 0),
                Span("second", 1, 2, 1, 0),
            ],
        )

    def test_a_span_can_start_at_an_earlier_choice(self) -> None:
        """The start argument moves the first choice back to an element's flag."""
        case = Case(Replaying([]))
        case.choose(_digit())
        with case.span("element", 0):
            case.choose(_digit())
        self.assertEqual(case.spans, [Span("element", 0, 2, 0, None)])

    def test_a_span_ends_where_its_block_raised(self) -> None:
        """A rejected decode still closes the spans it opened."""
        case = Case(Replaying([]))
        with self.assertRaises(Rejected), case.span("list"):
            case.choose(_digit())
            raise Rejected
        self.assertEqual(case.spans, [Span("list", 0, 1, 0, None)])


@final
class RewindTest(unittest.TestCase):
    """mark() and rewind(): removing what a case recorded after a point."""

    def test_rewind_removes_what_the_case_recorded_after_the_mark(self) -> None:
        """The choices, requests, spans and draws after the mark go."""
        case = Case(Replaying([Choice("integer", v) for v in (1, 2)]))
        case.draw(_Digit(), "kept")
        mark = case.mark()
        with case.span("attempt"):
            case.draw(_Digit(), "removed")
        case.rewind(mark)
        self.assertEqual(case.choices, [Choice("integer", 1)])
        self.assertEqual(len(case.requests), 1)
        self.assertEqual(case.spans, [])
        self.assertEqual([d.label for d in case.draws], ["kept"])

    def test_the_next_choice_takes_the_index_of_the_first_removed_one(self) -> None:
        """A replay reads the recorded choice at the mark again."""
        case = Case(Replaying([Choice("integer", v) for v in (1, 2, 3)]))
        case.choose(_digit())
        mark = case.mark()
        case.choose(_digit())
        case.rewind(mark)
        self.assertEqual(case.choose(_digit()), 2)

    def test_removed_choices_still_count_towards_the_cap(self) -> None:
        """A cap of 2 admits no third choice while the record contains one."""
        case = Case(Replaying([]), max_choices=2)
        start = case.mark()
        case.choose(_digit())
        case.rewind(start)
        case.choose(_digit())
        with self.assertRaises(Overrun):
            case.choose(_digit())

    def test_an_observer_keeps_the_steps_of_removed_choices(self) -> None:
        """The observer sees three steps, and the record keeps two choices."""
        steps = _Steps()
        recorded = [Choice("integer", v) for v in (1, 2, 3)]
        case = Case(Replaying(recorded), observer=steps)
        case.choose(_digit())
        mark = case.mark()
        case.choose(_digit())
        case.rewind(mark)
        case.choose(_digit())
        self.assertEqual(steps.values, [1, 2, 2])
        self.assertEqual(len(case.choices), 2)


@final
class RecordTest(unittest.TestCase):
    """The history, the steps and the tracer of a case."""

    def test_each_case_starts_with_an_empty_history_of_its_own(self) -> None:
        """A call recorded in one case is not in another."""
        first, second = Case(Replaying([])), Case(Replaying([]))
        first.history.invoke(0, "put", [1], []).ok(None)
        self.assertEqual(len(first.history.events()), 2)
        self.assertEqual(second.history.events(), [])

    def test_a_step_is_recorded_after_the_draws_before_it(self) -> None:
        """The number beside each step counts the draws the case recorded first."""
        case = Case(Replaying([]))
        case.step(Step("put"))
        case.draw(_Digit(), "v")
        case.step(Step("get", client=1))
        self.assertEqual(case.steps, [(0, Step("put")), (1, Step("get", client=1))])

    def test_a_provider_that_hears_of_draws_is_the_tracer(self) -> None:
        """Each draw tells the tracer its label before it decodes."""
        provider = _Announced()
        case = Case(provider)
        self.assertIs(case.tracer, provider)
        self.assertEqual([case.draw(_Digit(), label) for label in "ab"], [4, 5])
        self.assertEqual(provider.heard, [("a", 0), ("b", 1)])

    def test_a_provider_that_hears_of_no_draw_is_no_tracer(self) -> None:
        """A replaying case has no tracer."""
        self.assertIsNone(Case(Replaying([])).tracer)


@final
class WhereTest(unittest.TestCase):
    """Where a case made each request and observed each fingerprint."""

    def test_each_request_states_the_label_of_its_draw(self) -> None:
        """A request inside a draw takes its label, and one outside takes none."""
        case = Case(Replaying([]))
        case.draw(_Digit(), "v")
        case.choose(_digit())
        self.assertEqual(case.wheres, [Where("v"), Where()])

    def test_a_request_of_a_nested_draw_states_the_innermost_label(self) -> None:
        """The outer draw's own request takes outer, and the inner draw's inner."""
        case = Case(Replaying([]))
        case.draw(_Outer(), "outer")
        self.assertEqual(case.wheres, [Where("outer"), Where("inner")])

    def test_a_request_states_the_place_that_the_case_states(self) -> None:
        """A machine's steps set the place, and each request records it."""
        case = Case(Replaying([]))
        case.place = Place("sequential", 2, "put")
        case.draw(_Digit(), "v")
        self.assertEqual(case.wheres, [Where("v", Place("sequential", 2, "put"))])

    def test_rewind_removes_the_wheres_of_the_removed_choices(self) -> None:
        """A request after the mark leaves its where with it."""
        case = Case(Replaying([]))
        case.choose(_digit())
        mark = case.mark()
        case.draw(_Digit(), "v")
        case.rewind(mark)
        self.assertEqual(case.wheres, [Where()])

    def test_each_fingerprint_states_where_the_case_observed_it(self) -> None:
        """A fingerprint takes the place of the step that observed it."""
        case = Case(Replaying([]))
        case.observe(1)
        case.place = Place("drain", 0, "flush")
        case.observe(2)
        self.assertEqual(
            case.observed, [Where(), Where(None, Place("drain", 0, "flush"))]
        )

    def test_a_draw_that_raises_closes_its_label(self) -> None:
        """After a rejected draw, the case is outside every draw."""
        case = Case(Replaying([]))
        with self.assertRaises(Rejected):
            case.draw(_Refusing(), "v")
        self.assertEqual((case.wheres, case.where()), ([Where("v")], Where()))
