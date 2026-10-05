"""Decide whether a history of list-append transactions exhibits an isolation anomaly.

A transaction is one call whose operation is ``txn``. Its arguments are its
micro-operations in the order it ran them: ``["append", key, value]`` and
``["read", key, None]``. An ok completion commits the transaction, and its
output repeats the micro-operations with each read's list filled in, or null
for an empty list. A fail completion aborts it. A transaction whose
completion is unknown, or missing, counts as committed when a committed read
observed one of its appends, and is left out otherwise. Every value is
appended to its key once, so a value names the append that produced it.

check() first reads the micro-operations for the six anomalies that need no
dependency graph. It then takes each key's version order from its longest
committed read, places every committed append that no read observed after
that order, derives the write-write, write-read and read-write dependencies
between committed transactions, and searches the graph for the five kinds of
cycle. A level forbids a set of the eleven kinds, and the record reports the
first of them that the history exhibits.
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, final

from prop.literal import encode
from prop.value import canonical

from .seam import Event, Kind

#: The operation of a transaction's call.
TXN: Final = "txn"

#: The function of a micro-operation that appends a value to a key.
APPEND: Final = "append"

#: The function of a micro-operation that reads a key's list.
READ: Final = "read"

#: The functions a micro-operation may state.
_FUNCTIONS: Final = frozenset({APPEND, READ})

#: A micro-operation states its function, its key and its value.
_FIELDS: Final = 3


class Anomaly(StrEnum):
    """A kind of anomaly, in the order in which a record reports them."""

    GARBAGE_READ = "garbage-read"
    DUPLICATE_APPEND = "duplicate-append"
    INTERNAL_INCONSISTENCY = "internal-inconsistency"
    INCOMPATIBLE_ORDER = "incompatible-order"
    ABORTED_READ = "aborted-read"
    INTERMEDIATE_READ = "intermediate-read"
    G0 = "G0"
    G1C = "G1c"
    G_SINGLE = "G-single"
    G_NONADJACENT = "G-nonadjacent"
    G2 = "G2"


class Level(StrEnum):
    """An isolation level, which the assertion of the same name checks."""

    SERIALIZABLE = "serializable"
    SNAPSHOT_ISOLATION = "snapshot-isolation"


#: The kinds each level forbids. Snapshot isolation permits a cycle in which
#: two read-write dependencies are adjacent, such as write skew: a dependency
#: graph satisfies it exactly when every cycle has two adjacent read-write
#: dependencies.
FORBIDS: Final[dict[Level, tuple[Anomaly, ...]]] = {
    Level.SERIALIZABLE: tuple(Anomaly),
    Level.SNAPSHOT_ISOLATION: tuple(a for a in Anomaly if a is not Anomaly.G2),
}


class Relation(StrEnum):
    """A dependency of one committed transaction on another."""

    WW = "ww"
    WR = "wr"
    RW = "rw"


#: The relations in the order in which a cycle's entry lists them.
_RELATIONS: Final = tuple(Relation)

#: The relations other than a read-write dependency.
_NON_RW: Final = frozenset({Relation.WW, Relation.WR})

#: A state of the G-nonadjacent search: a transaction, whether the walk
#: entered it by a read-write edge, and whether the walk has taken one.
_State = tuple[int, bool, bool]

#: The fewest read-write edges of a G-nonadjacent cycle. A cycle with one is
#: G-single.
_NONADJACENT_RW: Final = 2


@dataclass(frozen=True)
class _Search:
    """How the search finds one kind of cycle.

    It takes the components of the graph over the component relations. In
    each, it tries the edges of the closing relation in the order of their
    sources and then their targets. An edge closes a cycle when a path over
    the path relations leads from its target back to its source.
    """

    component: frozenset[Relation]
    closing: Relation
    path: frozenset[Relation]


#: The search of each kind of cycle.
_SEARCHES: Final[dict[Anomaly, _Search]] = {
    Anomaly.G0: _Search(
        frozenset({Relation.WW}), Relation.WW, frozenset({Relation.WW})
    ),
    Anomaly.G1C: _Search(
        frozenset({Relation.WW, Relation.WR}),
        Relation.WR,
        frozenset({Relation.WW, Relation.WR}),
    ),
    Anomaly.G_SINGLE: _Search(
        frozenset(Relation), Relation.RW, frozenset({Relation.WW, Relation.WR})
    ),
    Anomaly.G2: _Search(frozenset(Relation), Relation.RW, frozenset(Relation)),
}


class TransactionError(ValueError):
    """A history that is no history of list-append transactions."""


@dataclass(frozen=True)
class Mop:
    """One micro-operation of a transaction.

    value is the appended value of an append. For a read, it is the list that
    the read returned, or None for a read whose transaction did not commit.
    """

    function: str
    key: object
    value: object


@dataclass(frozen=True)
class Transaction:
    """One call of a history, read as a transaction.

    call is the index of its invocation event, and completion the index of
    its completion event. kind is its completion's kind. Both are None for a
    pending transaction. mops come from the output of an ok transaction, with
    each read's list, and from the invocation otherwise.
    """

    call: int
    completion: int | None
    kind: Kind | None
    process: int
    args: tuple[object, ...]
    output: object
    mops: tuple[Mop, ...]

    def document(self) -> dict[str, Any]:
        """Return the transaction as a record states it, in the history's JSON form.

        A pending transaction states no completion and no kind, and only an
        ok transaction states an output.
        """
        form: dict[str, Any] = {"call": self.call}
        if self.completion is not None and self.kind is not None:
            form["completion"] = self.completion
            form["kind"] = self.kind.value
        form["process"] = self.process
        form["args"] = [encode(arg) for arg in self.args]
        if self.kind is Kind.OK:
            form["output"] = encode(self.output)
        return form


def transactions(events: Sequence[Event]) -> list[Transaction]:
    """Return a history's transactions in the order of their invocations.

    Raises:
        TransactionError: a call is no list-append transaction, an ok output
            does not repeat its invocation's micro-operations, or a value is
            appended to one key twice.
    """
    completions = {e.call: e for e in events if e.kind is not Kind.INVOKE}
    appended: dict[tuple[object, object], int] = {}
    out: list[Transaction] = []
    for invocation in events:
        if invocation.kind is Kind.INVOKE:
            txn = _transaction(invocation, completions.get(invocation.index))
            _register(txn, appended)
            out.append(txn)
    return out


def _transaction(invocation: Event, completion: Event | None) -> Transaction:
    """Return the transaction of one call.

    Raises:
        TransactionError: the call is no list-append transaction, or its ok
            output does not repeat its micro-operations.
    """
    call = invocation.index
    if invocation.operation != TXN:
        raise TransactionError(
            f"history: call {call} is {invocation.operation!r}, not {TXN!r}"
        )
    mops = tuple(
        _invoked(call, position, arg) for position, arg in enumerate(invocation.args)
    )
    if completion is None:
        return Transaction(
            call, None, None, invocation.process, invocation.args, None, mops
        )
    if completion.kind is Kind.OK:
        mops = _returned(call, mops, completion.output)
    return Transaction(
        call,
        completion.index,
        completion.kind,
        invocation.process,
        invocation.args,
        completion.output,
        mops,
    )


def _invoked(call: int, position: int, raw: object) -> Mop:
    """Return the micro-operation that one argument of an invocation states.

    Raises:
        TransactionError: the argument is no micro-operation, or a read states
            a list before it ran.
    """
    if not isinstance(raw, list) or len(raw) != _FIELDS or raw[0] not in _FUNCTIONS:
        raise TransactionError(
            f"history: argument {position} of call {call} is {raw!r}, not "
            "[append, key, value] or [read, key, null]"
        )
    function, key, value = raw
    if function == READ and value is not None:
        raise TransactionError(
            f"history: the read at argument {position} of call {call} states "
            "a list before it ran"
        )
    return Mop(str(function), key, value)


def _returned(call: int, invoked: tuple[Mop, ...], output: object) -> tuple[Mop, ...]:
    """Return the micro-operations of an ok output, which repeat invoked with lists.

    Raises:
        TransactionError: the output does not repeat invoked.
    """
    if not isinstance(output, list) or len(output) != len(invoked):
        raise TransactionError(
            f"history: the output of call {call} does not repeat its "
            f"{len(invoked)} micro-operations"
        )
    return tuple(
        _repeated(call, position, mop, raw)
        for position, (mop, raw) in enumerate(zip(invoked, output, strict=True))
    )


def _repeated(call: int, position: int, mop: Mop, raw: object) -> Mop:
    """Return one micro-operation of an ok output.

    A read that returned null returned the empty list.

    Raises:
        TransactionError: raw does not repeat mop, or a read returned no list.
    """
    if not (
        isinstance(raw, list)
        and len(raw) == _FIELDS
        and raw[0] == mop.function
        and canonical(raw[1]) == canonical(mop.key)
        and (mop.function == READ or canonical(raw[2]) == canonical(mop.value))
    ):
        stated = [mop.function, mop.key, mop.value]
        raise TransactionError(
            f"history: micro-operation {position} of the output of call {call} "
            f"is {raw!r}, which does not repeat {stated!r}"
        )
    value = raw[2]
    if mop.function == APPEND:
        return mop
    if value is None:
        return Mop(READ, mop.key, [])
    if not isinstance(value, list):
        raise TransactionError(
            f"history: the read at micro-operation {position} of the output of "
            f"call {call} returned {value!r}, not a list"
        )
    return Mop(READ, mop.key, value)


def _register(txn: Transaction, appended: dict[tuple[object, object], int]) -> None:
    """Record each value that txn appends, under its key.

    Raises:
        TransactionError: a value is appended to its key a second time.
    """
    for mop in txn.mops:
        if mop.function != APPEND:
            continue
        name = (canonical(mop.key), canonical(mop.value))
        first = appended.get(name)
        if first == txn.call:
            raise TransactionError(
                f"history: call {txn.call} appends {mop.value!r} to the key "
                f"{mop.key!r} twice"
            )
        if first is not None:
            raise TransactionError(
                f"history: calls {first} and {txn.call} both append {mop.value!r} "
                f"to the key {mop.key!r}"
            )
        appended[name] = txn.call


@dataclass(frozen=True)
class Case:
    """One instance of an anomaly.

    calls are the transactions it involves, in the order the record lists
    them. cycle lists each transaction of a cycle with the relations of the
    edge to the next, and is None for an anomaly that is no cycle.
    explanation is the evidence: one entry per edge of a cycle, and one entry
    for any other anomaly.
    """

    anomaly: Anomaly
    calls: tuple[int, ...]
    cycle: tuple[dict[str, Any], ...] | None
    explanation: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Verdict:
    """The outcome of a check, and for a failure the detail of its record.

    kinds lists every kind that the level forbids and the history exhibits,
    in report order. case is the first instance of the first of them, and
    None for a check that passed.
    """

    level: Level
    kinds: tuple[Anomaly, ...]
    case: Case | None
    transactions: Mapping[int, Transaction]

    @property
    def passed(self) -> bool:
        """Report whether the history exhibits no anomaly that the level forbids."""
        return self.case is None

    def detail(self) -> dict[str, Any]:
        """Return the detail of the record, with keys and values as typed literals.

        A check that passed reports no record. Its detail states no anomaly,
        no kinds, and null for every other field.
        """
        if self.case is None:
            return {
                "anomaly": None,
                "kinds": [],
                "transactions": None,
                "cycle": None,
                "explanation": None,
            }
        return {
            "anomaly": self.case.anomaly.value,
            "kinds": [kind.value for kind in self.kinds],
            "transactions": [
                self.transactions[call].document() for call in self.case.calls
            ],
            "cycle": None if self.case.cycle is None else list(self.case.cycle),
            "explanation": list(self.case.explanation),
        }


def check(events: Sequence[Event], level: Level) -> Verdict:
    """Return whether a list-append history exhibits an anomaly that level forbids.

    Raises:
        TransactionError: the history is no history of list-append transactions.
    """
    txns = transactions(events)
    analysis = Analysis(txns)
    found = [
        (kind, case)
        for kind in FORBIDS[level]
        if (case := analysis.case(kind)) is not None
    ]
    return Verdict(
        level,
        tuple(kind for kind, _ in found),
        found[0][1] if found else None,
        {txn.call: txn for txn in txns},
    )


def _name(key: object, value: object) -> tuple[object, object]:
    """Return the identity of an append: its key and its value, compared exactly."""
    return (canonical(key), canonical(value))


def _read_case(
    anomaly: Anomaly, call: int, key: object, read: list[object], value: object
) -> Case:
    """Return the case of an anomaly that one read of call shows by one value."""
    evidence = {
        "call": call,
        "key": encode(key),
        "read": encode(read),
        "value": encode(value),
    }
    return Case(anomaly, (call,), None, (evidence,))


@final
class Analysis:
    """The derivation over one history's transactions.

    The committed transactions are the ok ones, and the ones whose outcome
    is unknown and whose append a committed read observed. A key's version
    order is its longest committed read, and a key whose committed reads are
    not prefixes of one list has no version order. Every committed read is a
    prefix of the key's final list, so a committed append that no committed
    read observed follows the last value of the version order.
    """

    def __init__(self, txns: Sequence[Transaction]) -> None:
        """Index the appends and the committed reads of txns."""
        self._txns = txns
        self._appender: dict[tuple[object, object], int] = {}
        self._appends: dict[object, list[tuple[int, object]]] = {}
        self._later: dict[tuple[object, object], tuple[object]] = {}
        self._keys: dict[object, object] = {}
        for txn in txns:
            self._index(txn)
        self._aborted = {txn.call for txn in txns if txn.kind is Kind.FAIL}
        self._reads: list[tuple[int, object, list[object]]] = [
            (txn.call, mop.key, mop.value)
            for txn in txns
            if txn.kind is Kind.OK
            for mop in txn.mops
            if mop.function == READ and isinstance(mop.value, list)
        ]
        observed = {_name(key, v) for _, key, read in self._reads for v in read}
        undecided = {txn.call for txn in txns if txn.kind in {Kind.UNKNOWN, None}}
        self._committed = {txn.call for txn in txns if txn.kind is Kind.OK} | {
            self._appender[name]
            for name in observed
            if self._appender.get(name) in undecided
        }
        self._incompatible: Case | None = None
        self._orders = self._version_orders()
        self._edges: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self._derive()

    def _index(self, txn: Transaction) -> None:
        """Index the keys txn touches, and the appends it makes."""
        last: dict[object, tuple[object, object]] = {}
        for mop in txn.mops:
            key = canonical(mop.key)
            self._keys.setdefault(key, mop.key)
            if mop.function != APPEND:
                continue
            name = (key, canonical(mop.value))
            self._appender[name] = txn.call
            self._appends.setdefault(key, []).append((txn.call, mop.value))
            if key in last:
                self._later[last[key]] = (mop.value,)
            last[key] = name

    def case(self, anomaly: Anomaly) -> Case | None:
        """Return the first instance of an anomaly in the history, or None."""
        direct: dict[Anomaly, Callable[[], Case | None]] = {
            Anomaly.GARBAGE_READ: self._garbage_read,
            Anomaly.DUPLICATE_APPEND: self._duplicate_append,
            Anomaly.INTERNAL_INCONSISTENCY: self._internal_inconsistency,
            Anomaly.INCOMPATIBLE_ORDER: lambda: self._incompatible,
            Anomaly.ABORTED_READ: self._aborted_read,
            Anomaly.INTERMEDIATE_READ: self._intermediate_read,
        }
        finder = direct.get(anomaly)
        if finder is not None:
            return finder()
        if anomaly is Anomaly.G_NONADJACENT:
            return self._nonadjacent()
        return self._cycle(anomaly)

    def _garbage_read(self) -> Case | None:
        """Return the first committed read of a value that no transaction appended."""
        for call, key, read in self._reads:
            for value in read:
                if _name(key, value) not in self._appender:
                    return _read_case(Anomaly.GARBAGE_READ, call, key, read, value)
        return None

    def _duplicate_append(self) -> Case | None:
        """Return the first committed read that returned one value twice."""
        for call, key, read in self._reads:
            seen: set[object] = set()
            for value in read:
                identity = canonical(value)
                if identity in seen:
                    return _read_case(Anomaly.DUPLICATE_APPEND, call, key, read, value)
                seen.add(identity)
        return None

    def _internal_inconsistency(self) -> Case | None:
        """Return the first committed read that contradicts its own transaction."""
        for txn in self._txns:
            if txn.kind is Kind.OK and (case := _internal(txn)) is not None:
                return case
        return None

    def _aborted_read(self) -> Case | None:
        """Return the first committed read of a value that an aborted call appended."""
        for call, key, read in self._reads:
            for value in read:
                appender = self._appender.get(_name(key, value))
                if appender is not None and appender in self._aborted:
                    evidence = {
                        "call": call,
                        "key": encode(key),
                        "value": encode(value),
                        "appender": appender,
                    }
                    return Case(
                        Anomaly.ABORTED_READ, (call, appender), None, (evidence,)
                    )
        return None

    def _intermediate_read(self) -> Case | None:
        """Return the first committed read that ends in an append its appender followed.

        A transaction's read of its own appends is no intermediate read.
        """
        for call, key, read in self._reads:
            if not read:
                continue
            name = _name(key, read[-1])
            appender, later = self._appender.get(name), self._later.get(name)
            if appender is not None and appender != call and later is not None:
                evidence = {
                    "call": call,
                    "key": encode(key),
                    "value": encode(read[-1]),
                    "appender": appender,
                    "next": encode(later[0]),
                }
                return Case(
                    Anomaly.INTERMEDIATE_READ, (call, appender), None, (evidence,)
                )
        return None

    def _version_orders(self) -> dict[object, list[object]]:
        """Return each key's version order, in the order the keys first appear.

        Records the first key whose committed reads are not prefixes of one
        list as the incompatible-order case.
        """
        by_key: dict[object, list[tuple[int, list[object]]]] = {}
        for call, key, read in self._reads:
            by_key.setdefault(canonical(key), []).append((call, read))
        orders: dict[object, list[object]] = {}
        for key, stated in self._keys.items():
            order, clash = _longest(by_key.get(key, []))
            if clash is not None:
                if self._incompatible is None:
                    self._incompatible = _incompatible_case(stated, clash)
                continue
            orders[key] = order
        return orders

    def _derive(self) -> None:
        """Derive the dependencies between committed transactions, key by key.

        The transaction that appended the last value of a version order, and
        every read that returned the whole order, precede each committed
        append that no committed read observed.
        """
        reads: dict[object, list[_Read]] = {}
        for call, key, read in self._reads:
            reads.setdefault(canonical(key), []).append((call, read))
        for key, order in self._orders.items():
            present = {canonical(value) for value in order}
            versions = _Versions(
                encode(self._keys[key]),
                order,
                [self._writer(key, value) for value in order],
                [
                    (call, value)
                    for call, value in self._appends.get(key, [])
                    if call in self._committed and canonical(value) not in present
                ],
            )
            for (a, b), (value, following) in zip(
                itertools.pairwise(versions.writers),
                itertools.pairwise(order),
                strict=True,
            ):
                self._edge(a, b, _ww(versions.key, value, following))
            if order:
                for call, value in versions.unobserved:
                    self._edge(
                        versions.writers[-1], call, _ww(versions.key, order[-1], value)
                    )
            for call, read in reads.get(key, []):
                self._read_edges(call, read, versions)

    def _read_edges(self, call: int, read: list[object], versions: _Versions) -> None:
        """Derive the write-read and read-write dependencies of one committed read."""
        seen = len(read)
        last = encode(read[-1]) if read else None
        if seen:
            evidence = {
                "relation": Relation.WR.value,
                "key": versions.key,
                "value": last,
            }
            self._edge(versions.writers[seen - 1], call, evidence)
        following: Sequence[tuple[int | None, object]] = (
            [(versions.writers[seen], versions.order[seen])]
            if seen < len(versions.order)
            else versions.unobserved
        )
        for writer, value in following:
            self._edge(
                call,
                writer,
                {
                    "relation": Relation.RW.value,
                    "key": versions.key,
                    "value": last,
                    "next": encode(value),
                },
            )

    def _writer(self, key: object, value: object) -> int | None:
        """Return the committed transaction that appended value to key, or None."""
        appender = self._appender.get((key, canonical(value)))
        return appender if appender in self._committed else None

    def _edge(self, a: int | None, b: int | None, evidence: dict[str, Any]) -> None:
        """Add the evidence of a dependency of b on a, when both are committed."""
        if a is None or b is None or a == b:
            return
        self._edges.setdefault((a, b), []).append({"from": a, "to": b, **evidence})

    def _adjacency(self, relations: frozenset[Relation]) -> dict[int, list[int]]:
        """Return each transaction's targets over the edges of relations, in order."""
        out: dict[int, list[int]] = {}
        for (a, b), evidence in self._edges.items():
            if any(entry["relation"] in relations for entry in evidence):
                out.setdefault(a, []).append(b)
        for targets in out.values():
            targets.sort()
        return out

    def _cycle(self, anomaly: Anomaly) -> Case | None:
        """Return the first cycle of a kind, as the kind's search finds it, or None.

        The closing edge of a G-single cycle counts as its one read-write
        dependency. Each other edge counts by the relations the search follows.
        """
        search = _SEARCHES[anomaly]
        around = self._adjacency(search.component)
        back = self._adjacency(search.path)
        for component in _components(sorted(self._committed), around):
            members = set(component)
            for a in component:
                for b in around.get(a, []):
                    if b not in members or not self._has(a, b, search.closing):
                        continue
                    path = _path(b, a, back, members)
                    if path is None:
                        continue
                    first = search.component
                    if anomaly is Anomaly.G_SINGLE:
                        first = frozenset({search.closing})
                    used = [first] + [search.path] * (len(path) - 1)
                    return self._cycle_case(anomaly, [a, *path[:-1]], used)
        return None

    def _nonadjacent(self) -> Case | None:
        """Return the first G-nonadjacent cycle, or None.

        The search tries each component's read-write edges in the order of their
        sources and then their targets. From an edge's target it takes the
        shortest walk back to the edge's source on which no read-write edge
        follows another, that takes one more read-write edge at least, and whose
        last edge is no read-write edge. It reduces the closed walk to a simple
        cycle with no two adjacent read-write edges, and reports that cycle when
        it has two read-write edges or more.
        """
        around = self._adjacency(frozenset(Relation))
        for component in _components(sorted(self._committed), around):
            members = set(component)
            for a in component:
                for b in around.get(a, []):
                    if b not in members or not self._has(a, b, Relation.RW):
                        continue
                    steps = self._alternating(b, a, around, members)
                    if steps is None:
                        continue
                    nodes = [a, b, *(node for node, _ in steps[:-1])]
                    walk = list(
                        zip(nodes, [Relation.RW, *(r for _, r in steps)], strict=True)
                    )
                    cycle = _simple(walk)
                    if sum(r is Relation.RW for _, r in cycle) < _NONADJACENT_RW:
                        continue
                    return self._cycle_case(
                        Anomaly.G_NONADJACENT,
                        [node for node, _ in cycle],
                        [
                            frozenset({r}) if r is Relation.RW else _NON_RW
                            for _, r in cycle
                        ],
                    )
        return None

    def _alternating(
        self,
        start: int,
        goal: int,
        around: Mapping[int, Sequence[int]],
        members: set[int],
    ) -> list[tuple[int, Relation]] | None:
        """Return the shortest alternating walk from start to goal, or None.

        A read-write edge leads into start. Each step of the walk is the
        transaction it enters and the relation of the edge it follows, and the
        search tries each transaction's edges in the order of their targets
        and of the relations.
        """
        origin: _State = (start, True, False)
        parent: dict[_State, tuple[_State, Relation] | None] = {origin: None}
        queue: deque[_State] = deque([origin])
        while queue:
            state = queue.popleft()
            node, after_rw, taken = state
            if node == goal and not after_rw and taken:
                return _walk(state, parent)
            for target in around.get(node, ()):
                if target not in members:
                    continue
                for relation in self._relations(node, target):
                    if relation is Relation.RW and after_rw:
                        continue
                    rw = relation is Relation.RW
                    following: _State = (target, rw, taken or rw)
                    if following not in parent:
                        parent[following] = (state, relation)
                        queue.append(following)
        return None

    def _relations(self, a: int, b: int) -> list[Relation]:
        """Return the relations of the edge from a to b, in relation order."""
        present = {entry["relation"] for entry in self._edges[(a, b)]}
        return [relation for relation in _RELATIONS if relation in present]

    def _has(self, a: int, b: int, relation: Relation) -> bool:
        """Report whether the edge from a to b has a relation."""
        return any(entry["relation"] == relation for entry in self._edges[(a, b)])

    def _cycle_case(
        self, anomaly: Anomaly, nodes: list[int], used: list[frozenset[Relation]]
    ) -> Case:
        """Return the case of a cycle through nodes in order, back to the first.

        used gives, for the edge from each transaction to the next, the
        relations the search followed it by. The cycle lists the edge's
        relations among them, and the explanation the first evidence of one.
        """
        entries: list[dict[str, Any]] = []
        explanation: list[dict[str, Any]] = []
        for position, node in enumerate(nodes):
            following = nodes[(position + 1) % len(nodes)]
            evidence = [
                e
                for e in self._edges[(node, following)]
                if e["relation"] in used[position]
            ]
            relations = {entry["relation"] for entry in evidence}
            entries.append(
                {
                    "call": node,
                    "relations": [r.value for r in _RELATIONS if r in relations],
                }
            )
            explanation.append(evidence[0])
        return Case(anomaly, tuple(nodes), tuple(entries), tuple(explanation))


def _internal(txn: Transaction) -> Case | None:
    """Return the first read of an ok transaction that contradicts the transaction.

    Before a key's first read, the transaction knows only that the key ends
    with its own appends. After a read, it knows the whole list, and its
    later appends extend it. A read contains none of the values that the
    transaction appends to the key after it.
    """
    known: dict[object, tuple[bool, list[object]]] = {}
    for position, mop in enumerate(txn.mops):
        key = canonical(mop.key)
        whole, expected = known.get(key, (False, []))
        if mop.function == APPEND:
            known[key] = (whole, [*expected, mop.value])
            continue
        read = mop.value
        assert isinstance(read, list)
        future = _future(txn, position, read)
        if future or (key in known and not _agrees(read, whole, expected)):
            evidence = {
                "call": txn.call,
                "key": encode(mop.key),
                "read": encode(read),
                "expected": encode(expected),
                "whole": whole,
                "future": encode(future[0]) if future else None,
            }
            return Case(Anomaly.INTERNAL_INCONSISTENCY, (txn.call,), None, (evidence,))
        known[key] = (True, list(read))
    return None


def _future(txn: Transaction, position: int, read: list[object]) -> list[object]:
    """Return the values of a read at position that txn appends to the key after it."""
    key = canonical(txn.mops[position].key)
    later = {
        canonical(mop.value)
        for mop in txn.mops[position + 1 :]
        if mop.function == APPEND and canonical(mop.key) == key
    }
    return [value for value in read if canonical(value) in later]


def _agrees(read: list[object], whole: bool, expected: list[object]) -> bool:
    """Report whether a read is the expected list, or ends with it when not whole."""
    got = [canonical(value) for value in read]
    want = [canonical(value) for value in expected]
    if whole:
        return got == want
    return len(got) >= len(want) and got[len(got) - len(want) :] == want


#: A committed read: the reading transaction and the list it returned.
_Read = tuple[int, list[object]]


@dataclass(frozen=True)
class _Versions:
    """A key's version order.

    key is the key's typed literal, and order its values in order. writers
    lists the committed transaction that appended each value, or None for a
    value that no committed transaction appended. unobserved lists each
    committed append to the key that no committed read observed, as its
    transaction and its value, in the order of the transactions.
    """

    key: dict[str, Any]
    order: list[object]
    writers: list[int | None]
    unobserved: list[tuple[int, object]]


def _ww(key: dict[str, Any], value: object, following: object) -> dict[str, Any]:
    """Return the evidence that following comes after value in key's version order."""
    return {
        "relation": Relation.WW.value,
        "key": key,
        "value": encode(value),
        "next": encode(following),
    }


def _longest(reads: Sequence[_Read]) -> tuple[list[object], tuple[_Read, _Read] | None]:
    """Return the longest of a key's reads, or the first two that are not prefixes.

    The distinct reads, shortest first, must each be a prefix of the next.
    """
    distinct: dict[tuple[object, ...], _Read] = {}
    for call, read in reads:
        distinct.setdefault(tuple(canonical(value) for value in read), (call, read))
    ranked = sorted(distinct.items(), key=lambda item: len(item[0]))
    for (shorter, first), (longer, second) in itertools.pairwise(ranked):
        if longer[: len(shorter)] != shorter:
            return [], (first, second)
    return (ranked[-1][1][1] if ranked else []), None


def _incompatible_case(key: object, clash: tuple[_Read, _Read]) -> Case:
    """Return the case of two committed reads of key that no one list extends."""
    (first, shorter), (second, longer) = clash
    evidence = {
        "calls": [first, second],
        "key": encode(key),
        "reads": [encode(shorter), encode(longer)],
    }
    calls = tuple(dict.fromkeys((first, second)))
    return Case(Anomaly.INCOMPATIBLE_ORDER, calls, None, (evidence,))


@final
class _Tarjan:
    """Tarjan's algorithm without recursion, over one adjacency."""

    def __init__(self, adjacency: Mapping[int, Sequence[int]]) -> None:
        """Start with no transaction visited."""
        self._adjacency = adjacency
        self._order: dict[int, int] = {}
        self._low: dict[int, int] = {}
        self._stack: list[int] = []
        self._on_stack: set[int] = set()
        self.found: list[list[int]] = []

    def visit(self, root: int) -> None:
        """Find the new components that a search from root enters."""
        if root in self._order:
            return
        self._enter(root)
        work: list[tuple[int, Iterator[int]]] = [
            (root, iter(self._adjacency.get(root, ())))
        ]
        while work:
            node, targets = work[-1]
            target = next(targets, None)
            if target is None:
                work.pop()
                if work:
                    parent = work[-1][0]
                    self._low[parent] = min(self._low[parent], self._low[node])
                self._close(node)
            elif target not in self._order:
                self._enter(target)
                work.append((target, iter(self._adjacency.get(target, ()))))
            elif target in self._on_stack:
                self._low[node] = min(self._low[node], self._order[target])

    def _enter(self, node: int) -> None:
        """Number node in visiting order, and push it."""
        self._order[node] = self._low[node] = len(self._order)
        self._stack.append(node)
        self._on_stack.add(node)

    def _close(self, node: int) -> None:
        """Pop node's component when node is its root, and keep one of two or more."""
        if self._low[node] != self._order[node]:
            return
        component: list[int] = []
        while True:
            member = self._stack.pop()
            self._on_stack.discard(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1:
            self.found.append(sorted(component))


def _components(
    nodes: Sequence[int], adjacency: Mapping[int, Sequence[int]]
) -> list[list[int]]:
    """Return the strongly connected components of two or more transactions.

    Each component lists its transactions in ascending order, and the
    components come in the order of their lowest transactions.
    """
    tarjan = _Tarjan(adjacency)
    for node in nodes:
        tarjan.visit(node)
    return sorted(tarjan.found, key=lambda component: component[0])


def _walk(
    state: _State, parent: Mapping[_State, tuple[_State, Relation] | None]
) -> list[tuple[int, Relation]]:
    """Return the steps of the walk to state: each transaction, and the edge into it."""
    steps: list[tuple[int, Relation]] = []
    while (previous := parent[state]) is not None:
        before, relation = previous
        steps.append((state[0], relation))
        state = before
    return steps[::-1]


#: A closed walk: each transaction, and the relation of the edge that leaves it.
_Walk = list[tuple[int, Relation]]


def _simple(walk: _Walk) -> _Walk:
    """Return a simple cycle of a closed walk with no two adjacent read-write edges.

    While a transaction occurs twice, the walk splits at the first repeat into
    the part between the two occurrences and the rest. It keeps the part
    between them when that part has no two adjacent read-write edges, and the
    rest otherwise, and one of the two always has none. The cycle starts at
    its first read-write edge.
    """
    while (repeat := _first_repeat(walk)) is not None:
        first, second = repeat
        inner = walk[first:second]
        walk = inner if _alternates(inner) else walk[:first] + walk[second:]
    start = next((i for i, (_, r) in enumerate(walk) if r is Relation.RW), 0)
    return walk[start:] + walk[:start]


def _first_repeat(walk: _Walk) -> tuple[int, int] | None:
    """Return the two positions of the first transaction the walk visits twice."""
    seen: dict[int, int] = {}
    for position, (node, _) in enumerate(walk):
        if node in seen:
            return seen[node], position
        seen[node] = position
    return None


def _alternates(walk: _Walk) -> bool:
    """Report whether no read-write edge of a closed walk follows another."""
    return not any(
        relation is Relation.RW and walk[(i + 1) % len(walk)][1] is Relation.RW
        for i, (_, relation) in enumerate(walk)
    )


def _path(
    start: int, goal: int, adjacency: Mapping[int, Sequence[int]], members: set[int]
) -> list[int] | None:
    """Return the shortest path from start to goal within members, or None.

    The search visits each transaction's edges in the order of their targets,
    so of two shortest paths it returns the one that comes first in that
    order.
    """
    parent: dict[int, int] = {start: start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            path = [node]
            while node != start:
                node = parent[node]
                path.append(node)
            return path[::-1]
        for target in adjacency.get(node, ()):
            if target in members and target not in parent:
                parent[target] = node
                queue.append(target)
    return None
