"""Decide whether a history is linearizable, by a fixed search over its partitions.

check() first removes every call that failed. It joins the calls that
share a key into partitions, and searches each partition for an order of
its calls that keeps the history's precedence and that the model accepts.
A call that declares no key touches every key, so it puts the whole
history into one partition. Partitions are searched in the order of their
first invocation.

The search of a partition is Wing and Gong's, with a memo of the
configurations it has reached. Its entries are the invocations of the
partition's calls and the completions of its ok calls, in event order. A
call whose outcome is unknown, and a pending call, has no completion
entry: it takes effect at some point after its invocation, or never. The
candidates at each point are the calls whose invocations come before the
first completion of a call not yet linearized, in event order, and an
accepted call restarts the scan from the first entry. The search passes
when every ok call is linearized.

A configuration is a set of linearized calls and the list of states they
leave, with no two equal states in the list. Two configurations are the
same when their sets are equal and their lists contain the same states in
any order. The search stops as undecided before a step that would take
it past the budget, and before it stores a configuration that would take
the memo past its limit, which counts one bit per call of the partition
for each configuration.

The frontier of a search is its first configuration, in search order,
with the most linearized calls. The record of a violated check states the
frontier's order, its states and the candidates that the model rejected
in every one of them, which are all its candidates. An undecided check
states the candidates that the model had rejected there when the search
stopped.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, final

from prop.literal import encode
from prop.value import canonical

from .model import Model, Op
from .seam import Event, Kind

#: The steps one partition's search may spend unless a check states another.
BUDGET: Final = 10_000_000

#: The bits one partition's memo may count for its sets of calls, 1 GiB.
MEMO_LIMIT: Final = 1 << 33

#: The fields of a record's detail that describe the reported partition.
_REPORTED: Final = (
    "partition",
    "calls",
    "concurrency",
    "linearized",
    "states",
    "candidates",
    "limit",
)


class Outcome(StrEnum):
    """How a check ended."""

    PASSED = "passed"
    VIOLATED = "violated"
    UNDECIDED = "undecided"


class Limit(StrEnum):
    """The limit that stopped an undecided search."""

    STEPS = "steps"
    MEMO = "memo"


@dataclass(frozen=True)
class Call:
    """A call as the checker reads it.

    index is the index of its invocation event, and completion the index of
    its completion event, or None for a pending call. op is the call as the
    model sees it.
    """

    index: int
    completion: int | None
    process: int
    op: Op
    keys: tuple[object, ...]

    def document(self) -> dict[str, Any]:
        """Return the call as a record states it, in the history's JSON form.

        A pending call states no completion, and a call whose outcome is
        unknown states no output.
        """
        form: dict[str, Any] = {"call": self.index}
        if self.completion is not None:
            form["completion"] = self.completion
        form["process"] = self.process
        form["operation"] = self.op.operation
        form["args"] = [encode(arg) for arg in self.op.args]
        if self.op.known:
            form["output"] = encode(self.op.output)
        return form


@dataclass(frozen=True)
class Verdict:
    """The outcome of a check, and for a failure the detail of its record.

    steps counts the partitions up to and including the reported one, and
    every partition of a check that passed. The other fields describe the
    reported partition, and are empty for a check that passed.
    """

    outcome: Outcome
    partitions: int
    steps: int
    partition: tuple[object, ...] = ()
    calls: int = 0
    concurrency: int = 0
    linearized: tuple[Call, ...] = ()
    states: tuple[object, ...] = ()
    candidates: tuple[Call, ...] = ()
    limit: Limit | None = None

    def detail(self) -> dict[str, Any]:
        """Return the detail of the record, with values as typed literals.

        A check that passed reports no record. Its detail states the outcome,
        the partitions and the steps, and null for each field that describes
        a reported partition.
        """
        if self.outcome is Outcome.PASSED:
            return {
                "outcome": self.outcome.value,
                "partitions": self.partitions,
                "steps": self.steps,
                **dict.fromkeys(_REPORTED),
            }
        return {
            "outcome": self.outcome.value,
            "partitions": self.partitions,
            "steps": self.steps,
            "partition": [encode(key) for key in self.partition],
            "calls": self.calls,
            "concurrency": self.concurrency,
            "linearized": [call.document() for call in self.linearized],
            "states": [encode(state) for state in self.states],
            "candidates": [call.document() for call in self.candidates],
            "limit": None if self.limit is None else self.limit.value,
        }


def check(
    events: Sequence[Event],
    model: Model,
    budget: int = BUDGET,
    memo_limit: int = MEMO_LIMIT,
) -> Verdict:
    """Return whether a history is linearizable with respect to a model.

    The check reports the first violated partition. When no partition is
    violated, it reports the first undecided one, or passes.
    """
    partitions = _partitions(_calls(events))
    steps = 0
    undecided: Verdict | None = None
    for keys, calls in partitions:
        ending = _Search(calls, model, budget, memo_limit).run()
        steps += ending.steps
        if ending.outcome is Outcome.PASSED:
            continue
        verdict = Verdict(
            ending.outcome,
            len(partitions),
            steps,
            keys,
            len(calls),
            concurrency(calls),
            ending.linearized,
            ending.states,
            ending.candidates,
            ending.limit,
        )
        if ending.outcome is Outcome.VIOLATED:
            return verdict
        undecided = undecided or verdict
    return undecided or Verdict(Outcome.PASSED, len(partitions), steps)


def concurrency(calls: Sequence[Call]) -> int:
    """Return the most calls that are open at one event.

    A call is open from its invocation to its completion. A call whose
    outcome is unknown, and a pending call, is open to the end of the
    history.
    """
    changes = sorted(
        [(call.index, 1) for call in calls]
        + [
            (call.completion, -1)
            for call in calls
            if call.op.known and call.completion is not None
        ]
    )
    return max(itertools.accumulate(change for _, change in changes), default=0)


def _calls(events: Sequence[Event]) -> list[Call]:
    """Return the calls of a history in event order, without the calls that failed."""
    completions = {
        event.call: event for event in events if event.kind is not Kind.INVOKE
    }
    calls: list[Call] = []
    for invocation in events:
        if invocation.kind is not Kind.INVOKE:
            continue
        completion = completions.get(invocation.index)
        if completion is not None and completion.kind is Kind.FAIL:
            continue
        known = completion is not None and completion.kind is Kind.OK
        output = completion.output if completion is not None and known else None
        calls.append(
            Call(
                invocation.index,
                None if completion is None else completion.index,
                invocation.process,
                Op(invocation.operation, invocation.args, known, output),
                invocation.keys,
            )
        )
    return calls


def _partitions(
    calls: Sequence[Call],
) -> list[tuple[tuple[object, ...], list[Call]]]:
    """Return each partition's keys and calls, in the order of its first invocation.

    A partition lists its keys in the order the history first declares
    them, and lists no key when one of its calls touches every key.
    """
    if not calls:
        return []
    if any(not call.keys for call in calls):
        return [((), list(calls))]
    parent = list(range(len(calls)))
    first: dict[object, int] = {}
    for position, call in enumerate(calls):
        for name in call.keys:
            other = first.setdefault(canonical(name), position)
            parent[_root(parent, position)] = _root(parent, other)
    groups: dict[int, list[Call]] = {}
    for position, call in enumerate(calls):
        groups.setdefault(_root(parent, position), []).append(call)
    return [(_keys(group), group) for group in groups.values()]


def _root(parent: list[int], position: int) -> int:
    """Return the representative of a call's partition, halving the path to it."""
    while parent[position] != position:
        parent[position] = parent[parent[position]]
        position = parent[position]
    return position


def _keys(calls: Sequence[Call]) -> tuple[object, ...]:
    """Return the keys that calls declare, each once, in the order first declared."""
    seen: dict[object, object] = {}
    for call in calls:
        for name in call.keys:
            seen.setdefault(canonical(name), name)
    return tuple(seen.values())


@dataclass(frozen=True)
class _Ending:
    """How one partition's search ended, and its frontier."""

    outcome: Outcome
    steps: int
    linearized: tuple[Call, ...] = ()
    states: tuple[object, ...] = ()
    candidates: tuple[Call, ...] = ()
    limit: Limit | None = None


@final
class _Stopped(Exception):
    """A limit stopped the search."""

    def __init__(self, limit: Limit) -> None:
        """Name the limit."""
        super().__init__(limit.value)
        self.limit = limit


@final
class _Search:
    """The search of one partition.

    The entries are a doubly linked list between a head and a tail, so that
    the search lifts a linearized call's entries out of the scan and puts
    them back in constant time.
    """

    def __init__(
        self, calls: Sequence[Call], model: Model, budget: int, memo_limit: int
    ) -> None:
        """Lay out the entries of calls in event order, before the first step."""
        self._calls = calls
        self._model = model
        self._budget = budget
        self._memo_limit = memo_limit
        entries = sorted(
            [(call.index, position, True) for position, call in enumerate(calls)]
            + [
                (call.completion, position, False)
                for position, call in enumerate(calls)
                if call.op.known and call.completion is not None
            ]
        )
        self._head = len(entries)
        chain = [self._head, *range(len(entries)), self._head + 1]
        self._next = [0] * len(chain)
        self._prev = [0] * len(chain)
        for before, after in itertools.pairwise(chain):
            self._next[before] = after
            self._prev[after] = before
        self._position = [position for _, position, _ in entries]
        self._invokes = [invokes for _, _, invokes in entries]
        self._invocation = [0] * len(calls)
        self._completion: list[int | None] = [None] * len(calls)
        for entry, (_, position, invokes) in enumerate(entries):
            if invokes:
                self._invocation[position] = entry
            else:
                self._completion[position] = entry
        self._open = sum(1 for call in calls if call.op.known)
        self._steps = 0
        self._done = 0
        self._states: list[object] = [model.init()]
        self._stack: list[tuple[int, list[object]]] = []
        self._memo: dict[tuple[int, frozenset[object]], list[list[object]]] = {}
        self._configurations = 0
        self._linearized: tuple[Call, ...] = ()
        self._frontier: list[object] = self._states
        self._candidates: list[Call] = []
        self._at_frontier = True

    def run(self) -> _Ending:
        """Search the partition, and return how the search ended."""
        try:
            outcome = self._search()
        except _Stopped as stopped:
            return self._ending(Outcome.UNDECIDED, stopped.limit)
        if outcome is Outcome.PASSED:
            return _Ending(outcome, self._steps)
        return self._ending(outcome, None)

    def _ending(self, outcome: Outcome, limit: Limit | None) -> _Ending:
        """Return an ending that states the frontier."""
        return _Ending(
            outcome,
            self._steps,
            self._linearized,
            tuple(self._frontier),
            tuple(self._candidates),
            limit,
        )

    def _search(self) -> Outcome:
        """Scan the entries until every ok call is linearized or none can be.

        Raises:
            _Stopped: a limit stopped the search.
        """
        entry = self._next[self._head]
        while self._open:
            if not self._invokes[entry]:
                if not self._stack:
                    return Outcome.VIOLATED
                entry = self._backtrack()
            elif self._linearize(self._position[entry]):
                entry = self._next[self._head]
            else:
                entry = self._next[entry]
        return Outcome.PASSED

    def _linearize(self, position: int) -> bool:
        """Linearize a candidate when the model accepts it in a new configuration.

        Raises:
            _Stopped: a limit stopped the search.
        """
        call = self._calls[position]
        following = self._step(call.op)
        if not following:
            if self._at_frontier:
                self._candidates.append(call)
            return False
        done = self._done | (1 << position)
        if not self._remember(done, following):
            return False
        self._stack.append((position, self._states))
        self._done, self._states = done, following
        self._lift(position)
        self._at_frontier = len(self._stack) > len(self._linearized)
        if self._at_frontier:
            self._linearized = tuple(self._calls[p] for p, _ in self._stack)
            self._frontier = following
            self._candidates = []
        return True

    def _step(self, op: Op) -> list[object]:
        """Return the states that op leaves from the current ones, without repeats.

        Raises:
            _Stopped: a step would take the search past its budget.
        """
        model = self._model
        following: list[object] = []
        for state in self._states:
            cost = model.cost(state)
            if self._steps + cost > self._budget:
                raise _Stopped(Limit.STEPS)
            self._steps += cost
            for after in model.step(state, op):
                if not any(model.equal(after, kept) for kept in following):
                    following.append(after)
        return following

    def _remember(self, done: int, states: list[object]) -> bool:
        """Store a configuration, and report whether the memo lacked it.

        Raises:
            _Stopped: the configuration would take the memo past its limit.
        """
        model = self._model
        bucket = self._memo.setdefault(
            (done, frozenset(model.key(state) for state in states)), []
        )
        for seen in bucket:
            if len(seen) == len(states) and all(
                any(model.equal(state, other) for other in seen) for state in states
            ):
                return False
        if (self._configurations + 1) * len(self._calls) > self._memo_limit:
            raise _Stopped(Limit.MEMO)
        bucket.append(states)
        self._configurations += 1
        return True

    def _backtrack(self) -> int:
        """Undo the last linearized call, and return the entry after its invocation."""
        position, self._states = self._stack.pop()
        self._done &= ~(1 << position)
        self._unlift(position)
        self._at_frontier = False
        return self._next[self._invocation[position]]

    def _lift(self, position: int) -> None:
        """Take a call's entries out of the scan."""
        self._unlink(self._invocation[position])
        completion = self._completion[position]
        if completion is not None:
            self._unlink(completion)
            self._open -= 1

    def _unlift(self, position: int) -> None:
        """Put a call's entries back, in the reverse order of _lift."""
        completion = self._completion[position]
        if completion is not None:
            self._relink(completion)
            self._open += 1
        self._relink(self._invocation[position])

    def _unlink(self, entry: int) -> None:
        """Take one entry out of the list."""
        self._next[self._prev[entry]] = self._next[entry]
        self._prev[self._next[entry]] = self._prev[entry]

    def _relink(self, entry: int) -> None:
        """Put back an entry that _unlink took out, between its old neighbours."""
        self._next[self._prev[entry]] = entry
        self._prev[self._next[entry]] = entry
