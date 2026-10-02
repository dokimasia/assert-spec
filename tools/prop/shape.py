"""Shapes: a language-neutral description of a type's values, read into a generator.

A shape is a JSON object whose ``shape`` key names its id. A shape file is
a root shape that may also state ``definitions``, the shapes a ``ref``
names, and ``source``, the language and the type it was read from, which
no reader compares. read() turns a shape file into a generator of the
engine. Two implementations that read one shape decode the same value from
the same choices, so two types with one shape produce the same values from
one seed in every language.

Structural shapes decode as the generator vocabulary does: bool as
boolean, an int up to 64 bits wide as integer, float, char and string as
string, bytes, list, fixed-list and set as list, map as dict, optional,
and literal as sampled-from. A record decodes its fields in order, an
enum an index and then the chosen variant's payload, and a ref the
definition it names.

Domain shapes decode to the form the corpus states their values in:

- uuid and ip-address: bytes in network order.
- decimal: the unscaled integer.
- date: days since 1970-01-01. time-of-day: units since midnight.
  duration: units. offset: seconds east of UTC. zone: its name.
- instant: a record of its seconds since 1970-01-01T00:00:00Z and the
  units within the second. One 64-bit integer cannot state the
  nanoseconds of the years 1 to 9999, so an instant is two choices.
- local-date-time: a record of its date and its time of day.
- zoned-date-time: a record of its instant and its zone.
- wall-time: a record of its local-date-time and its zone.

A key that a shape does not take fails the read, and the failure names
where the key is. A constraint never becomes a filter.

A value of a recursive shape has a budget of BUDGET nodes. A node is the
value of a definition that can reach itself through refs. Once a value
has used its budget, every container that refers back takes its exit: an
optional is absent, a list, a set or a map takes no further element, and
an enum takes its first variant that does not refer back. The exit is
still a choice,
with bounds that admit only the exit, so a replay walks the same
positions. A definition that can reach itself without passing through
such a container has no finite value, and fails the read.
"""

from __future__ import annotations

import calendar
import collections.abc
import math
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, ClassVar, Final

from . import alphabet, draw, literal, pattern
from .case import Case, Generator, Request
from .choice import (
    INT64_MAX,
    INT64_MIN,
    UINT64_MAX,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
)
from .collection import ELEMENT, ENTRY, Sizes, collect
from .generator import (
    BYTE_VALUES,
    Boolean,
    Float,
    Integer,
    SampledFrom,
    String,
    StringMatching,
)
from .generator import Bytes as BytesGenerator
from .value import Pairs, Record, Variant, canonical
from .zone import Zone, zones

#: The nodes one value of a recursive shape may use.
BUDGET: Final = 100

#: The units of a time shape, by name, as the count of them in a second.
UNITS: Final = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}

#: The bounds of the date and time shapes by default: 0001-01-01T00:00:00Z
#: and 9999-12-31T23:59:59Z, in seconds since the epoch, and the same
#: dates in days.
FIRST_SECOND: Final = -62_135_596_800
LAST_SECOND: Final = 253_402_300_799
SECONDS_PER_DAY: Final = 86_400
FIRST_DAY: Final = FIRST_SECOND // SECONDS_PER_DAY
LAST_DAY: Final = LAST_SECOND // SECONDS_PER_DAY

#: The first and last years the date and time shapes state.
FIRST_YEAR: Final = 1
LAST_YEAR: Final = 9999

#: The last hour, minute and second of a day.
LAST_HOUR: Final = 23
LAST_MINUTE: Final = 59
LAST_SECOND_OF_MINUTE: Final = 59

#: The largest duration, in nanoseconds: the range of Go's time.Duration.
MAX_DURATION_NS: Final = INT64_MAX

#: The largest offset from UTC, in seconds: 18 hours.
MAX_OFFSET: Final = 64_800

#: The odds that a zoned-date-time or a wall-time comes from its zone's
#: offset changes, when the zone has one.
NEAR_CHANGE: Final = Fraction(1, 4)

#: The odds that a wall-time near a change takes the offset after it.
AFTER_CHANGE: Final = Fraction(1, 2)

#: The widths of the int shape, and the width that is two choices.
INT_WIDTHS: Final = (8, 16, 32, 64, 128)
WIDE: Final = 128
HALF: Final = 64
LOW_MASK: Final = UINT64_MAX

#: The bytes of an address of each IP version, and of a UUID.
ADDRESS_BYTES: Final = {4: 4, 6: 16}
UUID_BYTES: Final = 16

#: The largest finite float of each width.
FLOAT_MAX: Final = {32: 3.4028234663852886e38, 64: sys.float_info.max}

#: A field of a record and a variant of an enum are each a name and a shape.
PAIR: Final = 2

#: What each shape takes besides ``shape``: its required keys, then the
#: keys it may state.
KEYS: Final[dict[str, tuple[frozenset[str], frozenset[str]]]] = {
    "bool": (frozenset(), frozenset()),
    "int": (frozenset({"width", "signed"}), frozenset({"min", "max"})),
    "float": (
        frozenset({"width"}),
        frozenset({"min", "max", "allow_nan", "allow_infinity"}),
    ),
    "char": (frozenset(), frozenset({"alphabet"})),
    "string": (
        frozenset(),
        frozenset({"min_size", "max_size", "alphabet", "pattern"}),
    ),
    "bytes": (frozenset(), frozenset({"min_size", "max_size"})),
    "list": (frozenset({"of"}), frozenset({"min_size", "max_size"})),
    "fixed-list": (frozenset({"of", "size"}), frozenset()),
    "set": (frozenset({"of"}), frozenset({"min_size", "max_size"})),
    "map": (frozenset({"key", "of"}), frozenset({"min_size", "max_size"})),
    "optional": (frozenset({"of"}), frozenset()),
    "record": (frozenset({"fields"}), frozenset()),
    "enum": (frozenset({"variants"}), frozenset()),
    "literal": (frozenset({"values"}), frozenset()),
    "ref": (frozenset({"name"}), frozenset()),
    "uuid": (frozenset(), frozenset()),
    "ip-address": (frozenset(), frozenset({"version"})),
    "decimal": (frozenset({"scale"}), frozenset({"min", "max"})),
    "instant": (frozenset({"unit"}), frozenset({"min", "max"})),
    "date": (frozenset(), frozenset({"min", "max"})),
    "time-of-day": (frozenset({"unit"}), frozenset({"min", "max"})),
    "local-date-time": (frozenset({"unit"}), frozenset({"min", "max"})),
    "duration": (frozenset({"unit"}), frozenset({"min", "max"})),
    "offset": (frozenset(), frozenset({"min", "max"})),
    "zone": (frozenset(), frozenset()),
    "zoned-date-time": (frozenset({"unit"}), frozenset()),
    "wall-time": (frozenset({"unit"}), frozenset()),
}

#: The ids of the shape vocabulary.
SHAPES: Final = frozenset(KEYS)

#: The keys only a shape file's root states.
ROOT_KEYS: Final = frozenset({"definitions", "source"})

#: The text forms of a date, a time of day, and a date and time. A date
#: and time ends in Z when it is an instant in UTC.
DATE: Final = re.compile(r"^(\d{4})-(\d\d)-(\d\d)$")
TIME: Final = re.compile(r"^(\d\d):(\d\d):(\d\d)(?:\.(\d{1,9}))?$")
DATE_TIME: Final = re.compile(
    r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,9}))?(Z?)$"
)

#: The text form of a decimal bound.
DECIMAL: Final = re.compile(r"^-?\d+(\.\d+)?$")

#: A shape as the JSON states it.
Node = Mapping[str, Any]

#: The bounds of a two-choice time shape: each a first and a second part.
PairBounds = tuple[tuple[int, int], tuple[int, int]]


class ShapeError(ValueError):
    """A shape that does not read: unknown, misstated, or without a finite value."""


@dataclass(eq=False)
class Budget:
    """The nodes that each value in progress of one shape file has used."""

    limit: int = BUDGET
    _used: list[int] = field(default_factory=list)

    @contextmanager
    def value(self) -> collections.abc.Generator[None, None, None]:
        """Count the nodes of one value from zero while it decodes."""
        self._used.append(0)
        try:
            yield
        finally:
            self._used.pop()

    def spend(self) -> None:
        """Count one node of the value in progress."""
        self._used[-1] += 1

    @property
    def exhausted(self) -> bool:
        """Report whether the value in progress has used its budget."""
        return bool(self._used) and self._used[-1] >= self.limit

    def is_exhausted(self) -> bool:
        """Return exhausted, as a callable a collection asks before each element."""
        return self.exhausted


@dataclass(frozen=True, eq=False)
class Root:
    """A recursive shape's root: it counts the budget of each value from zero.

    A shape without a cyclic definition spends no budget, so it reads as
    the generator it maps to, without a Root. A draw of an int shape is
    then a draw from integer, and the explain phase steps it as one.
    """

    node: Generator
    budget: Budget

    def decode(self, case: Case) -> object:
        """Return one value of the root shape."""
        with self.budget.value():
            return self.node.decode(case)


@dataclass(frozen=True, eq=False)
class Ref:
    """The value of a definition, by name. A cyclic one counts one node."""

    name: str
    definitions: Mapping[str, Generator]
    cyclic: bool
    budget: Budget

    def decode(self, case: Case) -> object:
        """Return the value of the named definition."""
        if self.cyclic:
            self.budget.spend()
        return self.definitions[self.name].decode(case)


@dataclass(frozen=True, eq=False)
class OptionalShape:
    """A value or None: a presence choice, which is forced absent at an exit."""

    ID: ClassVar[str] = "optional"
    of: Generator
    exits: bool
    budget: Budget

    def decode(self, case: Case) -> object:
        """Return None when absent and the decoded value when present."""
        forced = self.exits and self.budget.exhausted
        with case.span(self.ID):
            if case.integer(IntegerBounds(0, 0 if forced else 1), edge=1):
                return self.of.decode(case)
            return None


@dataclass(frozen=True, eq=False)
class ListShape:
    """A list, a fixed-list or a set: elements as a collection, empty at an exit.

    A set is a list whose elements are unique under canonical().
    """

    ID: ClassVar[str] = "list"
    of: Generator
    sizes: Sizes
    unique: bool
    exits: bool
    budget: Budget

    def decode(self, case: Case) -> object:
        """Return the elements the case's flags and choices decode to."""

        def element() -> tuple[object, object]:
            value = self.of.decode(case)
            return value, canonical(value) if self.unique else None

        stop = self.budget.is_exhausted if self.exits else None
        with case.span(self.ID):
            return collect(case, self.sizes, ELEMENT, element, stop)


@dataclass(frozen=True, eq=False)
class MapShape:
    """A map: entries with distinct keys, as a dict decodes them, empty at an exit."""

    ID: ClassVar[str] = "dict"
    key: Generator
    of: Generator
    sizes: Sizes
    exits: bool
    budget: Budget

    def decode(self, case: Case) -> object:
        """Return the entries the case's flags, keys and values decode to."""

        def entry() -> tuple[tuple[object, object], object]:
            key = self.key.decode(case)
            return (key, self.of.decode(case)), canonical(key)

        stop = self.budget.is_exhausted if self.exits else None
        with case.span(self.ID):
            return Pairs(tuple(collect(case, self.sizes, ENTRY, entry, stop)))


@dataclass(frozen=True, eq=False)
class RecordShape:
    """Named fields, each decoded in declaration order, as one span."""

    ID: ClassVar[str] = "record"
    fields: tuple[tuple[str, Generator], ...]

    def decode(self, case: Case) -> object:
        """Return the record of each field's value."""
        with case.span(self.ID):
            return Record(tuple((name, of.decode(case)) for name, of in self.fields))


@dataclass(frozen=True, eq=False)
class EnumShape:
    """A variant: an index that decides structure, then its payload when it has one.

    exit is the index of the first variant that does not refer back, which
    the index takes once the budget is used. It is None when the enum does
    not refer back.
    """

    ID: ClassVar[str] = "enum"
    variants: tuple[tuple[str, Generator | None], ...]
    exit: int | None
    budget: Budget

    def decode(self, case: Case) -> object:
        """Return the variant the case chooses."""
        bounds = IntegerBounds(0, len(self.variants) - 1)
        if self.exit is not None and self.budget.exhausted:
            bounds = IntegerBounds(self.exit, self.exit)
        with case.span(self.ID):
            name, payload = self.variants[case.integer(bounds, edge=0)]
            if payload is None:
                return Variant(name)
            return Variant(name, payload.decode(case))


def second_part(
    first: int, lo: tuple[int, int], hi: tuple[int, int], top: int
) -> IntegerBounds:
    """Return the bounds of the second choice of a two-choice shape.

    It ranges over [0, top], except where the first choice equals a
    bound's first part, where it stops at that bound's second part.
    """
    return IntegerBounds(
        lo[1] if first == lo[0] else 0, hi[1] if first == hi[0] else top
    )


@dataclass(frozen=True, eq=False)
class Int128Shape:
    """A 128-bit integer: its high 64 bits, then its low 64 bits, as one span.

    The high half is signed when the shape is. The low half ranges over
    the unsigned 64-bit range, except where the high half equals the high
    half of a bound, where it stops at that bound's low half.
    """

    ID: ClassVar[str] = "int"
    lo: int
    hi: int

    def decode(self, case: Case) -> object:
        """Return the integer the two halves state."""
        lo = (self.lo >> HALF, self.lo & LOW_MASK)
        hi = (self.hi >> HALF, self.hi & LOW_MASK)
        with case.span(self.ID):
            high = case.integer(IntegerBounds(lo[0], hi[0]), reuse=True)
            low = case.integer(second_part(high, lo, hi, LOW_MASK), reuse=True)
        return (high << HALF) | low


@dataclass(frozen=True, eq=False)
class InstantShape:
    """An instant: its seconds, then the units within the second, as one span.

    A unit of a second makes no second choice, and the units are then 0.
    """

    ID: ClassVar[str] = "instant"
    per: int
    lo: tuple[int, int]
    hi: tuple[int, int]

    def decode(self, case: Case) -> object:
        """Return the record of the seconds and the units."""
        with case.span(self.ID):
            seconds = case.integer(IntegerBounds(self.lo[0], self.hi[0]), reuse=True)
            units = 0
            if self.per > 1:
                bounds = second_part(seconds, self.lo, self.hi, self.per - 1)
                units = case.integer(bounds, reuse=True)
        return instant_value(seconds, units)


@dataclass(frozen=True, eq=False)
class LocalDateTimeShape:
    """A date and a time of day without a zone, as one span."""

    ID: ClassVar[str] = "local-date-time"
    per: int
    lo: tuple[int, int]
    hi: tuple[int, int]

    def decode(self, case: Case) -> object:
        """Return the record of the date and the time of day."""
        with case.span(self.ID):
            day = case.integer(IntegerBounds(self.lo[0], self.hi[0]), reuse=True)
            top = SECONDS_PER_DAY * self.per - 1
            time = case.integer(second_part(day, self.lo, self.hi, top), reuse=True)
        return local_value(day, time)


def instant_value(seconds: int, units: int) -> Record:
    """Return the value of an instant: its seconds and its units within the second."""
    return Record((("seconds", seconds), ("units", units)))


def local_value(day: int, time: int) -> Record:
    """Return the value of a local-date-time: its date and its time of day."""
    return Record((("date", day), ("time-of-day", time)))


def _near(case: Case, zone: Zone) -> bool:
    """Return whether a value of a zone comes from one of its changes.

    A zone without a change, such as UTC, makes no choice here.
    """
    if not zone.changes:
        return False
    request = Request(
        IntegerBounds(0, 1), lambda source: draw.boolean(source, NEAR_CHANGE)
    )
    return case.choose(request) == 1


def _change_and_step(case: Case, zone: Zone) -> tuple[int, int]:
    """Return the index of one of a zone's changes, and a step from -1 to 1."""
    index = case.integer(IntegerBounds(0, len(zone.changes) - 1), edge=0)
    return index, case.integer(IntegerBounds(-1, 1), reuse=True)


def _zone(case: Case) -> Zone:
    """Return the zone of the list that an index chooses."""
    listed = zones()
    return listed[case.integer(IntegerBounds(0, len(listed) - 1), edge=0)]


@dataclass(frozen=True, eq=False)
class ZonedShape:
    """An instant in a zone: the zone, then an instant near one of its changes or not.

    The zone comes first, because the changes are the zone's.
    """

    ID: ClassVar[str] = "zoned-date-time"
    instant: InstantShape

    def decode(self, case: Case) -> object:
        """Return the record of the instant and the zone's name."""
        per = self.instant.per
        value: object
        with case.span(self.ID):
            zone = _zone(case)
            if _near(case, zone):
                index, step = _change_and_step(case, zone)
                value = instant_value(*divmod(zone.changes[index].at * per + step, per))
            else:
                value = self.instant.decode(case)
        return Record((("instant", value), ("zone", zone.name)))


@dataclass(frozen=True, eq=False)
class WallShape:
    """A wall time in a zone, which the code under test resolves.

    The zone comes first. A wall time near a change is the change's
    instant in the offset before it or after it, moved by a step of one
    unit, which reaches the wall times a gap skips and a fold repeats.
    """

    ID: ClassVar[str] = "wall-time"
    local: LocalDateTimeShape

    def decode(self, case: Case) -> object:
        """Return the record of the local date and time and the zone's name."""
        per = self.local.per
        value: object
        with case.span(self.ID):
            zone = _zone(case)
            if _near(case, zone):
                index, step = _change_and_step(case, zone)
                change = zone.changes[index]
                request = Request(
                    IntegerBounds(0, 1),
                    lambda source: draw.boolean(source, AFTER_CHANGE),
                )
                offset = change.after if case.choose(request) == 1 else change.before
                total = (change.at + offset) * per + step
                value = local_value(*divmod(total, SECONDS_PER_DAY * per))
            else:
                value = self.local.decode(case)
        return Record((("local-date-time", value), ("zone", zone.name)))


@dataclass(frozen=True, eq=False)
class IpShape:
    """An IP address of either version: an index, then 4 or 16 bytes."""

    ID: ClassVar[str] = "ip-address"
    versions: tuple[BytesGenerator, BytesGenerator]

    def decode(self, case: Case) -> object:
        """Return the address's bytes in network order."""
        with case.span(self.ID):
            return self.versions[case.integer(IntegerBounds(0, 1), edge=0)].decode(case)


def fixed_bytes(count: int) -> BytesGenerator:
    """Return the generator of exactly count bytes."""
    return BytesGenerator(SequenceBounds(BYTE_VALUES, count, count))


def read(document: object) -> Generator:
    """Return the generator of a shape file.

    Raises:
        ShapeError: the file states a shape the vocabulary does not have, a
            key a shape does not take, a parameter it cannot read, a ref to
            no definition, or a definition with no finite value.
    """
    if not isinstance(document, Mapping):
        raise ShapeError(f"prop: {document!r} is not a shape")
    return _Reader(document).root()


def _int(node: Node, key: str, where: str) -> int:
    """Return an integer parameter, as a typed literal states an int.

    Raises:
        ShapeError: the parameter is not an integer.
    """
    try:
        return literal.integer(node[key])
    except literal.LiteralError as bad:
        raise ShapeError(
            f"prop: {where}.{key} is {node[key]!r}, not an integer"
        ) from bad


def _count(node: Node, key: str, where: str) -> int | None:
    """Return a count parameter of at least 0, or None when the node states none.

    Raises:
        ShapeError: the parameter is not an integer of at least 0.
    """
    if node.get(key) is None:
        return None
    value = _int(node, key, where)
    if value < 0:
        raise ShapeError(f"prop: {where}.{key} is {value}, below 0")
    return value


def _sizes(node: Node, where: str) -> Sizes:
    """Return min_size, 0 by default, and max_size, unbounded by default.

    Raises:
        ShapeError: a size is not an integer of at least 0, or max_size is
            below min_size.
    """
    try:
        return Sizes(
            _count(node, "min_size", where) or 0, _count(node, "max_size", where)
        )
    except ShapeError:
        raise
    except ValueError as bad:
        raise ShapeError(f"prop: {where}: {bad}") from bad


def _unit(node: Node, where: str) -> int:
    """Return the units in a second of a time shape's unit.

    Raises:
        ShapeError: the unit is not s, ms, us or ns.
    """
    unit = node["unit"]
    if unit not in UNITS:
        raise ShapeError(f"prop: {where}.unit is {unit!r}, not one of {sorted(UNITS)}")
    return UNITS[unit]


def _fraction_units(digits: str | None, per: int, where: str) -> int:
    """Return the units within a second that a fraction's digits state.

    Raises:
        ShapeError: the digits state more precision than the unit has.
    """
    if not digits:
        return 0
    scaled = Fraction(int(digits), 10 ** len(digits)) * per
    if scaled.denominator != 1:
        raise ShapeError(f"prop: {where} states a fraction finer than its unit")
    return int(scaled)


def _day(year: str, month: str, day: str, where: str) -> int:
    """Return the days since 1970-01-01 of a date of the proleptic Gregorian calendar.

    Raises:
        ShapeError: the date does not exist, or is outside the years 1 to 9999.
    """
    y, m, d = int(year), int(month), int(day)
    exists = (
        FIRST_YEAR <= y <= LAST_YEAR
        and 1 <= m <= len(calendar.month_abbr) - 1
        and 1 <= d <= calendar.monthrange(y, m)[1]
    )
    if not exists:
        raise ShapeError(f"prop: {where} states {year}-{month}-{day}, which is no date")
    return calendar.timegm((y, m, d, 0, 0, 0)) // SECONDS_PER_DAY


def _time(hour: str, minute: str, second: str, where: str) -> int:
    """Return the seconds since midnight of a time of day.

    Raises:
        ShapeError: the time does not exist.
    """
    h, m, s = int(hour), int(minute), int(second)
    if h > LAST_HOUR or m > LAST_MINUTE or s > LAST_SECOND_OF_MINUTE:
        raise ShapeError(
            f"prop: {where} states {hour}:{minute}:{second}, which is no time"
        )
    return h * 3600 + m * 60 + s


def _range(
    node: Node, where: str, default: tuple[int, int], parse: Callable[[Any], int]
) -> tuple[int, int]:
    """Return the integers a shape's min and max bound, inside default.

    Raises:
        ShapeError: a bound is outside default, or min is above max.
    """
    lo = parse(node["min"]) if node.get("min") is not None else default[0]
    hi = parse(node["max"]) if node.get("max") is not None else default[1]
    if not default[0] <= lo <= hi <= default[1]:
        raise ShapeError(
            f"prop: {where} bounds [{lo}, {hi}] are empty or outside "
            f"[{default[0]}, {default[1]}]"
        )
    return lo, hi


def _bounded(
    node: Node, where: str, default: tuple[int, int], parse: Callable[[Any], int]
) -> IntegerBounds:
    """Return the bounds of one integer choice that a shape's min and max state.

    Raises:
        ShapeError: a bound is outside default, or min is above max.
    """
    return IntegerBounds(*_range(node, where, default, parse))


def _pair_bounds(
    node: Node, where: str, default: PairBounds, parse: Callable[[Any], tuple[int, int]]
) -> PairBounds:
    """Return the bounds of a two-choice shape, each a first and a second part.

    Raises:
        ShapeError: a bound is outside default, or min is after max.
    """
    lo = parse(node["min"]) if node.get("min") is not None else default[0]
    hi = parse(node["max"]) if node.get("max") is not None else default[1]
    if not default[0] <= lo <= hi <= default[1]:
        raise ShapeError(f"prop: {where} bounds {lo} to {hi} are empty or out of range")
    return lo, hi


@dataclass
class _Reader:
    """One shape file being read: its definitions and the budget of its values."""

    document: Node
    budget: Budget = field(default_factory=Budget)
    built: dict[str, Generator] = field(default_factory=dict)
    sources: dict[str, Node] = field(default_factory=dict)
    cyclic: frozenset[str] = frozenset()

    def root(self) -> Generator:
        """Read the definitions, check that each has a finite value, then the root.

        The root is wrapped in a Root only when a definition is cyclic.

        Raises:
            ShapeError: the definitions or the source are misstated, a
                definition has no finite value, or a shape does not read.
        """
        definitions: object = self.document.get("definitions", {})
        if not isinstance(definitions, Mapping):
            raise ShapeError("prop: definitions is not a map of names to shapes")
        for name, node in definitions.items():
            if not isinstance(name, str) or not isinstance(node, Mapping):
                raise ShapeError(f"prop: definitions.{name} is {node!r}, not a shape")
            self.sources[name] = node
        source = self.document.get("source")
        if source is not None and not (
            isinstance(source, Mapping)
            and all(isinstance(source.get(k), str) for k in ("language", "type"))
        ):
            raise ShapeError(f"prop: source is {source!r}, not a language and a type")
        self.cyclic = self._cyclic()
        self._finite()
        for name, node in self.sources.items():
            self.built[name] = self.build(node, f"definitions.{name}")
        root = self.build(self.document, "shape", root=True)
        return Root(root, self.budget) if self.cyclic else root

    def refs(self, node: object, *, stop_at_exits: bool = False) -> Iterator[str]:
        """Yield the name of every ref inside node, without following refs.

        With stop_at_exits, a container that can always exit is not
        entered, so only the refs that every value of node expands remain.
        """
        if isinstance(node, list):
            for item in node:
                yield from self.refs(item, stop_at_exits=stop_at_exits)
            return
        if not isinstance(node, Mapping):
            return
        if node.get("shape") == "ref":
            yield str(node.get("name"))
            return
        if stop_at_exits and self.exits(node):
            return
        for key, value in node.items():
            if key not in ROOT_KEYS and key != "values":
                yield from self.refs(value, stop_at_exits=stop_at_exits)

    def _cyclic(self) -> frozenset[str]:
        """Return the definitions that can reach themselves through refs.

        Raises:
            ShapeError: a ref names no definition.
        """
        reach = {name: set(self.refs(node)) for name, node in self.sources.items()}
        for target in set(self.refs(self.document)).union(*reach.values()):
            if target not in self.sources:
                raise ShapeError(
                    f"prop: a ref names {target!r}, which is no definition"
                )
        changed = True
        while changed:
            changed = False
            for name, targets in reach.items():
                wider = targets.union(*(reach[t] for t in targets))
                if wider != targets:
                    reach[name] = wider
                    changed = True
        return frozenset(name for name, targets in reach.items() if name in targets)

    def refers_back(self, node: object) -> bool:
        """Report whether node contains a ref to a definition that can reach itself."""
        return any(name in self.cyclic for name in self.refs(node))

    def exits(self, node: Node) -> bool:
        """Report whether a container can always take an exit, whatever it contains.

        An optional can be absent, a list, a set or a map without a minimum
        size can be empty, and an enum can take a variant that does not
        refer back.
        """
        kind = node.get("shape")
        if kind == "optional":
            return True
        if kind in ("list", "set", "map"):
            return node.get("min_size") in (None, 0)
        if kind == "enum":
            return self.exit_variant(node) is not None
        return False

    def exit_variant(self, node: Node) -> int | None:
        """Return the index of an enum's first variant that does not refer back."""
        variants = node.get("variants")
        for index, variant in enumerate(variants if isinstance(variants, list) else []):
            payload = (
                variant[1]
                if isinstance(variant, list) and len(variant) == PAIR
                else None
            )
            if not self.refers_back(payload):
                return index
        return None

    def _finite(self) -> None:
        """Refuse a definition that reaches itself through refs every value expands.

        Raises:
            ShapeError: such a definition exists.
        """
        must = {
            name: set(self.refs(node, stop_at_exits=True))
            for name, node in self.sources.items()
        }
        for start in sorted(self.cyclic):
            seen: set[str] = set()
            frontier = set(must[start])
            while frontier:
                if start in frontier:
                    raise ShapeError(
                        f"prop: definitions.{start} has no finite value, because it "
                        "refers back without an optional, a list, a set, a map or "
                        "an enum that can exit"
                    )
                seen |= frontier
                frontier = set().union(*(must[n] for n in frontier)) - seen

    def build(self, node: Node, where: str, *, root: bool = False) -> Generator:
        """Return the generator of one shape.

        Raises:
            ShapeError: the shape is unknown, lacks a required key, states a
                key it does not take, or misstates a parameter.
        """
        kind = node.get("shape")
        if not isinstance(kind, str) or kind not in KEYS:
            raise ShapeError(f"prop: {where} is {kind!r}, which is no shape")
        required, optional = KEYS[kind]
        stated = set(node) - {"shape"} - (ROOT_KEYS if root else set())
        missing = sorted(required - stated)
        if missing:
            raise ShapeError(
                f"prop: {where} states no {missing[0]}, which the {kind} shape needs"
            )
        extra = sorted(stated - required - optional)
        if extra:
            raise ShapeError(
                f"prop: {where}.{extra[0]} does not apply to the {kind} shape"
            )
        try:
            return _BUILDERS[kind](self, node, where)
        except ShapeError:
            raise
        except (ValueError, TypeError) as bad:
            raise ShapeError(f"prop: {where}: {bad}") from bad

    def child(self, node: object, where: str) -> Generator:
        """Return the generator of a shape nested in another.

        Raises:
            ShapeError: node is not a shape, or does not read.
        """
        if not isinstance(node, Mapping):
            raise ShapeError(f"prop: {where} is {node!r}, not a shape")
        return self.build(node, where)


def _int_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of an int of the stated width and signedness."""
    del reader
    width = _int(node, "width", where)
    signed = node["signed"]
    if width not in INT_WIDTHS or not isinstance(signed, bool):
        raise ShapeError(f"prop: {where} states width {width!r} and signed {signed!r}")
    if signed:
        widest = (-(1 << (width - 1)), (1 << (width - 1)) - 1)
    else:
        widest = (0, (1 << width) - 1)
    lo, hi = _range(node, where, widest, literal.integer)
    if width == WIDE:
        return Int128Shape(lo, hi)
    return Integer(IntegerBounds(lo, hi))


def _float_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a float of the stated width."""
    del reader
    width = _int(node, "width", where)
    if width not in FLOAT_MAX:
        raise ShapeError(f"prop: {where}.width is {width}, not 32 or 64")
    allow_nan = node.get("allow_nan", False)
    infinite = node.get("allow_infinity", False)
    if not isinstance(allow_nan, bool) or not isinstance(infinite, bool):
        raise ShapeError(
            f"prop: {where} states allow_nan or allow_infinity as no boolean"
        )
    edge = math.inf if infinite else FLOAT_MAX[width]
    lo = literal.number(node["min"]) if node.get("min") is not None else -edge
    hi = literal.number(node["max"]) if node.get("max") is not None else edge
    if infinite and not (math.isinf(lo) or math.isinf(hi)):
        raise ShapeError(f"prop: {where} allows the infinities and bounds out both")
    return Float(FloatBounds(lo, hi, allow_nan, width))


def _alphabet(node: Node, where: str) -> tuple[str | None, int]:
    """Return a stated alphabet and its size, or None and the default's size.

    Raises:
        ShapeError: the alphabet is empty, repeats a character, or is not
            made of Unicode scalar values.
    """
    characters = node.get("alphabet")
    if characters is None:
        return None, alphabet.SIZE
    if not isinstance(characters, str) or not characters:
        raise ShapeError(f"prop: {where}.alphabet is {characters!r}, not characters")
    if len(set(characters)) != len(characters):
        raise ShapeError(f"prop: {where}.alphabet repeats a character")
    for char in characters:
        alphabet.index(char)
    return characters, len(characters)


def _char_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of one character of the alphabet."""
    del reader
    characters, size = _alphabet(node, where)
    return String(characters, SequenceBounds(size, 1, 1))


def _string_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a string: over an alphabet, or matching a pattern."""
    del reader
    if "pattern" in node:
        if set(node) & {"alphabet", "min_size", "max_size"}:
            raise ShapeError(
                f"prop: {where} states a pattern and an alphabet or a size"
            )
        text = node["pattern"]
        if not isinstance(text, str):
            raise ShapeError(f"prop: {where}.pattern is {text!r}, not a pattern")
        return StringMatching(pattern.parse(text))
    characters, size = _alphabet(node, where)
    sizes = _sizes(node, where)
    return String(characters, SequenceBounds(size, sizes.min_size, sizes.max_size))


def _bytes_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a byte string."""
    del reader
    sizes = _sizes(node, where)
    return BytesGenerator(SequenceBounds(BYTE_VALUES, sizes.min_size, sizes.max_size))


def _list_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a list, a fixed-list or a set."""
    kind = node["shape"]
    of = reader.child(node["of"], f"{where}.of")
    if kind == "fixed-list":
        size = _count(node, "size", where)
        if size is None:
            raise ShapeError(f"prop: {where} is a fixed-list and states no size")
        sizes = Sizes(size, size)
    else:
        sizes = _sizes(node, where)
    exits = kind != "fixed-list" and reader.exits(node) and reader.refers_back(node)
    return ListShape(of, sizes, kind == "set", exits, reader.budget)


def _map_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a map from keys to values."""
    key = reader.child(node["key"], f"{where}.key")
    of = reader.child(node["of"], f"{where}.of")
    exits = reader.exits(node) and reader.refers_back(node)
    return MapShape(key, of, _sizes(node, where), exits, reader.budget)


def _optional_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of an optional value."""
    of = reader.child(node["of"], f"{where}.of")
    return OptionalShape(of, reader.refers_back(node), reader.budget)


def _pairs(node: Node, key: str, where: str) -> list[tuple[str, object]]:
    """Return a list of name and value pairs with distinct, non-empty names.

    Raises:
        ShapeError: the list is empty, an item is not a pair, or a name is
            empty or repeated.
    """
    items = node[key]
    if not isinstance(items, list) or not items:
        raise ShapeError(f"prop: {where}.{key} is {items!r}, not a list of pairs")
    pairs: list[tuple[str, object]] = []
    for item in items:
        if not (
            isinstance(item, list) and len(item) == PAIR and isinstance(item[0], str)
        ):
            raise ShapeError(
                f"prop: {where}.{key} has {item!r}, not a name and a shape"
            )
        if not item[0] or item[0] in (name for name, _ in pairs):
            raise ShapeError(
                f"prop: {where}.{key} names {item[0]!r} twice or not at all"
            )
        pairs.append((item[0], item[1]))
    return pairs


def _record_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a record of named fields."""
    return RecordShape(
        tuple(
            (name, reader.child(of, f"{where}.{name}"))
            for name, of in _pairs(node, "fields", where)
        )
    )


def _enum_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of an enum of named variants with optional payloads."""
    variants = tuple(
        (name, None if of is None else reader.child(of, f"{where}.{name}"))
        for name, of in _pairs(node, "variants", where)
    )
    exit_index = reader.exit_variant(node) if reader.refers_back(node) else None
    return EnumShape(variants, exit_index, reader.budget)


def _literal_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of one of the stated values."""
    del reader
    values = node["values"]
    if not isinstance(values, list) or not values:
        raise ShapeError(f"prop: {where}.values is {values!r}, not a list of literals")
    return SampledFrom(tuple(literal.decode(v) for v in values))


def _ref_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a named definition.

    The reader has refused every ref that names no definition before it
    builds any shape.
    """
    del where
    name = str(node["name"])
    return Ref(name, reader.built, name in reader.cyclic, reader.budget)


def _ip_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of an IP address of one version or either."""
    del reader
    version = node.get("version")
    if version is None:
        return IpShape((fixed_bytes(ADDRESS_BYTES[4]), fixed_bytes(ADDRESS_BYTES[6])))
    if version not in ADDRESS_BYTES:
        raise ShapeError(f"prop: {where}.version is {version!r}, not 4 or 6")
    return fixed_bytes(ADDRESS_BYTES[version])


def _decimal_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a decimal's unscaled value at the stated scale.

    A bound with more digits than the scale rounds inward.
    """
    del reader
    scale = _count(node, "scale", where)
    if scale is None:
        raise ShapeError(f"prop: {where} is a decimal and states no scale")
    factor = 10**scale

    def bound(key: str, rounding: Callable[[Fraction], int]) -> int | None:
        text = node.get(key)
        if text is None:
            return None
        if not isinstance(text, str) or not DECIMAL.match(text):
            raise ShapeError(f"prop: {where}.{key} is {text!r}, not a decimal")
        return rounding(Fraction(text) * factor)

    unscaled = {"min": bound("min", math.ceil), "max": bound("max", math.floor)}
    return Integer(_bounded(unscaled, where, (INT64_MIN, INT64_MAX), int))


def _instant(reader: _Reader, node: Node, where: str) -> InstantShape:
    """Return the generator of an instant at the stated unit."""
    del reader
    per = _unit(node, where)

    def parse(text: object) -> tuple[int, int]:
        match = DATE_TIME.match(text) if isinstance(text, str) else None
        if match is None or match[8] != "Z":
            raise ShapeError(f"prop: {where} bound {text!r} is no instant in UTC")
        day = _day(match[1], match[2], match[3], where)
        seconds = day * SECONDS_PER_DAY + _time(match[4], match[5], match[6], where)
        return seconds, _fraction_units(match[7], per, where)

    default = ((FIRST_SECOND, 0), (LAST_SECOND, per - 1))
    lo, hi = _pair_bounds(node, where, default, parse)
    return InstantShape(per, lo, hi)


def _date_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a date, in days since 1970-01-01."""
    del reader

    def parse(text: object) -> int:
        match = DATE.match(text) if isinstance(text, str) else None
        if match is None:
            raise ShapeError(f"prop: {where} bound {text!r} is no date")
        return _day(match[1], match[2], match[3], where)

    return Integer(_bounded(node, where, (FIRST_DAY, LAST_DAY), parse))


def _time_of_day_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a time of day, in units since midnight."""
    del reader
    per = _unit(node, where)

    def parse(text: object) -> int:
        match = TIME.match(text) if isinstance(text, str) else None
        if match is None:
            raise ShapeError(f"prop: {where} bound {text!r} is no time of day")
        seconds = _time(match[1], match[2], match[3], where)
        return seconds * per + _fraction_units(match[4], per, where)

    return Integer(_bounded(node, where, (0, SECONDS_PER_DAY * per - 1), parse))


def _local_date_time(reader: _Reader, node: Node, where: str) -> LocalDateTimeShape:
    """Return the generator of a date and a time of day without a zone."""
    del reader
    per = _unit(node, where)

    def parse(text: object) -> tuple[int, int]:
        match = DATE_TIME.match(text) if isinstance(text, str) else None
        if match is None or match[8]:
            raise ShapeError(f"prop: {where} bound {text!r} is no local date and time")
        day = _day(match[1], match[2], match[3], where)
        seconds = _time(match[4], match[5], match[6], where)
        return day, seconds * per + _fraction_units(match[7], per, where)

    default = ((FIRST_DAY, 0), (LAST_DAY, SECONDS_PER_DAY * per - 1))
    lo, hi = _pair_bounds(node, where, default, parse)
    return LocalDateTimeShape(per, lo, hi)


def _duration_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a duration, in units."""
    del reader
    largest = MAX_DURATION_NS // (UNITS["ns"] // _unit(node, where))
    return Integer(_bounded(node, where, (-largest, largest), literal.integer))


def _offset_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of an offset from UTC, in seconds east of it."""
    del reader
    return Integer(_bounded(node, where, (-MAX_OFFSET, MAX_OFFSET), literal.integer))


def _zone_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a zone of the list, by name."""
    del reader, node, where
    return SampledFrom(tuple(zone.name for zone in zones()))


def _zoned_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of an instant in a zone."""
    return ZonedShape(_instant(reader, {"unit": node["unit"]}, where))


def _wall_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a wall time in a zone."""
    return WallShape(_local_date_time(reader, {"unit": node["unit"]}, where))


def _bool_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a boolean, true with probability 1/2."""
    del reader, node, where
    return Boolean(Fraction(1, 2))


def _uuid_shape(reader: _Reader, node: Node, where: str) -> Generator:
    """Return the generator of a UUID's 16 bytes."""
    del reader, node, where
    return fixed_bytes(UUID_BYTES)


#: The builder of each shape, by id.
_BUILDERS: Final[dict[str, Callable[[_Reader, Node, str], Generator]]] = {
    "bool": _bool_shape,
    "int": _int_shape,
    "float": _float_shape,
    "char": _char_shape,
    "string": _string_shape,
    "bytes": _bytes_shape,
    "list": _list_shape,
    "fixed-list": _list_shape,
    "set": _list_shape,
    "map": _map_shape,
    "optional": _optional_shape,
    "record": _record_shape,
    "enum": _enum_shape,
    "literal": _literal_shape,
    "ref": _ref_shape,
    "uuid": _uuid_shape,
    "ip-address": _ip_shape,
    "decimal": _decimal_shape,
    "instant": _instant,
    "date": _date_shape,
    "time-of-day": _time_of_day_shape,
    "local-date-time": _local_date_time,
    "duration": _duration_shape,
    "offset": _offset_shape,
    "zone": _zone_shape,
    "zoned-date-time": _zoned_shape,
    "wall-time": _wall_shape,
}
