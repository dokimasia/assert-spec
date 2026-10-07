"""Property forms: the rule they read, each assertion's judge, and a run of a form."""

from __future__ import annotations

import unittest
from typing import Any, final

from . import generator
from .forms import (
    REPETITIONS,
    Detail,
    FormError,
    Observed,
    build,
    examples,
    rule,
    run_form,
)
from .inverse import invert
from .runner import Kind, Settings, Values
from .shape import read

#: The shape the runs of these tests generate from.
SMALL: dict[str, Any] = {
    "shape": "int",
    "width": 32,
    "signed": True,
    "min": -9,
    "max": 9,
}

#: A digit through identity, an input without an inverse.
MAPPED: dict[str, Any] = {
    "gen": "map",
    "of": {"gen": "integer", "min": 0, "max": 9},
    "subject": "identity",
}

#: A form over one input, which the examples tests extend.
TRUE: dict[str, Any] = {"form": "prop-true", "subjects": ["is-non-negative"]}


def _int(value: int) -> dict[str, Any]:
    """Return an int's typed literal."""
    return {"type": "int", "value": value}


def _float(value: float) -> dict[str, Any]:
    """Return a float's typed literal."""
    return {"type": "float", "value": value}


def _string(value: str) -> dict[str, Any]:
    """Return a string's typed literal."""
    return {"type": "string", "value": value}


def judged(
    form: str, subjects: list[str], *drawn: object, args: list[Any] | None = None
) -> Detail | None:
    """Build a form with fresh subjects, and judge one case of the drawn arguments."""
    spec = {"form": form, "subjects": subjects, "args": args or []}
    return build(spec).judge(list(drawn))


@final
class RuleTest(unittest.TestCase):
    """What the definition states about each form."""

    def test_a_form_runs_its_assertion_on_the_arguments_it_generates(self) -> None:
        """A form over a function generates input, and associative a, b and c."""
        self.assertEqual(rule()["prop-equal"], ("equal", ("input",)))
        self.assertEqual(rule()["prop-associative"], ("associative", ("a", "b", "c")))

    def test_every_form_but_the_allocation_ceilings_has_a_judge(self) -> None:
        """Every other form reads its subjects, and two forms have no judge.

        The forms of max-allocs and max-allocs-with-setup have none, because
        no case can state an allocation count.
        """
        for form, (assertion, _) in rule().items():
            with self.subTest(form=form), self.assertRaises(FormError) as raised:
                build({"form": form, "subjects": None})
            if assertion in {"max-allocs", "max-allocs-with-setup"}:
                self.assertIn(
                    f"no case can state the form of {assertion!r}",
                    str(raised.exception),
                )
            else:
                self.assertIn("subjects, not None", str(raised.exception))


@final
class BuildTest(unittest.TestCase):
    """What a vector must state for its form to build."""

    def test_a_form_the_definition_does_not_state_fails(self) -> None:
        """prop-invented is no form."""
        with self.assertRaisesRegex(FormError, "'prop-invented' is no form"):
            build({"form": "prop-invented", "subjects": []})

    def test_misstated_subjects_or_values_fail(self) -> None:
        """Too few subjects, a kind of another table, values a form does not take."""
        faults: list[tuple[dict[str, Any], str]] = [
            ({"form": "prop-equal", "subjects": ["identity"]}, "takes 2 subjects"),
            ({"form": "prop-equal", "subjects": "identity"}, "takes 2 subjects"),
            ({"form": "prop-nil", "subjects": ["adds"]}, "'adds' is none of"),
            ({"form": "prop-nil", "subjects": [{"kind": "identity"}]}, "is none of"),
            (
                {"form": "prop-nil", "subjects": ["identity"], "args": [_int(1)]},
                "states 1 values, and the form takes 0",
            ),
            ({"form": "prop-length", "subjects": ["identity"]}, "states 0 values"),
            (
                {"form": "prop-nil", "subjects": ["identity"], "args": _int(1)},
                "not a list of typed literals",
            ),
        ]
        for spec, message in faults:
            with self.subTest(spec=spec), self.assertRaisesRegex(FormError, message):
                build(spec)


@final
class ValueTest(unittest.TestCase):
    """The assertions over values, each on functions of the input."""

    def test_equal_compares_the_two_results(self) -> None:
        """A sort of an unsorted list differs from the list."""
        self.assertIsNone(judged("prop-equal", ["identity", "identity"], [1, 0]))
        self.assertEqual(
            judged("prop-equal", ["sorts", "identity"], [1, 0]),
            {"want": [1, 0], "got": [0, 1]},
        )

    def test_equal_tells_an_int_from_a_bool(self) -> None:
        """Equal means equal under canonical(), which keeps the types apart."""
        self.assertEqual(
            judged("prop-equal", ["is-non-negative", "identity"], 1),
            {"want": 1, "got": True},
        )

    def test_not_equal_states_the_equal_result(self) -> None:
        """A list with a zero before it differs from the list."""
        self.assertEqual(
            judged("prop-not-equal", ["identity", "identity"], 5), {"got": 5}
        )
        self.assertIsNone(judged("prop-not-equal", ["prepends-zero", "identity"], []))

    def test_true_and_false_hold_at_zero(self) -> None:
        """0 is non-negative, and -1 is not."""
        self.assertIsNone(judged("prop-true", ["is-non-negative"], 0))
        self.assertEqual(judged("prop-true", ["is-non-negative"], -1), {})
        self.assertIsNone(judged("prop-false", ["is-non-negative"], -1))
        self.assertEqual(judged("prop-false", ["is-non-negative"], 0), {})

    def test_nil_and_not_nil_count_zero_as_present(self) -> None:
        """0 is a value, and only null is absent."""
        self.assertIsNone(judged("prop-nil", ["returns-null"], 0))
        self.assertEqual(judged("prop-nil", ["identity"], 0), {"got": 0})
        self.assertIsNone(judged("prop-not-nil", ["identity"], 0))
        self.assertEqual(judged("prop-not-nil", ["returns-null"], 0), {})

    def test_length_counts_the_items(self) -> None:
        """Three items of three wanted, and one or four."""
        three = [_int(3)]
        self.assertIsNone(judged("prop-length", ["identity"], [1, 2, 3], args=three))
        self.assertEqual(
            judged("prop-length", ["identity"], [1], args=three), {"want": 3, "got": 1}
        )
        self.assertEqual(
            judged("prop-length", ["identity"], [1, 2, 3, 4], args=three),
            {"want": 3, "got": 4},
        )

    def test_empty_and_not_empty_state_the_value_and_count_its_items(self) -> None:
        """Dropping the first of one item leaves none, and of two leaves one."""
        self.assertIsNone(judged("prop-empty", ["drops-the-first"], [5]))
        self.assertEqual(
            judged("prop-empty", ["drops-the-first"], [5, 6]),
            {"got": [6], "length": 1},
        )
        self.assertIsNone(judged("prop-not-empty", ["prepends-zero"], []))
        self.assertEqual(judged("prop-not-empty", ["identity"], []), {"got": []})

    def test_contains_finds_an_element_or_a_substring(self) -> None:
        """A list contains an equal element, and text a substring."""
        zero = [_int(0)]
        self.assertIsNone(judged("prop-contains", ["prepends-zero"], [], args=zero))
        self.assertEqual(
            judged("prop-contains", ["identity"], [1], args=zero),
            {"haystack": [1], "needle": 0},
        )
        self.assertIsNone(
            judged("prop-contains", ["identity"], "xaby", args=[_string("ab")])
        )
        self.assertEqual(
            judged("prop-contains", ["identity"], "x1", args=[_int(1)]),
            {"haystack": "x1", "needle": 1},
        )

    def test_contains_tells_an_int_from_a_bool(self) -> None:
        """The value true is no element equal to 1."""
        self.assertEqual(
            judged("prop-contains", ["identity"], [True], args=[_int(1)]),
            {"haystack": [True], "needle": 1},
        )

    def test_not_contains_states_the_haystack_that_contains_the_needle(self) -> None:
        """A list with a zero before it contains zero."""
        zero = [_int(0)]
        self.assertIsNone(judged("prop-not-contains", ["identity"], [1], args=zero))
        self.assertEqual(
            judged("prop-not-contains", ["prepends-zero"], [], args=zero),
            {"haystack": [0], "needle": 0},
        )

    def test_contains_in_order_searches_after_the_previous_match(self) -> None:
        """The match of aa ends where ab would start, so ab is not after it."""
        needles = [{"type": "list", "of": "string", "value": ["aa", "ab"]}]
        self.assertIsNone(
            judged("prop-contains-in-order", ["identity"], "aaxab", args=needles)
        )
        self.assertEqual(
            judged("prop-contains-in-order", ["identity"], "aab", args=needles),
            {"haystack": "aab", "needle": "ab", "index": 1},
        )

    def test_permutation_counts_each_element(self) -> None:
        """A sort is a permutation, and one 1 of two 1s is not."""
        self.assertIsNone(judged("prop-permutation", ["sorts", "identity"], [2, 1, 2]))
        self.assertEqual(
            judged("prop-permutation", ["drops-the-first", "identity"], [1, 1]),
            {"want": [1, 1], "got": [1]},
        )

    def test_the_text_assertions_state_the_text_and_their_value(self) -> None:
        """Text wrapped in a and b meets each, and ba misses each.

        matches also states the reason of a refused pattern, which is null
        for a pattern inside the portable subset.
        """
        cases: list[tuple[str, str, dict[str, object]]] = [
            ("prop-has-prefix", "a", {"prefix": "a"}),
            ("prop-has-suffix", "b", {"suffix": "b"}),
            ("prop-matches", "^a", {"pattern": "^a", "reason": None}),
        ]
        for form, value, fields in cases:
            with self.subTest(form=form):
                args = [_string(value)]
                self.assertIsNone(judged(form, ["wraps-in-a-and-b"], "x", args=args))
                self.assertEqual(
                    judged(form, ["identity"], "ba", args=args),
                    {"got": "ba", **fields},
                )

    def test_matches_finds_a_pattern_anywhere_in_the_text(self) -> None:
        """An unanchored a matches the a at the end of ba."""
        self.assertIsNone(
            judged("prop-matches", ["identity"], "ba", args=[_string("a")])
        )

    def test_matches_refuses_a_pattern_other_engines_read_otherwise(self) -> None:
        """$ and . mean other things in Python's re than in the portable subset."""
        for pattern in ("a$", "a.b"):
            with (
                self.subTest(pattern=pattern),
                self.assertRaisesRegex(FormError, "matches no pattern such as"),
            ):
                judged("prop-matches", ["identity"], "ab", args=[_string(pattern)])

    def test_close_to_includes_the_tolerance(self) -> None:
        """A difference equal to the tolerance passes, and one above fails."""
        args = [_float(0), _float(1)]
        self.assertIsNone(judged("prop-close-to", ["identity"], -1, args=args))
        self.assertEqual(
            judged("prop-close-to", ["identity"], 2, args=args),
            {"got": 2, "want": 0.0, "tolerance": 1.0},
        )

    def test_in_range_includes_both_bounds(self) -> None:
        """0 and 1 are in the interval from 0 to 1, and -1 and 2 are not."""
        args = [_float(0), _float(1)]
        for inside in (0, 1):
            self.assertIsNone(judged("prop-in-range", ["identity"], inside, args=args))
        for outside in (-1, 2):
            self.assertEqual(
                judged("prop-in-range", ["identity"], outside, args=args),
                {"got": outside, "low": 0.0, "high": 1.0},
            )

    def test_pairwise_states_the_first_pair_out_of_order(self) -> None:
        """Equal neighbours are ascending, and 1 before 0 is not."""
        self.assertIsNone(judged("prop-pairwise", ["sorts", "ascending"], [3, 1, 2]))
        self.assertEqual(
            judged("prop-pairwise", ["identity", "ascending"], [1, 1, 0]),
            {"index": 1, "first": 1, "second": 0},
        )


@final
class CallableTest(unittest.TestCase):
    """The assertions over a callable, which takes the input."""

    def test_the_error_assertions_decide_by_the_subjects_own_failure(self) -> None:
        """A failure at -1 and none at 0, each for every error assertion."""
        cases: list[tuple[str, Detail | None, Detail | None]] = [
            ("prop-err-absent", {}, None),
            ("prop-err-present", None, {}),
            ("prop-err-is", None, {"got": None}),
            ("prop-err-is-not", {}, None),
            ("prop-err-as", None, {"got": None}),
        ]
        for form, at_negative, at_zero in cases:
            with self.subTest(form=form):
                self.assertEqual(judged(form, ["fails-on-negative"], -1), at_negative)
                self.assertEqual(judged(form, ["fails-on-negative"], 0), at_zero)

    def test_a_subject_that_always_fails_or_never_does(self) -> None:
        """fails-otherwise fails at 0 too, and returns-ok fails nowhere."""
        self.assertIsNone(judged("prop-err-is", ["fails-otherwise"], 0))
        self.assertIsNone(judged("prop-err-absent", ["returns-ok"], -1))

    def test_throws_and_not_throws_decide_by_whether_the_call_raises(self) -> None:
        """raises-on-negative raises at -1 and returns at 0."""
        self.assertIsNone(judged("prop-throws", ["raises-on-negative"], -1))
        self.assertEqual(judged("prop-throws", ["raises-on-negative"], 0), {})
        self.assertIsNone(judged("prop-throws", ["raises"], 0))
        self.assertEqual(judged("prop-not-throws", ["raises-on-negative"], -1), {})
        self.assertIsNone(judged("prop-not-throws", ["raises-on-negative"], 0))
        self.assertIsNone(judged("prop-not-throws", ["returns-ok"], -1))

    def test_the_handle_assertions_decide_by_the_subjects_answer(self) -> None:
        """Reading the handle honours it, and ignoring it does not."""
        for form in ("prop-honours-cancellation", "prop-honours-deadline"):
            with self.subTest(form=form):
                self.assertIsNone(judged(form, ["reads-handle"], 0))
                self.assertIsNone(judged(form, ["dereferences-handle"], 0))
                self.assertEqual(judged(form, ["ignores-handle"], 0), {"got": None})
                self.assertEqual(judged(form, ["returns-ok"], 0), {"got": None})

    def test_nil_context_safe_fails_for_a_subject_an_absent_handle_crashes(
        self,
    ) -> None:
        """Only dereferences-handle crashes."""
        for kind in ("returns-ok", "reads-handle", "ignores-handle"):
            self.assertIsNone(judged("prop-nil-context-safe", [kind], 0))
        self.assertEqual(
            judged("prop-nil-context-safe", ["dereferences-handle"], 0), {}
        )


@final
class StateTest(unittest.TestCase):
    """The assertions over a subject's observed state, which a run keeps."""

    def test_an_observed_subject_counts_sets_or_leaves_its_integer(self) -> None:
        """Two calls add two, set the input, or change nothing."""
        for kind, after in (
            ("accumulates", 2),
            ("sets-value", 7),
            ("leaves-state-alone", 0),
        ):
            subject = Observed(kind)
            subject.call(7)
            subject.call(7)
            self.assertEqual(subject.value, after, kind)

    def test_pure_and_not_pure_compare_the_state_around_a_call(self) -> None:
        """A counter changes, and a cell set to its own value does not."""
        self.assertIsNone(judged("prop-pure", ["leaves-state-alone"], 0))
        self.assertEqual(judged("prop-pure", ["accumulates"], 0), {})
        self.assertIsNone(judged("prop-pure", ["sets-value"], 0))
        self.assertIsNone(judged("prop-not-pure", ["accumulates"], 0))
        self.assertEqual(judged("prop-not-pure", ["leaves-state-alone"], 0), {})

    def test_idempotent_compares_the_state_after_one_call_and_two(self) -> None:
        """A cell set twice to one value is set once, and a counter is not."""
        self.assertIsNone(judged("prop-idempotent", ["sets-value"], 4))
        self.assertEqual(judged("prop-idempotent", ["accumulates"], 4), {})

    def test_accumulates_states_both_changes(self) -> None:
        """No change fails, and a cell changes once."""
        self.assertIsNone(judged("prop-accumulates", ["accumulates"], 4))
        self.assertEqual(
            judged("prop-accumulates", ["leaves-state-alone"], 4),
            {"first": 0, "second": 0},
        )
        self.assertEqual(
            judged("prop-accumulates", ["sets-value"], 7), {"first": 7, "second": 0}
        )

    def test_a_judge_keeps_its_subject_across_cases(self) -> None:
        """A cell left at 7 by one case does not change in the next."""
        judge = build({"form": "prop-accumulates", "subjects": ["sets-value"]}).judge
        judge([7])
        self.assertEqual(judge([7]), {"first": 0, "second": 0})

    def test_deterministic_compares_32_calls(self) -> None:
        """A subject that returns its input agrees, and one that counts does not."""
        self.assertEqual(REPETITIONS, 32)
        self.assertIsNone(judged("prop-deterministic", ["returns-ok"], 3))
        self.assertEqual(judged("prop-deterministic", ["counts-calls"], 3), {})


@final
class RelationTest(unittest.TestCase):
    """The relations that combine or convert the generated arguments."""

    def test_commutative_combines_a_and_b_both_ways(self) -> None:
        """2 - 3 differs from 3 - 2, and 3 - 3 does not differ."""
        self.assertIsNone(judged("prop-commutative", ["adds"], 2, 3))
        self.assertEqual(
            judged("prop-commutative", ["subtracts"], 2, 3), {"first": -1, "second": 1}
        )
        self.assertIsNone(judged("prop-commutative", ["subtracts"], 3, 3))

    def test_associative_groups_a_b_and_c_both_ways(self) -> None:
        """(1 - 2) - 3 is -4, and 1 - (2 - 3) is 2."""
        self.assertIsNone(judged("prop-associative", ["adds"], 1, 2, 3))
        self.assertEqual(
            judged("prop-associative", ["subtracts"], 1, 2, 3),
            {"first": -4, "second": 2},
        )
        self.assertIsNone(judged("prop-associative", ["subtracts"], 1, 2, 0))

    def test_round_trip_converts_the_input_and_back(self) -> None:
        """Dropping the sign loses -42 and keeps 5."""
        self.assertIsNone(judged("prop-round-trip", ["renders-decimal"], -42))
        self.assertEqual(
            judged("prop-round-trip", ["drops-the-sign"], -42), {"want": -42, "got": 42}
        )
        self.assertIsNone(judged("prop-round-trip", ["drops-the-sign"], 5))


@final
class RunTest(unittest.TestCase):
    """A form run as prop-for-all runs a body."""

    def ran(
        self, spec: dict[str, Any], shape: dict[str, Any], *, fresh: bool = False
    ) -> tuple[Kind, dict[str, Any] | None, list[str]]:
        """Run a form from seed 7, and return the outcome, the record and the labels."""
        outcome, record = run_form(spec, read(shape), Settings(7), fresh=fresh)
        failing = outcome.failing
        labels = [] if failing is None else [d.label for d in failing.case.draws]
        return outcome.kind, record, labels

    def test_a_passing_form_has_no_record(self) -> None:
        """Every input of the shape is non-negative."""
        natural = {**SMALL, "min": 0}
        got = self.ran({"form": "prop-true", "subjects": ["is-non-negative"]}, natural)
        self.assertEqual(got, (Kind.PASSED, None, []))

    def test_a_failing_form_states_the_assertions_record_of_the_minimal_case(
        self,
    ) -> None:
        """The minimal case is -1, and in-range states it as got."""
        spec = {
            "form": "prop-in-range",
            "subjects": ["identity"],
            "args": [_float(0), _float(9)],
        }
        kind, record, labels = self.ran(spec, SMALL)
        self.assertEqual((kind, labels), (Kind.COUNTEREXAMPLE, ["input"]))
        self.assertEqual(
            record,
            {
                "assertion": "in-range",
                "detail": {
                    "got": {"type": "int", "value": -1},
                    "low": {"type": "float", "value": 0.0},
                    "high": {"type": "float", "value": 9.0},
                },
            },
        )

    def test_a_relation_draws_each_argument_under_its_label(self) -> None:
        """The form of associative draws a, b and c."""
        spec = {"form": "prop-associative", "subjects": ["subtracts"]}
        self.assertEqual(self.ran(spec, SMALL)[2], ["a", "b", "c"])

    def test_a_subject_kept_across_cases_can_pass_the_minimal_case(self) -> None:
        """A cell that a case left at 1 does not change when 1 is set again.

        The replay of the first failing case then passes, so the run is
        flaky, and the record states no detail. With subjects built anew,
        every case that sets 1 fails.
        """
        spec = {"form": "prop-pure", "subjects": ["sets-value"]}
        bit = {**SMALL, "min": 0, "max": 1}
        kept = self.ran(spec, bit)
        self.assertEqual(kept[:2], (Kind.FLAKY, {"assertion": "pure", "detail": None}))
        fresh = self.ran(spec, bit, fresh=True)
        self.assertEqual(
            fresh[:2], (Kind.COUNTEREXAMPLE, {"assertion": "pure", "detail": {}})
        )


@final
class ExamplesTest(unittest.TestCase):
    """The examples a form vector states, one value per case."""

    def test_an_example_of_an_input_with_an_inverse_is_its_choices(self) -> None:
        """5 of the shape runs backwards."""
        spec = {**TRUE, "examples": [_int(5)]}
        shape = read(SMALL)
        self.assertEqual(examples(spec, build(spec), shape), (invert(shape, 5),))

    def test_an_example_of_an_input_without_an_inverse_is_its_value(self) -> None:
        """-5 is outside the map's source, and the case states it as it is."""
        spec = {**TRUE, "examples": [_int(-5)]}
        mapped = generator.build(MAPPED)
        self.assertEqual(examples(spec, build(spec), mapped), (Values((-5,)),))

    def test_a_misstated_example_fails(self) -> None:
        """Outside the domain, over two inputs, and not a list."""
        commutative = {"form": "prop-commutative", "subjects": ["adds"]}
        faults: list[tuple[dict[str, Any], str]] = [
            ({**TRUE, "examples": [_int(50)]}, "the example 50"),
            ({**commutative, "examples": [_int(1)]}, "the form generates 2"),
            ({**TRUE, "examples": _int(1)}, "not a list of typed literals"),
        ]
        for spec, message in faults:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(FormError, message),
            ):
                examples(spec, build(spec), read(SMALL))

    def test_a_failing_example_of_values_is_reported_as_found(self) -> None:
        """-5 fails prop-true at once, and its record states no field."""
        spec = {**TRUE, "examples": [_int(-5)]}
        mapped = generator.build(MAPPED)
        outcome, record = run_form(spec, mapped, Settings(7), fresh=False)
        self.assertTrue(outcome.valued)
        self.assertEqual(record, {"assertion": "true", "detail": {}})
        assert outcome.failing is not None
        self.assertEqual(outcome.failing.case.draws[0].value, -5)
