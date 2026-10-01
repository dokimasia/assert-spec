"""The coverage test: the Wilson bound and the verdicts it gives."""

from __future__ import annotations

import unittest
from statistics import NormalDist
from typing import final

from .coverage import CHECKS, TOLERANCE, Verdict, Z, bound, met, refuted, verdict

#: The certainty QuickCheck's checkCoverage uses, split between two tails.
TAIL = 5e-10

#: The definition's constants, pinned rather than read from the code under
#: test: the tolerance and the checks as multiples of cases.
PINNED_TOLERANCE = 0.9
PINNED_CHECKS = (1, 2, 4, 8)


@final
class BoundTest(unittest.TestCase):
    """bound(): the Wilson score interval, evaluated in the stated order."""

    def test_z_is_the_normal_quantile_at_one_minus_the_tail(self) -> None:
        """The statistics module's inverse CDF agrees to twelve places."""
        self.assertAlmostEqual(NormalDist().inv_cdf(1 - TAIL), Z, places=12)

    def test_the_constants_are_quickchecks(self) -> None:
        """A tolerance of 0.9 and checks at 1, 2, 4 and 8 times cases."""
        self.assertEqual(TOLERANCE, PINNED_TOLERANCE)
        self.assertEqual(CHECKS, PINNED_CHECKS)

    def test_the_lower_bound_of_27_in_100_is_pinned(self) -> None:
        """The exact double, so a reordered expression fails here."""
        self.assertEqual(bound(27, 100, -Z).hex(), "0x1.7bf6bece04433p-4")

    def test_the_bounds_enclose_the_observed_share(self) -> None:
        """Lower below p, upper above it, across shares and counts."""
        for k, n in ((0, 10), (1, 10), (5, 10), (10, 10), (27, 100), (80, 800)):
            p = k / n
            self.assertLessEqual(bound(k, n, -Z), p, (k, n))
            self.assertGreaterEqual(bound(k, n, Z), p, (k, n))

    def test_counts_that_are_no_share_raise(self) -> None:
        """No trials, a negative count, or more successes than trials."""
        for k, n in ((0, 0), (-1, 10), (11, 10)):
            with self.assertRaises(ValueError):
                bound(k, n, Z)


@final
class VerdictTest(unittest.TestCase):
    """met(), refuted() and verdict()."""

    def test_ten_percent_is_met_at_100_cases_from_27_counted(self) -> None:
        """27 of 100 meets 10%, and 26 does not."""
        self.assertTrue(met(27, 100, 0.1))
        self.assertFalse(met(26, 100, 0.1))

    def test_a_share_far_below_the_requirement_is_refuted(self) -> None:
        """None of 100 refutes 50%, and 40 of 100 does not."""
        self.assertTrue(refuted(0, 100, 0.5))
        self.assertFalse(refuted(40, 100, 0.5))

    def test_an_upper_bound_equal_to_the_share_does_not_refute_it(self) -> None:
        """Refuted means strictly below."""
        self.assertFalse(refuted(3, 100, bound(3, 100, Z)))

    def test_an_observed_share_of_exactly_nine_tenths_is_met(self) -> None:
        """9 of 10 against 100% is the tolerance itself."""
        self.assertEqual(verdict(9, 10, 1.0, last=True, exact=True), Verdict.MET)

    def test_a_check_before_the_last_can_leave_a_requirement_undecided(self) -> None:
        """10 of 100 against 10% is neither met nor refuted."""
        got = verdict(10, 100, 0.1, last=False, exact=False)
        self.assertEqual(got, Verdict.UNDECIDED)
        self.assertEqual(verdict(27, 100, 0.1, last=False, exact=False), Verdict.MET)
        self.assertEqual(verdict(0, 100, 0.5, last=False, exact=False), Verdict.REFUTED)

    def test_the_last_check_decides_by_the_observed_share(self) -> None:
        """75 of 800 is 9.375%, at least 0.9 times 10%; 70 of 800 is not."""
        self.assertEqual(verdict(75, 800, 0.1, last=True, exact=False), Verdict.MET)
        self.assertEqual(verdict(70, 800, 0.1, last=True, exact=False), Verdict.UNMET)

    def test_the_last_check_still_applies_the_interval_first(self) -> None:
        """A refuted requirement stays refuted at the last check."""
        self.assertEqual(verdict(0, 800, 0.5, last=True, exact=False), Verdict.REFUTED)

    def test_an_exhausted_domain_compares_its_exact_share(self) -> None:
        """One of six inputs meets 10%; none of six does not."""
        self.assertEqual(verdict(1, 6, 0.1, last=False, exact=True), Verdict.MET)
        self.assertEqual(verdict(0, 6, 0.1, last=False, exact=True), Verdict.UNMET)

    def test_an_exact_share_ignores_the_interval(self) -> None:
        """Six of six meet 100% exactly, though the interval cannot meet it."""
        self.assertEqual(verdict(6, 6, 1.0, last=False, exact=True), Verdict.MET)
        self.assertFalse(met(6, 6, 1.0))
