"""The replay token: its bytes, its round trip, and the tokens it refuses."""

from __future__ import annotations

import base64
import math
import sys
import unittest
from typing import final

from .choice import INT64_MIN, NAN_BITS, UINT64_MAX, Choice, bits_of, same_float
from .replay import PREFIX, decode, encode

#: A sequence of every kind, and the bytes the token rules give it, one
#: group per choice: a tag, then LEB128 or little-endian float bits.
CHOICES = [
    Choice("integer", 0),
    Choice("integer", -1),
    Choice("integer", 127),
    Choice("integer", 128),
    Choice("integer", 300),
    Choice("float", 1.5),
    Choice("sequence", (1, 200)),
]
BYTES = bytes.fromhex("0000 0101 007f 008001 00ac02 02000000000000f83f 030201c801")

#: The most negative finite binary64. Its bits are nearly all ones, so its
#: token contains the base64url character for 63.
LOWEST = Choice("float", -sys.float_info.max)


def _token(data: bytes) -> str:
    """Return the token of raw bytes, as base64url without padding."""
    return PREFIX + base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _same(a: list[Choice], b: list[Choice]) -> bool:
    """Report whether two choice sequences are equal, NaN and -0 included."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        if x.kind != y.kind:
            return False
        if isinstance(x.value, float) and isinstance(y.value, float):
            if not same_float(x.value, y.value):
                return False
        elif x.value != y.value:
            return False
    return True


@final
class EncodeTest(unittest.TestCase):
    """encode(): a tag byte, then the payload, per choice."""

    def test_each_kind_encodes_to_its_tag_and_payload(self) -> None:
        """LEB128 integers and lengths, little-endian float bits."""
        self.assertEqual(encode(CHOICES), _token(BYTES))

    def test_no_choices_encode_to_the_prefix_alone(self) -> None:
        """A case of targets only."""
        self.assertEqual(encode([]), PREFIX)

    def test_every_nan_encodes_with_the_canonical_bits(self) -> None:
        """A NaN with a sign or a payload has one token."""
        canonical = NAN_BITS.to_bytes(8, "little")
        self.assertEqual(
            encode([Choice("float", -math.nan)]), _token(bytes([0x02]) + canonical)
        )

    def test_the_text_is_base64url_without_padding(self) -> None:
        """63 encodes as an underscore, and no token contains + / or =."""
        token = encode([LOWEST])
        self.assertIn("_", token)
        for char in "+/=":
            self.assertNotIn(char, token)


@final
class DecodeTest(unittest.TestCase):
    """decode(): the inverse of encode(), and nothing else."""

    def test_a_token_decodes_to_its_choices(self) -> None:
        """The pinned bytes give the pinned choices."""
        self.assertTrue(_same(decode(_token(BYTES)), CHOICES))

    def test_every_choice_round_trips(self) -> None:
        """The extremes of each kind, signed zero and NaN included."""
        choices = [
            Choice("integer", INT64_MIN),
            Choice("integer", UINT64_MAX),
            Choice("float", -0.0),
            Choice("float", math.inf),
            Choice("float", math.nan),
            Choice("float", 5e-324),
            LOWEST,
            Choice("sequence", ()),
            Choice("sequence", (0, 1_112_063)),
        ]
        decoded = decode(encode(choices))
        self.assertTrue(_same(decoded, choices), decoded)

    def test_a_token_that_encode_never_returns_raises(self) -> None:
        """Every malformed shape, each alone."""
        malformed = {
            "another version": "prop2:AAA",
            "no prefix": "AAA",
            "padding": PREFIX + "AAA=",
            "a lone character": PREFIX + "A",
            "a character outside base64url": PREFIX + "AAA*",
            "a character outside ASCII": PREFIX + "AAAé",
            "trailing bits": PREFIX + "AAB",
            "standard base64": encode([LOWEST]).replace("_", "/"),
            "a superfluous LEB128 byte": _token(bytes.fromhex("008000")),
            "a negative zero": _token(bytes.fromhex("0100")),
            "past INT64_MIN": _token(bytes.fromhex("0181808080808080808001")),
            "the number 2^64": _token(bytes.fromhex("0080808080808080808002")),
            "a number cut short": _token(bytes.fromhex("0080")),
            "a float cut short": _token(bytes.fromhex("020000")),
            "a sequence cut short": _token(bytes.fromhex("030201")),
            "an unknown tag": _token(bytes.fromhex("04")),
        }
        for name, token in malformed.items():
            with self.assertRaises(ValueError, msg=name):
                decode(token)

    def test_the_largest_number_is_2_to_the_64_minus_1(self) -> None:
        """UINT64_MAX decodes from ten LEB128 bytes."""
        token = _token(bytes.fromhex("00ffffffffffffffffff01"))
        self.assertEqual(decode(token), [Choice("integer", UINT64_MAX)])

    def test_the_largest_negative_magnitude_is_2_to_the_63(self) -> None:
        """INT64_MIN decodes."""
        token = _token(bytes.fromhex("0180808080808080808001"))
        self.assertEqual(decode(token), [Choice("integer", INT64_MIN)])

    def test_negative_zero_keeps_its_sign(self) -> None:
        """The float payload is the bits, not the value."""
        value = decode(encode([Choice("float", -0.0)]))[0].value
        assert isinstance(value, float)
        self.assertEqual(bits_of(value), bits_of(-0.0))
