"""Running a generator backwards: the choices that decode to a given value.

invert() walks a generator with a value and emits each choice in the order
the generator's decode asks for it, with the bounds it asks with. Each
choice is checked against its bounds as it is emitted. invert() then
replays the choices, and returns them only when they decode to the value
and the case records them unchanged. A value the generator cannot produce
raises CannotInvert: a value of another type, one outside its bounds, a
collection of another size, or a set or a map with a repeated element.

Every generator of the vocabulary and every shape runs backwards, and a
filter does through the generator it filters. map, bind and composite
apply a function the engine cannot invert, so a language's generator
built with one of them does not run backwards.

Where more than one sequence of choices decodes to a value, the inverse
takes the first in a fixed order:

- one-of: its first alternative whose inverse succeeds.
- sampled-from: the first index of an equal value.
- permutation: the smallest index at each swap.
- string-matching: the match that a backtracking engine finds first, which
  tries alternatives in order and repeats each quantifier as often as the
  rest of the pattern allows. The search is exponential in the worst case,
  as a backtracking engine's is.
- optional: absent before present, so an absent optional of an optional
  is absent at the outer one.
- recursive: the base before the extension.
- a set's elements and a map's entries: in the shortlex order of their own
  choices, as the element's generator emits them on its own.

A zoned-date-time and a wall-time run backwards through the branch that
takes the whole range, so a value at an offset change has the same one
sequence of choices as any other value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from . import alphabet, pattern
from .case import Case, Generator, Rejected, Replaying, Request
from .choice import Bounds, Choice, IntegerBounds, Value
from .collection import Sizes
from .draw import flag_bounds
from .generator import (
    Boolean,
    Bytes,
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
from .value import NO_PAYLOAD, Pairs, Record, Variant, canonical
from .zone import zones

#: The choice of a zoned-date-time or a wall-time whose zone has a change
#: that takes the whole range.
WHOLE_RANGE: Final = 0


class CannotInvert(ValueError):
    """A value that a generator cannot produce from any sequence of choices."""


@dataclass(frozen=True)
class Step:
    """One emitted choice: the bounds its request states, and its value."""

    bounds: Bounds
    value: Value

    @property
    def choice(self) -> Choice:
        """Return the step as a recorded choice."""
        return Choice(self.bounds.kind, self.value)


#: The steps a generator emits for a value, and the value they decode to,
#: which differs from the given value only in the order of a set's
#: elements and a map's entries.
Emitted = tuple[list[Step], object]


def invert(generator: Generator, value: object) -> tuple[Choice, ...]:
    """Return the choices that decode to value.

    Raises:
        CannotInvert: the generator cannot produce value.
    """
    steps, normal = emit(generator, value)
    choices = [step.choice for step in steps]
    case = Case(Replaying(choices))
    try:
        decoded = generator.decode(case)
    except Rejected as rejected:
        raise CannotInvert(f"prop: {value!r} decodes to no value") from rejected
    if case.choices != choices or canonical(decoded) != canonical(normal):
        raise CannotInvert(f"prop: {value!r} is not a value the generator produces")
    return tuple(choices)


def emit(generator: Generator, value: object) -> Emitted:
    """Return the steps one generator emits for value, each within its bounds.

    Raises:
        CannotInvert: a step falls outside its bounds, the value is of a
            type the generator never decodes, or the generator applies a
            function it cannot run backwards.
    """
    emitter = _EMITTERS.get(type(generator))
    if emitter is None:
        raise CannotInvert(f"prop: {type(generator).__name__} does not run backwards")
    return emitter(generator, value)


def _step(bounds: Bounds, value: object) -> Step:
    """Return a step whose value its bounds admit.

    Raises:
        CannotInvert: the bounds do not admit value.
    """
    if not bounds.admits(value):
        raise CannotInvert(f"prop: {value!r} is outside {bounds}")
    assert isinstance(value, int | float | tuple)
    return Step(bounds, value)


def _emit_number(generator: Any, value: object) -> Emitted:
    """Return an integer's or a float's one choice: the value itself."""
    return [_step(generator.bounds, value)], value


def _emit_boolean(generator: Any, value: object) -> Emitted:
    """Return a boolean's one choice: 1 for true and 0 for false."""
    del generator
    if not isinstance(value, bool):
        raise CannotInvert(f"prop: {value!r} is not a boolean")
    return [Step(IntegerBounds(0, 1), 1 if value else 0)], value


def _emit_just(generator: Any, value: object) -> Emitted:
    """Return no choice, for the one value just decodes."""
    if canonical(value) != canonical(generator.value):
        raise CannotInvert(f"prop: {value!r} is not {generator.value!r}")
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
    raise CannotInvert(f"prop: {value!r} is none of the values")


def _emit_sampled_from(generator: Any, value: object) -> Emitted:
    """Return the index of the first equal value."""
    values: tuple[object, ...] = generator.values
    index = _index_of(values, value)
    return [Step(IntegerBounds(0, len(values) - 1), index)], value


def _emit_one_of(generator: Any, value: object) -> Emitted:
    """Return the index of the first alternative that produces value, then its steps."""
    alternatives: tuple[Generator, ...] = generator.of
    for index, alternative in enumerate(alternatives):
        try:
            steps, normal = emit(alternative, value)
        except CannotInvert:
            continue
        return [Step(IntegerBounds(0, len(alternatives) - 1), index), *steps], normal
    raise CannotInvert(f"prop: no alternative produces {value!r}")


def _emit_optional(generator: Any, value: object) -> Emitted:
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
    raise AssertionError(f"prop: an inverse's step does not draw from {source!r}")


def _shortlex(steps: Sequence[Step]) -> tuple[int, tuple[tuple[int, ...], ...]]:
    """Return the shortlex key of steps, as the shrinker orders choice sequences."""
    keys = tuple(
        choice_key(Node(Request(step.bounds, no_draw), step.choice)) for step in steps
    )
    return (len(steps), keys)


def _collection(sizes: Sizes, items: Sequence[list[Step]]) -> list[Step]:
    """Return a collection's steps: per item a continue flag and its steps, then a stop.

    Raises:
        CannotInvert: the collection has fewer or more items than its sizes.
    """
    count = len(items)
    if count < sizes.min_size or (
        sizes.max_size is not None and count > sizes.max_size
    ):
        raise CannotInvert(f"prop: {count} items are outside the collection's sizes")
    steps: list[Step] = []
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
        raise CannotInvert(f"prop: {list(values)!r} repeats a value")


def _elements(
    of: Generator, value: object, *, unique: bool
) -> list[tuple[list[Step], object]]:
    """Return each element's steps and the value they decode to.

    Raises:
        CannotInvert: value is not a list, or repeats an element of a unique one.
    """
    if not isinstance(value, list):
        raise CannotInvert(f"prop: {value!r} is not a list")
    if unique:
        _distinct(value)
    return [emit(of, element) for element in value]


def _emit_list(generator: Any, value: object) -> Emitted:
    """Return a list's flags and elements, in the list's order."""
    elements = _elements(generator.of, value, unique=generator.unique)
    steps = _collection(generator.sizes, [element for element, _ in elements])
    return steps, [normal for _, normal in elements]


def _emit_list_shape(generator: Any, value: object) -> Emitted:
    """Return a list's or a set's flags and elements, a set's in shortlex order."""
    elements = _elements(generator.of, value, unique=generator.unique)
    if generator.unique:
        elements.sort(key=lambda element: _shortlex(element[0]))
    steps = _collection(generator.sizes, [element for element, _ in elements])
    return steps, [normal for _, normal in elements]


def _entries(generator: Any, key: Generator, of: Generator, value: object) -> Emitted:
    """Return a map's flags and entries, each its key's steps then its value's.

    The entries are in shortlex order.

    Raises:
        CannotInvert: value is not a map, or repeats a key.
    """
    if not isinstance(value, Pairs):
        raise CannotInvert(f"prop: {value!r} is not a map")
    _distinct([entry_key for entry_key, _ in value.items])
    entries: list[tuple[list[Step], tuple[object, object]]] = []
    for entry_key, entry_value in value.items:
        key_steps, key_normal = emit(key, entry_key)
        value_steps, value_normal = emit(of, entry_value)
        entries.append(([*key_steps, *value_steps], (key_normal, value_normal)))
    entries.sort(key=lambda entry: _shortlex(entry[0]))
    steps = _collection(generator.sizes, [entry for entry, _ in entries])
    return steps, Pairs(tuple(normal for _, normal in entries))


def _emit_dict(generator: Any, value: object) -> Emitted:
    """Return a dict's flags and entries, in shortlex order."""
    return _entries(generator, generator.keys, generator.values, value)


def _emit_map_shape(generator: Any, value: object) -> Emitted:
    """Return a map shape's flags and entries, in shortlex order."""
    return _entries(generator, generator.key, generator.of, value)


def _emit_string(generator: Any, value: object) -> Emitted:
    """Return a string's one sequence: the index of each character in its alphabet."""
    if not isinstance(value, str):
        raise CannotInvert(f"prop: {value!r} is not a string")
    characters: str | None = generator.characters
    try:
        if characters is None:
            indices = tuple(alphabet.index(char) for char in value)
        else:
            indices = tuple(characters.index(char) for char in value)
    except ValueError as bad:
        raise CannotInvert(
            f"prop: {value!r} has a character outside the alphabet"
        ) from bad
    return [_step(generator.bounds, indices)], value


def _emit_bytes(generator: Any, value: object) -> Emitted:
    """Return a byte string's one sequence: its bytes."""
    if not isinstance(value, bytes):
        raise CannotInvert(f"prop: {value!r} is not bytes")
    return [_step(generator.bounds, tuple(value))], value


def _emit_permutation(generator: Any, value: object) -> Emitted:
    """Return the smallest index at each swap that orders the values as value is."""
    current = list(generator.values)
    if not isinstance(value, list) or len(value) != len(current):
        raise CannotInvert(f"prop: {value!r} is not a permutation of the values")
    steps: list[Step] = []
    last = len(current) - 1
    for i in range(last):
        j = i + _index_of(current[i:], value[i])
        steps.append(Step(IntegerBounds(i, last), j))
        current[i], current[j] = current[j], current[i]
    if canonical(current) != canonical(value):
        raise CannotInvert(f"prop: {value!r} is not a permutation of the values")
    return steps, value


def _emit_filter(generator: Any, value: object) -> Emitted:
    """Return the steps of the source, for a value the predicate keeps.

    Raises:
        CannotInvert: the predicate rejects value.
    """
    keep: Callable[[object], bool] = generator.keep
    if not keep(value):
        raise CannotInvert(f"prop: the filter rejects {value!r}")
    return emit(generator.of, value)


def _emit_recursive(generator: Any, value: object) -> Emitted:
    """Return one position of a recursive value: the base, or else the extension."""
    for index, branch in ((0, generator.base), (1, generator.extend)):
        try:
            steps, normal = emit(branch, value)
        except CannotInvert:
            continue
        return [Step(IntegerBounds(0, 1), index), *steps], normal
    raise CannotInvert(f"prop: neither the base nor the extension produces {value!r}")


def _emit_self(generator: Any, value: object) -> Emitted:
    """Return a position of the recursive value that the extension refers to."""
    return _emit_recursive(generator.owner, value)


def _emit_root(generator: Any, value: object) -> Emitted:
    """Return the steps of the root shape."""
    return emit(generator.node, value)


def _emit_ref(generator: Any, value: object) -> Emitted:
    """Return the steps of the named definition."""
    return emit(generator.definitions[generator.name], value)


def _emit_record(generator: Any, value: object) -> Emitted:
    """Return each field's steps, in declaration order.

    Raises:
        CannotInvert: value is not a record with the shape's fields in order.
    """
    fields: tuple[tuple[str, Generator], ...] = generator.fields
    names = [name for name, _ in fields]
    if not isinstance(value, Record) or [name for name, _ in value.fields] != names:
        raise CannotInvert(f"prop: {value!r} is not a record of {names}")
    steps: list[Step] = []
    normal: list[tuple[str, object]] = []
    for (name, of), (_, field) in zip(fields, value.fields, strict=True):
        field_steps, field_normal = emit(of, field)
        steps.extend(field_steps)
        normal.append((name, field_normal))
    return steps, Record(tuple(normal))


def _emit_enum(generator: Any, value: object) -> Emitted:
    """Return the variant's index, then its payload's steps.

    Raises:
        CannotInvert: value is not a variant of the enum, or its payload is
            present where the variant has none.
    """
    variants: tuple[tuple[str, Generator | None], ...] = generator.variants
    names = [name for name, _ in variants]
    if not isinstance(value, Variant) or value.name not in names:
        raise CannotInvert(f"prop: {value!r} is no variant of {names}")
    index = names.index(value.name)
    payload = variants[index][1]
    head = Step(IntegerBounds(0, len(variants) - 1), index)
    if payload is None:
        if value.payload is not NO_PAYLOAD:
            raise CannotInvert(f"prop: the variant {value.name!r} has no payload")
        return [head], value
    steps, normal = emit(payload, value.payload)
    return [head, *steps], Variant(value.name, normal)


def _emit_int128(generator: Any, value: object) -> Emitted:
    """Return the high half, then the low half."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise CannotInvert(f"prop: {value!r} is not an integer")
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
        raise CannotInvert(f"prop: {value!r} is not a record of {list(names)}")
    first, second = (part for _, part in value.fields)
    return first, second


def _emit_instant(generator: Any, value: object) -> Emitted:
    """Return the seconds, then the units within the second below a unit of s."""
    shape: InstantShape = generator
    seconds, units = _two_parts(value, ("seconds", "units"))
    steps = [_step(IntegerBounds(shape.lo[0], shape.hi[0]), seconds)]
    if shape.per == 1:
        if units != 0:
            raise CannotInvert(
                f"prop: an instant at seconds has no units, not {units!r}"
            )
        return steps, value
    assert isinstance(seconds, int)
    bounds = second_part(seconds, shape.lo, shape.hi, shape.per - 1)
    return [*steps, _step(bounds, units)], value


def _emit_local(generator: Any, value: object) -> Emitted:
    """Return the date, then the time of day."""
    shape: LocalDateTimeShape = generator
    day, time = _two_parts(value, ("date", "time-of-day"))
    day_step = _step(IntegerBounds(shape.lo[0], shape.hi[0]), day)
    assert isinstance(day, int)
    top = SECONDS_PER_DAY * shape.per - 1
    return [day_step, _step(second_part(day, shape.lo, shape.hi, top), time)], value


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


def _emit_zoned(generator: Any, value: object) -> Emitted:
    """Return the zone, the whole-range choice when it has one, then the instant."""
    steps, instant = _zone_steps(value, "instant")
    inner, _ = emit(generator.instant, instant)
    return [*steps, *inner], value


def _emit_wall(generator: Any, value: object) -> Emitted:
    """Return the zone, the whole-range choice when it has one, then the local value."""
    steps, local = _zone_steps(value, "local-date-time")
    inner, _ = emit(generator.local, local)
    return [*steps, *inner], value


def _emit_ip(generator: Any, value: object) -> Emitted:
    """Return the version's index, then the address's bytes."""
    versions: tuple[Bytes, Bytes] = generator.versions
    if not isinstance(value, bytes):
        raise CannotInvert(f"prop: {value!r} is not an address")
    for index, version in enumerate(versions):
        if version.bounds.min_size == len(value):
            steps, _ = emit(version, value)
            return [Step(IntegerBounds(0, 1), index), *steps], value
    raise CannotInvert(f"prop: {value!r} is neither 4 nor 16 bytes")


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
        assert isinstance(node, pattern.Repeat)
        yield from _repeat(node, text, at, 0)


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


def _emit_string_matching(generator: Any, value: object) -> Emitted:
    """Return the steps of the first match of the whole string.

    Raises:
        CannotInvert: value is not a string the pattern matches in full.
    """
    if not isinstance(value, str):
        raise CannotInvert(f"prop: {value!r} is not a string")
    for end, steps in _matches(generator.node, value, 0):
        if end == len(value):
            return steps, value
    raise CannotInvert(f"prop: the pattern does not match {value!r} in full")


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
