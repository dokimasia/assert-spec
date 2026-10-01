"""The fuzz bridge: which bytes each choice reads, and what they decode to."""

from __future__ import annotations

import math
import struct
import unittest
from typing import final

from .bridge import UNBOUNDED_LENGTHS, Bridging, width
from .case import Case, Request
from .choice import (
    INT64_MAX,
    INT64_MIN,
    NAN_BITS,
    WIDTH_32,
    Bounds,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
    Value,
    bits_of,
)
from .generator import build
from .source import Source


def _request(bounds: Bounds) -> Request:
    """Return a request with bounds, whose draw the bridge must never call."""

    def unused(source: Source) -> Value:
        raise AssertionError(f"the bridge drew from {source}")

    return Request(bounds, unused)


def read(data: bytes, *bounds: Bounds) -> list[Value]:
    """Return the values data decodes to under each bounds, in order."""
    case = Case(Bridging(data))
    return [case.choose(_request(b)) for b in bounds]


@final
class WidthTest(unittest.TestCase):
    """width(): the fewest bytes that cover a range."""

    def test_the_width_covers_the_spans_bit_length(self) -> None:
        """0 bytes for one value, 1 up to 256 values, 2 for 257."""
        cases = {0: 0, 1: 1, 255: 1, 256: 2, 65535: 2, 65536: 3, 2**64 - 1: 8}
        for span, want in cases.items():
            self.assertEqual(width(span), want, span)


@final
class IntegerTest(unittest.TestCase):
    """An integer reads its width as little-endian and wraps into range."""

    def test_a_byte_range_reads_one_byte(self) -> None:
        """[0, 255] takes the byte as it is."""
        self.assertEqual(read(b"\x07\x09", IntegerBounds(0, 255)), [7])

    def test_the_value_is_lo_plus_u_modulo_the_range(self) -> None:
        """[-100, 100] has 201 values, so 250 is -100 + 49."""
        self.assertEqual(read(bytes([250]), IntegerBounds(-100, 100)), [-51])

    def test_a_wider_range_reads_little_endian(self) -> None:
        """[0, 1000] reads two bytes, low byte first."""
        bounds = IntegerBounds(0, 1000)
        self.assertEqual(read(b"\x01\x01\x00\x01", bounds, bounds), [257, 256])

    def test_the_full_signed_range_reads_eight_bytes(self) -> None:
        """All zero bytes are INT64_MIN, and all ones are INT64_MAX."""
        bounds = IntegerBounds(INT64_MIN, INT64_MAX)
        data = b"\x00" * 8 + b"\xff" * 8
        self.assertEqual(read(data, bounds, bounds), [INT64_MIN, INT64_MAX])

    def test_a_flag_reads_one_byte(self) -> None:
        """An odd byte continues, an even one stops."""
        flag = IntegerBounds(0, 1)
        self.assertEqual(read(b"\x03\x04", flag, flag), [1, 0])

    def test_bounds_with_one_value_read_nothing(self) -> None:
        """A forced flag leaves the byte for the next choice."""
        self.assertEqual(
            read(b"\x05", IntegerBounds(1, 1), IntegerBounds(0, 9)), [1, 5]
        )


@final
class FloatTest(unittest.TestCase):
    """A float reads the bits of its width."""

    def test_a_binary64_reads_eight_bytes(self) -> None:
        """The little-endian bits of 1.5."""
        self.assertEqual(read(struct.pack("<d", 1.5), FloatBounds(-2.0, 2.0)), [1.5])

    def test_a_binary32_reads_four_bytes(self) -> None:
        """The little-endian bits of 0.5, then a byte for the next choice."""
        data = struct.pack("<f", 0.5) + b"\x02"
        bounds = FloatBounds(0.0, 1.0, width=WIDTH_32)
        self.assertEqual(read(data, bounds, IntegerBounds(0, 9)), [0.5, 2])

    def test_a_value_the_bounds_do_not_admit_takes_the_target(self) -> None:
        """3.0 is outside [-2, 2]."""
        self.assertEqual(read(struct.pack("<d", 3.0), FloatBounds(-2.0, 2.0)), [0.0])

    def test_nan_takes_the_target_unless_allowed(self) -> None:
        """Allowed, any NaN becomes the canonical NaN."""
        data = struct.pack("<Q", 0xFFF0000000000001)
        self.assertEqual(read(data, FloatBounds(1.0, 2.0)), [1.0])
        got = read(data, FloatBounds(1.0, 2.0, allow_nan=True))[0]
        assert isinstance(got, float)
        self.assertTrue(math.isnan(got))
        self.assertEqual(bits_of(got), NAN_BITS)

    def test_bounds_with_one_value_read_nothing(self) -> None:
        """[1, 1] without NaN reads no byte."""
        got = read(b"\x05", FloatBounds(1.0, 1.0), IntegerBounds(0, 9))
        self.assertEqual(got, [1.0, 5])

    def test_a_range_of_one_value_with_nan_reads_its_bytes(self) -> None:
        """[1, 1] with NaN has two values, so it reads eight bytes."""
        data = struct.pack("<d", 1.0) + b"\x05"
        got = read(data, FloatBounds(1.0, 1.0, allow_nan=True), IntegerBounds(0, 9))
        self.assertEqual(got, [1.0, 5])

    def test_a_zero_range_admits_both_zeros_and_reads(self) -> None:
        """[0, 0] decodes the bits of -0."""
        got = read(struct.pack("<d", -0.0), FloatBounds(0.0, 0.0))[0]
        assert isinstance(got, float)
        self.assertEqual(bits_of(got), bits_of(-0.0))


@final
class SequenceTest(unittest.TestCase):
    """A sequence reads its length, then its elements."""

    def test_a_bounded_length_reads_its_width_then_each_element(self) -> None:
        """Length 2 of [0, 8], then two bytes."""
        self.assertEqual(read(b"\x02hi", SequenceBounds(256, 0, 8)), [(104, 105)])

    def test_an_unbounded_length_reads_two_bytes(self) -> None:
        """Lengths from min_size to min_size + 65535, low byte first."""
        self.assertEqual(UNBOUNDED_LENGTHS, 0xFFFF)
        self.assertEqual(read(b"\x02\x00hi", SequenceBounds(256)), [(104, 105)])

    def test_the_length_counts_from_min_size(self) -> None:
        """Byte 1 over [2, 5] is length 3."""
        self.assertEqual(read(b"\x01abc", SequenceBounds(256, 2, 5)), [(97, 98, 99)])
        self.assertEqual(read(b"\x01\x00ab", SequenceBounds(256, 1)), [(97, 98)])

    def test_elements_wrap_into_k(self) -> None:
        """Three element values take each byte modulo 3."""
        self.assertEqual(read(b"\x02\x04\x05", SequenceBounds(3, 0, 2)), [(1, 2)])

    def test_a_sequence_cut_short_ends_at_the_last_whole_element(self) -> None:
        """Then zeros extend it to min_size."""
        self.assertEqual(read(b"\x03\x07", SequenceBounds(256, 0, 9)), [(7,)])
        self.assertEqual(read(b"\x05\x07", SequenceBounds(256, 3, 9)), [(7, 0, 0)])

    def test_a_byte_string_takes_one_fuzzer_byte_per_byte(self) -> None:
        """Through the bytes generator, after the two length bytes."""
        case = Case(Bridging(b"\x05\x00hello"))
        self.assertEqual(build({"gen": "bytes"}).decode(case), b"hello")


@final
class ExhaustionTest(unittest.TestCase):
    """When the bytes run out, every further choice takes its target."""

    def test_no_bytes_decode_to_the_targets(self) -> None:
        """An empty input is the simplest case."""
        bounds = (IntegerBounds(-5, 5), FloatBounds(0.25, 0.75), SequenceBounds(4, 2))
        self.assertEqual(read(b"", *bounds), [0, 0.5, (0, 0)])

    def test_a_choice_cut_short_takes_its_target_and_spends_the_rest(self) -> None:
        """One byte of a two-byte integer leaves nothing for the next choice."""
        got = read(b"\x07", IntegerBounds(0, 1000), IntegerBounds(0, 9))
        self.assertEqual(got, [0, 0])
