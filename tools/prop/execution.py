"""One call of a body, and how it ended.

The runner, the shrinker and the explain phase each call the body through
execute(). A case that walks the case tree can end early as a repeat or a
divergence. A case outside the tree, such as a stored case or a shrink
candidate, cannot.

Each call of a body has a phase, the part of the run that made it. An
observer of a run sees every call with its phase, in the order a run on
one worker makes them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .case import Case, Failed, Overrun, Place, Provider, Rejected, Where
from .tree import Diverged, Ending, Repeated, Tree

#: A body: it receives the case, draws from it, and fails it or returns.
#: Its return value is ignored.
Body = Callable[[Case], object]


class Phase(StrEnum):
    """The part of a run that called the body: the kind of a property's case.

    EXAMPLE is a case whose values the caller states, through draws or
    example. FUZZ is the case that the fuzz bridge decodes from a fuzzer's
    input, which a fuzz target runs and a run of the phases never does.
    """

    EXAMPLE = "example"
    STORED = "stored"
    SIMPLEST = "simplest"
    RANDOM = "random"
    PREFIX = "prefix"
    EDGE = "edge"
    COVERAGE = "coverage"
    REPLAY = "replay"
    SHRINK = "shrink"
    EXPLAIN = "explain"
    TOKEN = "token"
    FUZZ = "fuzz"


class Status(StrEnum):
    """How one case ended."""

    PASSED = "passed"
    FAILED = "failed"
    REJECTED = "rejected"
    REPEATED = "repeated"
    DIVERGED = "diverged"


@dataclass(frozen=True)
class Divergence:
    """The first difference between two runs of the same choices.

    what names the kind of difference: "request" for the bounds of a
    request, where None stands for a case that ended; "fingerprint" for an
    observed fingerprint, where None stands for no fingerprint; and
    "verdict" for a replay that passed or failed another way, with the two
    identities, where None stands for a pass.

    index is the position of the request or the fingerprint that differs.
    For a verdict, it is the number of choices the recorded case made,
    the position where the case ended.

    label and step state where the replay made the request or observed the
    fingerprint: the label of the draw that was running, and the part and
    step of a machine. Each is None where the replay was outside a draw or
    a machine's steps, where it made no request or observed no
    fingerprint at the position, and for a verdict.
    """

    what: str
    index: int
    recorded: object
    replayed: object
    label: str | None = None
    step: Place | None = None

    @classmethod
    def at(
        cls, what: str, index: int, recorded: object, replayed: object, where: Where
    ) -> Divergence:
        """Return a divergence whose label and step are those of where."""
        return cls(what, index, recorded, replayed, where.label, where.place)


@dataclass(frozen=True)
class Execution:
    """One call of the body: its case and how it ended."""

    case: Case
    status: Status
    failure: Failed | None = None
    divergence: Divergence | None = None

    @property
    def identity(self) -> str | None:
        """Return the failure's identity, or None when the case did not fail."""
        return None if self.failure is None else self.failure.identity


#: What watches the calls of a run's body: the phase of each call and how
#: it ended, in the order a run on one worker makes them.
Observer = Callable[[Phase, Execution], object]


def unobserved(phase: Phase, execution: Execution) -> None:
    """Watch nothing, as a run that nobody records."""
    del phase, execution


def execute(
    body: Body, provider: Provider, max_choices: int, tree: Tree | None = None
) -> Execution:
    """Call the body once on a case whose values come from provider.

    With a tree, the case walks it, and a repeat or a divergence ends the
    case early. A case that overruns its cap is rejected without a leaf.
    """
    walker = None if tree is None else tree.walker()
    case = Case(provider, max_choices, walker)
    failure = None
    try:
        body(case)
    except Repeated:
        return Execution(case, Status.REPEATED)
    except Diverged as diverged:
        divergence = _divergence(diverged, case)
        return Execution(case, Status.DIVERGED, divergence=divergence)
    except Overrun:
        return Execution(case, Status.REJECTED)
    except Rejected:
        ending = Ending.REJECTED
    except Failed as failed:
        ending, failure = Ending.FAILED, failed
    else:
        ending = Ending.PASSED
    if walker is not None:
        try:
            walker.end(ending)
        except Diverged as diverged:
            divergence = _divergence(diverged, case)
            return Execution(case, Status.DIVERGED, divergence=divergence)
    return Execution(case, Status(ending.value), failure)


def _divergence(diverged: Diverged, case: Case) -> Divergence:
    """Return the tree's divergence as a request divergence of case.

    A request that diverged is the case's last recorded request, and the
    divergence takes its label and step. A case that ended where an earlier
    case made a request made no request there.
    """
    where = Where() if diverged.requested is None else case.wheres[diverged.index]
    return Divergence.at(
        "request", diverged.index, diverged.recorded, diverged.requested, where
    )
