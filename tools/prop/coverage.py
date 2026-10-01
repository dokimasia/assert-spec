"""The coverage test: whether a label covers a required share of the cases.

A requirement is decided with the Wilson score interval of the label's
share, with the constants QuickCheck's checkCoverage uses: a certainty of
10^9 and a tolerance of 0.9. The runner checks every requirement after
CHECKS[0] times ``cases`` valid cases and again each time that count
doubles, up to the last check. The test uses only arithmetic and a square
root, which IEEE 754 rounds exactly, so every language decides the same
way from the same counts when it evaluates bound() in the order written.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Final

#: The standard normal quantile at 1 - 5e-10: QuickCheck's certainty of
#: 10^9, split between the two tails.
Z: Final = 6.109410191663286

#: A requirement is met when the lower bound reaches this fraction of the
#: required share.
TOLERANCE: Final = 0.9

#: The checks, as multiples of ``cases`` valid cases. The last is the
#: last check of the run.
CHECKS: Final = (1, 2, 4, 8)


class Verdict(StrEnum):
    """What a check decides about one requirement."""

    MET = "met"
    REFUTED = "refuted"
    UNDECIDED = "undecided"
    UNMET = "unmet"


def bound(k: int, n: int, z: float) -> float:
    """Return the Wilson score bound of k successes in n trials at quantile z.

    A positive z gives the upper bound and a negative z the lower one.

    Raises:
        ValueError: n is not positive, or k is outside [0, n].
    """
    if n < 1 or not 0 <= k <= n:
        raise ValueError(f"prop: {k} of {n} is not a share")
    p = k / n
    a = z * z / n
    centre = p + a / 2
    spread = z * math.sqrt(p * (1 - p) / n + a / (4 * n))
    return (centre + spread) / (1 + a)


def met(k: int, n: int, share: float) -> bool:
    """Report whether the lower bound reaches TOLERANCE times the share."""
    return bound(k, n, -Z) >= TOLERANCE * share


def refuted(k: int, n: int, share: float) -> bool:
    """Report whether the upper bound falls below the share."""
    return bound(k, n, Z) < share


def verdict(k: int, n: int, share: float, *, last: bool, exact: bool) -> Verdict:
    """Return the verdict on one requirement at one check.

    exact marks a run that tested every input of its domain, whose shares
    are exact. An exact share, and an undecided share at the last check,
    are met when k / n is at least TOLERANCE times the share, and unmet
    otherwise.
    """
    if not exact:
        if met(k, n, share):
            return Verdict.MET
        if refuted(k, n, share):
            return Verdict.REFUTED
        if not last:
            return Verdict.UNDECIDED
    return Verdict.MET if k / n >= TOLERANCE * share else Verdict.UNMET
