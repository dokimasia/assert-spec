"""A run: its phases, its counts and its outcome.

The runner calls a body once per case, in four phases, and stops at the
first failing case:

1. Examples and stored: each choice sequence of a case whose values the
   caller states, in order, then each stored choice sequence, oldest
   first. These cases do not enter the case tree.
2. Simplest: one case whose every choice is its target.
3. Random: case i of the seed, for i = 0, 1, 2, ..., until ``cases``
   valid cases have run, the domain is exhausted, or GENERATION_FACTOR
   times ``cases`` random cases have been generated, repeats included.
   Each random case is followed by two others:

   - Its prefix case, while at most prefix_cases(cases) cases are valid
     and the random case made at least two choices. It replays the first
     c of the random case's n choices, with c = 1 + below(n - 1) drawn
     from the random case's source after the case, and every later
     request takes its target.
   - The next edge case, one per boundary as the edge module states,
     until all four have run. Edge cases left when the random cases
     stop run then.

4. Coverage: when a requirement is undecided at a check, further random
   cases up to the next check, at the multiples of ``cases`` that
   coverage.CHECKS states.

A valid case is one that passed and repeated no earlier case. Every
earlier phase's valid cases count towards ``cases``.

A failing case is replayed, shrunk and explained, as the shrink module
states, and the run ends as a counterexample, or as flaky when the replay
differs. A diverging body ends the run as flaky. A shrink budget of 0
reports the first failing case as found, without replay or explanation.

A run that found no failing case fails anyway when it rejected more than
MAX_REJECTIONS times as many cases as were valid, when no case requested
an input, or when a coverage requirement is refuted or unmet, checked in
that order.

A run's observer sees every call of the body with its phase: an example,
a stored case, the simplest case, a random case before the first check
and a coverage case after it, a prefix case, an edge case, the replay
before shrinking, a shrink candidate, an explain run, or the case of a
replay token.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final, final

from . import coverage, shrink
from .case import MAX_CHOICES, Generating, Provider, Replaying
from .choice import Choice
from .edge import BOUNDARIES, Edge
from .execution import (
    Body,
    Divergence,
    Execution,
    Observer,
    Phase,
    Status,
    execute,
    unobserved,
)
from .replay import encode
from .source import case_source
from .tree import Tree

#: The valid cases a run aims for when the caller states no number.
DEFAULT_CASES: Final = 100

#: A run that rejects more than this many cases for every valid one ends
#: as rejected.
MAX_REJECTIONS: Final = 10

#: A phase generates at most this many times as many random cases as the
#: valid cases it aims for.
GENERATION_FACTOR: Final = 10

#: A run tries prefix cases while at most cases // PREFIX_DIVISOR of its
#: cases are valid, and never past MAX_PREFIX_CASES valid cases.
PREFIX_DIVISOR: Final = 10
MAX_PREFIX_CASES: Final = 50

#: A random case has a prefix case only when it made at least this many
#: choices: one to replay and one to give its target.
MIN_PREFIXED_CHOICES: Final = 2


class Kind(StrEnum):
    """How a run ended. Every kind but PASSED fails the test."""

    PASSED = "passed"
    COUNTEREXAMPLE = "counterexample"
    FLAKY = "flaky"
    REJECTED = "rejected"
    COVERAGE_UNMET = "coverage-unmet"
    VACUOUS = "vacuous"


@dataclass(frozen=True)
class Requirement:
    """A label that must count at least share of the valid cases."""

    label: str
    share: float


@dataclass(frozen=True)
class Settings:
    """What a run is asked to do.

    examples are the choice sequences of the cases whose values the caller
    states, which run first. shrink is the budget of runs that shrinking
    and explaining every failure may spend, and 0 turns both off. replay,
    when set, is the one case the run tries: a failure is reported as
    found, and a pass passes.
    """

    seed: int
    cases: int = DEFAULT_CASES
    max_choices: int = MAX_CHOICES
    requirements: tuple[Requirement, ...] = ()
    examples: tuple[tuple[Choice, ...], ...] = ()
    stored: tuple[tuple[Choice, ...], ...] = ()
    shrink: int = shrink.DEFAULT_BUDGET
    explain: bool = True
    replay: tuple[Choice, ...] | None = None

    def __post_init__(self) -> None:
        """Refuse a run that aims for no case.

        Raises:
            ValueError: cases is below 1.
        """
        if self.cases < 1:
            raise ValueError(f"prop: a run of {self.cases} cases tests nothing")


@dataclass(frozen=True)
class Shortfall:
    """A requirement a run refuted or left unmet, with its counts."""

    requirement: Requirement
    counted: int
    valid: int
    verdict: coverage.Verdict


@dataclass(frozen=True)
class Outcome:
    """The end of a run.

    cases counts the valid cases. failing is the minimal failing execution
    of a counterexample, or the case a flaky replay contradicted; token is
    its replay token. others are the minimal executions of the other
    failures, in the order they were found. divergence is the difference
    that made a run flaky, and shortfall the requirement a coverage-unmet
    run missed. runs counts the runs that shrinking and explaining spent.
    """

    kind: Kind
    cases: int
    rejected: int
    seed: int
    failing: Execution | None = None
    divergence: Divergence | None = None
    shortfall: Shortfall | None = None
    others: tuple[Execution, ...] = ()
    explanation: tuple[shrink.Explained, ...] = ()
    token: str | None = None
    runs: int = 0


def rejects_too_many(valid: int, rejected: int) -> bool:
    """Report whether a run rejected more than MAX_REJECTIONS cases per valid one."""
    return rejected > MAX_REJECTIONS * valid


def prefix_cases(cases: int) -> int:
    """Return the most valid cases a run may have and still try a prefix case."""
    return min(cases // PREFIX_DIVISOR, MAX_PREFIX_CASES)


@final
@dataclass
class _Tally:
    """The counts of a run so far."""

    seed: int
    valid: int = 0
    rejected: int = 0
    requested: bool = False
    labels: Counter[str] = field(default_factory=Counter[str])

    def take(self, execution: Execution) -> Outcome | None:
        """Count one execution, and return the outcome when it ends the run."""
        case = execution.case
        self.requested = self.requested or bool(case.draws or case.choices)
        if execution.status is Status.FAILED:
            return self.outcome(Kind.COUNTEREXAMPLE, failing=execution)
        if execution.status is Status.DIVERGED:
            return self.outcome(Kind.FLAKY, divergence=execution.divergence)
        if execution.status is Status.REJECTED:
            self.rejected += 1
        elif execution.status is Status.PASSED:
            self.valid += 1
            self.labels.update(case.labels)
        return None

    def outcome(
        self,
        kind: Kind,
        *,
        failing: Execution | None = None,
        divergence: Divergence | None = None,
        shortfall: Shortfall | None = None,
    ) -> Outcome:
        """Return an outcome of kind with the counts so far."""
        return Outcome(
            kind, self.valid, self.rejected, self.seed, failing, divergence, shortfall
        )

    def failure_without_counterexample(self) -> Outcome | None:
        """Return the outcome of too many rejections or of no input, if either."""
        if rejects_too_many(self.valid, self.rejected):
            return self.outcome(Kind.REJECTED)
        if not self.requested:
            return self.outcome(Kind.VACUOUS)
        return None


def _shortfall(
    tally: _Tally, requirements: Sequence[Requirement], *, last: bool, exact: bool
) -> tuple[Shortfall | None, bool]:
    """Return the first refuted or unmet requirement, and whether all are met."""
    met = True
    for requirement in requirements:
        counted = tally.labels[requirement.label]
        verdict = coverage.verdict(
            counted, tally.valid, requirement.share, last=last, exact=exact
        )
        if verdict in (coverage.Verdict.REFUTED, coverage.Verdict.UNMET):
            return Shortfall(requirement, counted, tally.valid, verdict), False
        met = met and verdict is coverage.Verdict.MET
    return None, met


def _conclude(
    body: Body, settings: Settings, outcome: Outcome, observer: Observer
) -> Outcome:
    """Replay, shrink and explain the failing case of a counterexample."""
    failing = outcome.failing
    if outcome.kind is not Kind.COUNTEREXAMPLE or failing is None:
        return outcome
    if settings.shrink == 0:
        return replace(outcome, token=encode(failing.case.choices))
    divergence = shrink.confirm(body, failing, settings.max_choices, observer)
    if divergence is not None:
        return replace(outcome, kind=Kind.FLAKY, divergence=divergence)
    shrinker = shrink.Shrinker(
        body, failing, settings.max_choices, settings.shrink, observer
    )
    shrinker.shrink_all()
    assert failing.identity is not None
    first = shrinker.failures[failing.identity]
    others = tuple(
        found.execution
        for identity, found in shrinker.failures.items()
        if identity != failing.identity
    )
    explanation = (
        shrink.explain(shrinker, first, settings.seed) if settings.explain else ()
    )
    return replace(
        outcome,
        failing=first.execution,
        others=others,
        explanation=explanation,
        token=encode(first.execution.case.choices),
        runs=shrinker.runs,
    )


@final
@dataclass
class _Phases:
    """The cases of a run after its stored cases, in the order one worker runs them.

    The simplest case comes first. Each random case is followed by its
    prefix case and the next edge case, and the edge cases left when the
    random cases stop run then. phase is the phase of the random cases:
    random up to the first check, and coverage after it.
    """

    body: Body
    settings: Settings
    tally: _Tally
    observer: Observer
    tree: Tree = field(default_factory=Tree)
    edges: deque[Edge] = field(
        default_factory=lambda: deque(Edge(boundary) for boundary in BOUNDARIES)
    )
    index: int = 0
    phase: Phase = Phase.RANDOM

    def call(self, provider: Provider, phase: Phase) -> Execution:
        """Run one case of phase into the tree, and show it to the observer."""
        execution = execute(self.body, provider, self.settings.max_choices, self.tree)
        self.observer(phase, execution)
        return execution

    def attempt(self, provider: Provider, phase: Phase) -> Outcome | None:
        """Run one case of phase, count it, and return the outcome it ends with."""
        return self.tally.take(self.call(provider, phase))

    def random(self) -> Outcome | None:
        """Run the next random case, then its prefix case and the next edge case."""
        source = case_source(self.settings.seed, self.index)
        self.index += 1
        execution = self.call(Generating(source), self.phase)
        if (outcome := self.tally.take(execution)) is not None:
            return outcome
        choices = execution.case.choices
        prefixed = (
            self.tally.valid <= prefix_cases(self.settings.cases)
            and len(choices) >= MIN_PREFIXED_CHOICES
            and not self.tree.exhausted
        )
        if prefixed:
            cut = 1 + source.below(len(choices) - 1)
            prefix = Replaying(tuple(choices[:cut]))
            if (outcome := self.attempt(prefix, Phase.PREFIX)) is not None:
                return outcome
        return self.next_edge()

    def next_edge(self) -> Outcome | None:
        """Run the next edge case, unless none is left or the domain is exhausted."""
        if not self.edges or self.tree.exhausted:
            return None
        return self.attempt(self.edges.popleft(), Phase.EDGE)

    def run_to(self, target: int) -> Outcome | None:
        """Run random cases until target cases are valid, then the edge cases left.

        The random cases also stop when the domain is exhausted, and after
        GENERATION_FACTOR times target random cases, repeats included.
        """
        while (
            self.tally.valid < target
            and not self.tree.exhausted
            and self.index < GENERATION_FACTOR * target
        ):
            if (outcome := self.random()) is not None:
                return outcome
        while self.edges and not self.tree.exhausted:
            if (outcome := self.next_edge()) is not None:
                return outcome
        return None


def _explore(body: Body, settings: Settings, observer: Observer) -> Outcome:
    """Run the phases until the run ends, without concluding a counterexample."""
    tally = _Tally(settings.seed)
    known = [(Phase.EXAMPLE, example) for example in settings.examples]
    known += [(Phase.STORED, stored) for stored in settings.stored]
    for phase, choices in known:
        execution = execute(body, Replaying(choices), settings.max_choices)
        observer(phase, execution)
        if (outcome := tally.take(execution)) is not None:
            return outcome
    phases = _Phases(body, settings, tally, observer)
    if (outcome := phases.attempt(Replaying(()), Phase.SIMPLEST)) is not None:
        return outcome
    return _checks(phases) or tally.outcome(Kind.PASSED)


def _checks(phases: _Phases) -> Outcome | None:
    """Run the random phase to each check, and return the outcome that ends the run.

    The random cases after the first check are the coverage phase's. None
    means the run passes.
    """
    settings, tally = phases.settings, phases.tally
    multiples = coverage.CHECKS if settings.requirements else coverage.CHECKS[:1]
    for position, multiple in enumerate(multiples):
        phases.phase = Phase.RANDOM if position == 0 else Phase.COVERAGE
        outcome = phases.run_to(multiple * settings.cases)
        outcome = outcome or tally.failure_without_counterexample()
        if outcome is not None or not settings.requirements:
            return outcome
        last = position == len(multiples) - 1
        shortfall, met = _shortfall(
            tally, settings.requirements, last=last, exact=phases.tree.exhausted
        )
        if shortfall is not None:
            return tally.outcome(Kind.COVERAGE_UNMET, shortfall=shortfall)
        if met:
            return None
    return None


def _replay(
    body: Body, settings: Settings, choices: tuple[Choice, ...], observer: Observer
) -> Outcome:
    """Run the one case choices record, and report it as found."""
    tally = _Tally(settings.seed)
    execution = execute(body, Replaying(choices), settings.max_choices)
    observer(Phase.TOKEN, execution)
    outcome = tally.take(execution)
    if outcome is None:
        return tally.failure_without_counterexample() or tally.outcome(Kind.PASSED)
    if outcome.failing is None:
        return outcome
    return replace(outcome, token=encode(outcome.failing.case.choices))


def run(body: Body, settings: Settings, observer: Observer = unobserved) -> Outcome:
    """Run the phases and return the outcome.

    A run with replay set runs that one case instead, and neither
    shrinks nor explains it. observer sees every call of the body with
    its phase, in the order of the run.
    """
    if settings.replay is not None:
        return _replay(body, settings, settings.replay, observer)
    explored = _explore(body, settings, observer)
    return _conclude(body, settings, explored, observer)
