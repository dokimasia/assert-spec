"""The random source, checked against the code its author published.

The stream must equal Bob Jenkins's C implementation bit for bit, because
every implementation of the standard computes it on its own. The outputs
in testdata/smallprng.json come from compiling that code, and
testdata/smallprng.c states the command that produced them.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import final

from .source import BITS, MASK, Source, case_source, mix

ORACLE = Path(__file__).resolve().parent / "testdata" / "smallprng.json"

#: The odds of the coin that the coin test replays.
COIN_NUM = 3
COIN_DEN = 8

#: The stream of the ``ci`` seed derived from this contract is pinned, so
#: that a change to the mixing fails here before any vector moves.
CONTRACT = "decoding undoes encoding"
CONTRACT_SEED = 14330315428228886101


@final
class SourceTest(unittest.TestCase):
    """The stream, its draws and the mixing, each held to its rule."""

    def test_the_stream_equals_the_published_c_code(self) -> None:
        """Five seeds, 32 outputs each, as Jenkins's code prints them."""
        outputs: dict[str, list[str]] = json.loads(ORACLE.read_text())["outputs"]
        self.assertEqual(len(outputs), 5)
        for seed, expected in outputs.items():
            source = Source(int(seed))
            got = [str(source.next()) for _ in expected]
            self.assertEqual(got, expected, f"seed {seed}")

    def test_a_seed_outside_64_bits_is_refused(self) -> None:
        """A seed is an unsigned 64-bit integer, and nothing else."""
        for seed in (-1, MASK + 1):
            with self.assertRaises(ValueError):
                Source(seed)

    def test_case_i_reads_the_stream_of_seed_plus_i(self) -> None:
        """Case 2 of seed 40 and case 0 of seed 42 are one stream."""
        self.assertEqual(case_source(40, 2).next(), Source(42).next())

    def test_the_case_seed_wraps_at_2_to_the_64(self) -> None:
        """Seed + index is taken modulo 2^64."""
        self.assertEqual(case_source(MASK, 1).next(), Source(0).next())

    def test_below_one_returns_zero_and_consumes_nothing(self) -> None:
        """A range with one value draws nothing from the stream."""
        source, twin = Source(7), Source(7)
        self.assertEqual(source.below(1), 0)
        self.assertEqual(source.next(), twin.next())

    def test_below_keeps_the_top_bits_and_redraws_values_out_of_range(
        self,
    ) -> None:
        """Each attempt keeps bit_length(n - 1) top bits; n or more redraws."""
        for n in (2, 3, 10, 1000, (1 << 63) + 5):
            source, twin = Source(n), Source(n)
            width = (n - 1).bit_length()
            for _ in range(200):
                expected = twin.next() >> (BITS - width)
                while expected >= n:
                    expected = twin.next() >> (BITS - width)
                self.assertEqual(source.below(n), expected, f"n = {n}")

    def test_below_2_to_the_64_returns_whole_values(self) -> None:
        """The widest range keeps all 64 bits and never redraws."""
        source, twin = Source(3), Source(3)
        for _ in range(10):
            self.assertEqual(source.below(MASK + 1), twin.next())

    def test_below_outside_its_domain_is_refused(self) -> None:
        """The range of below() is at least 1 and at most 2^64."""
        for n in (0, MASK + 2):
            with self.assertRaises(ValueError):
                Source(1).below(n)

    def test_coin_compares_one_below_draw_with_num(self) -> None:
        """coin(num, den) is below(den) < num, one draw per coin."""
        source, twin = Source(9), Source(9)
        for _ in range(100):
            self.assertEqual(
                source.coin(COIN_NUM, COIN_DEN), twin.below(COIN_DEN) < COIN_NUM
            )

    def test_coin_odds_outside_zero_to_one_are_refused(self) -> None:
        """The denominator is at least 1 and the numerator lies in [0, den]."""
        for num, den in ((1, 0), (-1, 2), (3, 2)):
            with self.assertRaises(ValueError):
                Source(1).coin(num, den)

    def test_mixing_nothing_returns_zero(self) -> None:
        """The fold starts at zero, so no bytes leave zero."""
        self.assertEqual(mix(b""), 0)

    def test_mixing_folds_each_byte_through_the_stream(self) -> None:
        """Each byte reseeds with value xor byte and takes the first output."""
        first = Source(0 ^ ord("a")).next()
        self.assertEqual(mix(b"ab"), Source(first ^ ord("b")).next())

    def test_mixing_a_contract_gives_its_pinned_value(self) -> None:
        """The ci seed of one contract, pinned."""
        self.assertEqual(mix(CONTRACT.encode()), CONTRACT_SEED)
