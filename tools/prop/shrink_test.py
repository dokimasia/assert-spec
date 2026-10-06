"""Shrinking: the order it uses, each pass, the replay check and the explanation."""

from __future__ import annotations

import unittest
from functools import partial
from typing import Any, final

from .case import Case, Place, Replaying, Request
from .choice import Bounds, Choice, FloatBounds, IntegerBounds, SequenceBounds
from .execution import Body, Execution, Status, execute
from .generator import build
from .replay import decode
from .runner import Kind, Settings, run
from .shrink import (
    DEFAULT_BUDGET,
    EXPLAIN_FILLINGS,
    Node,
    Shrinker,
    choice_key,
    confirm,
    explain_seed,
    find_integer,
    key,
    search,
)

#: The definition's constants, pinned rather than read from the code.
PINNED_BUDGET = 2000
PINNED_FILLINGS = 4

SEED = 7
MAX_CHOICES = 8192

#: The values the bodies of these tests fail at.
LIMIT = 1000
SUM_LIMIT = 10
PAIR_LIMIT = 500
FIFTY = 50
LOW, HIGH = 3, 5
NINE = 9
MIN_COUNT = 2
MIN_LENGTH = 3
HIGH_BYTE = 200
HALF = 2.5
SECOND = 2
THIRD = 3
THRESHOLD = 12
BOUNDARY = 7

#: The one digit that Seven decodes, and the seeds whose fillings of it
#: decode none and one value.
SEVEN_VALUE = 7
NO_FILLING_SEED = 7
ONE_FILLING_SEED = 11

#: A float32 range wider than its exact integers, and the smallest value
#: that fails in it: 2^24 + 2, the even integer after 2^24.
WIDE32 = 1 << 25
BIG32 = (1 << 24) + 2

DIGIT: dict[str, Any] = {"gen": "integer", "min": 0, "max": 9}
WIDE = build({"gen": "integer", "min": 0, "max": 10**9})
SMALL = build({"gen": "integer", "min": 0, "max": 1000})
PERCENT = build({"gen": "list", "of": {"gen": "integer", "min": 0, "max": 100}})
DIGITS = build({"gen": "list", "of": DIGIT})
UNIT = build({"gen": "float", "min": 0, "max": 10})
SIGNED = build({"gen": "integer", "min": -100, "max": 100})
SIGNED_LIST = build({"gen": "list", "of": {"gen": "integer", "min": -100, "max": 100}})
NESTED = build({"gen": "list", "of": {"gen": "list", "of": DIGIT}})
POSITIVE = build({"gen": "integer", "min": 1, "max": 1000})
SIGNED_FLOAT = build({"gen": "float", "min": -10, "max": 10})
INDEX = build(DIGIT)
BYTE_STRINGS = build({"gen": "bytes"})
PAIR_BYTES = build({"gen": "bytes", "min_size": MIN_COUNT})
JUST = build({"gen": "just", "value": {"type": "int", "value": SEVEN_VALUE}})


def node(bounds: Bounds, value: Any) -> Node:
    """Return a node with bounds and value; its draw is never called."""

    def unused(source: object) -> Any:
        raise AssertionError(f"a key drew from {source}")

    return Node(Request(bounds, unused), Choice(bounds.kind, value))


def failing(body: Body, *choices: Choice) -> Execution:
    """Return the execution of body on recorded choices; it must fail."""
    execution = execute(body, Replaying(choices), MAX_CHOICES)
    assert execution.status is Status.FAILED, execution.status
    return execution


def integers(*values: int) -> tuple[Choice, ...]:
    """Return integer choices."""
    return tuple(Choice("integer", v) for v in values)


def shrinker(body: Body, *choices: Choice, budget: int = PINNED_BUDGET) -> Shrinker:
    """Return a shrinker that starts from the failing case of choices."""
    return Shrinker(body, failing(body, *choices), MAX_CHOICES, budget)


def drawn(execution: Execution) -> list[object]:
    """Return the values an execution's case drew."""
    return [d.value for d in execution.case.draws]


@final
class Seven:
    """A digit that rejects its case unless it is 7.

    A replay of the choice 7 decodes it, and most fresh decodes reject, so
    the explain phase meets fillings that decode no value.
    """

    def __init__(self) -> None:
        """Decode from the digits."""
        self._digit = build(DIGIT)

    def decode(self, case: Case) -> object:
        """Return 7, or reject the case for any other digit."""
        value = self._digit.decode(case)
        case.assume(value == SEVEN_VALUE)
        return value


def at_most(threshold: int, k: int) -> bool:
    """Report whether k is at most threshold."""
    return k <= threshold


def contains(value: object, wanted: int) -> bool:
    """Report whether a nested list holds wanted anywhere."""
    if isinstance(value, list):
        return any(contains(item, wanted) for item in value)
    return value == wanted


def above(case: Case) -> None:
    """Fail when a wide integer is above LIMIT."""
    value = case.draw(WIDE, "n")
    assert isinstance(value, int)
    if value > LIMIT:
        case.fail("above")


def sum_above(case: Case) -> None:
    """Fail when a list of percentages sums above SUM_LIMIT."""
    values = case.draw(PERCENT, "xs")
    assert isinstance(values, list)
    if sum(values) > SUM_LIMIT:
        case.fail("sum")


def indexed_above(case: Case) -> None:
    """Fail when the percentage at an index drawn after the list is above FIFTY."""
    values = case.draw(PERCENT, "xs")
    index = case.draw(INDEX, "i")
    assert isinstance(values, list)
    assert isinstance(index, int)
    if index < len(values) and values[index] > FIFTY:
        case.fail("indexed")


def byte_at(case: Case) -> None:
    """Fail when the byte at an index drawn after the bytes is above HIGH_BYTE."""
    value = case.draw(BYTE_STRINGS, "b")
    index = case.draw(INDEX, "i")
    assert isinstance(value, bytes)
    assert isinstance(index, int)
    if index < len(value) and value[index] > HIGH_BYTE:
        case.fail("high")


def pair_byte_at(case: Case) -> None:
    """Fail as byte_at does, over bytes of at least MIN_COUNT."""
    value = case.draw(PAIR_BYTES, "b")
    index = case.draw(INDEX, "i")
    assert isinstance(value, bytes)
    assert isinstance(index, int)
    if index < len(value) and value[index] > HIGH_BYTE:
        case.fail("high")


def above_after_just(case: Case) -> None:
    """Fail when an integer drawn after a just is above FIFTY."""
    case.draw(JUST, "j")
    value = case.draw(SMALL, "n")
    assert isinstance(value, int)
    if value > FIFTY:
        case.fail("above")


@final
class OrderTest(unittest.TestCase):
    """The shortlex order, and the keys behind it."""

    def test_a_shorter_sequence_is_smaller(self) -> None:
        """Length decides before any value does."""
        digit = IntegerBounds(0, 9)
        self.assertLess(key([node(digit, 9)]), key([node(digit, 0), node(digit, 0)]))

    def test_equal_lengths_compare_at_the_first_difference(self) -> None:
        """The first choice that differs decides."""
        digit = IntegerBounds(0, 9)
        first = key([node(digit, 1), node(digit, 9)])
        self.assertLess(first, key([node(digit, 2), node(digit, 0)]))

    def test_kinds_order_integer_float_sequence(self) -> None:
        """Different kinds at one position compare by kind first."""
        integer = choice_key(node(IntegerBounds(0, 9), 9))
        number = choice_key(node(FloatBounds(0.0, 1.0), 0.0))
        sequence = choice_key(node(SequenceBounds(2), ()))
        self.assertLess(integer, number)
        self.assertLess(number, sequence)

    def test_an_integer_key_measures_distance_from_its_target(self) -> None:
        """Above the target is simpler than below at equal distance."""
        bounds = IntegerBounds(-5, 5)
        keys = [choice_key(node(bounds, v)) for v in (0, 1, -1, 2)]
        self.assertEqual(keys, sorted(keys))


@final
class SearchTest(unittest.TestCase):
    """find_integer() and search(): the probes the passes make."""

    def test_find_integer_returns_the_largest_true_k(self) -> None:
        """For thresholds small and large."""
        for threshold in (0, 1, 3, 4, 5, 17, 1000):
            self.assertEqual(find_integer(partial(at_most, threshold)), threshold)

    def test_find_integer_probes_linearly_then_doubles_then_bisects(self) -> None:
        """1, 2, 3, 4, then 5, 10, 20, then 15, 12, 13."""
        probes: list[int] = []

        def f(k: int) -> bool:
            probes.append(k)
            return k <= THRESHOLD

        find_integer(f)
        self.assertEqual(probes, [1, 2, 3, 4, 5, 10, 20, 15, 12, 13])

    def test_search_tries_zero_then_bisects_towards_it(self) -> None:
        """A boundary at 7 out of 20: 0, 10, 5, 7, 6."""
        probes: list[int] = []

        def at(distance: int) -> bool:
            probes.append(distance)
            return distance >= BOUNDARY

        self.assertTrue(search(20, at))
        self.assertEqual(probes, [0, 10, 5, 7, 6])


@final
class ConfirmTest(unittest.TestCase):
    """The replay before shrinking."""

    def test_a_replay_that_fails_the_same_way_confirms(self) -> None:
        """No divergence."""
        self.assertIsNone(confirm(above, failing(above, *integers(2000)), MAX_CHOICES))

    def test_a_replay_that_passes_is_a_verdict_divergence(self) -> None:
        """The recorded identity against None for a pass."""
        calls: list[Case] = []

        def once(case: Case) -> None:
            calls.append(case)
            case.draw(WIDE, "n")
            if len(calls) == 1:
                case.fail("once")

        divergence = confirm(once, failing(once, *integers(5)), MAX_CHOICES)
        assert divergence is not None
        got = (divergence.what, divergence.recorded, divergence.replayed)
        self.assertEqual(got, ("verdict", "once", None))

    def test_a_replay_that_requests_other_bounds_is_a_request_divergence(
        self,
    ) -> None:
        """The first position whose request differs."""
        calls: list[Case] = []

        def shifting(case: Case) -> None:
            calls.append(case)
            case.draw(WIDE if len(calls) == 1 else SMALL, "n")
            case.fail("always")

        divergence = confirm(shifting, failing(shifting, *integers(5)), MAX_CHOICES)
        assert divergence is not None
        got = (divergence.what, divergence.index, divergence.label, divergence.step)
        self.assertEqual(got, ("request", 0, "n", None))

    def test_a_request_divergence_states_the_step_of_the_replays_request(
        self,
    ) -> None:
        """The replay's request was made in a sequential step of put."""
        calls: list[Case] = []

        def stepping(case: Case) -> None:
            calls.append(case)
            case.place = Place("sequential", 1, "put")
            case.draw(WIDE if len(calls) == 1 else SMALL, "n")
            case.fail("always")

        divergence = confirm(stepping, failing(stepping, *integers(5)), MAX_CHOICES)
        assert divergence is not None
        self.assertEqual(divergence.step, Place("sequential", 1, "put"))

    def test_a_replay_that_ends_before_a_request_states_no_label(self) -> None:
        """The replay made no request at the position, so no draw was running."""
        calls: list[Case] = []

        def shortening(case: Case) -> None:
            calls.append(case)
            if len(calls) == 1:
                case.draw(WIDE, "n")
            case.fail("always")

        divergence = confirm(shortening, failing(shortening, *integers(5)), MAX_CHOICES)
        assert divergence is not None
        got = (divergence.replayed, divergence.label, divergence.step)
        self.assertEqual(got, (None, None, None))

    def test_a_replay_that_observes_another_fingerprint_diverges(self) -> None:
        """The fingerprints are compared after the requests, and name their step."""
        calls: list[Case] = []

        def observing(case: Case) -> None:
            calls.append(case)
            case.draw(WIDE, "n")
            case.place = Place("drain", 0, "flush")
            case.observe(len(calls))
            case.fail("always")

        divergence = confirm(observing, failing(observing, *integers(5)), MAX_CHOICES)
        assert divergence is not None
        got = (divergence.what, divergence.recorded, divergence.replayed)
        self.assertEqual(got, ("fingerprint", 1, 2))
        self.assertEqual(
            (divergence.label, divergence.step), (None, Place("drain", 0, "flush"))
        )

    def test_a_verdict_divergence_states_no_label_and_no_step(self) -> None:
        """A verdict differs where the case ended."""
        calls: list[Case] = []

        def once(case: Case) -> None:
            calls.append(case)
            case.place = Place("settle")
            case.draw(WIDE, "n")
            if len(calls) == 1:
                case.fail("once")

        divergence = confirm(once, failing(once, *integers(5)), MAX_CHOICES)
        assert divergence is not None
        self.assertEqual((divergence.label, divergence.step), (None, None))


@final
class PassTest(unittest.TestCase):
    """Each pass, run alone on a failing case."""

    def test_delete_span_chunk_removes_runs_of_two_or_more_siblings(self) -> None:
        """Eight elements, of which only the first matters, become two."""

        def first_above(case: Case) -> None:
            values = case.draw(PERCENT, "xs")
            assert isinstance(values, list)
            if values and values[0] > SUM_LIMIT:
                case.fail("first")

        elements = integers(1, FIFTY, *[1, LOW] * 7, 0)
        shrinking = shrinker(first_above, *elements)
        self.assertTrue(shrinking.delete_span_chunk())
        self.assertEqual(drawn(shrinking.best.execution), [[FIFTY, LOW]])

    def test_delete_span_chunk_tries_the_last_chunk_first(self) -> None:
        """[9, 1, 2, 9] summing to 10 or more keeps its first half: [9, 1]."""

        def ten(case: Case) -> None:
            values = case.draw(PERCENT, "xs")
            assert isinstance(values, list)
            if sum(values) >= SUM_LIMIT:
                case.fail("ten")

        shrinking = shrinker(ten, *integers(1, NINE, 1, 1, 1, 2, 1, NINE, 0))
        self.assertTrue(shrinking.delete_span_chunk())
        self.assertEqual(drawn(shrinking.best.execution), [[NINE, 1]])

    def test_delete_span_removes_one_element(self) -> None:
        """A list whose second element alone fails."""

        def has_fifty(case: Case) -> None:
            values = case.draw(PERCENT, "xs")
            assert isinstance(values, list)
            if FIFTY in values:
                case.fail("fifty")

        shrinking = shrinker(has_fifty, *integers(1, LOW, 1, FIFTY, 0))
        self.assertTrue(shrinking.delete_span())
        self.assertEqual(drawn(shrinking.best.execution), [[FIFTY]])

    def test_lift_descendant_replaces_a_tree_by_its_subtree(self) -> None:
        """A list holding a 9 lifts to the inner position that holds it."""
        tree = build(
            {
                "gen": "recursive",
                "base": DIGIT,
                "extend": {"gen": "list", "of": {"gen": "self"}, "max_size": 3},
            }
        )

        def nine(case: Case) -> None:
            if contains(case.draw(tree, "tree"), NINE):
                case.fail("nine")

        shrinking = shrinker(nine, *integers(1, 1, 0, NINE, 0))
        self.assertEqual(drawn(shrinking.best.execution), [[NINE]])
        self.assertTrue(shrinking.lift_descendant())
        self.assertEqual(drawn(shrinking.best.execution), [NINE])
        self.assertEqual(shrinking.runs, 1)

    def test_delete_span_run_removes_any_run_of_siblings(self) -> None:
        """Three trailing elements go in one adaptive run."""

        def first_above(case: Case) -> None:
            values = case.draw(PERCENT, "xs")
            assert isinstance(values, list)
            if values and values[0] > SUM_LIMIT:
                case.fail("first")

        shrinking = shrinker(first_above, *integers(1, FIFTY, *[1, LOW] * 3, 0))
        self.assertTrue(shrinking.delete_span_run())
        self.assertEqual(drawn(shrinking.best.execution), [[FIFTY]])

    def test_minimize_choice_finds_the_boundary_by_bisection(self) -> None:
        """2000 shrinks to 1001."""
        shrinking = shrinker(above, *integers(2000))
        self.assertTrue(shrinking.minimize_choice())
        self.assertEqual(drawn(shrinking.best.execution), [LIMIT + 1])

    def test_minimize_choice_moves_a_value_below_the_target_above_it(self) -> None:
        """[0, -1] is not its reverse, and [0, 1] is the simpler such list."""

        def unreversed(case: Case) -> None:
            values = case.draw(SIGNED_LIST, "xs")
            assert isinstance(values, list)
            if values != values[::-1]:
                case.fail("reverse")

        shrinking = shrinker(unreversed, *integers(1, 0, 1, -1, 0))
        self.assertTrue(shrinking.minimize_choice())
        self.assertEqual(drawn(shrinking.best.execution), [[0, 1]])

    def test_minimize_choice_crosses_the_target_to_a_nearer_value(self) -> None:
        """3 fails, 2 passes, and -2 is nearer than 3: the search finds -2."""

        def far(case: Case) -> None:
            value = case.draw(SIGNED, "x")
            assert isinstance(value, int)
            if abs(value) >= MIN_COUNT and value != MIN_COUNT:
                case.fail("far")

        shrinking = shrinker(far, *integers(LOW))
        self.assertTrue(shrinking.minimize_choice())
        self.assertEqual(drawn(shrinking.best.execution), [-MIN_COUNT])

    def test_delete_structure_pair_joins_two_lists(self) -> None:
        """[[1], [2]] becomes [[1, 2]]: a stop flag and a continue flag go."""

        def mixed(case: Case) -> None:
            lists = case.draw(NESTED, "xss")
            assert isinstance(lists, list)
            if len({x for inner in lists for x in inner}) >= MIN_COUNT:
                case.fail("mixed")

        shrinking = shrinker(mixed, *integers(1, 1, 1, 0, 1, 1, MIN_COUNT, 0, 0))
        self.assertTrue(shrinking.delete_structure_pair())
        self.assertEqual(drawn(shrinking.best.execution), [[[1, MIN_COUNT]]])

    def test_delete_structure_pair_leaves_a_forced_flag(self) -> None:
        """A list of exactly two digits has only forced flags, so nothing goes."""
        pair = build({"gen": "list", "of": DIGIT, "min_size": 2, "max_size": 2})

        def nine(case: Case) -> None:
            values = case.draw(pair, "xs")
            assert isinstance(values, list)
            if NINE in values:
                case.fail("nine")

        shrinking = shrinker(nine, *integers(1, NINE, 1, NINE, 0))
        self.assertFalse(shrinking.delete_structure_pair())

    def test_delete_structure_pair_tries_no_forced_pair(self) -> None:
        """Lists of one digit in a list of two have only forced flags: no run."""
        one = {"gen": "list", "of": DIGIT, "min_size": 1, "max_size": 1}
        nested = build({"gen": "list", "of": one, "min_size": 2, "max_size": 2})

        def nine(case: Case) -> None:
            lists = case.draw(nested, "xss")
            assert isinstance(lists, list)
            if any(NINE in inner for inner in lists):
                case.fail("nine")

        shrinking = shrinker(nine, *integers(1, 1, NINE, 0, 1, 1, NINE, 0, 0))
        self.assertFalse(shrinking.delete_structure_pair())
        self.assertEqual(shrinking.runs, 0)

    def test_lower_together_keeps_the_difference(self) -> None:
        """(36, 37) has difference 1, and lowering both by 26 keeps it: (10, 11)."""

        def one_apart(case: Case) -> None:
            x, y = case.draw(POSITIVE, "x"), case.draw(POSITIVE, "y")
            assert isinstance(x, int)
            assert isinstance(y, int)
            if x >= THRESHOLD - MIN_COUNT and abs(x - y) == 1:
                case.fail("one")

        shrinking = shrinker(one_apart, *integers(36, 37))
        self.assertTrue(shrinking.lower_together())
        self.assertEqual(drawn(shrinking.best.execution), [10, 11])
        self.assertEqual(shrinking.runs, 11)

    def test_lower_together_leaves_values_on_both_sides_of_the_target(self) -> None:
        """-3 and 4 cannot move by one amount towards the target 0."""

        def spread(case: Case) -> None:
            x, y = case.draw(SIGNED, "x"), case.draw(SIGNED, "y")
            assert isinstance(x, int)
            assert isinstance(y, int)
            if y - x >= BOUNDARY:
                case.fail("spread")

        shrinking = shrinker(spread, *integers(-LOW, 4))
        self.assertFalse(shrinking.lower_together())

    def test_minimize_choice_moves_a_float_to_its_target(self) -> None:
        """An unrelated float goes to 0.0."""

        def unrelated(case: Case) -> None:
            case.draw(UNIT, "v")
            value = case.draw(WIDE, "n")
            assert isinstance(value, int)
            if value > LIMIT:
                case.fail("above")

        shrinking = shrinker(unrelated, Choice("float", 3.75), Choice("integer", 2000))
        self.assertTrue(shrinking.minimize_choice())
        self.assertEqual(drawn(shrinking.best.execution), [0.0, LIMIT + 1])

    def test_sequence_delete_and_lower_shrink_a_byte_string(self) -> None:
        """Bytes holding a byte above 200 shrink to that byte, then to 201."""
        byte_strings = build({"gen": "bytes"})

        def high(case: Case) -> None:
            value = case.draw(byte_strings, "b")
            assert isinstance(value, bytes)
            if any(b > HIGH_BYTE for b in value):
                case.fail("high")

        shrinking = shrinker(high, Choice("sequence", (1, 250, LOW, 4)))
        self.assertTrue(shrinking.sequence_delete())
        self.assertEqual(drawn(shrinking.best.execution), [bytes([250])])
        self.assertTrue(shrinking.sequence_lower())
        self.assertEqual(drawn(shrinking.best.execution), [bytes([HIGH_BYTE + 1])])

    def test_sequence_delete_goes_down_to_min_size(self) -> None:
        """A byte string of at least one byte shrinks to exactly one."""
        byte_strings = build({"gen": "bytes", "min_size": 1})

        def high(case: Case) -> None:
            value = case.draw(byte_strings, "b")
            assert isinstance(value, bytes)
            if any(b > HIGH_BYTE for b in value):
                case.fail("high")

        shrinking = shrinker(high, Choice("sequence", (1, 250)))
        self.assertTrue(shrinking.sequence_delete())
        self.assertEqual(drawn(shrinking.best.execution), [bytes([250])])

    def test_target_span_sets_a_whole_draw_to_its_targets(self) -> None:
        """An unrelated draw goes to its target in one candidate."""

        def first_above(case: Case) -> None:
            value = case.draw(WIDE, "n")
            case.draw(WIDE, "noise")
            assert isinstance(value, int)
            if value > LIMIT:
                case.fail("above")

        shrinking = shrinker(first_above, *integers(2000, 12345))
        self.assertTrue(shrinking.target_span())
        self.assertEqual(drawn(shrinking.best.execution), [2000, 0])

    def test_lower_and_delete_shrinks_a_count_with_its_items(self) -> None:
        """A count of 3 whose last item is 9 becomes a count of 2 and [0, 9]."""
        digit = build(DIGIT)

        def last_nine(case: Case) -> None:
            count = case.draw(digit, "count")
            assert isinstance(count, int)
            items = [case.draw(digit, "item") for _ in range(count)]
            if count >= MIN_COUNT and items[-1] == NINE:
                case.fail("nine")

        shrinking = shrinker(last_nine, *integers(LOW, 0, 0, NINE))
        self.assertTrue(shrinking.lower_and_delete())
        self.assertEqual(drawn(shrinking.best.execution), [MIN_COUNT, 0, NINE])

    def test_lower_and_delete_deletes_nothing_after_a_step_that_sizes_nothing(
        self,
    ) -> None:
        """A first draw of 9 fails whatever the second is, so only two steps run."""
        digit = build(DIGIT)

        def first_nine(case: Case) -> None:
            x = case.draw(digit, "x")
            case.draw(digit, "y")
            if x == NINE:
                case.fail("nine")

        shrinking = shrinker(first_nine, *integers(NINE, HIGH))
        self.assertTrue(shrinking.lower_and_delete())
        self.assertEqual(drawn(shrinking.best.execution), [NINE, HIGH - 1])
        self.assertEqual(shrinking.runs, 2)

    def test_lower_and_delete_removes_an_element_inside_the_sized_list(self) -> None:
        """A count of 3 sizing [0, 0, 9] becomes a count of 1 and [9]."""
        digit = build(DIGIT)

        def has_nine(case: Case) -> None:
            count = case.draw(digit, "count")
            assert isinstance(count, int)
            sizes = {"min_size": count, "max_size": count}
            exact = build({"gen": "list", "of": DIGIT, **sizes})
            values = case.draw(exact, "xs")
            assert isinstance(values, list)
            if NINE in values:
                case.fail("nine")

        flags_and_values = (1, 0, 1, 0, 1, NINE, 0)
        shrinking = shrinker(has_nine, *integers(LOW, *flags_and_values))
        self.assertTrue(shrinking.lower_and_delete())
        self.assertEqual(drawn(shrinking.best.execution), [1, [NINE]])
        self.assertEqual(shrinking.runs, 16)

    def test_delete_and_lower_removes_a_list_element_before_its_index(self) -> None:
        """[0, 60] at index 1 becomes [60] at index 0 in one candidate.

        The index's step is tried with the spans that end at or before it,
        the list's own span included, and the ninth run deletes the first
        element.
        """
        shrinking = shrinker(indexed_above, *integers(1, 0, 1, 60, 0, 1))
        self.assertTrue(shrinking.delete_and_lower())
        self.assertEqual(drawn(shrinking.best.execution), [[60], 0])
        self.assertEqual(shrinking.runs, 9)

    def test_delete_and_lower_removes_a_sequence_element_before_its_index(
        self,
    ) -> None:
        """Bytes [1, 250] at index 1 become [250] at index 0 in one candidate.

        The bytes' span goes first, then the last element, then the first.
        """
        shrinking = shrinker(
            byte_at, Choice("sequence", (1, 250)), Choice("integer", 1)
        )
        self.assertTrue(shrinking.delete_and_lower())
        self.assertEqual(drawn(shrinking.best.execution), [bytes([250]), 0])
        self.assertEqual(shrinking.runs, 3)

    def test_delete_and_lower_keeps_a_sequence_at_its_min_size(self) -> None:
        """Bytes of at least 2 keep both elements: the one candidate deletes them."""
        shrinking = shrinker(
            pair_byte_at, Choice("sequence", (1, 250)), Choice("integer", 1)
        )
        self.assertFalse(shrinking.delete_and_lower())
        self.assertEqual(shrinking.runs, 1)

    def test_delete_and_lower_deletes_no_empty_span(self) -> None:
        """The pass skips the empty span of a just, so the step alone never runs."""
        shrinking = shrinker(above_after_just, *integers(60))
        self.assertFalse(shrinking.delete_and_lower())
        self.assertEqual(shrinking.runs, 0)

    def test_delete_and_lower_runs_nothing_without_earlier_data(self) -> None:
        """[60] at index 0: no integer that can step has data before it."""
        shrinking = shrinker(indexed_above, *integers(1, 60, 0, 0))
        self.assertFalse(shrinking.delete_and_lower())
        self.assertEqual(shrinking.runs, 0)

    def test_shrink_lowers_an_index_into_an_earlier_list(self) -> None:
        """[0, 60] at index 1 shrinks to [51] at index 0."""
        shrinking = shrinker(indexed_above, *integers(1, 0, 1, 60, 0, 1))
        shrinking.shrink_all()
        self.assertEqual(drawn(shrinking.best.execution), [[FIFTY + 1], 0])

    def test_sort_siblings_puts_the_smaller_element_first(self) -> None:
        """[5, 3] becomes [3, 5] for a property about the multiset."""

        def has_both(case: Case) -> None:
            values = case.draw(PERCENT, "xs")
            assert isinstance(values, list)
            if LOW in values and HIGH in values:
                case.fail("both")

        shrinking = shrinker(has_both, *integers(1, HIGH, 1, LOW, 0))
        self.assertTrue(shrinking.sort_siblings())
        self.assertEqual(drawn(shrinking.best.execution), [[LOW, HIGH]])

    def test_redistribute_moves_value_to_the_next_integer(self) -> None:
        """For a sum above 500, x gives all it has to y."""

        def sum_pair(case: Case) -> None:
            x, y = case.draw(SMALL, "x"), case.draw(SMALL, "y")
            assert isinstance(x, int)
            assert isinstance(y, int)
            if x + y > PAIR_LIMIT:
                case.fail("sum")

        shrinking = shrinker(sum_pair, *integers(300, 300))
        self.assertTrue(shrinking.redistribute())
        self.assertEqual(drawn(shrinking.best.execution), [0, 600])

    def test_minimize_duplicates_lowers_equal_values_together(self) -> None:
        """Two equal draws that must stay equal shrink together."""

        def equal(case: Case) -> None:
            x, y = case.draw(SMALL, "x"), case.draw(SMALL, "y")
            assert isinstance(x, int)
            if x == y and x > 0:
                case.fail("equal")

        shrinking = shrinker(equal, *integers(400, 400))
        self.assertTrue(shrinking.minimize_duplicates())
        self.assertEqual(drawn(shrinking.best.execution), [1, 1])

    def test_minimize_duplicates_leaves_a_value_that_occurs_once(self) -> None:
        """A third, unrelated draw of 7 stays for the other passes."""

        def equal(case: Case) -> None:
            x, y = case.draw(SMALL, "x"), case.draw(SMALL, "y")
            case.draw(SMALL, "z")
            assert isinstance(x, int)
            if x == y and x > 0:
                case.fail("equal")

        shrinking = shrinker(equal, *integers(400, 400, BOUNDARY))
        self.assertTrue(shrinking.minimize_duplicates())
        self.assertEqual(drawn(shrinking.best.execution), [1, 1, BOUNDARY])

    def test_float_simplify_rounds_a_fraction_to_fewer_bits(self) -> None:
        """2.875 must stay a fraction above 2.5, so it keeps two bits: 2.75."""

        def fractional(case: Case) -> None:
            value = case.draw(UNIT, "v")
            assert isinstance(value, float)
            if value > HALF and not value.is_integer():
                case.fail("fraction")

        shrinking = shrinker(fractional, Choice("float", 2.875))
        self.assertTrue(shrinking.float_simplify())
        self.assertEqual(drawn(shrinking.best.execution), [2.75])

    def test_float_simplify_rounds_away_from_the_target_to_an_integer(self) -> None:
        """2.875 above 2.5 rounds up to 3.0, which 2.0 cannot replace."""

        def bigger(case: Case) -> None:
            value = case.draw(UNIT, "v")
            assert isinstance(value, float)
            if value > HALF:
                case.fail("bigger")

        shrinking = shrinker(bigger, Choice("float", 2.875))
        self.assertTrue(shrinking.float_simplify())
        self.assertEqual(drawn(shrinking.best.execution), [3.0])

    def test_float_simplify_moves_a_negative_integral_float_above_zero(self) -> None:
        """-9.0 fails at magnitude 3 or more, and 3.0 is simpler than -3.0."""

        def large(case: Case) -> None:
            value = case.draw(SIGNED_FLOAT, "v")
            assert isinstance(value, float)
            if abs(value) >= THIRD:
                case.fail("large")

        shrinking = shrinker(large, Choice("float", -9.0))
        self.assertTrue(shrinking.float_simplify())
        self.assertEqual(drawn(shrinking.best.execution), [3.0])

    def test_float_simplify_skips_integers_a_float32_cannot_state(self) -> None:
        """2^25 shrinks to 2^24 + 2 without running an odd integer above 2^24."""
        wide32 = build({"gen": "float", "min": 0, "max": WIDE32, "width": 32})

        def big(case: Case) -> None:
            value = case.draw(wide32, "v")
            assert isinstance(value, float)
            if value >= BIG32:
                case.fail("big")

        shrinking = shrinker(big, Choice("float", float(WIDE32)))
        self.assertTrue(shrinking.float_simplify())
        self.assertEqual(drawn(shrinking.best.execution), [float(BIG32)])
        self.assertEqual(shrinking.runs, 25)

    def test_float_simplify_lowers_an_integral_float_as_an_integer(self) -> None:
        """9.0 above 2.5 becomes 3.0."""

        def bigger(case: Case) -> None:
            value = case.draw(UNIT, "v")
            assert isinstance(value, float)
            if value > HALF:
                case.fail("bigger")

        shrinking = shrinker(bigger, Choice("float", 9.0))
        self.assertTrue(shrinking.float_simplify())
        self.assertEqual(drawn(shrinking.best.execution), [3.0])


@final
class BudgetTest(unittest.TestCase):
    """The shared budget of runs."""

    def test_the_default_budget_is_2000_runs(self) -> None:
        """The fixed default."""
        self.assertEqual(DEFAULT_BUDGET, PINNED_BUDGET)

    def test_a_spent_budget_stops_with_the_smallest_case_found(self) -> None:
        """Ten runs leave 2000 partly shrunk, and never spend an eleventh."""
        shrinking = shrinker(above, *integers(2000), budget=10)
        shrinking.shrink_all()
        self.assertEqual(shrinking.runs, 10)
        value = drawn(shrinking.best.execution)[0]
        assert isinstance(value, int)
        self.assertGreater(value, LIMIT + 1)

    def test_a_candidate_tried_before_costs_nothing(self) -> None:
        """A passing candidate considered twice runs the body once."""
        shrinking = shrinker(above, *integers(2000))
        request = shrinking.nodes[0].request
        self.assertFalse(shrinking.consider((Node(request, Choice("integer", 500)),)))
        self.assertFalse(shrinking.consider((Node(request, Choice("integer", 500)),)))
        self.assertEqual(shrinking.runs, 1)

    def test_a_candidate_no_smaller_than_the_best_is_not_run(self) -> None:
        """A larger value costs nothing."""
        shrinking = shrinker(above, *integers(2000))
        larger = (Node(shrinking.nodes[0].request, Choice("integer", 3000)),)
        self.assertFalse(shrinking.consider(larger))
        self.assertEqual(shrinking.runs, 0)


@final
class RunTest(unittest.TestCase):
    """Shrinking and explaining inside a run."""

    def test_classic_failures_shrink_to_their_minimum(self) -> None:
        """A sum above 10 is [11]; a length of 3 is [0, 0, 0]; unsorted is [1, 0]."""

        def length(case: Case) -> None:
            values = case.draw(DIGITS, "xs")
            assert isinstance(values, list)
            if len(values) >= MIN_LENGTH:
                case.fail("length")

        def unsorted(case: Case) -> None:
            values = case.draw(DIGITS, "xs")
            assert isinstance(values, list)
            if values != sorted(values):
                case.fail("unsorted")

        cases: list[tuple[Body, list[object]]] = [
            (sum_above, [[SUM_LIMIT + 1]]),
            (length, [[0, 0, 0]]),
            (unsorted, [[1, 0]]),
        ]
        for body, want in cases:
            outcome = run(body, Settings(SEED))
            assert outcome.failing is not None
            self.assertEqual(drawn(outcome.failing), want)

    def test_a_second_identity_is_shrunk_and_reported_under_others(self) -> None:
        """Odd values and large even values fail differently."""

        def two(case: Case) -> None:
            value = case.draw(SMALL, "x")
            assert isinstance(value, int)
            if value % 2:
                case.fail("odd")
            if value > FIFTY:
                case.fail("big")

        outcome = run(two, Settings(SEED))
        assert outcome.failing is not None and outcome.failing.failure is not None
        found = {outcome.failing.failure.identity: drawn(outcome.failing)}
        for other in outcome.others:
            assert other.failure is not None
            found[other.failure.identity] = drawn(other)
        self.assertEqual(found, {"big": [FIFTY + 2], "odd": [1]})

    def test_the_explanation_marks_irrelevant_draws_and_boundaries(self) -> None:
        """The noise draw fails for any value; n's nearest passing value is 1000."""

        def noisy(case: Case) -> None:
            value = case.draw(WIDE, "n")
            case.draw(WIDE, "noise")
            assert isinstance(value, int)
            if value > LIMIT:
                case.fail("above")

        outcome = run(noisy, Settings(SEED))
        explained = {
            e.label: (e.any_value_fails, e.nearest_passing) for e in outcome.explanation
        }
        self.assertEqual(explained, {"n": (False, LIMIT), "noise": (True, None)})

    def test_no_nearest_value_is_reported_when_the_step_fails(self) -> None:
        """1001 is minimal for above, and 1000 fails too, another way."""

        def two(case: Case) -> None:
            value = case.draw(WIDE, "n")
            assert isinstance(value, int)
            if value > LIMIT:
                case.fail("above")
            if value == LIMIT:
                case.fail("limit")

        outcome = run(two, Settings(SEED))
        assert outcome.failing is not None and outcome.failing.failure is not None
        self.assertEqual(outcome.failing.failure.identity, "above")
        explained = outcome.explanation[0]
        self.assertEqual(
            (explained.any_value_fails, explained.nearest_passing), (False, None)
        )

    def test_a_map_of_an_integer_reports_the_map_of_the_nearest_integer(self) -> None:
        """The integer steps from 1001 to 1000, and the map wraps it as a1000b."""
        wrapped = build(
            {
                "gen": "map",
                "of": {"gen": "integer", "min": 0, "max": 10**9},
                "subject": "wraps-in-a-and-b",
            }
        )

        def above_wrapped(case: Case) -> None:
            text = case.draw(wrapped, "n")
            assert isinstance(text, str)
            if int(text[1:-1]) > LIMIT:
                case.fail("above")

        outcome = run(above_wrapped, Settings(SEED))
        assert outcome.failing is not None
        nearest = outcome.explanation[0].nearest_passing
        self.assertEqual((drawn(outcome.failing), nearest), (["a1001b"], "a1000b"))

    def test_a_failure_that_does_not_replay_is_flaky(self) -> None:
        """A body that fails only on its second call, random case 0."""
        calls: list[Case] = []

        def second(case: Case) -> None:
            calls.append(case)
            case.draw(WIDE, "n")
            if len(calls) == SECOND:
                case.fail("second")

        outcome = run(second, Settings(SEED))
        self.assertIs(outcome.kind, Kind.FLAKY)
        assert outcome.divergence is not None
        self.assertEqual(outcome.divergence.what, "verdict")

    def test_a_budget_of_zero_reports_the_first_failing_case(self) -> None:
        """No replay, no shrink, no explanation."""
        outcome = run(above, Settings(SEED, shrink=0))
        assert outcome.failing is not None
        self.assertEqual(outcome.explanation, ())
        value = drawn(outcome.failing)[0]
        assert isinstance(value, int)
        self.assertGreater(value, LIMIT + 1)

    def test_a_filling_that_decodes_no_value_is_skipped_without_a_run(
        self,
    ) -> None:
        """A draw none of whose four fillings decodes is untested, at no cost."""
        seven = Seven()

        def always(case: Case) -> None:
            case.draw(seven, "seven")
            case.fail("always")

        skipped = run(always, Settings(NO_FILLING_SEED))
        explained = skipped.explanation[0]
        self.assertEqual((explained.value, explained.any_value_fails), (7, None))
        once = run(always, Settings(ONE_FILLING_SEED))
        self.assertIs(once.explanation[0].any_value_fails, True)
        self.assertEqual(once.runs, skipped.runs + 1)

    def test_a_unique_list_whose_filling_rejects_is_explained(self) -> None:
        """Three distinct values in [0, 2]: a filling may discard its way out."""
        triple = build(
            {
                "gen": "list",
                "of": {"gen": "integer", "min": 0, "max": 2},
                "unique": True,
                "min_size": 3,
                "max_size": 3,
            }
        )

        def always(case: Case) -> None:
            case.draw(triple, "xs")
            case.fail("always")

        outcome = run(always, Settings(0))
        assert outcome.failing is not None
        self.assertEqual(drawn(outcome.failing), [[0, 1, 2]])
        self.assertIs(outcome.explanation[0].any_value_fails, True)

    def test_the_token_replays_the_counterexample(self) -> None:
        """The outcome's token encodes the minimal case."""
        outcome = run(above, Settings(SEED))
        assert outcome.token is not None
        replayed = execute(above, Replaying(decode(outcome.token)), MAX_CHOICES)
        self.assertEqual(drawn(replayed), [LIMIT + 1])


@final
class ExplainSeedTest(unittest.TestCase):
    """The seeds and the number of the explain phase's fillings."""

    def test_each_filling_has_its_own_seed(self) -> None:
        """The seed plus (draw + 1) * 2^32 plus the filling, modulo 2^64."""
        self.assertEqual(explain_seed(SEED, 0, 0), SEED + (1 << 32))
        self.assertEqual(explain_seed(SEED, 2, 3), SEED + (3 << 32) + 3)
        self.assertEqual(explain_seed((1 << 64) - 1, 0, 1), 1 << 32)

    def test_there_are_four_fillings(self) -> None:
        """The fixed number."""
        self.assertEqual(EXPLAIN_FILLINGS, PINNED_FILLINGS)
