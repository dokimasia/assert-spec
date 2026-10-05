"""The machine subjects the corpus names, each a body that runs one machine.

Every subject records each call of a client in the case's history, with
an empty list of keys, and completes it as ok with its output.

- queue-loses-on-wrap: a bounded queue of a capacity drawn under
  "capacity" from [1, 8]. put writes its value at the write index and
  returns true, or returns false when the queue is full. get returns the
  oldest value, or null when the queue is empty. When the write index is
  at the last slot, put writes the value into the first slot instead, and
  the index wraps to the first slot. The machine's actions are put, whose
  input is drawn under "v" from [0, 1000], and get. Its model is a
  bounded queue of the capacity.
- correct-queue: the same machine over a queue that writes every value
  at its write index.
- counter-overflows: a counter whose increment adds one and returns the
  count, and whose reset sets it to 0 and returns null. When an increment
  takes the count to 3, the counter sets it to 0 and returns 0. The
  actions are increment and reset, and the model is a counter.
- store-loses-on-crash: a store that puts a value under a key into a
  buffer, moves the buffer into its durable map on flush, and empties the
  buffer on crash. The actions are put, whose input is a key drawn under
  "key" from [0, 3] and the next value of a counter from 1, flush, a
  drain action enabled while the buffer is not empty, and crash. The
  machine has no model. The drain empties the buffer, and the settle
  check then reads the durable value of every key that a put returned
  for. It fails with the identity LOST when the value is not the last one
  put.
- racy-counter: a counter whose increment reads the count, yields to the
  task scheduler, writes the count plus one and returns it. The action is
  increment, the model a counter, and the clients run as tasks of a
  scheduler.
- correct-counter: the same machine over an increment that adds one and
  returns the count without yielding.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from typing import Final

from history import equality
from history.model import Model, Op
from prop.case import Case
from prop.choice import IntegerBounds
from prop.generator import Integer

from .machine import Action, Machine, Options, steps
from .scheduler import Scheduler, Strategy, Uniform

#: The names of the subjects.
QUEUE_LOSES_ON_WRAP: Final = "queue-loses-on-wrap"
CORRECT_QUEUE: Final = "correct-queue"
COUNTER_OVERFLOWS: Final = "counter-overflows"
STORE_LOSES_ON_CRASH: Final = "store-loses-on-crash"
RACY_COUNTER: Final = "racy-counter"
CORRECT_COUNTER: Final = "correct-counter"

#: The identity of store-loses-on-crash's settle failure.
LOST: Final = "lost-write"

#: The count at which counter-overflows sets its count to 0.
OVERFLOW: Final = 3

#: The draws of the subjects.
CAPACITIES: Final = Integer(IntegerBounds(1, 8))
VALUES: Final = Integer(IntegerBounds(0, 1000))
KEYS: Final = Integer(IntegerBounds(0, 3))


@dataclass(frozen=True)
class Setup:
    """The options a run states for a subject, and its scheduler's strategy.

    A subject without a concurrent section ignores clients, concurrent and
    strategy.
    """

    mean: int = 30
    max: int = 100
    swarm: bool = True
    clients: int = 2
    concurrent: int = 16
    strategy: Strategy = field(default_factory=Uniform)

    def sequential(self) -> Options:
        """Return the options of a machine without a concurrent section."""
        return Options(self.mean, self.max, self.swarm)

    def concurrent_in(self, case: Case) -> Options:
        """Return the options of a machine whose clients run as tasks in case."""
        scheduler = Scheduler(case, self.strategy)
        return Options(
            self.mean, self.max, self.swarm, self.clients, self.concurrent, scheduler
        )


#: A subject: it builds its subject and runs its machine in a case.
Subject = Callable[[Case, Setup], None]


@dataclass
class Ring:
    """A bounded queue in a ring of slots.

    loses_on_wrap writes the value of a put at the last slot into the
    first slot.
    """

    capacity: int
    loses_on_wrap: bool
    slots: list[int | None] = field(default_factory=list)
    head: int = 0
    tail: int = 0
    size: int = 0

    def __post_init__(self) -> None:
        """Start with every slot empty."""
        self.slots = [None] * self.capacity

    def put(self, value: int) -> bool:
        """Add value, and report whether the queue had room for it."""
        if self.size == self.capacity:
            return False
        last = self.tail == self.capacity - 1
        self.slots[0 if last and self.loses_on_wrap else self.tail] = value
        self.tail = 0 if last else self.tail + 1
        self.size += 1
        return True

    def get(self) -> int | None:
        """Remove and return the oldest value, or None when the queue is empty."""
        if self.size == 0:
            return None
        value = self.slots[self.head]
        self.head = (self.head + 1) % self.capacity
        self.size -= 1
        return value


def bounded_queue(capacity: int) -> Model:
    """Return the model of a queue of at most capacity values."""

    def step(state: object, op: Op) -> list[object]:
        assert isinstance(state, list)
        if op.operation == "put":
            full = len(state) == capacity
            if op.known and op.output != (not full):
                return []
            return [state if full else [*state, op.args[0]]]
        if not state:
            return [state] if not op.known or op.output is None else []
        if op.known and not equality.equal(op.output, state[0]):
            return []
        return [state[1:]]

    return Model(list, step)


def counter() -> Model:
    """Return the model of a counter: increment returns the new count."""

    def step(state: object, op: Op) -> list[object]:
        assert isinstance(state, int)
        if op.operation == "reset":
            return [0]
        if op.known and not equality.equal(op.output, state + 1):
            return []
        return [state + 1]

    return Model(lambda: 0, step)


def _queue(case: Case, setup: Setup, *, loses_on_wrap: bool) -> None:
    """Run the queue machine over a queue of a drawn capacity."""
    capacity = case.draw(CAPACITIES, "capacity")
    assert isinstance(capacity, int)
    ring = Ring(capacity, loses_on_wrap)

    def put(case: Case, client: int, value: object) -> None:
        assert isinstance(value, int)
        call = case.history.invoke(client, "put", (value,), ())
        call.ok(ring.put(value))

    def get(case: Case, client: int, value: object) -> None:
        del value
        call = case.history.invoke(client, "get", (), ())
        call.ok(ring.get())

    machine = Machine(
        (
            Action("put", put, input=lambda case, state: case.draw(VALUES, "v")),
            Action("get", get),
        ),
        bounded_queue(capacity),
    )
    steps(case, machine, setup.sequential())


def _counter_overflows(case: Case, setup: Setup) -> None:
    """Run the counter machine over a counter that overflows at OVERFLOW."""
    count = [0]

    def increment(case: Case, client: int, value: object) -> None:
        del value
        call = case.history.invoke(client, "increment", (), ())
        count[0] = (count[0] + 1) % OVERFLOW
        call.ok(count[0])

    def reset(case: Case, client: int, value: object) -> None:
        del value
        call = case.history.invoke(client, "reset", (), ())
        count[0] = 0
        call.ok(None)

    machine = Machine(
        (Action("increment", increment), Action("reset", reset)), counter()
    )
    steps(case, machine, setup.sequential())


def _store_loses_on_crash(case: Case, setup: Setup) -> None:
    """Run the store machine, whose settle check reads every acknowledged put."""
    durable: dict[int, int] = {}
    buffer: dict[int, int] = {}
    acknowledged: dict[int, int] = {}
    written = itertools.count(1)

    def put(case: Case, client: int, value: object) -> None:
        assert isinstance(value, tuple)
        key, stored = value
        call = case.history.invoke(client, "put", (key, stored), ())
        buffer[key] = stored
        call.ok(None)
        acknowledged[key] = stored

    def flush(case: Case, client: int, value: object) -> None:
        del case, client, value
        durable.update(buffer)
        buffer.clear()

    def crash(case: Case, client: int, value: object) -> None:
        del case, client, value
        buffer.clear()

    def settle(case: Case, state: object) -> None:
        del state
        for key, stored in acknowledged.items():
            if durable.get(key) != stored:
                case.fail(LOST, f"key {key} lost {stored}")

    machine = Machine(
        (
            Action(
                "put",
                put,
                input=lambda case, state: (case.draw(KEYS, "key"), next(written)),
            ),
            Action("flush", flush, enabled=lambda state: bool(buffer), drain=True),
            Action("crash", crash),
        ),
        settle=settle,
    )
    steps(case, machine, setup.sequential())


def _shared_counter(case: Case, setup: Setup, *, racy: bool) -> None:
    """Run the counter machine with clients, over an increment that may yield."""
    count = [0]

    def add() -> Generator[None, None, int]:
        read = count[0]
        if racy:
            yield
        count[0] = read + 1
        return count[0]

    def increment(case: Case, client: int, value: object) -> Iterator[None]:
        del value
        call = case.history.invoke(client, "increment", (), ())
        call.ok((yield from add()))

    machine = Machine((Action("increment", increment),), counter())
    steps(case, machine, setup.concurrent_in(case))


#: The subjects, keyed by name.
SUBJECTS: Final[dict[str, Subject]] = {
    QUEUE_LOSES_ON_WRAP: lambda case, setup: _queue(case, setup, loses_on_wrap=True),
    CORRECT_QUEUE: lambda case, setup: _queue(case, setup, loses_on_wrap=False),
    COUNTER_OVERFLOWS: _counter_overflows,
    STORE_LOSES_ON_CRASH: _store_loses_on_crash,
    RACY_COUNTER: lambda case, setup: _shared_counter(case, setup, racy=True),
    CORRECT_COUNTER: lambda case, setup: _shared_counter(case, setup, racy=False),
}


def body(name: str, setup: Setup | None = None) -> Callable[[Case], None]:
    """Return the body that runs the named subject with setup, or the defaults.

    Raises:
        KeyError: no subject has the name.
    """
    subject = SUBJECTS[name]
    chosen = setup or Setup()
    return lambda case: subject(case, chosen)
