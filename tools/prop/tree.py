"""The case tree: the choice sequences a run generated, as a trie.

A node is one choice request, recorded with its bounds, and an edge is the
value the request took. A case that ends marks its last node as a leaf,
with how it ended. A Walker follows one case down the tree and finds:

- A repeated case. A body is a function of its choices, so a choice that
  arrives at a leaf would end the body as that leaf's case ended. The
  walker raises Repeated there, and the case does not count.
- A diverging body. A request whose bounds differ from the request the
  tree recorded at the same position, a request where an earlier case
  ended, or an end where an earlier case made a request, raises Diverged.
- An exhausted domain. A node is exhausted when it is a leaf, or when
  every value its bounds allow leads to an exhausted node. A float choice
  never exhausts, and neither does a sequence without a maximum size.

The tree stops growing at NODE_LIMIT nodes. A walk that would add a node
past the limit stops checking for the rest of its case, and the tree no
longer reports an exhausted domain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from .case import Request
from .choice import NAN_BITS, Bounds, IntegerBounds, SequenceBounds, Value, bits_of

#: The most nodes a tree holds.
NODE_LIMIT: Final = 1 << 20


class Ending(StrEnum):
    """How a case that reached its end ended."""

    PASSED = "passed"
    FAILED = "failed"
    REJECTED = "rejected"


class Repeated(Exception):
    """The signal that stops a case whose choices repeat a tested case."""


@final
class Diverged(Exception):
    """The body requested different choices after the same values.

    recorded is what the tree recorded at the position and requested is
    what the body did there. Each is a request's bounds, or None for a
    case that ended at that position.
    """

    def __init__(
        self, index: int, recorded: Bounds | None, requested: Bounds | None
    ) -> None:
        """Record the position and the two versions."""
        super().__init__(f"choice {index}: recorded {recorded}, requested {requested}")
        self.index = index
        self.recorded = recorded
        self.requested = requested


def size(bounds: Bounds) -> int | None:
    """Return the number of values the bounds allow, or None if it is unbounded.

    A float's count is never taken, so a float choice never exhausts.
    """
    if isinstance(bounds, IntegerBounds):
        return bounds.hi - bounds.lo + 1
    if isinstance(bounds, SequenceBounds) and bounds.max_size is not None:
        lengths = range(bounds.min_size, bounds.max_size + 1)
        return sum(int(bounds.k**length) for length in lengths)
    return None


def _key(value: Value) -> object:
    """Return the key of an edge: floats by their bits, with one NaN."""
    if isinstance(value, float):
        return ("float", NAN_BITS if math.isnan(value) else bits_of(value))
    return value


@dataclass(eq=False)
class Node:
    """One position of the tree: the request made there, or the case's end."""

    bounds: Bounds | None = None
    ending: Ending | None = None
    exhausted: bool = False
    children: dict[object, Node] = field(default_factory=dict)

    def settle(self) -> None:
        """Recompute whether the node is exhausted from its children."""
        if self.ending is not None:
            self.exhausted = True
            return
        if self.bounds is None:
            return
        count = size(self.bounds)
        self.exhausted = (
            count is not None
            and len(self.children) == count
            and all(child.exhausted for child in self.children.values())
        )


@final
class Tree:
    """Every case the simplest, edge and random phases generated."""

    def __init__(self, limit: int = NODE_LIMIT) -> None:
        """Start with a root and nothing recorded, growing to limit nodes."""
        self.root = Node()
        self.nodes = 1
        self.limit = limit
        self.full = False

    @property
    def exhausted(self) -> bool:
        """Report whether the run has tested every input of its domain."""
        return not self.full and self.root.exhausted

    def walker(self) -> Walker:
        """Return a walker for one new case."""
        return Walker(self)


@final
class Walker:
    """One case's path down the tree. It is the case's observer."""

    def __init__(self, tree: Tree) -> None:
        """Start at the root of tree."""
        self._tree = tree
        self._path = [tree.root]
        self._off = False

    def step(self, index: int, request: Request, value: Value) -> None:
        """Follow the choice at index.

        Raises:
            Diverged: an earlier case ended here, or made another request.
            Repeated: the choice arrives at a leaf.
        """
        if self._off:
            return
        node = self._path[-1]
        if node.ending is not None:
            raise Diverged(index, None, request.bounds)
        if node.bounds is None:
            node.bounds = request.bounds
        elif node.bounds != request.bounds:
            raise Diverged(index, node.bounds, request.bounds)
        key = _key(value)
        child = node.children.get(key)
        if child is None:
            if self._tree.nodes >= self._tree.limit:
                self._tree.full = True
                self._off = True
                return
            child = Node()
            node.children[key] = child
            self._tree.nodes += 1
        if child.ending is not None:
            raise Repeated
        self._path.append(child)

    def end(self, ending: Ending) -> None:
        """Mark where the case ended as a leaf.

        No case ends at an existing leaf: a choice that arrives at one
        raises Repeated, and a root that is a leaf exhausts the domain, so
        the run starts no further case.

        Raises:
            Diverged: an earlier case made a request where this one ended.
        """
        if self._off:
            return
        node = self._path[-1]
        if node.bounds is not None:
            raise Diverged(len(self._path) - 1, node.bounds, None)
        node.ending = ending
        for passed in reversed(self._path):
            passed.settle()
