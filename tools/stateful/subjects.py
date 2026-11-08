# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

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
- counter-refuses-every-third: a counter that refuses every third
  increment, counted over every case of the run. A refused increment
  completes with fail and the error REFUSED, and leaves the count. Any
  other increment adds one and returns the count, and read returns the
  count. The actions are increment, enabled while the model's count is
  below LIMIT, and read. Its model is a counter that reads. The enabled
  list of a step depends on the refusals, so a case that repeats an
  earlier case's choices can request other bounds, and the run is flaky.
- register-flushes-in-two-parts: a register of a buffer and a durable
  value. write sets the buffer to its value and returns null. read returns
  the buffer when it is set, and the durable value otherwise. A flusher
  task of the subject waits until the buffer is set, takes the value and
  clears the buffer, yields, and then sets the durable value to the value
  it took. The actions are write, whose input is drawn under "v" from
  [0, 1000], and read. The model is a register, and the clients and the
  flusher run as tasks of one scheduler.
- register-flushes: the same machine over a flusher that sets the durable
  value to the buffer and then clears the buffer, without a yield between.
- ticker-skips-its-first-tick: a ticker task that sleeps PERIOD on the
  clock of its scheduler and adds one to its count, TICKS times, and skips
  the first addition. The actions are advance, which advances the
  scheduler by a number of milliseconds drawn under "ms" from [0, 10],
  and read, which returns the count. The model counts the ticks of the
  advances.
- ticker: the same machine over a ticker that adds one at each tick.
- spins-until-a-flag: a subject whose action spin spawns a task that
  yields until a flag is set, and runs the scheduler. No action sets the
  flag, and the machine has no model.

Each subject is built anew for every run, so a subject that counts over
the cases of a run starts each run at 0. A subject that spawns tasks of
its own spawns them on a scheduler of the case with the setup's strategy
and limit of releases, and the clients of its concurrent section run on
the same scheduler. Each subject sets keep on the actions that the setup
names.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field, replace
from typing import Final

from history import equality
from history.model import Model, Op
from prop.case import Case
from prop.choice import IntegerBounds
from prop.generator import Integer
from prop.value import as_type

from .machine import Action, Machine, Options, steps
from .scheduler import MAX_RELEASES, Scheduler, Strategy, Uniform, Yielded

#: The names of the subjects.
QUEUE_LOSES_ON_WRAP: Final = "queue-loses-on-wrap"
CORRECT_QUEUE: Final = "correct-queue"
COUNTER_OVERFLOWS: Final = "counter-overflows"
STORE_LOSES_ON_CRASH: Final = "store-loses-on-crash"
RACY_COUNTER: Final = "racy-counter"
CORRECT_COUNTER: Final = "correct-counter"
COUNTER_REFUSES_EVERY_THIRD: Final = "counter-refuses-every-third"
REGISTER_FLUSHES_IN_TWO_PARTS: Final = "register-flushes-in-two-parts"
REGISTER_FLUSHES: Final = "register-flushes"
TICKER_SKIPS_ITS_FIRST_TICK: Final = "ticker-skips-its-first-tick"
TICKER: Final = "ticker"
SPINS_UNTIL_A_FLAG: Final = "spins-until-a-flag"

#: The identity of store-loses-on-crash's settle failure.
LOST: Final = "lost-write"

#: The count at which counter-overflows sets its count to 0.
OVERFLOW: Final = 3

#: counter-refuses-every-third refuses each increment whose number, counted
#: over the run, is a multiple of REFUSAL, with the error REFUSED.
REFUSAL: Final = 3
REFUSED: Final = "refused"

#: counter-refuses-every-third enables increment while the model's count is
#: below LIMIT.
LIMIT: Final = 3

#: The ticker sleeps PERIOD_MS milliseconds before each of its TICKS ticks.
PERIOD_MS: Final = 4
TICKS: Final = 4

#: A millisecond, in the nanoseconds of the clock of a scheduler.
MILLISECOND: Final = 1_000_000

#: The draws of the subjects.
CAPACITIES: Final = Integer(IntegerBounds(1, 8))
VALUES: Final = Integer(IntegerBounds(0, 1000))
KEYS: Final = Integer(IntegerBounds(0, 3))
MILLISECONDS: Final = Integer(IntegerBounds(0, 10))


@dataclass(frozen=True)
class Setup:
    """The options a run states for a subject, and its scheduler's strategy and limit.

    A subject without a concurrent section and without tasks of its own
    ignores clients, concurrent, concurrent_mean, strategy and max_releases.
    keep names the actions of the subject that every case keeps.
    """

    mean: int = 30
    max: int = 100
    swarm: bool = True
    clients: int = 2
    concurrent: int = 16
    strategy: Strategy = field(default_factory=Uniform)
    concurrent_mean: int | None = None
    max_releases: int = MAX_RELEASES
    keep: frozenset[str] = frozenset()

    def marked(self, machine: Machine) -> Machine:
        """Return machine with keep set on each action that the setup names."""
        actions = tuple(
            replace(action, keep=True) if action.name in self.keep else action
            for action in machine.actions
        )
        return replace(machine, actions=actions)

    def sequential(self) -> Options:
        """Return the options of a machine without a concurrent section."""
        return Options(self.mean, self.max, self.swarm)

    def scheduler_in(self, case: Case) -> Scheduler:
        """Return a scheduler of case with the setup's strategy and release limit."""
        return Scheduler(case, self.strategy, self.max_releases)

    def concurrent_on(self, scheduler: Scheduler) -> Options:
        """Return the options of a machine whose clients run as tasks of scheduler."""
        return Options(
            self.mean,
            self.max,
            self.swarm,
            self.clients,
            self.concurrent,
            scheduler,
            concurrent_mean=self.concurrent_mean,
        )

    def concurrent_in(self, case: Case) -> Options:
        """Return the options of a machine whose clients run as tasks in case."""
        return self.concurrent_on(self.scheduler_in(case))


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


def bounded_queue(capacity: int) -> Model[list[object]]:
    """Return the model of a queue of at most capacity values."""

    def step(state: list[object], op: Op) -> list[list[object]]:
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


def counter() -> Model[int]:
    """Return the model of a counter: increment returns the new count."""

    def step(state: int, op: Op) -> list[int]:
        if op.operation == "reset":
            return [0]
        if op.known and not equality.equal(op.output, state + 1):
            return []
        return [state + 1]

    return Model(lambda: 0, step)


def reading_counter() -> Model[int]:
    """Return the model of a counter that reads.

    increment returns the new count, and read returns the count.
    """

    def step(state: int, op: Op) -> list[int]:
        if op.operation == "read":
            if op.known and not equality.equal(op.output, state):
                return []
            return [state]
        if op.known and not equality.equal(op.output, state + 1):
            return []
        return [state + 1]

    return Model(lambda: 0, step)


def register() -> Model[object]:
    """Return the model of a register: write leaves its value, read returns it."""

    def step(state: object, op: Op) -> list[object]:
        if op.operation == "write":
            return [op.args[0]]
        if op.known and not equality.equal(op.output, state):
            return []
        return [state]

    return Model(lambda: None, step)


def ticks() -> Model[int]:
    """Return the model of the ticker: the milliseconds that the advances add.

    read returns the elapsed milliseconds divided by PERIOD_MS, at most TICKS.
    """

    def step(state: int, op: Op) -> list[int]:
        if op.operation == "advance":
            return [state + as_type(op.args[0], int)]
        if op.known and not equality.equal(op.output, min(TICKS, state // PERIOD_MS)):
            return []
        return [state]

    return Model(lambda: 0, step)


def _queue(case: Case, setup: Setup, *, loses_on_wrap: bool) -> None:
    """Run the queue machine over a queue of a drawn capacity."""
    capacity = as_type(case.draw(CAPACITIES, "capacity"), int)
    ring = Ring(capacity, loses_on_wrap)

    def put(case: Case, client: int, value: object) -> None:
        stored = as_type(value, int)
        call = case.history.invoke(client, "put", (stored,), ())
        call.ok(ring.put(stored))

    def get(case: Case, client: int, value: object) -> None:
        del value
        call = case.history.invoke(client, "get", (), ())
        call.ok(ring.get())

    machine = Machine(
        (
            Action("put", put, input=lambda case, _: case.draw(VALUES, "v")),
            Action("get", get),
        ),
        bounded_queue(capacity),
    )
    steps(case, setup.marked(machine), setup.sequential())


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
    steps(case, setup.marked(machine), setup.sequential())


def _store_loses_on_crash(case: Case, setup: Setup) -> None:
    """Run the store machine, whose settle check reads every acknowledged put."""
    durable: dict[int, int] = {}
    buffer: dict[int, int] = {}
    acknowledged: dict[int, int] = {}
    written = itertools.count(1)

    def put(case: Case, client: int, value: object) -> None:
        key, stored = as_type(value, tuple)
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
                input=lambda case, _: (case.draw(KEYS, "key"), next(written)),
            ),
            Action("flush", flush, enabled=lambda _: bool(buffer), drain=True),
            Action("crash", crash),
        ),
        settle=settle,
    )
    steps(case, setup.marked(machine), setup.sequential())


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
    steps(case, setup.marked(machine), setup.concurrent_in(case))


def _refusing_counter() -> Subject:
    """Return counter-refuses-every-third, with no increment counted yet."""
    increments = [0]

    def subject(case: Case, setup: Setup) -> None:
        count = [0]

        def increment(case: Case, client: int, value: object) -> None:
            del value
            call = case.history.invoke(client, "increment", (), ())
            increments[0] += 1
            if increments[0] % REFUSAL == 0:
                call.fail(REFUSED)
                return
            count[0] += 1
            call.ok(count[0])

        def read(case: Case, client: int, value: object) -> None:
            del value
            case.history.invoke(client, "read", (), ()).ok(count[0])

        def below_limit(state: object) -> bool:
            return as_type(state, int) < LIMIT

        machine = Machine(
            (
                Action("increment", increment, enabled=below_limit),
                Action("read", read),
            ),
            reading_counter(),
        )
        steps(case, setup.marked(machine), setup.sequential())

    return subject


def _flushed_register(case: Case, setup: Setup, *, in_two_parts: bool) -> None:
    """Run the register machine with clients, over a buffer that a flusher moves."""
    scheduler = setup.scheduler_in(case)
    buffer: list[object] = [None]
    durable: list[object] = [None]

    def flusher() -> Iterator[Yielded]:
        while True:
            yield scheduler.wait(lambda: buffer[0] is not None)
            if in_two_parts:
                taken = buffer[0]
                buffer[0] = None
                yield None
                durable[0] = taken
            else:
                durable[0] = buffer[0]
                buffer[0] = None

    def write(case: Case, client: int, value: object) -> None:
        stored = as_type(value, int)
        call = case.history.invoke(client, "write", (stored,), ())
        buffer[0] = stored
        call.ok(None)

    def read(case: Case, client: int, value: object) -> None:
        del value
        call = case.history.invoke(client, "read", (), ())
        call.ok(durable[0] if buffer[0] is None else buffer[0])

    scheduler.spawn(flusher())
    machine = Machine(
        (
            Action("write", write, input=lambda case, _: case.draw(VALUES, "v")),
            Action("read", read),
        ),
        register(),
    )
    steps(case, setup.marked(machine), setup.concurrent_on(scheduler))


def _ticker(case: Case, setup: Setup, *, skips_first: bool) -> None:
    """Run the ticker machine, whose advance moves the clock of the scheduler."""
    scheduler = setup.scheduler_in(case)
    count = [0]

    def ticking() -> Iterator[Yielded]:
        for tick in range(TICKS):
            yield scheduler.clock().sleep(PERIOD_MS * MILLISECOND)
            if tick > 0 or not skips_first:
                count[0] += 1

    def advance(case: Case, client: int, value: object) -> None:
        milliseconds = as_type(value, int)
        call = case.history.invoke(client, "advance", (milliseconds,), ())
        scheduler.advance(milliseconds * MILLISECOND)
        call.ok(None)

    def read(case: Case, client: int, value: object) -> None:
        del value
        case.history.invoke(client, "read", (), ()).ok(count[0])

    scheduler.spawn(ticking())
    machine = Machine(
        (
            Action(
                "advance", advance, input=lambda case, _: case.draw(MILLISECONDS, "ms")
            ),
            Action("read", read),
        ),
        ticks(),
    )
    steps(case, setup.marked(machine), setup.sequential())


def _spinner(case: Case, setup: Setup) -> None:
    """Run the machine whose one action spawns a task that yields without an end."""
    scheduler = setup.scheduler_in(case)
    flag = [False]

    def spinning() -> Iterator[None]:
        while not flag[0]:
            yield

    def spin(case: Case, client: int, value: object) -> None:
        del case, client, value
        scheduler.spawn(spinning())
        scheduler.run()

    steps(case, setup.marked(Machine((Action("spin", spin),))), setup.sequential())


#: The subjects, keyed by name. Each entry returns a subject for one run.
SUBJECTS: Final[dict[str, Callable[[], Subject]]] = {
    QUEUE_LOSES_ON_WRAP: lambda: (
        lambda case, setup: _queue(case, setup, loses_on_wrap=True)
    ),
    CORRECT_QUEUE: lambda: lambda case, setup: _queue(case, setup, loses_on_wrap=False),
    COUNTER_OVERFLOWS: lambda: _counter_overflows,
    STORE_LOSES_ON_CRASH: lambda: _store_loses_on_crash,
    RACY_COUNTER: lambda: lambda case, setup: _shared_counter(case, setup, racy=True),
    CORRECT_COUNTER: lambda: (
        lambda case, setup: _shared_counter(case, setup, racy=False)
    ),
    COUNTER_REFUSES_EVERY_THIRD: _refusing_counter,
    REGISTER_FLUSHES_IN_TWO_PARTS: lambda: (
        lambda case, setup: _flushed_register(case, setup, in_two_parts=True)
    ),
    REGISTER_FLUSHES: lambda: (
        lambda case, setup: _flushed_register(case, setup, in_two_parts=False)
    ),
    TICKER_SKIPS_ITS_FIRST_TICK: lambda: (
        lambda case, setup: _ticker(case, setup, skips_first=True)
    ),
    TICKER: lambda: lambda case, setup: _ticker(case, setup, skips_first=False),
    SPINS_UNTIL_A_FLAG: lambda: _spinner,
}


def body(name: str, setup: Setup | None = None) -> Callable[[Case], None]:
    """Return the body that runs a new subject of the name with setup, or the defaults.

    Raises:
        KeyError: no subject has the name.
    """
    subject = SUBJECTS[name]()
    chosen = setup or Setup()
    return lambda case: subject(case, chosen)
