"""The three kinds of choice a case is made of.

A choice is one typed decision within bounds: an integer, a float or a
sequence of small integers. Every choice has a target, the simplest value
its bounds allow, and a sort key that orders its values from simplest.
The shrinker moves values towards their targets, and it accepts a
candidate only when the case gets shortlex-smaller under these keys.

A replay hands a generator the value a case recorded. When that value is
of another kind, or outside the bounds the generator now requests, the
bounds coerce it: a sequence is cut, extended or cleaned, and any other
value becomes the target. Every prefix of a recorded case is therefore a
valid case.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, Literal

#: The bounds an integer choice may have: both inside the signed or both
#: inside the unsigned 64-bit range.
INT64_MIN: Final = -(1 << 63)
INT64_MAX: Final = (1 << 63) - 1
UINT64_MAX: Final = (1 << 64) - 1

#: Integral floats below this magnitude sort first, by magnitude.
INTEGRAL_LIMIT: Final = 1 << 53

#: The widths of a float choice, and the most fractional bits a finite
#: float of each width has.
WIDTH_32: Final = 32
WIDTH_64: Final = 64
MAX_FRACTION_BITS: Final = {WIDTH_32: 149, WIDTH_64: 1074}

#: The canonical quiet NaN. Every NaN in a choice has these bits.
NAN_BITS: Final = 0x7FF8000000000000

#: The values a float's sort key starts with, one per group, simplest
#: first.
GROUP_INTEGRAL: Final = 0
GROUP_FRACTION: Final = 1
GROUP_INFINITE: Final = 2
GROUP_NAN: Final = 3

Kind = Literal["integer", "float", "sequence"]
Value = int | float | tuple[int, ...]


def bits_of(x: float) -> int:
    """Return the IEEE 754 binary64 bits of x."""
    bits: int = struct.unpack("<Q", struct.pack("<d", x))[0]
    return bits


def from_bits(bits: int) -> float:
    """Return the binary64 float with these bits."""
    value: float = struct.unpack("<d", struct.pack("<Q", bits))[0]
    return value


def from_bits32(bits: int) -> float:
    """Return the binary32 float with these bits, as a Python float."""
    value: float = struct.unpack("<f", struct.pack("<I", bits))[0]
    return value


NAN: Final = from_bits(NAN_BITS)


def _round32(x: float) -> float:
    """Round x to the nearest binary32 value, or to an infinity."""
    try:
        rounded: float = struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)
    return rounded


def representable(x: float, width: int) -> bool:
    """Report whether x is a value of a float of the given width."""
    if width == WIDTH_64 or math.isnan(x) or math.isinf(x):
        return True
    return _round32(x) == x


def next_up(x: float, width: int) -> float:
    """Return the smallest value of the width above x.

    Both zeros step to the smallest positive subnormal. Positive infinity
    and NaN return themselves.
    """
    if width == WIDTH_64:
        return math.nextafter(x, math.inf)
    if math.isnan(x) or x == math.inf:
        return x
    if x == 0.0:
        return from_bits32(1)
    bits: int = struct.unpack("<I", struct.pack("<f", x))[0]
    return from_bits32(bits + 1 if x > 0.0 else bits - 1)


def next_down(x: float, width: int) -> float:
    """Return the largest value of the width below x."""
    return -next_up(-x, width)


def ceil_width(x: float, width: int) -> float:
    """Return the smallest value of the width that is x or more."""
    if width == WIDTH_64:
        return x
    rounded = _round32(x)
    return rounded if rounded >= x else next_up(rounded, width)


def float_key(x: float) -> tuple[int, ...]:
    """Return the sort key of a float: a smaller key is a simpler value.

    From simplest: integral values below 2^53 in magnitude, by magnitude;
    other finite values, by their number of fractional bits and then
    their numerator; the infinities; NaN. Within a group a positive value
    precedes the negative value of equal magnitude, and +0 precedes -0.
    """
    if math.isnan(x):
        return (GROUP_NAN,)
    negative = 1 if math.copysign(1.0, x) < 0.0 else 0
    if math.isinf(x):
        return (GROUP_INFINITE, negative)
    exact = Fraction(x)
    if exact.denominator == 1 and abs(exact) < INTEGRAL_LIMIT:
        return (GROUP_INTEGRAL, abs(exact.numerator), negative)
    fraction_bits = exact.denominator.bit_length() - 1
    return (GROUP_FRACTION, fraction_bits, abs(exact.numerator), negative)


def same_float(a: float, b: float) -> bool:
    """Report whether two floats are one value, NaN and signed zeros included."""
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return bits_of(a) == bits_of(b)


def simplest_float(lo: float, hi: float, width: int) -> float:
    """Return the value of the width in [lo, hi] with the smallest key.

    Raises:
        ValueError: [lo, hi] contains no value of the width.
    """
    if lo <= 0.0 <= hi:
        return 0.0
    if lo > 0.0:
        return _simplest_positive(lo, hi, width)
    return -_simplest_positive(-hi, -lo, width)


def _simplest_positive(lo: float, hi: float, width: int) -> float:
    """Return the simplest value of the width in [lo, hi], for 0 < lo <= hi.

    Raises:
        ValueError: [lo, hi] contains no value of the width.
    """
    if math.isinf(lo):
        return lo

    smallest_integral = math.ceil(lo)
    if smallest_integral < INTEGRAL_LIMIT:
        candidate = ceil_width(float(smallest_integral), width)
        if candidate <= hi and candidate < INTEGRAL_LIMIT:
            return candidate

    # Every value of either width at 2^53 or above is an integer, and the
    # integers there precede every fraction.
    if hi >= INTEGRAL_LIMIT:
        candidate = ceil_width(max(lo, float(INTEGRAL_LIMIT)), width)
        if candidate <= hi:
            return candidate

    # A fraction n / 2^f in lowest terms has an odd n. At one f, the
    # smallest odd n in range has the fewest significant bits, so when it
    # is not a value of the width, no larger n at that f is either.
    low = Fraction(lo)
    high = None if math.isinf(hi) else Fraction(hi)
    for fraction_bits in range(1, MAX_FRACTION_BITS[width] + 1):
        scale = 1 << fraction_bits
        numerator = math.ceil(low * scale)
        if numerator % 2 == 0:
            numerator += 1
        exact = Fraction(numerator, scale)
        if high is not None and exact > high:
            continue
        candidate = float(exact)
        if Fraction(candidate) == exact and representable(candidate, width):
            return candidate
    raise ValueError(f"prop: [{lo}, {hi}] contains no float of width {width}")


@dataclass(frozen=True)
class Choice:
    """One recorded decision: its kind and the value the case used."""

    kind: Kind
    value: Value


def _is_int(value: object) -> bool:
    """Report whether value is an int and not a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class IntegerBounds:
    """The bounds of an integer choice, both inclusive."""

    lo: int
    hi: int

    def __post_init__(self) -> None:
        """Refuse bounds that are empty or straddle the two 64-bit ranges.

        Raises:
            ValueError: lo exceeds hi, or the bounds lie inside neither the
                signed nor the unsigned 64-bit range.
        """
        if self.lo > self.hi:
            raise ValueError(f"prop: integer bounds [{self.lo}, {self.hi}] are empty")
        signed = self.lo >= INT64_MIN and self.hi <= INT64_MAX
        unsigned = self.lo >= 0 and self.hi <= UINT64_MAX
        if not (signed or unsigned):
            raise ValueError(
                f"prop: integer bounds [{self.lo}, {self.hi}] are inside neither "
                "the signed nor the unsigned 64-bit range"
            )

    @property
    def kind(self) -> Kind:
        """Return the kind these bounds take."""
        return "integer"

    @property
    def target(self) -> int:
        """Return the value closest to zero, which is zero when the bounds admit it."""
        if self.lo <= 0 <= self.hi:
            return 0
        return self.lo if self.lo > 0 else self.hi

    def key(self, value: int) -> tuple[int, int]:
        """Return (distance to the target, 1 when below the target, else 0)."""
        target = self.target
        return (abs(value - target), 1 if value < target else 0)

    def rank(self, value: int) -> int:
        """Return the position of value in the key order of the bounds.

        The target is 0. The order runs one above the target, one below,
        two above, two below, and so on, and continues on the longer side
        once the shorter side reaches its bound.
        """
        target = self.target
        shorter = min(self.hi - target, target - self.lo)
        distance = abs(value - target)
        if distance > shorter:
            return shorter + distance
        if value > target:
            return 2 * distance - 1
        return 2 * distance

    def at_rank(self, rank: int) -> int:
        """Return the value at a position of the key order, the inverse of rank()."""
        target = self.target
        above, below = self.hi - target, target - self.lo
        shorter = min(above, below)
        if rank > 2 * shorter:
            distance = rank - shorter
            return target + distance if above > below else target - distance
        distance = (rank + 1) // 2
        return target + distance if rank % 2 == 1 else target - distance

    def admits(self, value: object) -> bool:
        """Report whether value is an integer inside the bounds."""
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        return self.lo <= value <= self.hi

    def coerce(self, recorded: Choice) -> int:
        """Return the recorded value when it fits, otherwise the target."""
        value = recorded.value
        if recorded.kind == "integer" and isinstance(value, int) and self.admits(value):
            return value
        return self.target


@dataclass(frozen=True)
class FloatBounds:
    """The bounds of a float choice: an inclusive range, NaN and a width.

    An infinite bound admits that infinity. NaN is a value only when
    allow_nan is set, and it is always the canonical quiet NaN.
    """

    lo: float
    hi: float
    allow_nan: bool = False
    width: int = WIDTH_64

    def __post_init__(self) -> None:
        """Refuse bounds that contain no value of their width.

        Raises:
            ValueError: the width is neither 32 nor 64, a bound is NaN or
                not of the width, lo exceeds hi, or no value of the width
                lies between them.
        """
        if self.width not in MAX_FRACTION_BITS:
            raise ValueError(f"prop: float width {self.width} is neither 32 nor 64")
        if math.isnan(self.lo) or math.isnan(self.hi) or self.lo > self.hi:
            raise ValueError(f"prop: float bounds [{self.lo}, {self.hi}] are empty")
        for bound in (self.lo, self.hi):
            if not representable(bound, self.width):
                raise ValueError(
                    f"prop: float bound {bound} is not a value of width {self.width}"
                )
        simplest_float(self.lo, self.hi, self.width)

    @property
    def kind(self) -> Kind:
        """Return the kind these bounds take."""
        return "float"

    @property
    def target(self) -> float:
        """Return the value in the bounds with the smallest sort key."""
        return simplest_float(self.lo, self.hi, self.width)

    def key(self, value: float) -> tuple[int, ...]:
        """Return the sort key of value."""
        return float_key(value)

    def admits(self, value: object) -> bool:
        """Report whether value is a float of the width inside the bounds."""
        if not isinstance(value, float):
            return False
        if math.isnan(value):
            return self.allow_nan
        return self.lo <= value <= self.hi and representable(value, self.width)

    def coerce(self, recorded: Choice) -> float:
        """Return the recorded value when it fits, otherwise the target."""
        value = recorded.value
        if recorded.kind == "float" and isinstance(value, float) and self.admits(value):
            return NAN if math.isnan(value) else value
        return self.target


@dataclass(frozen=True)
class SequenceBounds:
    """The bounds of a sequence choice: its element range and its length.

    Every element is an integer in [0, k). A max_size of None leaves the
    length unbounded, and the cap on choices per case bounds it instead.
    """

    k: int
    min_size: int = 0
    max_size: int | None = None

    def __post_init__(self) -> None:
        """Refuse bounds that admit no sequence.

        Raises:
            ValueError: k is below 1, min_size is negative, or max_size is
                below min_size.
        """
        if self.k < 1:
            raise ValueError(f"prop: a sequence with k = {self.k} has no element")
        if self.min_size < 0 or (
            self.max_size is not None and self.max_size < self.min_size
        ):
            raise ValueError(
                f"prop: sequence sizes [{self.min_size}, {self.max_size}] are empty"
            )

    @property
    def kind(self) -> Kind:
        """Return the kind these bounds take."""
        return "sequence"

    @property
    def target(self) -> tuple[int, ...]:
        """Return min_size zeros."""
        return (0,) * self.min_size

    def key(self, value: tuple[int, ...]) -> tuple[int, tuple[int, ...]]:
        """Return (length, elements): shorter first, then smaller first."""
        return (len(value), value)

    def admits(self, value: object) -> bool:
        """Report whether value is a sequence the bounds admit."""
        if not isinstance(value, tuple):
            return False
        if len(value) < self.min_size:
            return False
        if self.max_size is not None and len(value) > self.max_size:
            return False
        return all(_is_int(e) and 0 <= e < self.k for e in value)

    def coerce(self, recorded: Choice) -> tuple[int, ...]:
        """Fit a recorded sequence to the bounds, or return the target.

        A longer sequence is cut to max_size, a shorter one is extended
        with zeros to min_size, and an element outside [0, k) becomes 0.
        A value of another kind becomes the target.
        """
        value = recorded.value
        if recorded.kind != "sequence" or not isinstance(value, tuple):
            return self.target
        elements = [e if _is_int(e) and 0 <= e < self.k else 0 for e in value]
        if self.max_size is not None:
            elements = elements[: self.max_size]
        elements.extend([0] * (self.min_size - len(elements)))
        return tuple(elements)


Bounds = IntegerBounds | FloatBounds | SequenceBounds
