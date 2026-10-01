"""The replay token: the choice values of one case as one printable string.

A token is PREFIX followed by the unpadded base64url encoding of the
choice values in order. Each value is a tag byte and then its payload:

- TAG_NON_NEGATIVE: a non-negative integer, in unsigned LEB128.
- TAG_NEGATIVE: a negative integer, its magnitude in unsigned LEB128.
- TAG_FLOAT: a float, its binary64 bits in eight bytes, little-endian.
  Every NaN has the canonical bits.
- TAG_SEQUENCE: a sequence, its length and then each element, each in
  unsigned LEB128.

The token records no bounds, because the generators state them again when
the case replays. A choice sequence has exactly one token, so the name of a
store entry, which derives from the token, is the same in every language.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Sequence
from typing import Final, final

from .choice import NAN_BITS, Choice, bits_of, from_bits

#: The text every token of this version starts with.
PREFIX: Final = "prop1:"

#: The tag byte before each choice value.
TAG_NON_NEGATIVE: Final = 0
TAG_NEGATIVE: Final = 1
TAG_FLOAT: Final = 2
TAG_SEQUENCE: Final = 3

#: The bytes of a float's payload.
FLOAT_BYTES: Final = 8

#: Each LEB128 byte carries seven bits, and its top bit marks that another
#: byte follows.
LEB128_BITS: Final = 7
LEB128_MORE: Final = 0x80
LEB128_PAYLOAD: Final = 0x7F

#: Every number a token encodes is below 2^64, and a negative integer's
#: magnitude is at most 2^63.
NUMBER_LIMIT: Final = 1 << 64
NEGATIVE_LIMIT: Final = 1 << 63

#: base64 encodes three bytes as four characters.
_BASE64_QUANTUM: Final = 4


def encode(choices: Sequence[Choice]) -> str:
    """Return the token of a choice sequence."""
    data = bytearray()
    for choice in choices:
        value = choice.value
        if choice.kind == "integer":
            assert isinstance(value, int)
            data.append(TAG_NEGATIVE if value < 0 else TAG_NON_NEGATIVE)
            _append_number(data, abs(value))
        elif choice.kind == "float":
            assert isinstance(value, float)
            bits = NAN_BITS if math.isnan(value) else bits_of(value)
            data.append(TAG_FLOAT)
            data += bits.to_bytes(FLOAT_BYTES, "little")
        else:
            assert isinstance(value, tuple)
            data.append(TAG_SEQUENCE)
            _append_number(data, len(value))
            for element in value:
                _append_number(data, element)
    text = base64.urlsafe_b64encode(bytes(data)).rstrip(b"=").decode("ascii")
    return PREFIX + text


def decode(token: str) -> list[Choice]:
    """Return the choice sequence a token records.

    A token is valid only in the form encode() returns. decode() reads the
    text leniently and then encodes the choices it read, so padding,
    characters outside base64url, trailing bits, a negative zero and a
    number with superfluous bytes each fail that comparison.

    Raises:
        ValueError: token is not the token encode() returns for any choice
            sequence, or it states an unknown tag, a payload cut short, a
            number of 2^64 or more, or a negative integer below -2^63.
    """
    if not token.startswith(PREFIX):
        raise ValueError(f"prop: token {token!r} does not start with {PREFIX}")
    text = token.removeprefix(PREFIX)
    try:
        data = base64.urlsafe_b64decode(text + "=" * (-len(text) % _BASE64_QUANTUM))
    except ValueError as bad:
        raise ValueError(f"prop: token {token!r} is not base64url: {bad}") from bad
    reader = _Reader(data)
    choices: list[Choice] = []
    while not reader.done():
        choices.append(reader.choice())
    if encode(choices) != token:
        raise ValueError(f"prop: token {token!r} is not in canonical form")
    return choices


def _append_number(data: bytearray, number: int) -> None:
    """Append number, at least 0, in unsigned LEB128."""
    while number > LEB128_PAYLOAD:
        data.append(number & LEB128_PAYLOAD | LEB128_MORE)
        number >>= LEB128_BITS
    data.append(number)


@final
class _Reader:
    """The bytes of a token, read once from the start."""

    def __init__(self, data: bytes) -> None:
        """Read data from its first byte."""
        self._data = data
        self._at = 0

    def done(self) -> bool:
        """Report whether every byte has been read."""
        return self._at == len(self._data)

    def take(self, count: int) -> bytes:
        """Return the next count bytes.

        Raises:
            ValueError: fewer than count bytes remain.
        """
        if count > len(self._data) - self._at:
            raise ValueError("prop: a token ends inside a choice")
        taken = self._data[self._at : self._at + count]
        self._at += count
        return taken

    def number(self) -> int:
        """Return the next unsigned LEB128 number.

        Raises:
            ValueError: the bytes end inside the number, or the number is
                2^64 or more.
        """
        number = 0
        shift = 0
        while True:
            byte = self.take(1)[0]
            number |= (byte & LEB128_PAYLOAD) << shift
            if number >= NUMBER_LIMIT:
                raise ValueError("prop: a token states a number of 2^64 or more")
            if byte < LEB128_MORE:
                return number
            shift += LEB128_BITS

    def choice(self) -> Choice:
        """Return the next choice.

        Raises:
            ValueError: the tag is unknown, or the payload is malformed.
        """
        tag = self.take(1)[0]
        if tag == TAG_NON_NEGATIVE:
            return Choice("integer", self.number())
        if tag == TAG_NEGATIVE:
            magnitude = self.number()
            if magnitude > NEGATIVE_LIMIT:
                raise ValueError(f"prop: a token states the negative of {magnitude}")
            return Choice("integer", -magnitude)
        if tag == TAG_FLOAT:
            bits = int.from_bytes(self.take(FLOAT_BYTES), "little")
            return Choice("float", from_bits(bits))
        if tag == TAG_SEQUENCE:
            length = self.number()
            return Choice("sequence", tuple(self.number() for _ in range(length)))
        raise ValueError(f"prop: a token states tag {tag}")
