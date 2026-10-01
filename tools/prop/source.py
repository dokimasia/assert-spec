"""The random source behind every generated case.

The source is the 64-bit three-rotate variant of Bob Jenkins's small
noncryptographic generator. It uses addition, subtraction, exclusive or
and rotation modulo 2^64 and nothing else, so every target language,
JavaScript and PHP included, computes the same stream from the same seed.

Case ``i`` of a run with seed ``s`` reads the stream of ``s + i``. The
draws consume that stream in an order that is part of the definition, so
two implementations that consume it differently produce different cases
from the same seed.
"""

from __future__ import annotations

from typing import Final, final

#: Every value of the stream is an unsigned 64-bit integer.
BITS: Final = 64
MASK: Final = (1 << BITS) - 1

#: The constant that the initialisation puts in the first word.
FIRST_WORD: Final = 0xF1EA5EED

#: The rounds that the initialisation discards, so that nearby seeds
#: give unrelated streams.
WARMUP_ROUNDS: Final = 20

#: The rotations of the three-rotate variant for 64-bit words.
ROTATE_B: Final = 7
ROTATE_C: Final = 13
ROTATE_D: Final = 37


def _rotl(value: int, count: int) -> int:
    """Rotate a 64-bit value left by count bits."""
    return ((value << count) | (value >> (BITS - count))) & MASK


@final
class Source:
    """The stream of 64-bit values that one seed produces.

    A source is not safe for concurrent use. Each case reads its own.
    """

    __slots__ = ("_a", "_b", "_c", "_d")

    def __init__(self, seed: int) -> None:
        """Start the stream of seed, an unsigned 64-bit integer.

        Raises:
            ValueError: seed is outside [0, 2^64).
        """
        if not 0 <= seed <= MASK:
            raise ValueError(f"prop: seed {seed} is not an unsigned 64-bit integer")
        self._a = FIRST_WORD
        self._b = seed
        self._c = seed
        self._d = seed
        for _ in range(WARMUP_ROUNDS):
            self.next()

    def next(self) -> int:
        """Return the next 64-bit value of the stream."""
        e = (self._a - _rotl(self._b, ROTATE_B)) & MASK
        self._a = self._b ^ _rotl(self._c, ROTATE_C)
        self._b = (self._c + _rotl(self._d, ROTATE_D)) & MASK
        self._c = (self._d + e) & MASK
        self._d = (e + self._a) & MASK
        return self._d

    def below(self, n: int) -> int:
        """Return a value in [0, n), uniform, for 1 <= n <= 2^64.

        For n of 1 the result is 0 and nothing is consumed. Otherwise each
        attempt consumes one value and keeps its top bit_length(n - 1)
        bits, and the draw repeats while the result is n or more.

        Raises:
            ValueError: n is outside [1, 2^64].
        """
        if not 1 <= n <= MASK + 1:
            raise ValueError(f"prop: below({n}) needs 1 <= n <= 2^64")
        if n == 1:
            return 0
        width = (n - 1).bit_length()
        while True:
            value = self.next() >> (BITS - width)
            if value < n:
                return value

    def coin(self, num: int, den: int) -> bool:
        """Return True with probability num/den, from one below(den) draw.

        Raises:
            ValueError: den is below 1, or num is outside [0, den].
        """
        if den < 1 or not 0 <= num <= den:
            raise ValueError(f"prop: coin({num}, {den}) needs 0 <= num <= den")
        return self.below(den) < num


def case_source(seed: int, index: int) -> Source:
    """Return the source of case index in a run with seed.

    The case's seed is seed + index, modulo 2^64.
    """
    return Source((seed + index) & MASK)


def mix(data: bytes) -> int:
    """Fold bytes into one 64-bit value with the random source alone.

    The value starts at zero. For each byte, it becomes the first output
    of the stream seeded with the value xor the byte. This derives the
    ``ci`` seed from a contract's UTF-8 bytes, and the name of a store
    entry, without a hash function that a target language may lack.
    """
    value = 0
    for byte in data:
        value = Source(value ^ byte).next()
    return value
