"""The sequential model a history is checked against, and the named models.

A model is an initial state and a step function over states. step
returns the states that may follow a state when a call takes effect, and
an empty list rejects the call in that state. For a call whose outcome is
unknown, it returns the states the call leaves when it takes effect.
step must not change its state argument.

equal decides whether two states are interchangeable, and is the
standard's equality unless a model states its own. key returns a hashable
form that two equal states share, so that the search finds a
configuration in its memo without comparing every state. cost is the
number of steps of the budget that one call of step counts for.

NAMED maps each name that the corpus uses to its model. Every named model
accepts a call whose outcome is unknown in every state, and raises
ValueError for an operation it does not define. model_from() builds a
model from a subject.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Final

from prop.value import Pairs

from . import equality


@dataclass(frozen=True)
class Op:
    """A call as a model sees it.

    known reports whether the call completed with ok. output is the call's
    output when known is true, and None otherwise.
    """

    operation: str
    args: tuple[object, ...]
    known: bool
    output: object = None


def _one(state: object) -> int:
    """Return the cost of a step of a written model, which is one step."""
    del state
    return 1


@dataclass(frozen=True)
class Model:
    """An initial state, a step function, and how states compare and cost."""

    init: Callable[[], object]
    step: Callable[[object, Op], Sequence[object]]
    equal: Callable[[object, object], bool] = equality.equal
    key: Callable[[object], Hashable] = equality.key
    cost: Callable[[object], int] = _one


#: The value of a key that the key-value model has not stored.
EMPTY: Final = ""


def _unknown(operation: str, model: str) -> ValueError:
    """Return the error for an operation that a named model does not define."""
    return ValueError(f"history: the {model} model has no operation {operation!r}")


def _read(state: object, op: Op, model: str) -> list[object]:
    """Step a register's read, which outputs the state and changes nothing.

    Raises:
        ValueError: the operation is not a read.
    """
    if op.operation != "read":
        raise _unknown(op.operation, model)
    return [state] if not op.known or equality.equal(op.output, state) else []


def _register(state: object, op: Op) -> list[object]:
    """Step the register: a write stores its value, and a read outputs it."""
    if op.operation == "write":
        (value,) = op.args
        return [value]
    return _read(state, op, "register")


def _cas_register(state: object, op: Op) -> list[object]:
    """Step the register with compare-and-set.

    cas(from, to) outputs whether the state equals from, and stores to when
    it does. A cas whose outcome is unknown takes effect when the state
    equals from, and otherwise leaves the state.
    """
    if op.operation == "write":
        return _register(state, op)
    if op.operation != "cas":
        return _read(state, op, "cas-register")
    expected, value = op.args
    matches = equality.equal(state, expected)
    if op.known and op.output is not matches:
        return []
    return [value] if matches else [state]


def _lossy_register(state: object, op: Op) -> list[object]:
    """Step the register whose write may be lost: the new value, then the old."""
    if op.operation == "write":
        (value,) = op.args
        return [value, state]
    return _read(state, op, "lossy-register")


def _lookup(state: Pairs, name: object) -> object:
    """Return the value that the key-value state stores under name, or EMPTY."""
    for stored, value in state.items:
        if equality.equal(stored, name):
            return value
    return EMPTY


def _store(state: Pairs, name: object, value: object) -> Pairs:
    """Return the key-value state with value under name, in name's place.

    The state stores no key whose value is EMPTY, so two states are equal
    exactly when every key reads the same value from both.
    """
    kept = [
        (stored, held)
        for stored, held in state.items
        if not equality.equal(stored, name)
    ]
    if value != EMPTY:
        place = next(
            (
                i
                for i, (stored, _) in enumerate(state.items)
                if equality.equal(stored, name)
            ),
            len(kept),
        )
        kept.insert(place, (name, value))
    return Pairs(tuple(kept))


def _key_value(state: object, op: Op) -> list[object]:
    """Step the map from keys to strings, each of which starts empty."""
    assert isinstance(state, Pairs)
    name = op.args[0]
    held = _lookup(state, name)
    if op.operation == "get":
        return [state] if not op.known or equality.equal(op.output, held) else []
    if op.operation == "put":
        return [_store(state, name, op.args[1])]
    if op.operation == "append":
        suffix = op.args[1]
        assert isinstance(held, str)
        assert isinstance(suffix, str)
        return [_store(state, name, held + suffix)]
    raise _unknown(op.operation, "key-value")


def _queue(state: object, op: Op) -> list[object]:
    """Step the queue: dequeue outputs the head, or null when the queue is empty."""
    assert isinstance(state, list)
    if op.operation == "enqueue":
        (value,) = op.args
        return [[*state, value]]
    if op.operation != "dequeue":
        raise _unknown(op.operation, "queue")
    if not state:
        return [state] if not op.known or op.output is None else []
    return [state[1:]] if not op.known or equality.equal(op.output, state[0]) else []


def _set(state: object, op: Op) -> list[object]:
    """Step the set, which lists its values in the order they were added.

    remove and contains output whether the value is present. A remove whose
    outcome is unknown removes the value when it is present.
    """
    assert isinstance(state, list)
    (value,) = op.args
    present = any(equality.equal(value, held) for held in state)
    if op.operation == "add":
        return [state if present else [*state, value]]
    if op.operation == "contains":
        return [state] if not op.known or op.output is present else []
    if op.operation != "remove":
        raise _unknown(op.operation, "set")
    if op.known and op.output is not present:
        return []
    return [[held for held in state if not equality.equal(held, value)]]


def _same_set(a: object, b: object) -> bool:
    """Report whether two set states list the same values, in any order."""
    assert isinstance(a, list)
    assert isinstance(b, list)
    return len(a) == len(b) and all(any(equality.equal(x, y) for y in b) for x in a)


def _set_key(state: object) -> Hashable:
    """Return a key that two set states with the same values share."""
    assert isinstance(state, list)
    return frozenset(equality.key(value) for value in state)


#: The models the corpus names, keyed by name.
NAMED: Final[dict[str, Model]] = {
    "register": Model(lambda: None, _register),
    "cas-register": Model(lambda: None, _cas_register),
    "key-value": Model(lambda: Pairs(()), _key_value),
    "queue": Model(list, _queue),
    "set": Model(list, _set, _same_set, _set_key),
    "lossy-register": Model(lambda: None, _lossy_register),
}

#: A subject applies an operation to its arguments and returns the output.
Subject = Callable[[str, tuple[object, ...]], object]


def model_from(factory: Callable[[], Subject]) -> Model:
    """Return a model whose state is the sequence of calls applied so far.

    The state lists the operation and the arguments of each applied call,
    which is all that a fresh subject replays. step builds a fresh subject
    with factory, applies the sequence, applies the call, and accepts it
    when the subject's output equals the recorded output. A call whose
    outcome is unknown is accepted. A step at depth d calls the subject
    d + 1 times and costs d + 1 steps. Two states are equal when they list
    equal operations with equal arguments, in the same order.
    """

    def step(state: object, op: Op) -> list[object]:
        assert isinstance(state, tuple)
        subject = factory()
        for operation, args in state:
            subject(operation, args)
        output = subject(op.operation, op.args)
        if op.known and not equality.equal(output, op.output):
            return []
        return [(*state, (op.operation, op.args))]

    return Model(tuple, step, _same_calls, _calls_key, _replays)


def _same_calls(a: object, b: object) -> bool:
    """Report whether two sequences list equal operations with equal arguments."""
    assert isinstance(a, tuple)
    assert isinstance(b, tuple)
    return len(a) == len(b) and all(
        x[0] == y[0] and equality.equal(list(x[1]), list(y[1]))
        for x, y in zip(a, b, strict=True)
    )


def _calls_key(state: object) -> Hashable:
    """Return a key that two equal sequences of calls share."""
    assert isinstance(state, tuple)
    return tuple((operation, equality.key(list(args))) for operation, args in state)


def _replays(state: object) -> int:
    """Return the cost of a step of model_from: the calls it replays, plus one."""
    assert isinstance(state, tuple)
    return len(state) + 1
