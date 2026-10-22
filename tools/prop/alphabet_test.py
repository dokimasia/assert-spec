# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""The default alphabet: its order, its size, and its two directions."""

from __future__ import annotations

import sys
import unittest
from typing import final

import pytest

from .alphabet import PRINTABLE, SIZE, character, index, indices, merge

#: The surrogates, which are code points but not Unicode scalar values.
SURROGATES = range(0xD800, 0xE000)

#: The printable ASCII characters, space to tilde.
PRINTABLE_ASCII = range(0x20, 0x7F)


@final
class AlphabetTest(unittest.TestCase):
    """The order a string shrinks along."""

    def test_the_alphabet_holds_every_scalar_value_once(self) -> None:
        """Every scalar value has one index, and the indices fill [0, SIZE)."""
        scalars = [p for p in range(sys.maxunicode + 1) if p not in SURROGATES]
        assert len(scalars) == SIZE
        assert sorted(index(chr(p)) for p in scalars) == list(range(SIZE))

    def test_character_inverts_index(self) -> None:
        """At the first and last index of every range."""
        edges = (0, 9, 10, 35, 36, 61, 62, 94, 95, 126, 127, 55295, 55296, 63487)
        for i in (*edges, 63488, SIZE - 1):
            assert index(character(i)) == i, i

    def test_the_printable_ascii_characters_come_first(self) -> None:
        """All 95 of them, and nothing else, at indices 0 to 94."""
        assert sorted(PRINTABLE) == [chr(p) for p in PRINTABLE_ASCII]
        assert [character(i) for i in range(95)] == list(PRINTABLE)

    def test_digits_then_lowercase_then_uppercase_then_space(self) -> None:
        """A string shrinks towards "0", and "a" precedes "A"."""
        assert character(0) == "0"
        assert character(10) == "a"
        assert character(36) == "A"
        assert character(62) == " "

    def test_the_controls_follow_the_printable_characters(self) -> None:
        """U+0000 is index 95, then DEL follows U+001F."""
        assert character(95) == "\x00"
        assert character(126) == "\x1f"
        assert character(127) == "\x7f"

    def test_the_surrogates_are_skipped(self) -> None:
        """U+E000 follows U+D7FF, and U+10000 follows U+FFFF."""
        assert index(chr(0xE000)) == index(chr(0xD7FF)) + 1
        assert index(chr(0x10000)) == index(chr(0xFFFF)) + 1
        assert character(SIZE - 1) == chr(sys.maxunicode)

    def test_an_index_outside_the_alphabet_raises(self) -> None:
        """Below zero, or SIZE and above."""
        for i in (-1, SIZE):
            with pytest.raises(IndexError):
                character(i)

    def test_a_surrogate_or_several_characters_have_no_index(self) -> None:
        """Only one Unicode scalar value has an index."""
        for text, reason in (
            (chr(0xD800), "is a surrogate"),
            (chr(0xDFFF), "is a surrogate"),
            ("ab", "is not one character"),
            ("", "is not one character"),
        ):
            with pytest.raises(ValueError, match=reason):
                index(text)


@final
class IndicesTest(unittest.TestCase):
    """indices(): a code point range as intervals of the alphabet's indices."""

    def test_every_range_gives_the_indices_of_its_code_points(self) -> None:
        """Ranges inside, across and between the alphabet's pieces."""
        ranges = [
            (ord("a"), ord("z")),
            (ord(" "), ord("~")),
            (0x00, 0x7F),
            (0x1F, 0x21),
            (0xD7FE, 0xE001),
            (0xFFFE, 0x10001),
            (0x41, 0x40),
        ]
        for lo, hi in ranges:
            want = sorted(
                index(chr(p)) for p in range(lo, hi + 1) if p not in SURROGATES
            )
            got = [i for start, end in indices(lo, hi) for i in range(start, end + 1)]
            assert got == want, (hex(lo), hex(hi))

    def test_the_intervals_neither_overlap_nor_touch(self) -> None:
        """Digits to z are the letters and digits, then two runs of punctuation."""
        assert indices(ord("a"), ord("z")) == [(10, 35)]
        assert indices(ord("0"), ord("z")) == [(0, 61), (78, 90)]

    def test_merge_joins_overlapping_and_touching_intervals(self) -> None:
        """Sorted, with each gap of at least one index kept."""
        got = merge([(5, 6), (0, 2), (3, 3), (8, 9), (9, 12)])
        assert got == [(0, 3), (5, 6), (8, 12)]
