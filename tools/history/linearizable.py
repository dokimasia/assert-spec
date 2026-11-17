# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

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
leave, with no two equal states in the list. The search skips a
configuration that the memo covers: a configuration in the memo whose list
contains the same states in any order, whose set has the same calls with a
completion entry, and whose other calls are among the configuration's. A
call without a completion entry, whose outcome is unknown or which is
pending, need not take effect. Every order that follows the configuration
then also follows the configuration in the memo. The search stops as
undecided before a step that would take it past the budget, and before it
stores a configuration that would take the memo past its limit, which
counts one bit per call of the partition for each configuration.

The frontier of a search is its first configuration, in search order,
with the most linearized calls. The record of a violated check states the
frontier's order, its states and the candidates that the model rejected
in every one of them, which are all its candidates. An undecided check
states the candidates that the model had rejected there when the search
stopped.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, final

from prop.literal import encode
from prop.value import canonical

from .model import Model, Op
from .seam import Event, Kind

if TYPE_CHECKING:
    from collections.abc import Sequence

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


@final
class Checkpoint:
    """The searches of the last check of a history that passed with it.

    A check with a checkpoint continues the search of each kept partition
    over the calls that the history recorded since, and keeps its own
    searches in the checkpoint when it passes. A check that does not pass
    leaves the checkpoint without a search. A continued search takes the
    steps that a search of every call takes after the order that the kept
    search found, so the check returns what a check of every call returns.
    """

    def __init__(self) -> None:
        """Return a checkpoint that does not keep a search."""
        self._kept: _Kept | None = None

    def searches(
        self, events: Sequence[Event], budget: int, memo_limit: int
    ) -> dict[int, _Search]:
        """Return the kept search of each call, by the index of its invocation.

        The searches continue only for the same history under the same
        limits: the events that the kept check read must be the first events
        of the history, and the budget and the memo limit must be the same.
        """
        kept = self._kept
        if (
            kept is None
            or (kept.budget, kept.memo_limit) != (budget, memo_limit)
            or tuple(events[: len(kept.events)]) != kept.events
        ):
            return {}
        return {call.index: search for search in kept.searches for call in search.calls}

    def keep(self, kept: _Kept | None) -> None:
        """Keep the searches of a check that passed, or none after another check."""
        self._kept = kept


@dataclass(frozen=True)
class _Kept:
    """The searches of a check that passed, and the history and limits they need."""

    events: tuple[Event, ...]
    budget: int
    memo_limit: int
    searches: tuple[_Search, ...]


def check(
    events: Sequence[Event],
    model: Model[Any],
    budget: int = BUDGET,
    memo_limit: int = MEMO_LIMIT,
    checkpoint: Checkpoint | None = None,
) -> Verdict:
    """Return whether a history is linearizable with respect to a model.

    The check reports the first violated partition. When no partition is
    violated, it reports the first undecided one, or passes. With a
    checkpoint, the check continues the searches that the checkpoint keeps,
    and keeps its own searches there when it passes.
    """
    partitions = _partitions(_calls(events))
    kept = {} if checkpoint is None else checkpoint.searches(events, budget, memo_limit)
    steps = 0
    undecided: Verdict | None = None
    violated: Verdict | None = None
    searches: list[_Search] = []
    for keys, calls in partitions:
        search = _continued(kept, calls, model, memo_limit) or _Search(
            calls, model, budget, memo_limit
        )
        searches.append(search)
        ending = search.run()
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
            violated = verdict
            break
        undecided = undecided or verdict
    outcome = violated or undecided or Verdict(Outcome.PASSED, len(partitions), steps)
    if checkpoint is not None:
        searched = _Kept(tuple(events), budget, memo_limit, tuple(searches))
        checkpoint.keep(searched if outcome.outcome is Outcome.PASSED else None)
    return outcome


def _continued(
    kept: dict[int, _Search],
    calls: Sequence[Call],
    model: Model[Any],
    memo_limit: int,
) -> _Search | None:
    """Return the kept search of a partition grown by its new calls, or None.

    A kept search continues when its calls, unchanged, are the first calls
    of the partition and every later call of the partition is new. A
    completion of a call that the kept search read as pending changes the
    call, and a call of another kept search joins two partitions, so either
    makes the partition search again from its first call. So does a memo
    that contains more configurations than the grown partition may store.
    """
    olds = [call for call in calls if call.index in kept]
    if not olds:
        return None
    search = kept[olds[0].index]
    count = len(search.calls)
    if (
        tuple(calls[:count]) != search.calls
        or len(olds) != count
        or search.configurations * len(calls) > memo_limit
    ):
        return None
    search.grow(calls[count:], model)
    return search


def whole(
    events: Sequence[Event],
    model: Model[Any],
    budget: int = BUDGET,
    memo_limit: int = MEMO_LIMIT,
) -> tuple[Verdict, tuple[object, ...]]:
    """Check a history as one partition, whatever keys its calls declare.

    A machine checks its case's history this way, because its model is one
    state of the whole subject. The result is the verdict, and for a pass
    the states after the order the search found: the initial state for a
    history without calls.
    """
    calls = _calls(events)
    if not calls:
        return Verdict(Outcome.PASSED, 0, 0), (model.init(),)
    ending = _Search(calls, model, budget, memo_limit).run()
    if ending.outcome is Outcome.PASSED:
        return Verdict(Outcome.PASSED, 1, ending.steps), ending.states
    verdict = Verdict(
        ending.outcome,
        1,
        ending.steps,
        (),
        len(calls),
        concurrency(calls),
        ending.linearized,
        ending.states,
        ending.candidates,
        ending.limit,
    )
    return verdict, ()


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
    them back in constant time. The head and the tail are the entries 0 and
    1, so a search that grows appends entries without moving any.
    """

    _HEAD: Final = 0
    _TAIL: Final = 1

    def __init__(
        self, calls: Sequence[Call], model: Model[Any], budget: int, memo_limit: int
    ) -> None:
        """Lay out the entries of calls in event order, before the first step."""
        self._calls: list[Call] = []
        self._model = model
        self._budget = budget
        self._memo_limit = memo_limit
        self._head = self._HEAD
        self._next = [self._TAIL, self._TAIL]
        self._prev = [self._HEAD, self._HEAD]
        self._position = [-1, -1]
        self._invokes = [False, False]
        self._invocation: list[int] = []
        self._completion: list[int | None] = []
        self._open = 0
        self._optional = 0
        self._steps = 0
        self._done = 0
        self._states: list[object] = [model.init()]
        self._stack: list[tuple[int, list[object]]] = []
        self._memo: dict[
            tuple[int, frozenset[object]], list[tuple[int, list[object]]]
        ] = {}
        self._configurations = 0
        self._linearized: tuple[Call, ...] = ()
        self._frontier: list[object] = self._states
        self._candidates: list[Call] = []
        self._at_frontier = True
        self.grow(calls, model)

    @property
    def calls(self) -> tuple[Call, ...]:
        """Return the calls of the search, in event order."""
        return tuple(self._calls)

    @property
    def configurations(self) -> int:
        """Return the number of configurations that the memo stores."""
        return self._configurations

    def grow(self, calls: Sequence[Call], model: Model[Any]) -> None:
        """Add calls whose entries follow every entry of the search.

        The new entries go between the last entry and the tail, in event
        order. An entry that the search took out while the tail followed it
        then points at the first new entry, so that a backtrack puts it back
        before the new entries, as a search of every call does. model is the
        model of the check that grows the search, and it takes the steps
        from here on.
        """
        self._model = model
        start = len(self._calls)
        entries = sorted(
            [(call.index, start + offset, True) for offset, call in enumerate(calls)]
            + [
                (call.completion, start + offset, False)
                for offset, call in enumerate(calls)
                if call.op.known and call.completion is not None
            ]
        )
        if not entries:
            return
        first = len(self._next)
        for entry in range(self._TAIL + 1, first):
            if self._next[entry] == self._TAIL:
                self._next[entry] = first
        last = self._prev[self._TAIL]
        self._next[last] = first
        for offset, (_, position, invokes) in enumerate(entries):
            entry = first + offset
            self._prev.append(entry - 1 if offset else last)
            self._next.append(entry + 1)
            self._position.append(position)
            self._invokes.append(invokes)
        self._next[-1] = self._TAIL
        self._prev[self._TAIL] = len(self._next) - 1
        self._calls.extend(calls)
        self._invocation.extend([0] * len(calls))
        self._completion.extend([None] * len(calls))
        for offset, (_, position, invokes) in enumerate(entries):
            if invokes:
                self._invocation[position] = first + offset
            else:
                self._completion[position] = first + offset
        for offset, call in enumerate(calls):
            if call.op.known and call.completion is not None:
                self._open += 1
            else:
                self._optional |= 1 << (start + offset)

    def run(self) -> _Ending:
        """Search the partition, and return how the search ended.

        A search that passed states the states after the order it found.
        """
        try:
            outcome = self._search()
        except _Stopped as stopped:
            return self._ending(Outcome.UNDECIDED, stopped.limit)
        if outcome is Outcome.PASSED:
            return _Ending(outcome, self._steps, states=tuple(self._states))
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
        """Store a configuration, and report whether the memo did not cover it.

        A configuration in the memo covers this one when the two have the
        same states and the same calls with a completion entry, and its calls
        without one are among this configuration's.

        Raises:
            _Stopped: the configuration would take the memo past its limit.
        """
        model = self._model
        optional = done & self._optional
        bucket = self._memo.setdefault(
            (done & ~self._optional, frozenset(model.key(state) for state in states)),
            [],
        )
        for taken, seen in bucket:
            if (
                taken & ~optional == 0
                and len(seen) == len(states)
                and all(
                    any(model.equal(state, other) for other in seen) for state in states
                )
            ):
                return False
        if (self._configurations + 1) * len(self._calls) > self._memo_limit:
            raise _Stopped(Limit.MEMO)
        bucket.append((optional, states))
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
