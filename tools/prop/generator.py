"""The generator vocabulary, stated as data and decoded from a case.

The corpus states a generator as a JSON object whose ``gen`` key names its
id. build() turns that object into a generator, and a generator's decode()
asks the case for its choices in a fixed order and returns the value they
decode to. The order of the requests, their bounds, which of them decide
structure, and the spans around them are the definition. Two
implementations that agree on them decode the same value from the same
choices.

Every generator but map decodes inside a span labelled with its id. map
makes its source's choices and opens no span of its own. A list and a
dict decode their elements as collection.collect states, each in a span
that starts at the element's continue flag.

Decoded values are Python values, as the value module states, and the
values a spec states are typed literals, as the literal module states.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, ClassVar, Final, TypeGuard

from . import alphabet, draw, literal, pattern
from .case import Case, Generator, Request
from .choice import (
    UINT64_MAX,
    WIDTH_64,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
)
from .collection import ELEMENT, ENTRY, Sizes, collect
from .function import FUNCTIONS
from .predicate import Predicate, predicate
from .value import Pairs, canonical

#: A generator spec: a decoded JSON object.
Spec = Mapping[str, Any]

#: The values one recursive value may draw from its base when the spec
#: states no max_leaves.
DEFAULT_MAX_LEAVES: Final = 100

#: The probability that a boolean is true when the spec states no p.
DEFAULT_TRUE: Final = Fraction(1, 2)

#: The element values of the sequence behind a byte string.
BYTE_VALUES: Final = 256

#: The attempts a filter makes in all before it rejects the case.
FILTER_ATTEMPTS: Final = 3

#: A probability is stated as [numerator, denominator].
_RATIONAL_PARTS: Final = 2


class SpecError(ValueError):
    """A spec that names no generator, or misstates a parameter or a literal."""


def _is_int(value: object) -> TypeGuard[int]:
    """Report whether value is an int and not a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Integer:
    """An integer in [min, max]: one integer choice."""

    ID: ClassVar[str] = "integer"
    bounds: IntegerBounds

    def decode(self, case: Case) -> object:
        """Return the integer the case chooses, which may reuse an earlier one."""
        with case.span(self.ID):
            return case.integer(self.bounds, reuse=True)


@dataclass(frozen=True)
class Duration(Integer):
    """A duration in nanoseconds in [min, max]: one integer choice."""

    ID: ClassVar[str] = "duration"


@dataclass(frozen=True)
class Float:
    """A float inside its bounds: one float choice."""

    ID: ClassVar[str] = "float"
    bounds: FloatBounds

    def decode(self, case: Case) -> object:
        """Return the float the case chooses."""
        bounds = self.bounds
        with case.span(self.ID):
            return case.choose(
                Request(bounds, lambda source: draw.float_value(source, bounds))
            )


@dataclass(frozen=True)
class Boolean:
    """True with probability p: one integer choice in [0, 1], drawn by one coin."""

    ID: ClassVar[str] = "boolean"
    p: Fraction

    def decode(self, case: Case) -> object:
        """Return whether the case chooses 1."""
        p = self.p
        request = Request(IntegerBounds(0, 1), lambda source: draw.boolean(source, p))
        with case.span(self.ID):
            return case.choose(request) == 1


@dataclass(frozen=True)
class Just:
    """One stated value. It makes no choice."""

    ID: ClassVar[str] = "just"
    value: object

    def decode(self, case: Case) -> object:
        """Return the stated value."""
        with case.span(self.ID):
            return self.value


@dataclass(frozen=True)
class SampledFrom:
    """One of the stated values: an integer index that decides structure."""

    ID: ClassVar[str] = "sampled-from"
    values: tuple[object, ...]

    def decode(self, case: Case) -> object:
        """Return the value at the index the case chooses."""
        bounds = IntegerBounds(0, len(self.values) - 1)
        with case.span(self.ID):
            return self.values[case.integer(bounds, edge=0)]


@dataclass(frozen=True)
class OneOf:
    """A value of one of the generators: an index, then that generator's choices.

    The index decides structure.
    """

    ID: ClassVar[str] = "one-of"
    of: tuple[Generator, ...]

    def decode(self, case: Case) -> object:
        """Return the value the chosen generator decodes."""
        bounds = IntegerBounds(0, len(self.of) - 1)
        with case.span(self.ID):
            return self.of[case.integer(bounds, edge=0)].decode(case)


@dataclass(frozen=True)
class Optional:
    """A value or None: a presence choice in [0, 1], then the value when present.

    The presence choice decides structure. Its target is absent, and the
    edge phase makes it present.
    """

    ID: ClassVar[str] = "optional"
    of: Generator

    def decode(self, case: Case) -> object:
        """Return None when absent and the decoded value when present."""
        with case.span(self.ID):
            if case.integer(IntegerBounds(0, 1), edge=1):
                return self.of.decode(case)
            return None


@dataclass(frozen=True)
class List:
    """A list of the element generator's values.

    With unique set, an element equal under canonical() to an earlier one
    is discarded, as collection.collect states.
    """

    ID: ClassVar[str] = "list"
    of: Generator
    sizes: Sizes
    unique: bool = False

    def decode(self, case: Case) -> object:
        """Return the list the case's flags and elements decode to.

        Raises:
            Rejected: a unique list stopped below its minimum size.
        """

        def element() -> tuple[object, object]:
            value = self.of.decode(case)
            return value, canonical(value) if self.unique else None

        with case.span(self.ID):
            return collect(case, self.sizes, ELEMENT, element)


@dataclass(frozen=True)
class Dict:
    """Entries of a key and a value, with distinct keys.

    An entry whose key equals an earlier key under canonical() is
    discarded, as collection.collect states.
    """

    ID: ClassVar[str] = "dict"
    keys: Generator
    values: Generator
    sizes: Sizes

    def decode(self, case: Case) -> object:
        """Return the entries the case's flags, keys and values decode to.

        Raises:
            Rejected: the dict stopped below its minimum size.
        """

        def entry() -> tuple[tuple[object, object], object]:
            key = self.keys.decode(case)
            return (key, self.values.decode(case)), canonical(key)

        with case.span(self.ID):
            return Pairs(tuple(collect(case, self.sizes, ENTRY, entry)))


@dataclass(frozen=True)
class String:
    """A string: one sequence of indices into its alphabet.

    characters of None selects the default alphabet. Otherwise the
    alphabet is characters in their stated order, so the first character
    is the simplest.
    """

    ID: ClassVar[str] = "string"
    characters: str | None
    bounds: SequenceBounds

    def decode(self, case: Case) -> object:
        """Return the string the case's sequence spells."""
        with case.span(self.ID):
            indices = case.sequence(self.bounds)
        if self.characters is None:
            return "".join(alphabet.character(i) for i in indices)
        return "".join(self.characters[i] for i in indices)


@dataclass(frozen=True)
class StringMatching:
    """A string a pattern of the portable subset matches in full.

    The pattern's nodes make the choices, as the pattern module states.
    """

    ID: ClassVar[str] = "string-matching"
    node: pattern.Node

    def decode(self, case: Case) -> object:
        """Return the characters the pattern's nodes decode."""
        out: list[str] = []
        with case.span(self.ID):
            self.node.emit(case, out)
        return "".join(out)


@dataclass(frozen=True)
class Bytes:
    """A byte string: one sequence with BYTE_VALUES element values."""

    ID: ClassVar[str] = "bytes"
    bounds: SequenceBounds

    def decode(self, case: Case) -> object:
        """Return the bytes the case's sequence contains."""
        with case.span(self.ID):
            return bytes(case.sequence(self.bounds))


@dataclass(frozen=True)
class Permutation:
    """An ordering of the stated values: one swap choice per position.

    Position i, for i from 0 to n - 2, swaps with the index the case
    chooses in [i, n - 1]. The target of that choice is i, so the targets
    leave the values in their stated order.
    """

    ID: ClassVar[str] = "permutation"
    values: tuple[object, ...]

    def decode(self, case: Case) -> object:
        """Return the values in the order the case's swaps leave them."""
        ordered = list(self.values)
        last = len(ordered) - 1
        with case.span(self.ID):
            for i in range(last):
                j = case.integer(IntegerBounds(i, last))
                ordered[i], ordered[j] = ordered[j], ordered[i]
        return ordered


@dataclass(frozen=True)
class Filter:
    """A value of the source generator that a predicate keeps.

    Each attempt decodes in a span labelled with the id. A rejected attempt
    is removed from the case's record, so a replay of the record decodes
    the kept value at its first attempt. The removed choices still count
    towards the case's cap, and the case tree keeps them. The filter tries
    FILTER_ATTEMPTS times in all, and rejects the case when the predicate
    is false of the last attempt too.
    """

    ID: ClassVar[str] = "filter"
    of: Generator
    keep: Predicate

    def decode(self, case: Case) -> object:
        """Return the first attempt's value that the predicate keeps.

        Raises:
            Rejected: the predicate is false of every attempt.
        """
        mark = case.mark()
        value = self._attempt(case)
        for _ in range(FILTER_ATTEMPTS - 1):
            if self.keep(value):
                return value
            case.rewind(mark)
            value = self._attempt(case)
        case.assume(self.keep(value))
        return value

    def _attempt(self, case: Case) -> object:
        """Decode one attempt in its own span."""
        with case.span(self.ID):
            return self.of.decode(case)


@dataclass(frozen=True)
class Map:
    """The value that a subject kind's function returns for the source's value.

    It makes the source's choices and opens no span of its own. It has no
    inverse, because the engine cannot run a function backwards.
    """

    ID: ClassVar[str] = "map"
    of: Generator
    subject: str

    def decode(self, case: Case) -> object:
        """Return the function of the value the source decodes."""
        return FUNCTIONS[self.subject](self.of.decode(case))


@dataclass(eq=False)
class Recursive:
    """A base value, or an extension whose positions are recursive values.

    Each position decides between the base, 0, and the extension, 1, with
    an integer choice that decides structure. Once one value has drawn
    max_leaves values from the base, every further position takes the
    base, with bounds [0, 0]. A ``self`` inside the extension is one
    position.

    The count of leaves belongs to the decode in progress, so a recursive
    generator decodes one case at a time.
    """

    ID: ClassVar[str] = "recursive"
    base: Generator
    max_leaves: int
    extend: Generator = field(init=False)
    _leaves: list[int] = field(init=False, default_factory=list)

    def decode(self, case: Case) -> object:
        """Return one recursive value, counting its leaves from zero."""
        self._leaves.append(0)
        try:
            return self.position(case)
        finally:
            self._leaves.pop()

    def position(self, case: Case) -> object:
        """Decode one position of the value being decoded."""
        exhausted = self._leaves[-1] >= self.max_leaves
        bounds = IntegerBounds(0, 0 if exhausted else 1)
        with case.span(self.ID):
            if case.integer(bounds, edge=0):
                return self.extend.decode(case)
            self._leaves[-1] += 1
            return self.base.decode(case)


@dataclass(frozen=True, eq=False)
class Self:
    """A position of the recursive value being decoded, inside its extension."""

    ID: ClassVar[str] = "self"
    owner: Recursive

    def decode(self, case: Case) -> object:
        """Decode the next position of the owner's value."""
        return self.owner.position(case)


def build(spec: object, scope: Recursive | None = None) -> Generator:
    """Return the generator a spec states.

    scope is the recursive generator whose extension contains spec, the
    generator a ``self`` inside spec refers to.

    Raises:
        SpecError: spec names no generator of the vocabulary, lacks a
            parameter, or states a parameter the generator cannot take.
    """
    if not isinstance(spec, Mapping):
        raise SpecError(f"prop: {spec!r} is not a generator spec")
    kind = spec.get("gen")
    if not isinstance(kind, str):
        raise SpecError(f"prop: {spec!r} names no generator")
    try:
        if kind == Self.ID:
            return _self(scope)
        if kind in _LEAVES:
            return _LEAVES[kind](spec)
        if kind in _COMPOSITES:
            return _COMPOSITES[kind](spec, scope)
    except SpecError:
        raise
    except KeyError as missing:
        raise SpecError(f"prop: {kind} needs {missing}") from None
    except (TypeError, ValueError) as bad:
        raise SpecError(f"prop: {kind}: {bad}") from bad
    raise SpecError(f"prop: {kind!r} is not a generator")


def _self(scope: Recursive | None) -> Self:
    """Return a position of scope.

    Raises:
        SpecError: the spec is outside every recursive extension.
    """
    if scope is None:
        raise SpecError("prop: self appears outside a recursive generator's extension")
    return Self(scope)


def _int(spec: Spec, key: str) -> int:
    """Return the integer parameter key, as a typed literal states an int.

    An integer beyond 2^53 - 1 in magnitude is a decimal string.

    Raises:
        KeyError: spec does not state key.
        LiteralError: the parameter is not an integer in that form.
    """
    return literal.integer(spec[key])


def _bool(spec: Spec, key: str) -> bool:
    """Return the boolean parameter key, false when spec does not state it.

    Raises:
        SpecError: the parameter is not a boolean.
    """
    value = spec.get(key, False)
    if not isinstance(value, bool):
        raise SpecError(f"prop: {key} is {value!r}, not a boolean")
    return value


def _text(spec: Spec, key: str) -> str:
    """Return the string parameter key.

    Raises:
        KeyError: spec does not state key.
        SpecError: the parameter is not a string.
    """
    value = spec[key]
    if not isinstance(value, str):
        raise SpecError(f"prop: {key} is {value!r}, not a string")
    return value


def _sizes(spec: Spec) -> Sizes:
    """Return min_size, 0 by default, and max_size, unbounded by default."""
    min_size = _int(spec, "min_size") if "min_size" in spec else 0
    max_size = _int(spec, "max_size") if spec.get("max_size") is not None else None
    return Sizes(min_size, max_size)


def _float_bound(spec: Spec, key: str) -> float:
    """Return the float bound key, which may name an infinity.

    Raises:
        KeyError: spec does not state key.
        SpecError: the bound is neither a number nor a float's name.
    """
    return literal.number(spec[key])


def _probability(spec: Spec) -> Fraction:
    """Return p, stated as [numerator, denominator], or DEFAULT_TRUE.

    The fraction is reduced to lowest terms, so [2, 4] draws as [1, 2]
    does.

    Raises:
        SpecError: p is not two integers with 0 <= p <= 1 and a
            denominator of at most 2^64.
    """
    value = spec.get("p")
    if value is None:
        return DEFAULT_TRUE
    if (
        not isinstance(value, list)
        or len(value) != _RATIONAL_PARTS
        or not all(_is_int(part) for part in value)
        or not 0 <= value[0] <= value[1]
        or not 1 <= value[1] <= UINT64_MAX + 1
    ):
        raise SpecError(f"prop: p is {value!r}, want [numerator, denominator]")
    return Fraction(value[0], value[1])


def _values(spec: Spec) -> tuple[object, ...]:
    """Return the typed literals of the values parameter.

    Raises:
        KeyError: spec does not state values.
        SpecError: values is not a list of typed literals.
    """
    values = spec["values"]
    if not isinstance(values, list):
        raise SpecError(f"prop: values is {values!r}, not a list")
    return tuple(literal.decode(v) for v in values)


def _sampled_from(spec: Spec) -> SampledFrom:
    """Build sampled-from, which needs at least one value."""
    values = _values(spec)
    if not values:
        raise SpecError("prop: sampled-from needs at least one value")
    return SampledFrom(values)


def _one_of(spec: Spec, scope: Recursive | None) -> OneOf:
    """Build one-of, which needs at least one generator."""
    of = spec["of"]
    if not isinstance(of, list) or not of:
        raise SpecError(f"prop: one-of needs a list of generators, not {of!r}")
    return OneOf(tuple(build(g, scope) for g in of))


def _string(spec: Spec) -> String:
    """Build string over the default alphabet or the stated characters.

    A stated alphabet is non-empty, repeats no character, and contains
    only Unicode scalar values.
    """
    sizes = _sizes(spec)
    characters = spec.get("alphabet")
    if characters is None:
        bounds = SequenceBounds(alphabet.SIZE, sizes.min_size, sizes.max_size)
        return String(None, bounds)
    if not isinstance(characters, str) or not characters:
        raise SpecError(f"prop: alphabet is {characters!r}, not a non-empty string")
    if len(set(characters)) != len(characters):
        raise SpecError(f"prop: alphabet {characters!r} repeats a character")
    for char in characters:
        alphabet.index(char)
    bounds = SequenceBounds(len(characters), sizes.min_size, sizes.max_size)
    return String(characters, bounds)


def _bytes(spec: Spec) -> Bytes:
    """Build bytes."""
    sizes = _sizes(spec)
    return Bytes(SequenceBounds(BYTE_VALUES, sizes.min_size, sizes.max_size))


def _map(spec: Spec, scope: Recursive | None) -> Map:
    """Build map, over the function of a subject kind that takes one input."""
    subject = _text(spec, "subject")
    if subject not in FUNCTIONS:
        raise SpecError(f"prop: the subject {subject!r} is none of {sorted(FUNCTIONS)}")
    return Map(build(spec["of"], scope), subject)


def _recursive(spec: Spec) -> Recursive:
    """Build recursive, binding each self in its extension to the result.

    A self in the base refers to no position and is refused.
    """
    max_leaves = (
        _int(spec, "max_leaves") if "max_leaves" in spec else DEFAULT_MAX_LEAVES
    )
    if max_leaves < 1:
        raise SpecError(f"prop: max_leaves is {max_leaves}, below 1")
    node = Recursive(build(spec["base"]), max_leaves)
    node.extend = build(spec["extend"], node)
    return node


#: The generators whose specs contain no self, keyed by id.
_LEAVES: Final[dict[str, Callable[[Spec], Generator]]] = {
    Integer.ID: lambda s: Integer(IntegerBounds(_int(s, "min"), _int(s, "max"))),
    Duration.ID: lambda s: Duration(IntegerBounds(_int(s, "min"), _int(s, "max"))),
    Float.ID: lambda s: Float(
        FloatBounds(
            _float_bound(s, "min"),
            _float_bound(s, "max"),
            _bool(s, "allow_nan"),
            _int(s, "width") if "width" in s else WIDTH_64,
        )
    ),
    Boolean.ID: lambda s: Boolean(_probability(s)),
    Just.ID: lambda s: Just(literal.decode(s["value"])),
    SampledFrom.ID: _sampled_from,
    String.ID: _string,
    StringMatching.ID: lambda s: StringMatching(pattern.parse(_text(s, "pattern"))),
    Bytes.ID: _bytes,
    Permutation.ID: lambda s: Permutation(_values(s)),
    Recursive.ID: _recursive,
}

#: The generators that contain other generators, and so a self, keyed by id.
_COMPOSITES: Final[dict[str, Callable[[Spec, Recursive | None], Generator]]] = {
    OneOf.ID: _one_of,
    Optional.ID: lambda s, scope: Optional(build(s["of"], scope)),
    List.ID: lambda s, scope: List(
        build(s["of"], scope), _sizes(s), _bool(s, "unique")
    ),
    Dict.ID: lambda s, scope: Dict(
        build(s["keys"], scope), build(s["values"], scope), _sizes(s)
    ),
    Filter.ID: lambda s, scope: Filter(build(s["of"], scope), predicate(s["keep"])),
    Map.ID: _map,
}

#: The ids of the vocabulary's generators. ``self`` is a position inside a
#: recursive generator's extension, not a generator of its own.
IDS: Final = frozenset(_LEAVES) | frozenset(_COMPOSITES)
