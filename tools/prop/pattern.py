r"""The portable pattern subset: parsed, then decoded from a case.

string-matching takes a regular expression from a subset that the engines
of every target language read the same way. A pattern describes the whole
string, so every string it decodes matches the pattern in full. The subset
contains:

- A literal: any character but the metacharacters ``\ . ^ $ | ? * + ( ) [
  ] { }``, or a metacharacter after a backslash.
- ``.``: any character but the line terminators LINE_TERMINATORS.
- ``\d``, ``\w`` and ``\s``: the characters every engine's class
  contains, DIGITS, WORD and SPACE.
- A class ``[...]`` of characters, ranges and those three escapes,
  negated by a leading ``^``. Inside a class, ``\``, ``[``, ``]`` and a
  hyphen that forms no range are escaped. A hyphen may stand unescaped
  first or last, and RESERVED_PAIRS are refused.
- A group, ``(...)`` or ``(?:...)``, nested at most MAX_DEPTH deep, and
  alternation with ``|``.
- The quantifiers ``*``, ``+``, ``?``, ``{m}``, ``{m,}`` and ``{m,n}``, with
  counts of at most MAX_COUNT and without a leading zero, and never two in
  a row. Along every chain of nested quantifiers, the counts multiply to
  at most MAX_COUNT, each count the upper one, or the lower one when there
  is no upper one, and a count of 0 counted as 1.
- ``^`` as the first character of the pattern and ``$`` as its last.

Each node decodes from the case in a fixed way. An alternation of two or
more branches chooses one with an integer that decides structure. A
quantifier decodes its repetitions as a collection. A class chooses a
character with an integer index over its members, in the order of the
default alphabet. The targets give the first branch of each alternation,
the fewest repetitions, and the simplest character of each class.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Final, Protocol, final

from . import alphabet
from .case import Case
from .choice import IntegerBounds
from .collection import ELEMENT, Sizes, collect

#: The characters that are literal only after a backslash.
METACHARACTERS: Final = frozenset("\\.^$|?*+()[]{}")

#: The characters a backslash makes literal inside a class.
CLASS_ESCAPES: Final = METACHARACTERS | {"-"}

#: Pairs a class may not contain. Java reads ``&&`` as an intersection,
#: and other engines reserve the rest for set operations.
RESERVED_PAIRS: Final = frozenset({"&&", "--", "||", "~~"})

#: The characters ``.`` leaves out, because some engine's ``.`` does not
#: match them.
LINE_TERMINATORS: Final = "\n\r\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}"

#: What ``\d``, ``\w`` and ``\s`` decode to: the members every engine's
#: class has.
DIGITS: Final = string.digits
WORD: Final = string.digits + string.ascii_letters + "_"
SPACE: Final = " \t\n\f\r"
SHORTHANDS: Final = {"d": DIGITS, "w": WORD, "s": SPACE}

#: The largest count a quantifier may state, and the largest product of
#: the counts of nested quantifiers. RE2 refuses a larger one of either.
MAX_COUNT: Final = 1000

#: The deepest that groups may nest. Python's re module refuses a pattern
#: whose groups nest 495 deep.
MAX_DEPTH: Final = 100

#: The span labels of an alternation and of a quantifier's repetitions.
ALTERNATION: Final = "alternation"
REPEAT: Final = "repeat"

#: The characters that start a quantifier.
_QUANTIFIERS: Final = frozenset("*+?{")

#: Inclusive intervals of default-alphabet indices.
Intervals = tuple[tuple[int, int], ...]


class PatternError(ValueError):
    """A pattern outside the portable subset."""


class Node(Protocol):
    """A parsed piece of a pattern, which decodes characters from a case."""

    def emit(self, case: Case, out: list[str]) -> None:
        """Ask the case for this piece's choices and append its characters."""
        ...


@dataclass(frozen=True)
class Literal:
    """One character, which makes no choice."""

    char: str

    def emit(self, case: Case, out: list[str]) -> None:
        """Append the character."""
        del case
        out.append(self.char)


@dataclass(frozen=True)
class Class:
    """One character of a set: an integer index over its members.

    The members are in default-alphabet order, so index 0, the target, is
    the simplest member.
    """

    intervals: Intervals
    size: int

    def emit(self, case: Case, out: list[str]) -> None:
        """Append the member at the index the case chooses."""
        offset = case.integer(IntegerBounds(0, self.size - 1))
        for start, end in self.intervals:
            if offset <= end - start:
                out.append(alphabet.character(start + offset))
                return
            offset -= end - start + 1


@dataclass(frozen=True)
class Sequence:
    """Pieces decoded one after another."""

    items: tuple[Node, ...]

    def emit(self, case: Case, out: list[str]) -> None:
        """Decode each piece in order."""
        for item in self.items:
            item.emit(case, out)


@dataclass(frozen=True)
class Alternation:
    """Two or more branches: an index that decides structure, then the branch."""

    branches: tuple[Node, ...]

    def emit(self, case: Case, out: list[str]) -> None:
        """Decode the branch the case chooses, in a span labelled ALTERNATION."""
        bounds = IntegerBounds(0, len(self.branches) - 1)
        with case.span(ALTERNATION):
            self.branches[case.integer(bounds, edge=0)].emit(case, out)


@dataclass(frozen=True)
class Repeat:
    """A quantified piece, its repetitions decoded as a collection."""

    item: Node
    sizes: Sizes

    def emit(self, case: Case, out: list[str]) -> None:
        """Decode the repetitions in a span labelled REPEAT."""

        def element() -> tuple[None, None]:
            self.item.emit(case, out)
            return None, None

        with case.span(REPEAT):
            collect(case, self.sizes, ELEMENT, element)


def _weight(node: Node) -> int:
    """Return the largest product of quantifier counts along a path through node."""
    if isinstance(node, Repeat):
        high = node.sizes.max_size
        count = node.sizes.min_size if high is None else high
        return max(count, 1) * _weight(node.item)
    if isinstance(node, Sequence):
        return max((_weight(item) for item in node.items), default=1)
    if isinstance(node, Alternation):
        return max(_weight(branch) for branch in node.branches)
    return 1


def _class_of(intervals: list[tuple[int, int]]) -> Class:
    """Return the class of the merged intervals.

    Raises:
        PatternError: the class has no member.
    """
    merged = tuple(alphabet.merge(intervals))
    size = sum(end - start + 1 for start, end in merged)
    if size == 0:
        raise PatternError("prop: a class in the pattern has no member")
    return Class(merged, size)


def _members(chars: str) -> list[tuple[int, int]]:
    """Return the intervals of a set of characters."""
    return [(alphabet.index(c), alphabet.index(c)) for c in chars]


def _complement(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return the default-alphabet indices outside intervals."""
    gaps: list[tuple[int, int]] = []
    start = 0
    for first, last in alphabet.merge(intervals):
        if first > start:
            gaps.append((start, first - 1))
        start = last + 1
    if start < alphabet.SIZE:
        gaps.append((start, alphabet.SIZE - 1))
    return gaps


#: The class ``.`` decodes from.
DOT: Final = _class_of(_complement(_members(LINE_TERMINATORS)))


def parse(text: str) -> Node:
    """Return the node a pattern of the portable subset parses to.

    Raises:
        PatternError: text is outside the subset, or contains a surrogate.
    """
    return _Parser(text).pattern()


@final
class _Parser:
    """A recursive-descent parser over one pattern."""

    def __init__(self, text: str) -> None:
        """Parse text from its first character.

        Raises:
            PatternError: text contains a surrogate.
        """
        try:
            for char in text:
                alphabet.index(char)
        except ValueError as bad:
            raise PatternError(f"prop: pattern {text!r}: {bad}") from bad
        self._text = text
        self._at = 0
        self._depth = 0

    def _fail(self, what: str) -> PatternError:
        """Return the error for what is wrong at the current position."""
        return PatternError(f"prop: pattern {self._text!r} at {self._at}: {what}")

    def _peek(self, ahead: int = 0) -> str:
        """Return the character ahead of the current one, or "" past the end."""
        at = self._at + ahead
        return self._text[at] if at < len(self._text) else ""

    def _next(self, missing: str) -> str:
        """Return the current character and move past it.

        Raises:
            PatternError: the pattern ends here; missing says what it lacks.
        """
        if self._at >= len(self._text):
            raise self._fail(missing)
        char = self._text[self._at]
        self._at += 1
        return char

    def pattern(self) -> Node:
        """Parse the whole pattern, with its optional anchors."""
        if self._peek() == "^":
            self._at += 1
        node = self._alternation()
        if self._peek() == "$" and self._at == len(self._text) - 1:
            self._at += 1
        if self._at != len(self._text):
            raise self._fail(f"{self._peek()!r} is not expected")
        return node

    def _alternation(self) -> Node:
        """Parse branches separated by |."""
        branches = [self._sequence()]
        while self._peek() == "|":
            self._at += 1
            branches.append(self._sequence())
        return branches[0] if len(branches) == 1 else Alternation(tuple(branches))

    def _sequence(self) -> Node:
        """Parse pieces up to a |, a ), the closing anchor or the end.

        A $ that ends the pattern inside a group stops the sequence, and the
        group then raises because no ) closes it.
        """
        items: list[Node] = []
        while self._peek() not in ("", "|", ")"):
            if self._peek() == "$" and self._at == len(self._text) - 1:
                break
            items.append(self._quantified())
        return items[0] if len(items) == 1 else Sequence(tuple(items))

    def _quantified(self) -> Node:
        """Parse an atom and the quantifier after it, if any.

        A second quantifier is then parsed as an atom, and refused as an
        unescaped metacharacter.
        """
        atom = self._atom()
        if self._peek() not in _QUANTIFIERS:
            return atom
        repeat = Repeat(atom, self._quantifier())
        if (weight := _weight(repeat)) > MAX_COUNT:
            raise self._fail(f"nested counts multiply to {weight}, above {MAX_COUNT}")
        return repeat

    def _quantifier(self) -> Sizes:
        """Parse *, +, ?, {m}, {m,} or {m,n} into the repetitions it allows."""
        char = self._next("a quantifier is missing")
        if char == "*":
            return Sizes(0, None)
        if char == "+":
            return Sizes(1, None)
        if char == "?":
            return Sizes(0, 1)
        low = self._count()
        high: int | None = low
        if self._peek() == ",":
            self._at += 1
            high = None if self._peek() == "}" else self._count()
        if self._next("a count is not closed") != "}":
            raise self._fail("a count is not closed by }")
        if high is not None and high < low:
            raise self._fail(f"the count {{{low},{high}}} runs backwards")
        return Sizes(low, high)

    def _count(self) -> int:
        """Parse the digits of a count, at most MAX_COUNT.

        RE2 reads a count with a leading zero, such as {007}, as literal
        text, so a count of two or more digits does not start with 0.
        """
        start = self._at
        while self._peek().isdigit() and self._peek().isascii():
            self._at += 1
        if start == self._at:
            raise self._fail("a count has no digits")
        digits = self._text[start : self._at]
        if len(digits) > 1 and digits[0] == "0":
            raise self._fail(f"the count {digits} has a leading zero")
        count = int(digits)
        if count > MAX_COUNT:
            raise self._fail(f"the count {count} is above {MAX_COUNT}")
        return count

    def _atom(self) -> Node:
        """Parse a literal, a dot, an escape, a class or a group."""
        char = self._next("the pattern ends where a character belongs")
        if char == "(":
            return self._group()
        if char == "[":
            return self._class()
        if char == ".":
            return DOT
        if char == "\\":
            escaped = self._next("the pattern ends with a backslash")
            if escaped in SHORTHANDS:
                return _class_of(_members(SHORTHANDS[escaped]))
            if escaped not in METACHARACTERS:
                raise self._fail(f"\\{escaped} is not in the portable subset")
            return Literal(escaped)
        if char in METACHARACTERS:
            raise self._fail(f"{char!r} must be escaped here")
        return Literal(char)

    def _group(self) -> Node:
        """Parse a group after its (, at most MAX_DEPTH deep."""
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise self._fail(f"groups nest deeper than {MAX_DEPTH}")
        if self._peek() == "?":
            if self._peek(1) != ":":
                raise self._fail("only the (?: group is in the portable subset")
            self._at += 2
        node = self._alternation()
        if self._next("a group is not closed") != ")":
            raise self._fail("a group is not closed by )")
        self._depth -= 1
        return node

    def _class(self) -> Class:
        """Parse a class after its [."""
        negated = self._peek() == "^"
        if negated:
            self._at += 1
        members: list[tuple[int, int]] = []
        previous = ""
        first = True
        while (char := self._next("a class is not closed")) != "]":
            if char == "\\" and self._peek() in SHORTHANDS:
                members += _members(SHORTHANDS[self._next("a class is not closed")])
                previous, first = "", False
                continue
            low = self._class_char(char, previous, first=first)
            previous = "" if char == "\\" else char
            first = False
            if self._peek() == "-" and self._peek(1) not in ("", "]"):
                if previous + "-" in RESERVED_PAIRS:
                    raise self._fail("'--' is reserved inside a class")
                self._at += 1
                end = self._next("a class is not closed")
                high = self._class_char(end, "-", first=False)
                if ord(high) < ord(low):
                    raise self._fail(f"the range {low}-{high} runs backwards")
                members += alphabet.indices(ord(low), ord(high))
                previous = ""
            else:
                members += _members(low)
        if first:
            raise self._fail("a class is empty")
        return _class_of(_complement(members) if negated else members)

    def _class_char(self, char: str, previous: str, *, first: bool) -> str:
        """Return the character a class member states, unescaping it.

        Raises:
            PatternError: the member is a [, a reserved pair, a misplaced
                hyphen, or an escape the subset does not have.
        """
        if char == "\\":
            escaped = self._next("a class ends inside an escape")
            if escaped not in CLASS_ESCAPES:
                raise self._fail(f"\\{escaped} is not in the portable subset")
            return escaped
        if char == "[":
            raise self._fail("[ must be escaped inside a class")
        if previous + char in RESERVED_PAIRS:
            raise self._fail(f"{previous + char!r} is reserved inside a class")
        if char == "-" and not first and self._peek() != "]":
            raise self._fail("a hyphen inside a class must be escaped")
        return char
