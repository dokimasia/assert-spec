"""Shrinking: the search for the smallest case that fails the same way.

A case is smaller than another when its choice sequence is shorter, or
equally long and smaller in the first choice where the two differ. Choices
of one kind compare by their sort keys, and choices of different kinds by
kind: integer, then float, then sequence.

Before shrinking, the failing case is replayed once from its choices. A
replay that requests another choice, observes another fingerprint, or ends
another way makes the run flaky.

The shrinker runs its passes over the best case of one failure, in the
order Shrinker.shrink() lists them, until a whole round accepts no
candidate. delete-and-lower runs only in a round in which no other pass
accepted a candidate. A candidate is run only when it is smaller than the
best case and no earlier candidate had the same choices.
It is accepted when its run fails with the same identity and the run's
recorded choices are smaller than the best case's. A run that fails with
another identity is kept as a further failure. Every failure is shrunk in
turn, the one with the smallest case first, and all of them share one
budget of runs. Each pass visits its candidates in the order its method
states.

The explain phase then fills each draw of the counterexample with
EXPLAIN_FILLINGS random values. A draw for which every filling still fails
the same way is one where any value fails. For an integer draw that
matters, one step towards its target that passes is its nearest passing
value.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import partial
from itertools import pairwise
from typing import Final, final

from .case import Case, Drawn, Failed, Generating, Rejected, Replaying, Request, Span
from .choice import (
    INTEGRAL_LIMIT,
    Choice,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    Value,
    float_key,
)
from .execution import Body, Divergence, Execution, Status, execute
from .generator import Integer
from .replay import encode
from .source import MASK, Source

#: The runs of the body that shrinking every failure of a run may spend.
DEFAULT_BUDGET: Final = 2000

#: The random fillings the explain phase tries for each draw.
EXPLAIN_FILLINGS: Final = 4

#: The rank of each kind, which orders choices of different kinds.
KIND_RANKS: Final = {"integer": 0, "float": 1, "sequence": 2}

#: The probes find_integer makes one by one before it starts doubling.
_LINEAR_PROBES: Final = 4

#: The fewest siblings delete-span-chunk deletes at once; delete-span
#: deletes one.
_SMALLEST_CHUNK: Final = 2

#: The sort key of a choice sequence: its length, then each choice's key.
Key = tuple[int, tuple[tuple[int, ...], ...]]


class Exhausted(Exception):
    """The signal that the shrink budget is spent."""


@dataclass(frozen=True)
class Node:
    """One recorded choice, with the request it answered."""

    request: Request
    choice: Choice


Nodes = tuple[Node, ...]


@dataclass(frozen=True)
class Failure:
    """The smallest case found so far that fails with one identity."""

    identity: str
    execution: Execution
    nodes: Nodes


@dataclass(frozen=True)
class Explained:
    """One draw of the counterexample, explained.

    any_value_fails is None when the draw makes no choice or the budget
    ran out before its fillings. nearest_passing is the value one step
    towards the target, for an integer draw where that value passes.
    """

    label: str
    value: object
    any_value_fails: bool | None
    nearest_passing: object | None


def nodes_of(case: Case) -> Nodes:
    """Return a case's choices with their requests."""
    return tuple(
        Node(request, choice)
        for request, choice in zip(case.requests, case.choices, strict=True)
    )


def choice_key(node: Node) -> tuple[int, ...]:
    """Return a choice's key: its kind's rank, then its sort key."""
    bounds, value = node.request.bounds, node.choice.value
    if isinstance(bounds, IntegerBounds):
        assert isinstance(value, int)
        return (KIND_RANKS["integer"], *bounds.key(value))
    if isinstance(bounds, FloatBounds):
        assert isinstance(value, float)
        return (KIND_RANKS["float"], *float_key(value))
    assert isinstance(value, tuple)
    return (KIND_RANKS["sequence"], len(value), *value)


def key(nodes: Sequence[Node]) -> Key:
    """Return the shortlex key of a choice sequence."""
    return (len(nodes), tuple(choice_key(node) for node in nodes))


def find_integer(f: Callable[[int], bool]) -> int:
    """Return a k with f(k) true and f(k + 1) false, given that f(0) is true.

    It probes 1 to 4 in turn, then doubles until f fails, then bisects.
    """
    for k in range(1, _LINEAR_PROBES + 1):
        if not f(k):
            return k - 1
    low, high = _LINEAR_PROBES, _LINEAR_PROBES + 1
    while f(high):
        low, high = high, high * 2
    while low + 1 < high:
        middle = (low + high) // 2
        if f(middle):
            low = middle
        else:
            high = middle
    return low


def search(position: int, at: Callable[[int], bool]) -> bool:
    """Try position 0, then bisect towards the smallest position at() accepts.

    at(p) runs the candidate at position p of an order whose position 0
    is the target, and reports whether it was accepted. position is the
    current one, which counts as accepted. The result reports whether any
    candidate was accepted.
    """
    if position == 0:
        return False
    if at(0):
        return True
    low, high, improved = 0, position, False
    while high - low > 1:
        middle = (low + high) // 2
        if at(middle):
            high, improved = middle, True
        else:
            low = middle
    return improved


def explain_seed(seed: int, draw: int, filling: int) -> int:
    """Return the seed of a draw's filling: seed + (draw + 1) * 2^32 + filling."""
    return (seed + ((draw + 1) << 32) + filling) & MASK


def confirm(body: Body, failing: Execution, max_choices: int) -> Divergence | None:
    """Replay a failing case once, and return how the replay differed, if it did.

    The comparison takes the requests' bounds first, then the observed
    fingerprints, then the way the replay ended.
    """
    replay = execute(body, Replaying(failing.case.choices), max_choices)
    pairs = (
        (
            "request",
            [r.bounds for r in failing.case.requests],
            [r.bounds for r in replay.case.requests],
        ),
        ("fingerprint", failing.case.fingerprints, replay.case.fingerprints),
    )
    for what, recorded, replayed in pairs:
        for index in range(max(len(recorded), len(replayed))):
            before = recorded[index] if index < len(recorded) else None
            after = replayed[index] if index < len(replayed) else None
            if before != after:
                return Divergence(what, index, before, after)
    if replay.identity != failing.identity:
        index = len(failing.case.choices)
        return Divergence("verdict", index, failing.identity, replay.identity)
    return None


def _replace(nodes: Nodes, index: int, value: Value) -> Nodes:
    """Return nodes with one choice's value replaced."""
    node = nodes[index]
    changed = Node(node.request, Choice(node.choice.kind, value))
    return (*nodes[:index], changed, *nodes[index + 1 :])


def _length(node: Node) -> int:
    """Return the number of elements of a sequence choice, and 0 for another kind."""
    value = node.choice.value
    return len(value) if isinstance(value, tuple) else 0


def _at_target(node: Node) -> Node:
    """Return the node with its choice at its target."""
    return Node(node.request, Choice(node.choice.kind, node.request.bounds.target))


def _children(spans: Sequence[Span], parent: int | None) -> list[Span]:
    """Return the spans whose parent is parent, in order."""
    return [span for span in spans if span.parent == parent]


def _parents(spans: Sequence[Span]) -> list[int | None]:
    """Return every parent of a sibling group: the later parents first, then the top."""
    parents = sorted({span.parent for span in spans if span.parent is not None})
    top: list[int | None] = [None] if spans else []
    return [*reversed(parents), *top]


def _groups(spans: Sequence[Span]) -> list[list[Span]]:
    """Return the sibling groups, in the order _parents() gives their parents."""
    return [_children(spans, parent) for parent in _parents(spans)]


def _descendants(spans: Sequence[Span], index: int) -> Iterator[Span]:
    """Yield the descendants of the span at index, in order."""
    inside = {index}
    for later in range(index + 1, len(spans)):
        if spans[later].parent not in inside:
            return
        inside.add(later)
        yield spans[later]


def _rounded_floats(value: float, bounds: FloatBounds) -> Iterator[float]:
    """Yield a fraction rounded to fewer fractional bits, from 0 bits up.

    At each number of bits it yields the value rounded towards the target,
    then away from it, when the bounds admit them. An integral value, an
    infinity and NaN yield nothing.
    """
    if math.isnan(value) or math.isinf(value):
        return
    exact = Fraction(value)
    bits = exact.denominator.bit_length() - 1
    downward = value > bounds.target
    for fraction_bits in range(bits):
        scale = 1 << fraction_bits
        scaled = exact * scale
        roundings = (math.floor, math.ceil) if downward else (math.ceil, math.floor)
        for rounding in roundings:
            candidate = float(Fraction(rounding(scaled), scale))
            if bounds.admits(candidate):
                yield candidate


@final
class Shrinker:
    """The shrink of every failure of one run, over one budget."""

    def __init__(
        self, body: Body, first: Execution, max_choices: int, budget: int
    ) -> None:
        """Start from the first failing case."""
        assert first.identity is not None
        self._body = body
        self._max_choices = max_choices
        self.budget = budget
        self.runs = 0
        self.failures: dict[str, Failure] = {}
        # The token of every candidate run so far, with the number of
        # choices its run recorded.
        self._sizes: dict[str, int] = {
            encode(first.case.choices): len(first.case.choices)
        }
        self._target = first.identity
        self._record(first)

    @property
    def best(self) -> Failure:
        """Return the failure being shrunk."""
        return self.failures[self._target]

    @property
    def nodes(self) -> Nodes:
        """Return the best case's choices."""
        return self.best.nodes

    @property
    def spans(self) -> list[Span]:
        """Return the best case's spans."""
        return self.best.execution.case.spans

    def _record(self, execution: Execution) -> None:
        """Keep a failing run when it is its identity's first or smallest."""
        identity = execution.identity
        assert identity is not None
        nodes = nodes_of(execution.case)
        known = self.failures.get(identity)
        if known is None or key(nodes) < key(known.nodes):
            self.failures[identity] = Failure(identity, execution, nodes)

    def run(self, choices: Sequence[Choice]) -> Execution:
        """Run the body on choices, spending one run of the budget.

        Raises:
            Exhausted: the budget is spent.
        """
        if self.runs >= self.budget:
            raise Exhausted
        self.runs += 1
        return execute(self._body, Replaying(choices), self._max_choices)

    def consider(self, nodes: Sequence[Node]) -> bool:
        """Run a candidate that is smaller and new; report whether it became the best.

        Raises:
            Exhausted: the budget is spent.
        """
        if key(nodes) >= key(self.nodes):
            return False
        choices = [node.choice for node in nodes]
        token = encode(choices)
        if token in self._sizes:
            return False
        execution = self.run(choices)
        self._sizes[token] = len(execution.case.choices)
        if execution.failure is None:
            return False
        before = self.best
        self._record(execution)
        return self.best is not before

    def shrink_all(self) -> None:
        """Shrink each failure in turn, the one with the smallest case first.

        Shrinking stops when every failure is done or the budget is spent.
        """
        done: set[str] = set()
        try:
            while pending := [f for i, f in self.failures.items() if i not in done]:
                target = min(pending, key=lambda f: (key(f.nodes), f.identity))
                self.shrink(target.identity)
                done.add(target.identity)
        except Exhausted:
            return

    def shrink(self, identity: str) -> None:
        """Run rounds of every pass on one failure until a round accepts nothing.

        delete-and-lower runs only in a round in which no other pass
        accepted a candidate, and a round it improves is followed by another.

        Raises:
            Exhausted: the budget is spent.
        """
        self._target = identity
        passes = (
            self.delete_span_chunk,
            self.delete_span,
            self.lift_descendant,
            self.delete_span_run,
            self.sequence_delete,
            self.delete_structure_pair,
            self.target_span,
            self.minimize_choice,
            self.sequence_lower,
            self.lower_and_delete,
            self.sort_siblings,
            self.redistribute,
            self.lower_together,
            self.minimize_duplicates,
            self.float_simplify,
        )
        while True:
            improved = False
            for shrink_pass in passes:
                if shrink_pass():
                    improved = True
            if not improved and not self.delete_and_lower():
                return

    def _sweep(self, candidates: Callable[[], Iterator[Nodes]]) -> bool:
        """Try candidates in order; after an acceptance, start over on the new best."""
        improved = False
        while True:
            for candidate in candidates():
                if self.consider(candidate):
                    improved = True
                    break
            else:
                return improved

    def delete_span_chunk(self) -> bool:
        """Delete 2^k consecutive siblings, the largest k first, the last chunk first.

        The groups are visited in _parents() order, and k runs down to 1.
        """

        def candidates() -> Iterator[Nodes]:
            nodes = self.nodes
            for group in _groups(self.spans):
                count = len(group)
                size = 1 << (count.bit_length() - 1) if count else 0
                while size >= _SMALLEST_CHUNK:
                    for first in range(count - size, -1, -1):
                        start, end = group[first].start, group[first + size - 1].end
                        if start < end:
                            yield (*nodes[:start], *nodes[end:])
                    size //= 2

        return self._sweep(candidates)

    def delete_span(self) -> bool:
        """Delete one span, from the span that starts last to the first.

        Of spans that start together, the longer is tried first.
        """

        def candidates() -> Iterator[Nodes]:
            nodes = self.nodes
            for span in sorted(
                self.spans, key=lambda s: (s.start, s.end), reverse=True
            ):
                if span.start < span.end:
                    yield (*nodes[: span.start], *nodes[span.end :])

        return self._sweep(candidates)

    def lift_descendant(self) -> bool:
        """Replace a span by a shorter descendant with the same label.

        Spans are visited in order, and each one's descendants in order.
        """

        def candidates() -> Iterator[Nodes]:
            nodes, spans = self.nodes, self.spans
            for index, span in enumerate(spans):
                for inner in _descendants(spans, index):
                    shorter = inner.end - inner.start < span.end - span.start
                    if inner.label == span.label and shorter:
                        yield (
                            *nodes[: span.start],
                            *nodes[inner.start : inner.end],
                            *nodes[span.end :],
                        )

        return self._sweep(candidates)

    def delete_span_run(self) -> bool:
        """Delete as long a run of siblings as find_integer finds, at each start.

        The groups are visited in _parents() order, which keeps the spans
        of a parent not yet visited where they were. Within a group the
        runs start at the first sibling and move to the last. After a
        deletion, the next start is the sibling after the one that ended
        the run, because deleting it with the run failed.
        """
        improved = False
        for parent in _parents(self.spans):
            first = 0
            while first < len(group := _children(self.spans, parent)):
                deleted = partial(self._delete_run, self.nodes, group, first)
                if find_integer(deleted) > 0:
                    improved = True
                first += 1
        return improved

    def _delete_run(
        self, original: Nodes, group: list[Span], first: int, count: int
    ) -> bool:
        """Consider original without count siblings of group from first."""
        if first + count > len(group):
            return False
        start, end = group[first].start, group[first + count - 1].end
        return self.consider((*original[:start], *original[end:]))

    def sequence_delete(self) -> bool:
        """Delete 2^k consecutive elements of a sequence, the largest k first.

        Sequences are visited in order, and within one the last run first.
        No deletion goes below the sequence's min_size.
        """

        def candidates() -> Iterator[Nodes]:
            nodes = self.nodes
            for index, node in enumerate(nodes):
                bounds, elements = node.request.bounds, node.choice.value
                if not isinstance(bounds, SequenceBounds):
                    continue
                assert isinstance(elements, tuple)
                count = len(elements)
                size = 1 << (count.bit_length() - 1) if count else 0
                while size >= 1:
                    if count - size >= bounds.min_size:
                        for first in range(count - size, -1, -1):
                            kept = elements[:first] + elements[first + size :]
                            yield _replace(nodes, index, kept)
                    size //= 2

        return self._sweep(candidates)

    def delete_structure_pair(self) -> bool:
        """Delete two adjacent free structure choices, from the last pair to the first.

        Deleting the stop flag of one collection and the continue flag of
        the next joins the two collections, which no span deletion does.
        """

        def candidates() -> Iterator[Nodes]:
            nodes = self.nodes
            for first in range(len(nodes) - 2, -1, -1):
                if _free_structure(nodes[first]) and _free_structure(nodes[first + 1]):
                    yield (*nodes[:first], *nodes[first + 2 :])

        return self._sweep(candidates)

    def target_span(self) -> bool:
        """Set every choice of one span to its target, for each span in order."""

        def candidates() -> Iterator[Nodes]:
            nodes = self.nodes
            for span in self.spans:
                inside = tuple(
                    _at_target(node) for node in nodes[span.start : span.end]
                )
                yield (*nodes[: span.start], *inside, *nodes[span.end :])

        return self._sweep(candidates)

    def _lower(self, indices: Sequence[int]) -> bool:
        """Move integer choices of one value together towards their target.

        The target first, then a binary search over the value's position
        in the key order of its bounds, so a value below the target can
        move to one above it.
        """
        nodes = self.nodes
        node = nodes[indices[0]]
        bounds, value = node.request.bounds, node.choice.value
        assert isinstance(bounds, IntegerBounds)
        assert isinstance(value, int)

        def at(rank: int) -> bool:
            moved = nodes
            for index in indices:
                moved = _replace(moved, index, bounds.at_rank(rank))
            return self.consider(moved)

        return search(bounds.rank(value), at)

    def minimize_choice(self) -> bool:
        """Move each choice towards its target, in order.

        An integer tries its target and then a binary search over the
        distance. A float or a sequence tries its target.
        """
        improved = False
        index = 0
        while index < len(self.nodes):
            node = self.nodes[index]
            if isinstance(node.request.bounds, IntegerBounds):
                improved = self._lower([index]) or improved
            else:
                improved = (
                    self.consider(
                        _replace(self.nodes, index, node.request.bounds.target)
                    )
                    or improved
                )
            index += 1
        return improved

    def sequence_lower(self) -> bool:
        """Move each element of each sequence towards 0: 0, then a binary search.

        Sequences are visited in order, and their elements from the first.
        """
        improved = False
        index = 0
        while index < len(self.nodes):
            position = 0
            while index < len(self.nodes) and position < _length(self.nodes[index]):
                improved = self._lower_element(index, position) or improved
                position += 1
            index += 1
        return improved

    def _lower_element(self, index: int, position: int) -> bool:
        """Move one element of a sequence towards 0."""
        nodes = self.nodes
        elements = nodes[index].choice.value
        assert isinstance(elements, tuple)
        value = elements[position]

        def at(element: int) -> bool:
            changed = (*elements[:position], element, *elements[position + 1 :])
            return self.consider(_replace(nodes, index, changed))

        return search(value, at)

    def lower_and_delete(self) -> bool:
        """Step each integer towards its target, deleting a later span it sizes.

        Integers are visited in order. A step accepted with a deletion is
        tried again on the same integer, so a count falls one element at a
        time. A step accepted alone moves on to the next integer.
        """
        improved = False
        index = 0
        while index < len(self.nodes):
            before = self.best
            deleted = self._step_and_delete(index)
            improved = improved or self.best is not before
            if not deleted:
                index += 1
        return improved

    def _step_and_delete(self, index: int) -> bool:
        """Step the integer at index by one, alone and then with a later span deleted.

        When the step alone makes the run record another number of
        choices, the integer sizes what follows it. The step is then tried
        with each span that starts after the integer deleted, at any depth,
        the span that starts last first, and of two that start together
        the longer first. The result reports whether a step with a deletion
        was accepted.
        """
        nodes = self.nodes
        bounds, value = nodes[index].request.bounds, nodes[index].choice.value
        if not isinstance(bounds, IntegerBounds) or not isinstance(value, int):
            return False
        target = bounds.target
        if value == target:
            return False
        stepped = _replace(nodes, index, value - 1 if value > target else value + 1)
        if self.consider(stepped):
            return False
        size = self._sizes.get(encode([node.choice for node in stepped]))
        if size is None or size == len(nodes):
            return False
        later = sorted(
            (span for span in self.spans if index < span.start < span.end),
            key=lambda span: (span.start, span.end),
            reverse=True,
        )
        return any(
            self.consider((*stepped[: span.start], *stepped[span.end :]))
            for span in later
        )

    def delete_and_lower(self) -> bool:
        """Step each integer towards its target with earlier data deleted.

        Integers are visited in order. Each one's step is tried with one
        span removed that is not empty and ends at or before the integer,
        the span that starts last first and of two that start together the
        longer first. Then it is tried with one element removed from an
        earlier sequence, the last sequence and its last element first,
        when the sequence is longer than its min_size. The step alone is no
        candidate of this pass.
        """

        def candidates() -> Iterator[Nodes]:
            nodes, spans = self.nodes, self.spans
            for index, node in enumerate(nodes):
                bounds, value = node.request.bounds, node.choice.value
                if not isinstance(bounds, IntegerBounds) or not isinstance(value, int):
                    continue
                target = bounds.target
                if value == target:
                    continue
                step = value - 1 if value > target else value + 1
                stepped = _replace(nodes, index, step)
                earlier = sorted(
                    (span for span in spans if span.start < span.end <= index),
                    key=lambda span: (span.start, span.end),
                    reverse=True,
                )
                for span in earlier:
                    yield (*stepped[: span.start], *stepped[span.end :])
                for at in range(index - 1, -1, -1):
                    before = stepped[at]
                    sequence, elements = before.request.bounds, before.choice.value
                    if not isinstance(sequence, SequenceBounds):
                        continue
                    assert isinstance(elements, tuple)
                    if len(elements) <= sequence.min_size:
                        continue
                    for position in range(len(elements) - 1, -1, -1):
                        kept = elements[:position] + elements[position + 1 :]
                        yield _replace(stepped, at, kept)

        return self._sweep(candidates)

    def sort_siblings(self) -> bool:
        """Swap adjacent siblings with one label when the later one is smaller.

        Groups are visited in _parents() order, and pairs from the first.
        """

        def candidates() -> Iterator[Nodes]:
            nodes = self.nodes
            for group in _groups(self.spans):
                for left, right in pairwise(group):
                    first = nodes[left.start : left.end]
                    second = nodes[right.start : right.end]
                    if left.label == right.label and key(second) < key(first):
                        yield (
                            *nodes[: left.start],
                            *second,
                            *nodes[left.end : right.start],
                            *first,
                            *nodes[right.end :],
                        )

        return self._sweep(candidates)

    def redistribute(self) -> bool:
        """Move value from an integer to the next integer with the same bounds.

        For each integer, in order: the whole distance to its target, then
        a binary search for the largest amount the property accepts. The
        sum of the two values stays the same.
        """
        improved = False
        index = 0
        while index < len(self.nodes):
            improved = self._move(index) or improved
            index += 1
        return improved

    def _move(self, index: int) -> bool:
        """Move value from the integer at index to the next one with its bounds."""
        nodes = self.nodes
        bounds, value = nodes[index].request.bounds, nodes[index].choice.value
        if not isinstance(bounds, IntegerBounds) or not isinstance(value, int):
            return False
        later = next(
            (
                j
                for j in range(index + 1, len(nodes))
                if nodes[j].request.bounds == bounds
            ),
            None,
        )
        target = bounds.target
        if later is None or value == target:
            return False
        other = nodes[later].choice.value
        assert isinstance(other, int)
        sign = 1 if value > target else -1

        def moved(amount: int) -> bool:
            raised = other + sign * amount
            if not bounds.admits(raised):
                return False
            lowered = _replace(nodes, index, value - sign * amount)
            return self.consider(_replace(lowered, later, raised))

        distance = abs(value - target)
        if moved(distance):
            return True
        low, high, improved = 0, distance, False
        while high - low > 1:
            middle = (low + high) // 2
            if moved(middle):
                low, improved = middle, True
            else:
                high = middle
        return improved

    def lower_together(self) -> bool:
        """Move an integer and the next integer with its bounds towards their targets.

        Both move by one amount, so their difference stays the same. Both
        must lie on one side of the target. For each integer, in order,
        find_integer finds the largest amount the property accepts.
        """
        improved = False
        index = 0
        while index < len(self.nodes):
            improved = self._lower_pair(index) or improved
            index += 1
        return improved

    def _lower_pair(self, index: int) -> bool:
        """Move the integer at index and the next one with its bounds by one amount."""
        nodes = self.nodes
        bounds, value = nodes[index].request.bounds, nodes[index].choice.value
        if not isinstance(bounds, IntegerBounds) or not isinstance(value, int):
            return False
        later = next(
            (
                j
                for j in range(index + 1, len(nodes))
                if nodes[j].request.bounds == bounds
            ),
            None,
        )
        if later is None:
            return False
        other = nodes[later].choice.value
        assert isinstance(other, int)
        target = bounds.target
        if (value > target) != (other > target) or target in (value, other):
            return False
        step = -1 if value > target else 1
        room = min(abs(value - target), abs(other - target))

        def moved(amount: int) -> bool:
            if amount > room:
                return False
            lowered = _replace(nodes, index, value + step * amount)
            return self.consider(_replace(lowered, later, other + step * amount))

        return find_integer(moved) > 0

    def minimize_duplicates(self) -> bool:
        """Move every choice that shares a value and bounds towards the target together.

        Groups of two or more choices away from their target are visited
        by their first choice. Integers search the distance; floats and
        sequences try the target.
        """
        improved = False
        group = 0
        while True:
            groups = _duplicates(self.nodes)
            if group >= len(groups):
                return improved
            indices = groups[group]
            if isinstance(self.nodes[indices[0]].request.bounds, IntegerBounds):
                improved = self._lower(indices) or improved
            else:
                at_target = self.nodes
                for index in indices:
                    at_target = (
                        *at_target[:index],
                        _at_target(at_target[index]),
                        *at_target[index + 1 :],
                    )
                improved = self.consider(at_target) or improved
            group += 1

    def float_simplify(self) -> bool:
        """Simplify each float, in order: fewer fractional bits, then a smaller integer.

        A fraction takes the first candidate of _rounded_floats() that is
        accepted. An integral value below 2^53 in magnitude, whose target
        is integral too, then moves towards its target as an integer does.
        """
        improved = False
        index = 0
        while index < len(self.nodes):
            node = self.nodes[index]
            bounds, value = node.request.bounds, node.choice.value
            if isinstance(bounds, FloatBounds) and isinstance(value, float):
                for rounded in _rounded_floats(value, bounds):
                    if self.consider(_replace(self.nodes, index, rounded)):
                        improved = True
                        break
                improved = self._lower_float(index) or improved
            index += 1
        return improved

    def _lower_float(self, index: int) -> bool:
        """Move an integral float towards an integral target, as an integer.

        The search runs over the integers of the bounds below 2^53 in
        magnitude, in their key order, and skips a value the float's width
        cannot state.
        """
        nodes = self.nodes
        bounds, value = nodes[index].request.bounds, nodes[index].choice.value
        assert isinstance(bounds, FloatBounds)
        assert isinstance(value, float)
        target = bounds.target
        integral = (
            value.is_integer()
            and target.is_integer()
            and abs(value) < INTEGRAL_LIMIT
            and abs(target) < INTEGRAL_LIMIT
        )
        if not integral:
            return False
        limit = INTEGRAL_LIMIT - 1
        integers = IntegerBounds(
            -limit if math.isinf(bounds.lo) else max(math.ceil(bounds.lo), -limit),
            limit if math.isinf(bounds.hi) else min(math.floor(bounds.hi), limit),
        )

        def at(rank: int) -> bool:
            candidate = float(integers.at_rank(rank))
            if not bounds.admits(candidate):
                return False
            return self.consider(_replace(nodes, index, candidate))

        return search(integers.rank(int(value)), at)


def _free_structure(node: Node) -> bool:
    """Report whether a choice decides structure and allows two values or more."""
    bounds = node.request.bounds
    return (
        node.request.edge is not None
        and isinstance(bounds, IntegerBounds)
        and bounds.lo < bounds.hi
    )


def _duplicates(nodes: Nodes) -> list[list[int]]:
    """Return the groups of choices that share bounds and a value off the target."""
    shared: dict[object, list[int]] = {}
    for index, node in enumerate(nodes):
        if choice_key(node) == choice_key(_at_target(node)):
            continue
        identity = (node.request.bounds, encode([node.choice]))
        shared.setdefault(identity, []).append(index)
    return [indices for indices in shared.values() if len(indices) > 1]


def explain(shrinker: Shrinker, failure: Failure, seed: int) -> tuple[Explained, ...]:
    """Explain each draw of a failure's case, spending what remains of the budget."""
    case = failure.execution.case
    nodes = failure.nodes
    explained: list[Explained] = []
    for number, drawn in enumerate(case.draws):
        span = case.spans[drawn.span]
        if span.start == span.end:
            explained.append(Explained(drawn.label, drawn.value, None, None))
            continue
        seeds = [explain_seed(seed, number, j) for j in range(EXPLAIN_FILLINGS)]
        try:
            any_value = _relevance(shrinker, failure, span, drawn, seeds)
            nearest = (
                _nearest(shrinker, nodes, span, drawn) if any_value is False else None
            )
        except Exhausted:
            explained.append(Explained(drawn.label, drawn.value, None, None))
            continue
        explained.append(Explained(drawn.label, drawn.value, any_value, nearest))
    return tuple(explained)


def _relevance(
    shrinker: Shrinker, failure: Failure, span: Span, drawn: Drawn, seeds: list[int]
) -> bool | None:
    """Run the fillings of one draw from seeds, and report whether any value fails.

    A filling whose decode returns no value is skipped, and costs no run.
    The result is True when every filling that decoded fails the same
    way, False at the first that does not, and None when none decoded.

    Raises:
        Exhausted: the budget is spent.
    """
    decoded = False
    for seed in seeds:
        choices = _filled(failure.nodes, span, drawn, Source(seed))
        if choices is None:
            continue
        decoded = True
        if not _fails_with(shrinker, failure, choices):
            return False
    return True if decoded else None


def _filled(
    nodes: Nodes, span: Span, drawn: Drawn, source: Source
) -> list[Choice] | None:
    """Return the choices with one draw's span replaced by a filling from source.

    A fresh decode that returns no value, because it rejects the case,
    exceeds the cap on choices or fails, is no filling, and the result is
    None.
    """
    fresh = Case(Generating(source))
    try:
        drawn.generator.decode(fresh)
    except (Rejected, Failed):
        return None
    before = [node.choice for node in nodes[: span.start]]
    after = [node.choice for node in nodes[span.end :]]
    return [*before, *fresh.choices, *after]


def _fails_with(shrinker: Shrinker, failure: Failure, choices: list[Choice]) -> bool:
    """Run choices and report whether they fail with the failure's identity."""
    return shrinker.run(choices).identity == failure.identity


def _nearest(
    shrinker: Shrinker, nodes: Nodes, span: Span, drawn: Drawn
) -> object | None:
    """Return an integer draw's value one step towards its target, when it passes."""
    value = drawn.value
    if not isinstance(drawn.generator, Integer) or not isinstance(value, int):
        return None
    target = drawn.generator.bounds.target
    if value == target:
        return None
    stepped = value - 1 if value > target else value + 1
    choices = [node.choice for node in _replace(nodes, span.start, stepped)]
    return stepped if shrinker.run(choices).status is Status.PASSED else None
