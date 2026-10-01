"""The default alphabet of the string generator, ordered from simplest.

A string is a sequence of indices into an alphabet, so the order of the
alphabet decides what a string shrinks towards. The default alphabet puts
the 95 printable ASCII characters first, digits, then lowercase and
uppercase letters, then space and punctuation, so a string shrinks
towards "0", then "00". After them come the other code points of the
Basic Multilingual Plane, ascending, without the surrogates, and then the
code points above it.
"""

from __future__ import annotations

from typing import Final

#: The first 95 characters, in order.
PRINTABLE: Final = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
)

#: The code point ranges that follow the printable characters, inclusive
#: and ascending: the controls below space, everything from DEL to the
#: surrogates, everything after the surrogates in the plane, and the
#: supplementary planes.
REST: Final = (
    (0x00, 0x1F),
    (0x7F, 0xD7FF),
    (0xE000, 0xFFFF),
    (0x10000, 0x10FFFF),
)

#: The number of characters in the default alphabet: every Unicode scalar
#: value.
SIZE: Final = len(PRINTABLE) + sum(hi - lo + 1 for lo, hi in REST)

_PRINTABLE_INDEX: Final = {char: index for index, char in enumerate(PRINTABLE)}


def character(index: int) -> str:
    """Return the character at index of the default alphabet.

    Raises:
        IndexError: index is outside [0, SIZE).
    """
    if not 0 <= index < SIZE:
        raise IndexError(f"prop: index {index} is outside the default alphabet")
    if index < len(PRINTABLE):
        return PRINTABLE[index]
    offset = index - len(PRINTABLE)
    for lo, hi in REST:
        if offset <= hi - lo:
            return chr(lo + offset)
        offset -= hi - lo + 1
    raise AssertionError("unreachable: SIZE covers every range")


def index(char: str) -> int:
    """Return the index of a character in the default alphabet.

    Raises:
        ValueError: char is not one Unicode scalar value.
    """
    if len(char) != 1:
        raise ValueError(f"prop: {char!r} is not one character")
    if char in _PRINTABLE_INDEX:
        return _PRINTABLE_INDEX[char]
    point = ord(char)
    offset = len(PRINTABLE)
    for lo, hi in REST:
        if lo <= point <= hi:
            return offset + point - lo
        offset += hi - lo + 1
    raise ValueError(f"prop: U+{point:04X} is a surrogate, not a scalar value")


def indices(lo: int, hi: int) -> list[tuple[int, int]]:
    """Return the indices of the code points in [lo, hi], as inclusive intervals.

    The intervals are sorted and do not overlap or touch. The surrogates in
    the range have no index and are left out, and an empty range has none.
    """
    found: list[tuple[int, int]] = []
    for point in range(max(lo, ord(" ")), min(hi, ord("~")) + 1):
        position = _PRINTABLE_INDEX[chr(point)]
        found.append((position, position))
    offset = len(PRINTABLE)
    for first, last in REST:
        start, end = max(lo, first), min(hi, last)
        if start <= end:
            found.append((offset + start - first, offset + end - first))
        offset += last - first + 1
    return merge(found)


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return the union of inclusive intervals, sorted, with touching ones joined."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
