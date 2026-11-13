# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""Running a generator backwards: the choices that decode to a given value.

invert() walks a generator with a value and emits each choice in the order
the generator's decode asks for it, with the bounds it asks with. Each
choice is checked against its bounds as it is emitted. invert() then
replays the choices, and returns them only when they decode to the value
and the case records them unchanged. A value the generator cannot produce
raises CannotInvert: a value of another type, one outside its bounds, a
collection of another size, or a set or a map with a repeated element.

Every generator of the vocabulary but map, and every shape, runs
backwards, and a filter does through the generator it filters. map and
bind apply a function the engine cannot invert, so a generator built with
one of them does not run backwards. Its refusal is NoInverse, which tells
it from a value outside a domain: a one-of and a recursive report
NoInverse when no branch produces the value and one of them has no
inverse, and every other generator passes on the refusal of the generator
inside it.

A composite runs backwards to a Placeholder, which makes no choice. In a
trace the draws of the composite take their own entries, so
invert_through() returns the choices of the generator around its
composites. invert() refuses a value through a composite with NoInverse,
because no trace serves the draws of the composite there. A filter does
not test the value of a composite, and a unique list does not compare
values through one, because the record of a composite may not state the
parts that the predicate or the comparison reads. A dict through a
composite does not run backwards: the value of a map does not state the
order in which the case drew its entries, which the draws of the
composites follow.

Where more than one sequence of choices decodes to a value, the inverse
takes the first in a fixed order:

- one-of: its first alternative whose inverse succeeds without a
  composite, and else its first alternative through a composite.
- sampled-from: the first index of an equal value.
- permutation: the smallest index at each swap.
- string-matching: the match that a backtracking engine finds first, which
  tries alternatives in order and repeats each quantifier as often as the
  rest of the pattern allows. The search is exponential in the worst case,
  as a backtracking engine's is.
- optional: absent before present, so an absent optional of an optional
  is absent at the outer one.
- recursive: the base before the extension, by the rule of a one-of.
- a set's elements and a map's entries: in the shortlex order of their own
  choices, as the element's generator emits them on its own.

A zoned-date-time and a wall-time run backwards through the branch that
takes the whole range, so a value at an offset change has the same one
sequence of choices as any other value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from . import alphabet, pattern
from .case import Case, Generator, Rejected, Replaying, Request
from .choice import Bounds, Choice, IntegerBounds, Value
from .draw import flag_bounds
from .generator import (
    Boolean,
    Bytes,
    Composite,
    Dict,
    Duration,
    Filter,
    Float,
    Integer,
    Just,
    List,
    OneOf,
    Optional,
    Permutation,
    Recursive,
    SampledFrom,
    Self,
    String,
    StringMatching,
)
from .shape import (
    HALF,
    LOW_MASK,
    SECONDS_PER_DAY,
    EnumShape,
    InstantShape,
    Int128Shape,
    IpShape,
    ListShape,
    LocalDateTimeShape,
    MapShape,
    OptionalShape,
    RecordShape,
    Ref,
    Root,
    WallShape,
    ZonedShape,
    second_part,
)
from .shrink import Node, choice_key
from .value import NO_PAYLOAD, Pairs, Record, Variant, as_type, canonical
from .zone import zones

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .collection import Sizes

#: The choice of a zoned-date-time or a wall-time whose zone has a change
#: that takes the whole range.
WHOLE_RANGE: Final = 0


class CannotInvert(ValueError):
    """A value that a generator cannot produce from any sequence of choices."""


class NoInverse(CannotInvert):
    """A value whose choices the engine cannot compute.

    A generator on the way applies a function that the engine cannot run
    backwards, so whether the generator produces the value is unknown.
    """


@dataclass(frozen=True)
class Step:
    """One emitted choice: the bounds its request states, and its value."""

    bounds: Bounds
    value: Value

    @property
    def choice(self) -> Choice:
        """Return the step as a recorded choice."""
        return Choice(self.bounds.kind, self.value)


@dataclass(frozen=True)
class Placeholder:
    """The place of a composite among the steps of a value.

    The composite makes no choice of its own. In a trace its draws take
    their own entries, and the steps after the placeholder serve the
    generator around the composite.
    """


#: The steps a generator emits for a value, and the value they decode to,
#: which differs from the given value only in the order of a set's
#: elements and a map's entries.
Emitted = tuple[Sequence[Step | Placeholder], object]


def invert(generator: Generator, value: object) -> tuple[Choice, ...]:
    """Return the choices that decode to value.

    Raises:
        NoInverse: a generator on the way applies a function that the
            engine cannot run backwards, or value runs backwards through a
            composite, whose draws no trace serves here.
        CannotInvert: the generator cannot produce value.
    """
    steps, normal = emit(generator, value)
    return _verified(generator, value, _chosen(steps), normal)


def invert_through(
    generator: Generator, value: object
) -> tuple[tuple[Choice, ...], bool]:
    """Return the choices of generator around its composites, and whether value has one.

    A composite inside generator makes no choice, and its draws take their
    own entries in a trace. A value without a composite has the choices of
    invert(). A value through a composite is not replayed here, because
    the draws of the composite need the entries of the trace.

    Raises:
        NoInverse: a generator on the way applies a function that the
            engine cannot run backwards.
        CannotInvert: the generator cannot produce value.
    """
    steps, normal = emit(generator, value)
    if any(isinstance(step, Placeholder) for step in steps):
        return tuple(step.choice for step in steps if isinstance(step, Step)), True
    return _verified(generator, value, _chosen(steps), normal), False


def through_composite(generator: Generator) -> bool:
    """Report whether generator has a composite inside a generator with an inverse.

    A one-of, an optional, a list, a dict, a filter and a recursive count, at
    any depth. A composite on its own does not, and a map or a bind does not
    either, because neither runs backwards.
    """
    return not isinstance(generator, Composite) and _holds_composite(generator, set())


def _holds_composite(generator: Generator, seen: set[int]) -> bool:
    """Report whether generator is a composite or has one inside, at any depth.

    seen holds the recursive generators on the way, so a self inside the
    extension of a recursive ends the walk.
    """
    if isinstance(generator, Composite):
        return True
    return any(_holds_composite(inner, seen) for inner in _inner(generator, seen))


def _inner(generator: Generator, seen: set[int]) -> tuple[Generator, ...]:
    """Return the generators inside generator that run backwards with it.

    A recursive that seen holds returns none, and joins seen otherwise.
    """
    if isinstance(generator, OneOf):
        return tuple(generator.of)
    if isinstance(generator, Optional | List | Filter):
        return (generator.of,)
    if isinstance(generator, Dict):
        return (generator.keys, generator.values)
    if isinstance(generator, Self):
        return (generator.owner,)
    if isinstance(generator, Recursive) and id(generator) not in seen:
        seen.add(id(generator))
        return (generator.base, generator.extend)
    return ()


def _chosen(steps: Sequence[Step | Placeholder]) -> list[Step]:
    """Return steps that make a choice each.

    Raises:
        NoInverse: a step is the placeholder of a composite.
    """
    chosen = [step for step in steps if isinstance(step, Step)]
    if len(chosen) != len(steps):
        msg = "prop: Composite does not run backwards"
        raise NoInverse(msg)
    return chosen


def _verified(
    generator: Generator, value: object, steps: Sequence[Step], normal: object
) -> tuple[Choice, ...]:
    """Return the choices of steps once they decode to normal and record unchanged.

    Raises:
        CannotInvert: the choices decode to another value, or to no value.
    """
    choices = [step.choice for step in steps]
    case = Case(Replaying(choices))
    try:
        decoded = generator.decode(case)
    except Rejected as rejected:
        msg = f"prop: {value!r} decodes to no value"
        raise CannotInvert(msg) from rejected
    if case.choices != choices or canonical(decoded) != canonical(normal):
        msg = f"prop: {value!r} is not a value the generator produces"
        raise CannotInvert(msg)
    return tuple(choices)


def emit(generator: Generator, value: object) -> Emitted:
    """Return the steps one generator emits for value, each within its bounds.

    Raises:
        CannotInvert: a step falls outside its bounds, or the value is of a
            type the generator never decodes.
        NoInverse: the generator applies a function it cannot run backwards.
    """
    emitter = _EMITTERS.get(type(generator))
    if emitter is None:
        msg = f"prop: {type(generator).__name__} does not run backwards"
        raise NoInverse(msg)
    return emitter(generator, value)


def _step(bounds: Bounds, value: object) -> Step:
    """Return a step whose value its bounds admit.

    Raises:
        CannotInvert: the bounds do not admit value.
    """
    if not bounds.admits(value) or not isinstance(value, int | float | tuple):
        msg = f"prop: {value!r} is outside {bounds}"
        raise CannotInvert(msg)
    return Step(bounds, value)


def _emit_number(generator: Integer | Duration | Float, value: object) -> Emitted:
    """Return an integer's or a float's one choice: the value itself."""
    return [_step(generator.bounds, value)], value


def _emit_boolean(generator: Boolean, value: object) -> Emitted:
    """Return a boolean's one choice: 1 for true and 0 for false."""
    del generator
    if not isinstance(value, bool):
        msg = f"prop: {value!r} is not a boolean"
        raise CannotInvert(msg)
    return [Step(IntegerBounds(0, 1), 1 if value else 0)], value


def _emit_just(generator: Just, value: object) -> Emitted:
    """Return no choice, for the one value just decodes."""
    if canonical(value) != canonical(generator.value):
        msg = f"prop: {value!r} is not {generator.value!r}"
        raise CannotInvert(msg)
    return [], value


def _index_of(values: Sequence[object], value: object) -> int:
    """Return the first index of an equal value.

    Raises:
        CannotInvert: no value is equal.
    """
    wanted = canonical(value)
    for index, candidate in enumerate(values):
        if canonical(candidate) == wanted:
            return index
    msg = f"prop: {value!r} is none of the values"
    raise CannotInvert(msg)


def _emit_sampled_from(generator: SampledFrom, value: object) -> Emitted:
    """Return the index of the first equal value."""
    values: tuple[object, ...] = generator.values
    index = _index_of(values, value)
    return [Step(IntegerBounds(0, len(values) - 1), index)], value


def _first_branch(
    branches: Sequence[tuple[int, Generator]],
    value: object,
    bounds: IntegerBounds,
    refusal: str,
) -> Emitted:
    """Return the index of the first branch that produces value, then its steps.

    A branch through a composite produces every value, so it counts only
    when no branch produces value without one. refusal is the reason of
    the refusal when no branch produces value.

    Raises:
        NoInverse: no branch produces value, and one of them has no inverse.
        CannotInvert: no branch produces value.
    """
    unknown = False
    through: Emitted | None = None
    for index, branch in branches:
        try:
            steps, normal = emit(branch, value)
        except NoInverse:
            unknown = True
            continue
        except CannotInvert:
            continue
        emitted: Emitted = ([Step(bounds, index), *steps], normal)
        if not any(isinstance(step, Placeholder) for step in steps):
            return emitted
        if through is None:
            through = emitted
    if through is not None:
        return through
    if unknown:
        msg = f"prop: {refusal}, and one of them has no inverse"
        raise NoInverse(msg)
    msg = f"prop: {refusal}"
    raise CannotInvert(msg)


def _emit_one_of(generator: OneOf, value: object) -> Emitted:
    """Return the index of the first alternative that produces value, then its steps."""
    alternatives: tuple[Generator, ...] = generator.of
    bounds = IntegerBounds(0, len(alternatives) - 1)
    refusal = f"no alternative produces {value!r}"
    return _first_branch(list(enumerate(alternatives)), value, bounds, refusal)


def _emit_optional(generator: Optional | OptionalShape, value: object) -> Emitted:
    """Return absent, or present and then the value's steps."""
    if value is None:
        return [Step(IntegerBounds(0, 1), 0)], None
    steps, normal = emit(generator.of, value)
    return [Step(IntegerBounds(0, 1), 1), *steps], normal


def no_draw(source: object) -> Value:
    """Draw nothing: a step's request is read for its bounds alone.

    Raises:
        AssertionError: always, because nothing draws an inverse's step.
    """
    msg = f"prop: an inverse's step does not draw from {source!r}"
    raise AssertionError(msg)


def _shortlex(steps: Sequence[Step]) -> tuple[int, tuple[tuple[int, ...], ...]]:
    """Return the shortlex key of steps, as the shrinker orders choice sequences."""
    keys = tuple(
        choice_key(Node(Request(step.bounds, no_draw), step.choice)) for step in steps
    )
    return (len(steps), keys)


def _collection(
    sizes: Sizes, items: Sequence[Sequence[Step | Placeholder]]
) -> list[Step | Placeholder]:
    """Return a collection's steps: per item a continue flag and its steps, then a stop.

    Raises:
        CannotInvert: the collection has fewer or more items than its sizes.
    """
    count = len(items)
    if count < sizes.min_size or (
        sizes.max_size is not None and count > sizes.max_size
    ):
        msg = f"prop: {count} items are outside the collection's sizes"
        raise CannotInvert(msg)
    steps: list[Step | Placeholder] = []
    for index, item in enumerate(items):
        steps.append(Step(flag_bounds(index, sizes.min_size, sizes.max_size), 1))
        steps.extend(item)
    steps.append(Step(flag_bounds(count, sizes.min_size, sizes.max_size), 0))
    return steps


def _distinct(values: Sequence[object]) -> None:
    """Refuse values with two equal ones.

    Raises:
        CannotInvert: two values are equal.
    """
    if len({canonical(value) for value in values}) != len(values):
        msg = f"prop: {list(values)!r} repeats a value"
        raise CannotInvert(msg)


def _elements(of: Generator, value: object, *, unique: bool) -> list[Emitted]:
    """Return each element's steps and the value they decode to.

    A unique list compares the elements without a composite alone, because
    the record of a composite may not state its value.

    Raises:
        CannotInvert: value is not a list, or repeats an element of a unique one.
    """
    if not isinstance(value, list):
        msg = f"prop: {value!r} is not a list"
        raise CannotInvert(msg)
    elements = [emit(of, element) for element in value]
    if unique:
        _distinct(
            [
                element
                for element, (steps, _) in zip(value, elements, strict=True)
                if not any(isinstance(step, Placeholder) for step in steps)
            ]
        )
    return elements


def _emit_list(generator: List, value: object) -> Emitted:
    """Return a list's flags and elements, in the list's order."""
    elements = _elements(generator.of, value, unique=generator.unique)
    steps = _collection(generator.sizes, [element for element, _ in elements])
    return steps, [normal for _, normal in elements]


def _emit_list_shape(generator: ListShape, value: object) -> Emitted:
    """Return a list's or a set's flags and elements, a set's in shortlex order."""
    elements = _elements(generator.of, value, unique=generator.unique)
    if generator.unique:
        elements.sort(key=lambda element: _shortlex(_chosen(element[0])))
    steps = _collection(generator.sizes, [element for element, _ in elements])
    return steps, [normal for _, normal in elements]


def _entries(
    generator: Dict | MapShape, key: Generator, of: Generator, value: object
) -> Emitted:
    """Return a map's flags and entries, each its key's steps then its value's.

    The entries are in shortlex order.

    Raises:
        CannotInvert: value is not a map, or repeats a key.
        NoInverse: a key or a value runs backwards through a composite. The
            value of a map does not state the order in which the case drew
            its entries, and the draws of the composites follow that order.
    """
    if not isinstance(value, Pairs):
        msg = f"prop: {value!r} is not a map"
        raise CannotInvert(msg)
    _distinct([entry_key for entry_key, _ in value.items])
    entries: list[tuple[list[Step], tuple[object, object]]] = []
    for entry_key, entry_value in value.items:
        key_steps, key_normal = emit(key, entry_key)
        value_steps, value_normal = emit(of, entry_value)
        steps = [*key_steps, *value_steps]
        if any(isinstance(step, Placeholder) for step in steps):
            msg = "prop: a map does not state the order in which its composites drew"
            raise NoInverse(msg)
        entries.append((_chosen(steps), (key_normal, value_normal)))
    entries.sort(key=lambda entry: _shortlex(entry[0]))
    steps = _collection(generator.sizes, [entry for entry, _ in entries])
    return steps, Pairs(tuple(normal for _, normal in entries))


def _emit_dict(generator: Dict, value: object) -> Emitted:
    """Return a dict's flags and entries, in shortlex order."""
    return _entries(generator, generator.keys, generator.values, value)


def _emit_map_shape(generator: MapShape, value: object) -> Emitted:
    """Return a map shape's flags and entries, in shortlex order."""
    return _entries(generator, generator.key, generator.of, value)


def _emit_string(generator: String, value: object) -> Emitted:
    """Return a string's one sequence: the index of each character in its alphabet."""
    if not isinstance(value, str):
        msg = f"prop: {value!r} is not a string"
        raise CannotInvert(msg)
    characters: str | None = generator.characters
    try:
        if characters is None:
            indices = tuple(alphabet.index(char) for char in value)
        else:
            indices = tuple(characters.index(char) for char in value)
    except ValueError as bad:
        msg = f"prop: {value!r} has a character outside the alphabet"
        raise CannotInvert(msg) from bad
    return [_step(generator.bounds, indices)], value


def _emit_bytes(generator: Bytes, value: object) -> Emitted:
    """Return a byte string's one sequence: its bytes."""
    if not isinstance(value, bytes):
        msg = f"prop: {value!r} is not bytes"
        raise CannotInvert(msg)
    return [_step(generator.bounds, tuple(value))], value


def _emit_permutation(generator: Permutation, value: object) -> Emitted:
    """Return the smallest index at each swap that orders the values as value is."""
    current = list(generator.values)
    if not isinstance(value, list) or len(value) != len(current):
        msg = f"prop: {value!r} is not a permutation of the values"
        raise CannotInvert(msg)
    steps: list[Step] = []
    last = len(current) - 1
    for i in range(last):
        j = i + _index_of(current[i:], value[i])
        steps.append(Step(IntegerBounds(i, last), j))
        current[i], current[j] = current[j], current[i]
    if canonical(current) != canonical(value):
        msg = f"prop: {value!r} is not a permutation of the values"
        raise CannotInvert(msg)
    return steps, value


def _emit_filter(generator: Filter, value: object) -> Emitted:
    """Return the steps of the source, for a value the predicate keeps.

    A value through a composite is not tested, because the record of a
    composite may not state the parts that the predicate reads. The decode
    still filters the value that the composite returns.

    Raises:
        CannotInvert: the predicate rejects value.
    """
    steps, normal = emit(generator.of, value)
    if any(isinstance(step, Placeholder) for step in steps):
        return steps, normal
    keep: Callable[[object], bool] = generator.keep
    if not keep(value):
        msg = f"prop: the filter rejects {value!r}"
        raise CannotInvert(msg)
    return steps, normal


def _emit_composite(generator: Composite, value: object) -> Emitted:
    """Return the placeholder of a composite, whose own draws state its value."""
    del generator
    return [Placeholder()], value


def _emit_recursive(generator: Recursive, value: object) -> Emitted:
    """Return one position of a recursive value: the base, or else the extension."""
    branches = [(0, generator.base), (1, generator.extend)]
    refusal = f"neither the base nor the extension produces {value!r}"
    return _first_branch(branches, value, IntegerBounds(0, 1), refusal)


def _emit_self(generator: Self, value: object) -> Emitted:
    """Return a position of the recursive value that the extension refers to."""
    return _emit_recursive(generator.owner, value)


def _emit_root(generator: Root, value: object) -> Emitted:
    """Return the steps of the root shape."""
    return emit(generator.node, value)


def _emit_ref(generator: Ref, value: object) -> Emitted:
    """Return the steps of the named definition."""
    return emit(generator.definitions[generator.name], value)


def _emit_record(generator: RecordShape, value: object) -> Emitted:
    """Return each field's steps, in declaration order.

    Raises:
        CannotInvert: value is not a record with the shape's fields in order.
    """
    fields: tuple[tuple[str, Generator], ...] = generator.fields
    names = [name for name, _ in fields]
    if not isinstance(value, Record) or [name for name, _ in value.fields] != names:
        msg = f"prop: {value!r} is not a record of {names}"
        raise CannotInvert(msg)
    steps: list[Step | Placeholder] = []
    normal: list[tuple[str, object]] = []
    for (name, of), (_, field) in zip(fields, value.fields, strict=True):
        field_steps, field_normal = emit(of, field)
        steps.extend(field_steps)
        normal.append((name, field_normal))
    return steps, Record(tuple(normal))


def _emit_enum(generator: EnumShape, value: object) -> Emitted:
    """Return the variant's index, then its payload's steps.

    Raises:
        CannotInvert: value is not a variant of the enum, or its payload is
            present where the variant has none.
    """
    variants: tuple[tuple[str, Generator | None], ...] = generator.variants
    names = [name for name, _ in variants]
    if not isinstance(value, Variant) or value.name not in names:
        msg = f"prop: {value!r} is no variant of {names}"
        raise CannotInvert(msg)
    index = names.index(value.name)
    payload = variants[index][1]
    head = Step(IntegerBounds(0, len(variants) - 1), index)
    if payload is None:
        if value.payload is not NO_PAYLOAD:
            msg = f"prop: the variant {value.name!r} has no payload"
            raise CannotInvert(msg)
        return [head], value
    steps, normal = emit(payload, value.payload)
    return [head, *steps], Variant(value.name, normal)


def _emit_int128(generator: Int128Shape, value: object) -> Emitted:
    """Return the high half, then the low half."""
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"prop: {value!r} is not an integer"
        raise CannotInvert(msg)
    lo = (generator.lo >> HALF, generator.lo & LOW_MASK)
    hi = (generator.hi >> HALF, generator.hi & LOW_MASK)
    high, low = value >> HALF, value & LOW_MASK
    high_step = _step(IntegerBounds(lo[0], hi[0]), high)
    return [high_step, _step(second_part(high, lo, hi, LOW_MASK), low)], value


def _two_parts(value: object, names: tuple[str, str]) -> tuple[object, object]:
    """Return the two fields of a record of a two-choice shape.

    Raises:
        CannotInvert: value is not a record of those two fields.
    """
    if not isinstance(value, Record) or [n for n, _ in value.fields] != list(names):
        msg = f"prop: {value!r} is not a record of {list(names)}"
        raise CannotInvert(msg)
    first, second = (part for _, part in value.fields)
    return first, second


def _emit_instant(shape: InstantShape, value: object) -> Emitted:
    """Return the seconds, then the units within the second below a unit of s."""
    seconds, units = _two_parts(value, ("seconds", "units"))
    steps = [_step(IntegerBounds(shape.lo[0], shape.hi[0]), seconds)]
    if shape.per == 1:
        if units != 0:
            msg = f"prop: an instant at seconds has no units, not {units!r}"
            raise CannotInvert(msg)
        return steps, value
    bounds = second_part(as_type(seconds, int), shape.lo, shape.hi, shape.per - 1)
    return [*steps, _step(bounds, units)], value


def _emit_local(shape: LocalDateTimeShape, value: object) -> Emitted:
    """Return the date, then the time of day."""
    day, time = _two_parts(value, ("date", "time-of-day"))
    day_step = _step(IntegerBounds(shape.lo[0], shape.hi[0]), day)
    top = SECONDS_PER_DAY * shape.per - 1
    bounds = second_part(as_type(day, int), shape.lo, shape.hi, top)
    return [day_step, _step(bounds, time)], value


def _zone_steps(value: object, part: str) -> tuple[list[Step], object]:
    """Return the zone's index and the whole-range choice, and the other part.

    Raises:
        CannotInvert: value is not a record of part and a zone of the list.
    """
    inner, name = _two_parts(value, (part, "zone"))
    listed = zones()
    index = _index_of([zone.name for zone in listed], name)
    steps = [Step(IntegerBounds(0, len(listed) - 1), index)]
    if listed[index].changes:
        steps.append(Step(IntegerBounds(0, 1), WHOLE_RANGE))
    return steps, inner


def _emit_zoned(generator: ZonedShape, value: object) -> Emitted:
    """Return the zone, the whole-range choice when it has one, then the instant."""
    steps, instant = _zone_steps(value, "instant")
    inner, _ = emit(generator.instant, instant)
    return [*steps, *inner], value


def _emit_wall(generator: WallShape, value: object) -> Emitted:
    """Return the zone, the whole-range choice when it has one, then the local value."""
    steps, local = _zone_steps(value, "local-date-time")
    inner, _ = emit(generator.local, local)
    return [*steps, *inner], value


def _emit_ip(generator: IpShape, value: object) -> Emitted:
    """Return the version's index, then the address's bytes."""
    versions: tuple[Bytes, Bytes] = generator.versions
    if not isinstance(value, bytes):
        msg = f"prop: {value!r} is not an address"
        raise CannotInvert(msg)
    for index, version in enumerate(versions):
        if version.bounds.min_size == len(value):
            steps, _ = emit(version, value)
            return [Step(IntegerBounds(0, 1), index), *steps], value
    msg = f"prop: {value!r} is neither 4 nor 16 bytes"
    raise CannotInvert(msg)


def _class_offset(node: pattern.Class, char: str) -> int | None:
    """Return a character's offset among a class's members, or None."""
    position = alphabet.index(char)
    offset = 0
    for start, end in node.intervals:
        if start <= position <= end:
            return offset + position - start
        offset += end - start + 1
    return None


def _matches(node: object, text: str, at: int) -> Iterator[tuple[int, list[Step]]]:
    """Yield each way node matches text from at: where it ends, and its steps.

    The ways come in a backtracking engine's order: alternatives in order,
    and the most repetitions first.
    """
    if isinstance(node, pattern.Literal):
        if text.startswith(node.char, at):
            yield at + 1, []
    elif isinstance(node, pattern.Class):
        offset = _class_offset(node, text[at]) if at < len(text) else None
        if offset is not None:
            yield at + 1, [Step(IntegerBounds(0, node.size - 1), offset)]
    elif isinstance(node, pattern.Sequence):
        yield from _sequence(node.items, text, at)
    elif isinstance(node, pattern.Alternation):
        bounds = IntegerBounds(0, len(node.branches) - 1)
        for index, branch in enumerate(node.branches):
            for end, steps in _matches(branch, text, at):
                yield end, [Step(bounds, index), *steps]
    else:
        yield from _repeat(as_type(node, pattern.Repeat), text, at, 0)


def _sequence(
    items: Sequence[object], text: str, at: int
) -> Iterator[tuple[int, list[Step]]]:
    """Yield each way the items match one after another from at."""
    if not items:
        yield at, []
        return
    for middle, first in _matches(items[0], text, at):
        for end, rest in _sequence(items[1:], text, middle):
            yield end, [*first, *rest]


def _repeat(
    node: pattern.Repeat, text: str, at: int, count: int
) -> Iterator[tuple[int, list[Step]]]:
    """Yield each way the repetitions from count on match, the most first.

    A repetition that matches nothing is not repeated beyond the minimum,
    so the search ends.
    """
    sizes = node.sizes
    flag = flag_bounds(count, sizes.min_size, sizes.max_size)
    if flag.hi == 1:
        for middle, item in _matches(node.item, text, at):
            if middle == at and count >= sizes.min_size:
                continue
            for end, rest in _repeat(node, text, middle, count + 1):
                yield end, [Step(flag, 1), *item, *rest]
    if flag.lo == 0:
        yield at, [Step(flag, 0)]


def _emit_string_matching(generator: StringMatching, value: object) -> Emitted:
    """Return the steps of the first match of the whole string.

    Raises:
        CannotInvert: value is not a string the pattern matches in full.
    """
    if not isinstance(value, str):
        msg = f"prop: {value!r} is not a string"
        raise CannotInvert(msg)
    for end, steps in _matches(generator.node, value, 0):
        if end == len(value):
            return steps, value
    msg = f"prop: the pattern does not match {value!r} in full"
    raise CannotInvert(msg)


#: The inverse of each kind of generator, by its class.
_EMITTERS: Final[dict[type, Callable[[Any, object], Emitted]]] = {
    Integer: _emit_number,
    Duration: _emit_number,
    Float: _emit_number,
    Boolean: _emit_boolean,
    Just: _emit_just,
    SampledFrom: _emit_sampled_from,
    OneOf: _emit_one_of,
    Optional: _emit_optional,
    OptionalShape: _emit_optional,
    List: _emit_list,
    ListShape: _emit_list_shape,
    Dict: _emit_dict,
    MapShape: _emit_map_shape,
    String: _emit_string,
    Bytes: _emit_bytes,
    StringMatching: _emit_string_matching,
    Permutation: _emit_permutation,
    Filter: _emit_filter,
    Composite: _emit_composite,
    Recursive: _emit_recursive,
    Self: _emit_self,
    Root: _emit_root,
    Ref: _emit_ref,
    RecordShape: _emit_record,
    EnumShape: _emit_enum,
    Int128Shape: _emit_int128,
    InstantShape: _emit_instant,
    LocalDateTimeShape: _emit_local,
    ZonedShape: _emit_zoned,
    WallShape: _emit_wall,
    IpShape: _emit_ip,
}
