"""A run: its phases, its counts, and each of its outcomes."""

from __future__ import annotations

import unittest
from typing import Any, final

from .case import Case, Generating
from .choice import Choice
from .coverage import Verdict
from .execution import Body, Execution, Phase, Status, execute
from .generator import build
from .runner import (
    Kind,
    Requirement,
    Settings,
    Values,
    prefix_cases,
    rejects_too_many,
    run,
)
from .source import case_source
from .trace import Draw, TraceError

#: The definition's run constants, pinned rather than read from the code.
PINNED_CASES = 100
PINNED_REJECTIONS = 10
PINNED_GENERATION = 10

#: prefix_cases() of 100, 500, 1000 and 9 cases.
PINNED_PREFIX = [10, 50, 50, 0]

#: The random fillings the explain phase tries for each draw.
PINNED_FILLINGS = 4

SEED = 7

#: The values the failing bodies fail at.
SUM_LIMIT = 10
SEVEN = 7

DIGIT: dict[str, Any] = {"gen": "integer", "min": 0, "max": 9}
DIGITS = build({"gen": "list", "of": DIGIT, "max_size": 8})
BOOLEAN = build({"gen": "boolean"})
THREE = build(
    {"gen": "sampled-from", "values": [{"type": "int", "value": v} for v in (1, 2, 3)]}
)
WIDE = build({"gen": "integer", "min": 0, "max": 1 << 32})


def passes(case: Case) -> None:
    """Draw a list of digits and pass."""
    case.draw(DIGITS, "digits")


@final
class Calls:
    """A body that counts its calls, around another body."""

    def __init__(self, body: Body) -> None:
        """Wrap body."""
        self.body = body
        self.count = 0

    def __call__(self, case: Case) -> None:
        """Count the call, then run the wrapped body."""
        self.count += 1
        self.body(case)


@final
class Seen:
    """An observer that keeps the phase and the status of every call."""

    def __init__(self) -> None:
        """Start with no call seen."""
        self.calls: list[tuple[Phase, Status]] = []

    def __call__(self, phase: Phase, execution: Execution) -> None:
        """Keep one call."""
        self.calls.append((phase, execution.status))

    @property
    def phases(self) -> list[Phase]:
        """Return the phase of every call, in order."""
        return [phase for phase, _ in self.calls]


#: The values above_million and the explain test's body fail above.
MILLION = 10**6
THOUSAND = 1000


def above_million(case: Case) -> None:
    """Draw a wide integer and fail above 10^6."""
    n = case.draw(WIDE, "n")
    assert isinstance(n, int)
    if n > MILLION:
        case.fail("big")


@final
class PassTest(unittest.TestCase):
    """A body that never fails."""

    def test_a_passing_body_runs_the_default_number_of_cases(self) -> None:
        """100 valid cases, then passed."""
        outcome = run(passes, Settings(SEED))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, PINNED_CASES))

    def test_an_exhausted_domain_passes_after_its_inputs(self) -> None:
        """A boolean and a three-valued choice pass after six cases."""

        def body(case: Case) -> None:
            case.draw(BOOLEAN, "flag")
            case.draw(THREE, "one of three")

        outcome = run(body, Settings(SEED))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, 6))

    def test_a_repeated_case_does_not_count(self) -> None:
        """A boolean alone has two inputs, whatever the seed."""
        outcome = run(lambda case: case.draw(BOOLEAN, "flag"), Settings(SEED))
        self.assertEqual(outcome.cases, 2)

    def test_generation_stops_after_ten_times_cases(self) -> None:
        """A float of one value never exhausts and repeats from the second case."""
        one = build({"gen": "float", "min": 1, "max": 1})
        body = Calls(lambda case: case.draw(one, "one"))
        outcome = run(body, Settings(SEED, cases=20))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, 1))
        self.assertEqual(body.count, 1 + 4 + PINNED_GENERATION * 20)


@final
class CounterexampleTest(unittest.TestCase):
    """A failing case ends the run."""

    def test_the_simplest_case_finds_a_failure_on_the_empty_input(self) -> None:
        """The first case, with no valid case before it."""

        def body(case: Case) -> None:
            digits = case.draw(DIGITS, "digits")
            if digits == []:
                case.fail("empty")

        outcome = run(body, Settings(SEED))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.COUNTEREXAMPLE, 0))
        assert outcome.failing is not None
        self.assertEqual(outcome.failing.case.choices, [Choice("integer", 0)])

    def test_the_edges_find_an_overflow_at_the_maximum(self) -> None:
        """Edge case 1, after the simplest case and random cases 0 and 1 passed.

        Edge case 0, the minimum, repeats the simplest case and does not count.
        """

        def body(case: Case) -> None:
            if case.draw(WIDE, "n") == 1 << 32:
                case.fail("overflow")

        outcome = run(body, Settings(SEED))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.COUNTEREXAMPLE, 3))

    def test_a_random_failure_reports_its_case_and_identity(self) -> None:
        """A sum above 10 fails, and the case's draws decode to that sum."""

        def body(case: Case) -> None:
            digits = case.draw(DIGITS, "digits")
            assert isinstance(digits, list)
            if sum(digits) > SUM_LIMIT:
                case.fail("sum-above", f"sum is {sum(digits)}")

        outcome = run(body, Settings(SEED))
        self.assertIs(outcome.kind, Kind.COUNTEREXAMPLE)
        assert outcome.failing is not None and outcome.failing.failure is not None
        self.assertEqual(outcome.failing.failure.identity, "sum-above")
        drawn = outcome.failing.case.draws[0].value
        assert isinstance(drawn, list)
        self.assertGreater(sum(drawn), SUM_LIMIT)

    def test_a_stored_case_runs_first(self) -> None:
        """A stored failing sequence fails before any generated case."""

        def body(case: Case) -> None:
            if case.draw(build(DIGIT), "n") == SEVEN:
                case.fail("seven")

        stored = ((Choice("integer", SEVEN),),)
        outcome = run(body, Settings(SEED, stored=stored))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.COUNTEREXAMPLE, 0))

    def test_case_i_uses_the_stream_of_seed_plus_i(self) -> None:
        """A random case decodes as its source alone decodes."""
        execution = execute(passes, Generating(case_source(SEED, 3)), 8192, None)
        twin = Case(Generating(case_source(SEED, 3)))
        self.assertEqual(execution.case.draws[0].value, DIGITS.decode(twin))
        self.assertIs(execution.status, Status.PASSED)


@final
class PhaseTest(unittest.TestCase):
    """The order of the simplest, random, prefix and edge cases."""

    def test_prefix_cases_run_while_a_tenth_of_cases_are_valid(self) -> None:
        """10 for the default 100 cases, never more than 50, and none below 10 cases."""
        got = [prefix_cases(n) for n in (PINNED_CASES, 500, 1000, 9)]
        self.assertEqual(got, PINNED_PREFIX)

    def test_a_prefix_case_keeps_a_random_choice_and_targets_the_rest(self) -> None:
        """A nonzero n followed by m = 0 fails first in prefix case 0."""

        def body(case: Case) -> None:
            n, m = case.draw(WIDE, "n"), case.draw(WIDE, "m")
            if n != 0 and m == 0:
                case.fail("zero after nonzero")

        outcome = run(body, Settings(SEED, shrink=0))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.COUNTEREXAMPLE, 2))
        random_case = Case(Generating(case_source(SEED, 0)))
        n = WIDE.decode(random_case)
        assert isinstance(n, int)
        assert outcome.failing is not None
        want = [Choice("integer", n), Choice("integer", 0)]
        self.assertEqual(outcome.failing.case.choices, want)

    def test_a_prefix_case_runs_while_the_valid_cases_equal_the_limit(self) -> None:
        """20 cases allow 2: the simplest case and random case 0, then prefix case 0."""

        def body(case: Case) -> None:
            n, m = case.draw(WIDE, "n"), case.draw(WIDE, "m")
            if n != 0 and m == 0:
                case.fail("zero after nonzero")

        outcome = run(body, Settings(SEED, cases=20, shrink=0))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.COUNTEREXAMPLE, 2))

    def test_every_edge_case_runs_when_the_random_cases_stop_first(self) -> None:
        """A run of one case: the simplest case, then the four edge cases."""
        body = Calls(lambda case: case.draw(WIDE, "n"))
        outcome = run(body, Settings(SEED, cases=1))
        self.assertEqual((outcome.kind, body.count), (Kind.PASSED, 5))


@final
class FailureWithoutCounterexampleTest(unittest.TestCase):
    """Runs that found no failing case and still fail."""

    def test_a_body_that_rejects_every_case_is_rejected(self) -> None:
        """More than ten rejections for every valid case."""

        def body(case: Case) -> None:
            case.draw(DIGITS, "digits")
            case.assume(False)

        outcome = run(body, Settings(SEED, cases=10))
        self.assertIs(outcome.kind, Kind.REJECTED)

    def test_the_limit_is_more_than_ten_rejections_per_valid_case(self) -> None:
        """Ten per valid case is within the limit, and eleven is not."""
        self.assertFalse(rejects_too_many(3, PINNED_REJECTIONS * 3))
        self.assertTrue(rejects_too_many(3, PINNED_REJECTIONS * 3 + 1))
        self.assertTrue(rejects_too_many(0, 1))

    def test_a_case_past_its_cap_is_rejected_and_leaves_no_leaf(self) -> None:
        """Lists of two digits overrun three choices; later ones overrun again."""
        outcome = run(passes, Settings(SEED, max_choices=3))
        self.assertIs(outcome.kind, Kind.REJECTED)

    def test_a_body_that_requests_no_input_is_vacuous(self) -> None:
        """One case, the only one, and nothing drawn."""
        outcome = run(lambda case: None, Settings(SEED))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.VACUOUS, 1))

    def test_a_body_that_only_reads_the_random_source_requests_input(self) -> None:
        """Its choices are inputs, though it draws from no generator."""
        outcome = run(lambda case: case.random(), Settings(SEED))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, PINNED_CASES))

    def test_a_body_that_requests_different_choices_is_flaky(self) -> None:
        """The second case requests a boolean where the first drew a digit."""
        calls: list[Case] = []

        def body(case: Case) -> None:
            calls.append(case)
            case.draw(build(DIGIT) if len(calls) == 1 else BOOLEAN, "n")

        outcome = run(body, Settings(SEED))
        self.assertIs(outcome.kind, Kind.FLAKY)
        assert outcome.divergence is not None
        self.assertEqual(outcome.divergence.index, 0)


@final
class CoverageTest(unittest.TestCase):
    """Requirements on labels."""

    def test_a_requirement_the_share_meets_passes(self) -> None:
        """About half the digits are even."""

        def body(case: Case) -> None:
            n = case.draw(WIDE, "n")
            assert isinstance(n, int)
            if n % 2 == 0:
                case.classify("even")

        settings = Settings(SEED, requirements=(Requirement("even", 0.2),))
        outcome = run(body, settings)
        self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, PINNED_CASES))

    def test_a_label_never_counted_is_refuted(self) -> None:
        """The run names the label and its counts."""
        settings = Settings(SEED, requirements=(Requirement("never", 0.5),))
        outcome = run(passes, settings)
        self.assertIs(outcome.kind, Kind.COVERAGE_UNMET)
        assert outcome.shortfall is not None
        self.assertEqual(outcome.shortfall.requirement.label, "never")
        self.assertEqual(outcome.shortfall.counted, 0)

    def test_an_exhausted_domain_compares_exact_shares(self) -> None:
        """One digit of ten is 7: 10% meets 10%, and fails 20%."""

        def body(case: Case) -> None:
            if case.draw(build(DIGIT), "n") == SEVEN:
                case.classify("seven")

        met = Settings(SEED, requirements=(Requirement("seven", 0.1),))
        unmet = Settings(SEED, requirements=(Requirement("seven", 0.2),))
        self.assertEqual(run(body, met).kind, Kind.PASSED)
        outcome = run(body, unmet)
        self.assertEqual((outcome.kind, outcome.cases), (Kind.COVERAGE_UNMET, 10))

    def test_an_undecided_requirement_runs_up_to_the_last_check(self) -> None:
        """A share near the requirement runs eight times cases."""

        def body(case: Case) -> None:
            n = case.draw(WIDE, "n")
            assert isinstance(n, int)
            if n % 10 == 0:
                case.classify("tenth")

        settings = Settings(SEED, cases=50, requirements=(Requirement("tenth", 0.1),))
        outcome = run(body, settings)
        self.assertEqual(outcome.cases, 400)

    def test_the_last_check_decides_an_undecided_requirement_by_its_share(
        self,
    ) -> None:
        """43 of 400 is below nine tenths of 12%, so the requirement is unmet."""

        def body(case: Case) -> None:
            n = case.draw(WIDE, "n")
            assert isinstance(n, int)
            if n % 10 == 0:
                case.classify("tenth")

        settings = Settings(SEED, cases=50, requirements=(Requirement("tenth", 0.12),))
        outcome = run(body, settings)
        assert outcome.shortfall is not None
        shortfall = outcome.shortfall
        self.assertEqual((shortfall.counted, shortfall.valid), (43, 400))
        self.assertIs(shortfall.verdict, Verdict.UNMET)


@final
class ObserverTest(unittest.TestCase):
    """The phase of every call of the body, in the order of the run."""

    def test_a_run_of_one_case_calls_the_simplest_case_then_the_edges(self) -> None:
        """No random case runs once the simplest case is valid."""
        seen = Seen()
        run(lambda case: case.draw(WIDE, "n"), Settings(SEED, cases=1), seen)
        self.assertEqual(seen.phases, [Phase.SIMPLEST, *[Phase.EDGE] * 4])

    def test_the_examples_and_the_stored_cases_come_first(self) -> None:
        """An example, two stored cases, then the simplest case."""
        seen = Seen()
        examples = ((Choice("integer", 5),),)
        stored = ((Choice("integer", 3),), (Choice("integer", 4),))
        settings = Settings(SEED, cases=1, examples=examples, stored=stored)
        body = Calls(lambda case: case.draw(WIDE, "n"))
        run(body, settings, seen)
        known = [Phase.EXAMPLE, Phase.STORED, Phase.STORED, Phase.SIMPLEST]
        self.assertEqual(seen.phases[:4], known)
        self.assertEqual(len(seen.calls), body.count)

    def test_a_trace_runs_before_the_examples(self) -> None:
        """The trace's draw takes its entry, and an example follows it."""
        values: list[object] = []
        seen = Seen()
        settings = Settings(
            SEED,
            cases=1,
            traces=((Draw("n", 5),),),
            examples=((Choice("integer", 3),),),
        )
        run(lambda case: values.append(case.draw(WIDE, "n")), settings, seen)
        self.assertEqual(
            seen.phases[:3], [Phase.EXAMPLE, Phase.EXAMPLE, Phase.SIMPLEST]
        )
        self.assertEqual(values[:2], [5, 3])

    def test_a_trace_the_body_cannot_follow_ends_the_run(self) -> None:
        """A draw under another label than its entry's raises before any case."""
        seen = Seen()
        settings = Settings(SEED, traces=((Draw("m", 5),),))
        with self.assertRaises(TraceError):
            run(lambda case: case.draw(WIDE, "n"), settings, seen)
        self.assertEqual(seen.calls, [])

    def test_a_random_case_is_followed_by_its_prefix_case(self) -> None:
        """Random case 0 of two wide integers has a prefix case."""
        seen = Seen()

        def body(case: Case) -> None:
            case.draw(WIDE, "n")
            case.draw(WIDE, "m")

        run(body, Settings(SEED), seen)
        self.assertEqual(seen.phases[1:3], [Phase.RANDOM, Phase.PREFIX])

    def test_random_cases_after_the_first_check_are_coverage_cases(self) -> None:
        """The first check is at 50 valid cases, and the rest are coverage cases."""
        seen = Seen()

        def body(case: Case) -> None:
            n = case.draw(WIDE, "n")
            assert isinstance(n, int)
            if n % 10 == 0:
                case.classify("tenth")

        requirement = (Requirement("tenth", 0.1),)
        run(body, Settings(SEED, cases=50, requirements=requirement), seen)
        first = seen.phases.index(Phase.COVERAGE)
        valid = [status for _, status in seen.calls[:first] if status is Status.PASSED]
        self.assertEqual(len(valid), 50)
        later = set(seen.phases[first:])
        self.assertEqual(later, {Phase.COVERAGE})

    def test_a_failure_is_replayed_shrunk_and_explained_in_that_order(self) -> None:
        """The shrink and explain runs are the runs the outcome counts."""
        seen = Seen()
        outcome = run(above_million, Settings(SEED), seen)
        replay = seen.phases.index(Phase.REPLAY)
        self.assertEqual(seen.calls[replay - 1][1], Status.FAILED)
        after = seen.phases[replay + 1 :]
        shrinks = after.count(Phase.SHRINK)
        explains = len(after) - shrinks
        self.assertEqual(after, [Phase.SHRINK] * shrinks + [Phase.EXPLAIN] * explains)
        self.assertGreater(explains, 0)
        self.assertEqual(len(after), outcome.runs)

    def test_each_filling_of_a_draw_is_an_explain_run(self) -> None:
        """Every value fails: the simplest case, its replay, a shrink, four fillings."""

        def body(case: Case) -> None:
            case.draw(WIDE, "n")
            case.fail("always")

        seen = Seen()
        run(body, Settings(SEED), seen)
        concluded = [Phase.REPLAY, Phase.SHRINK, *[Phase.EXPLAIN] * PINNED_FILLINGS]
        self.assertEqual(seen.phases, [Phase.SIMPLEST, *concluded])

    def test_the_step_to_the_nearest_passing_value_is_an_explain_run(self) -> None:
        """Above 1000 fails, so the explain phase ends by passing 1000."""

        def body(case: Case) -> None:
            n = case.draw(build({"gen": "integer", "min": 0, "max": 10000}), "n")
            assert isinstance(n, int)
            if n > THOUSAND:
                case.fail("big")

        seen = Seen()
        run(body, Settings(SEED), seen)
        self.assertEqual(seen.calls[-1], (Phase.EXPLAIN, Status.PASSED))

    def test_a_run_without_shrinking_replays_nothing(self) -> None:
        """The first failing case is the last call."""
        seen = Seen()
        run(above_million, Settings(SEED, shrink=0), seen)
        self.assertEqual(seen.calls[-1][1], Status.FAILED)
        self.assertNotIn(Phase.REPLAY, seen.phases)

    def test_a_replayed_token_is_one_token_case(self) -> None:
        """The case of the token, and nothing else."""
        seen = Seen()
        replayed = (Choice("integer", MILLION + 1),)
        run(above_million, Settings(SEED, replay=replayed), seen)
        self.assertEqual(seen.calls, [(Phase.TOKEN, Status.FAILED)])


@final
class ValuesTest(unittest.TestCase):
    """An example of values, which a generator without an inverse needs."""

    def test_a_passing_example_of_values_counts_as_a_valid_case(self) -> None:
        """A boolean's two inputs are two valid cases, and the example a third.

        The example enters no case tree, so the run still finds both inputs.
        """

        def body(case: Case) -> None:
            case.draw(BOOLEAN, "flag")

        outcome = run(body, Settings(SEED, examples=(Values((True,)),)))
        self.assertEqual((outcome.kind, outcome.cases), (Kind.PASSED, 3))

    def test_a_failing_example_of_values_is_reported_as_found(self) -> None:
        """No replay, shrink or explain run follows it, and it has no token."""
        seen = Seen()
        settings = Settings(SEED, examples=(Values((MILLION + 5,)),))
        outcome = run(above_million, settings, seen)
        self.assertEqual(seen.calls, [(Phase.EXAMPLE, Status.FAILED)])
        self.assertIs(outcome.kind, Kind.COUNTEREXAMPLE)
        self.assertTrue(outcome.valued)
        self.assertEqual((outcome.token, outcome.runs, outcome.others), (None, 0, ()))
        assert outcome.failing is not None
        self.assertEqual(outcome.failing.case.choices, [])
        self.assertEqual(outcome.failing.case.draws[0].value, MILLION + 5)

    def test_a_failing_example_of_choices_is_shrunk(self) -> None:
        """The same value as a choice sequence runs as every example does."""
        settings = Settings(SEED, examples=((Choice("integer", MILLION + 5),),))
        outcome = run(above_million, settings)
        self.assertFalse(outcome.valued)
        self.assertIsNotNone(outcome.token)
        assert outcome.failing is not None
        self.assertEqual(outcome.failing.case.draws[0].value, MILLION + 1)


@final
class SettingsTest(unittest.TestCase):
    """The settings a run refuses."""

    def test_a_run_of_no_cases_raises(self) -> None:
        """A run must aim for at least one case."""
        with self.assertRaises(ValueError):
            Settings(SEED, cases=0)
