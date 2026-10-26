---
rfc: 0041
title: Complex numbers, fractions and uintptr in the reading table
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-26
updated: 2026-10-26
discussion: https://github.com/dokimasia/assert-spec/issues/24
supersedes: RFC-0011, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0041: Complex numbers, fractions and uintptr in the reading table

## Summary

The Go reader refuses `uintptr`, `complex64`, `complex128` and a
`*big.Rat` whose tag states no scale. The Python reader refuses `complex`
and `fractions.Fraction`. A type that contains one of them fails to read
as a whole. This proposal reads each of them into shapes that the
definition already has:

- `uintptr` reads as an unsigned `int` of the platform's width, as `uint`
  does.
- A complex number reads as a `record` of the fields `real` and `imag`.
  Each field is a `float` of half the width of a Go complex type, and of
  64 bits in Python.
- A fraction reads as a `record` of `num`, a signed 64-bit `int`, and
  `den`, an unsigned 64-bit `int` from 1. Its value is `num/den` in
  lowest terms. A Go `*big.Rat` whose tag states a scale keeps the
  `decimal`.

The fixtures `signal` and `share` of definition 12.2.0 pin both records.

## Motivation

### The types that the readers refuse

`prop.ShapeOf` on assert-go v0.8.0 refuses four types:

```text
uintptr    prop.ShapeOf: uintptr: uintptr is no type that a shape states
complex64  prop.ShapeOf: complex64: complex64 is no type that a shape states
complex128 prop.ShapeOf: complex128: complex128 is no type that a shape states
*big.Rat   prop.ShapeOf: *big.Rat: a *big.Rat reads as a decimal, which needs the tag key scale
```

`prop.shape_of` of assert-python refuses two:

```text
prop.shape_of: complex: complex is not a type that the reader reads
prop.shape_of: Fraction: Fraction is not a type that the reader reads
```

The reading table has no row for these types, apart from the decimal of
a `*big.Rat`. A decimal has no default scale, so a decimal that states no
scale fails to read. The tag of a struct field states the scale. The tag
of a slice field applies to the elements of the slice. A `*big.Rat` that
is a parameter of a property form or a value of a map never reads,
because neither takes a tag.

One such type at any depth fails the read of the whole type. The
property whose input contains one then fails before its first case.
dokimi's suite generator derives the input of each callable through
`of`. The same failure stops the property runs, the budgets, the fuzz
targets and the benchmarks of every callable that takes such a type.

### A generator in every test

Each test states a generator of the type through `using`, or the test
binary registers one:

```go
prop.Using(prop.Composite(func(c *prop.Case) complex128 {
	return complex(c.Draw(prop.Of[float64](), "real"), c.Draw(prop.Of[float64](), "imag"))
}))
```

Each test that takes the type repeats this generator. Because a
generator that a test states has no shape, another language does not
generate the same values for the seed. A registration applies to the
whole test binary instead, and a second registration of one type panics.

## Detailed design

### The readings

| Language | Type | Shape |
|---|---|---|
| Go | `uintptr` | `int` of the platform's width, unsigned: 64 bits on a 64-bit platform |
| Go | `complex64` | `record` of `real` and `imag`, each a `float` of width 32 |
| Go | `complex128` | `record` of `real` and `imag`, each a `float` of width 64 |
| Go | `*big.Rat` whose tag states `scale` | `decimal` of the scale, as today |
| Go | `*big.Rat` whose tag states no `scale` | `record` of `num`, an `int` of width 64, signed, and `den`, an `int` of width 64, unsigned, with `min` 1 |
| Python | `complex` | `record` of `real` and `imag`, each a `float` of width 64 |
| Python | `fractions.Fraction` | The record of a Go `*big.Rat` without a scale |

A `complex128` and a Python `complex` read as this shape file:

```json
{ "shape": "record", "fields": [
    ["real", { "shape": "float", "width": 64 }],
    ["imag", { "shape": "float", "width": 64 }] ] }
```

A fraction of either language reads as this one:

```json
{ "shape": "record", "fields": [
    ["num", { "shape": "int", "width": 64, "signed": true }],
    ["den", { "shape": "int", "width": 64, "signed": false, "min": 1 }] ] }
```

The Go and Python rows of the reading table become:

| Language | Reads | Does not read |
|---|---|---|
| Go | `bool`, the sized integers, `uintptr`, `float32`, `float64`, `complex64` and `complex128` as records, `string`, `[]byte` and `[N]byte` as `bytes`, slices, arrays, maps, `map[T]struct{}` as a `set`, structs, pointers as `optional`, `time.Time` as an `instant` at nanoseconds, `time.Duration`, `*time.Location` as a `zone`, `uuid.UUID`, `netip.Addr`, `*big.Int` as a 128-bit `int`, `*big.Rat` as a `decimal` of the scale that its tag states and as a fraction without one | Interfaces without `RegisterVariants`, channels, functions. Unexported fields keep their zero value. A `rune` reads as an `int32` unless its tag states `char` |
| Python | `bool`, `int` as a signed 64-bit `int` unless constrained, `float`, `complex` and `Fraction` as records, `str`, `bytes`, `list`, `tuple` as a `record`, `set`, `frozenset`, `dict`, `Optional`, a union as an `enum` of its members, `Literal`, `Enum`, dataclasses, `TypedDict`, `NamedTuple`, `date`, `time`, `datetime` by its `Timezone` constraint, `timedelta`, `ZoneInfo`, `UUID`, `IPv4Address`, `IPv6Address`, `Decimal` | `Any`, and protocols without registration |

Rust, Java, Kotlin and TypeScript keep their rows.

### Values

- The value of a complex record is the complex number of its parts. The
  inverse of a complex number is the record of its real and its imaginary
  part.
- The value of a fraction record is `num/den`. Go's `big.Rat.SetFrac` and
  Python's `Fraction` reduce it to lowest terms, so the records 2/4 and
  1/2 decode to the same value. The inverse of a fraction is the record of
  its lowest terms, with a denominator above 0, as both types store it.
- A fraction whose numerator is outside the signed 64-bit range, or whose
  denominator is outside the unsigned 64-bit range, has no record, and its
  inverse fails. A decimal whose unscaled value is outside the 64-bit
  range fails its inverse in the same way.
- A nil `*big.Rat` has no inverse, as a nil decimal has none.

Each part keeps the default of its shape. The parts of a complex number
are finite. The number shrinks towards 0. A numerator ranges over the
signed 64-bit range and a denominator from 1 to the largest unsigned
64-bit integer, so a fraction shrinks towards 0/1.

### Constraints

A bound of a complex number can apply to each part, to the modulus or to
the argument, so a complex number takes no constraint. A bound of a
rational value bounds neither its numerator nor its denominator, so a
fraction takes none either.

- In Go, a key of the tag of a complex field fails the read, with the
  reader's fault for a key that applies to no part of the type.
- A Go `*big.Rat` whose tag states `min` or `max` without `scale` fails
  to read, because a bound applies to a decimal:
  `a *big.Rat with a bound reads as a decimal, which needs the tag key scale`.
- In Python, a constraint of a `complex` or a `Fraction` fails the read,
  as any constraint that a part does not take fails it.

A caller who needs a bound states a decimal with a scale or a generator
through `using`.

### The width of a uintptr

A `uintptr` is as wide as a pointer. It has 64 bits on a 64-bit platform
and 32 bits on a 32-bit platform, and its shape states that width. The
entry `prop.of` of the Go overlay declares the 32-bit readings of `int`
and `uint` on a 32-bit platform. It adds `uintptr`. Like the other
integers, a `uintptr` takes the tag keys `min` and `max`.

### The fixture vectors

`corpus/prop/fixtures.yaml` gains two fixtures:

```yaml
- id: fixtures/signal
  fixture: signal
  covers: complex
  summary: >-
    A record of one complex field, sample, a record of the 64-bit floats
    real and imag.
  shape:
    shape: record
    fields:
      - - sample
        - shape: record
          fields: [[real, {shape: float, width: 64}], [imag, {shape: float, width: 64}]]
  skip: *no-complex
- id: fixtures/share
  fixture: share
  covers: fraction
  summary: >-
    A record of one rational field, part, a record of num, a signed 64-bit
    integer, and den, an unsigned 64-bit integer from 1.
  shape:
    shape: record
    fields:
      - - part
        - shape: record
          fields:
            - [num, {shape: int, width: 64, signed: true}]
            - [den, {shape: int, width: 64, signed: false, min: 1}]
  skip: *no-fraction
```

Go declares `signal` with a `complex128` field and `share` with a
`*big.Rat` field whose tag states no scale. Python declares a dataclass
with a `complex` field and one with a `Fraction` field. Rust, Java and
Kotlin skip both fixtures. Their standard libraries have no complex type
and no rational type. Its compiler erases types, so TypeScript skips
these two as it skips every fixture.

The width of a `uintptr` follows the platform, as the widths of a Go
`int` and `uint` do. No fixture states those two types or a `uintptr`.
The specs of assert-go check its reading.

### The implementations

| Implementation | Change |
|---|---|
| assert-go | The reader gains the three readings, and their converters the values and the inverses. The conformance runner declares `signal` and `share` |
| assert-python | The reader gains the readings of `complex` and `Fraction`, with their converters. The conformance runner declares `signal` and `share` |
| assert-rust | The runner of the property vectors skips a vector whose skip names Rust, as its runner of the corpus does |
| assert-typescript | Vendors the definition. Its runner skips both fixtures already |
| assert-java | Skips both fixtures when it vendors 12.2.0 |

### Versioning

Definition 12.2.0 is a minor version. It adds two vectors and widens the
reading table. A type that read before reads as before, and a stored case
of a property decodes to the same value. A type that failed to read now
reads. Every overlay extends 12.2.0.

## Alternatives considered

### A. A default scale for a `*big.Rat`

A `*big.Rat` without a tag would read as a decimal of a default scale,
such as 2.

**Why not:** no single scale suits most domains. For that reason a
decimal has no default scale. No finite scale states 1/3, while a
fraction states every rational value whose parts fit 64 bits. A caller
who wants a decimal states its scale.

### B. The shapes `complex` and `rational`

The definition would gain two shapes, each with its own generator.

**Why not:** every language would map two more shapes, and the
definition would gain two generators for values that a record of floats
and a record of integers state already. A record generates, shrinks and
runs backwards through the shapes that exist, and two languages that
read the same record generate the same values for a seed.

### C. A complex number as a fixed list of two floats

A `fixed-list` of two floats of half the width.

**Why not:** the elements of a list have positions and no names. The
fields of a record have the names `real` and `imag`, the names of Go's
built-in functions and of Python's attributes for the two parts. A
counterexample in a failure report then shows each part under its name.

### D. The denominator first

Hypothesis 6.168.3 generates the denominator of a `Fraction` before its
numerator. It shrinks a fraction towards smaller denominators first.

**Why not:** both orders shrink each part towards its target. For a
failure that does not depend on the value, both end at 0/1. The
numerator comes first in `big.Rat.SetFrac(a, b)`, in
`Fraction(numerator, denominator)` and in a fraction as a person writes
it.

### E. Each test states its generator

The readers keep refusing these types. Each test states a generator
through `using`, or the test binary registers one.

**Why not:** each test repeats the generator. A generator without a
shape generates other values in another language for one seed. A
registration applies to every test of the binary, and a second
registration of the type panics.

### F. A `uintptr` refused as an address

A `uintptr` often stores an address, and a generated address points
nowhere.

**Why not:** the reader reads the fields of a struct, and a `uintptr`
field there is an integer of the platform's width. `testing/quick`,
gofuzz and rapid generate `uintptr` as an unsigned integer. A test that
needs valid addresses states its own generator.

### G. The Go reader alone

The Python reader would keep its table, and Python would skip both
fixtures.

**Why not:** Python's standard library has both types, and Hypothesis
derives a strategy for both from the type. A fixture that Python skips
although its standard library has the type pins its record in one
language. With Python, the vectors pin both records in two languages.

## Drawbacks

- The Go reader gains three readings and two converters, and the Python
  reader two readings and two converters. Rust's runner of the property
  vectors gains the skip that its runner of the corpus has, and each
  implementation that vendors the definition moves to 12.2.0.
- Most generated fractions have parts of many digits, because the parts
  range over 64 bits. A test that needs small fractions states a decimal
  with a scale, or a generator through `using`.
- A complex number and a fraction take no constraint, so a test that
  needs bounded values states a generator.
- A `*big.Rat` field without a tag reads as a fraction instead of failing.
  A suite that relied on the failure to make every `*big.Rat` state its
  scale loses that check.
- A `uintptr` generates other values on a 32-bit platform than on a
  64-bit one, as an `int` does.

## Unresolved and future work

- The standard libraries of Rust, Java and Kotlin have no complex or
  rational type, and this proposal does not read one of their crates or
  libraries. Rust's `num-complex` and `num-rational` and the types of
  Apache Commons Numbers stay outside their readers, so a caller states a
  generator or registers one.
- This proposal does not state a constraint of a complex number or a
  fraction.

## References

| What | Where |
|---|---|
| The issue that this proposal answers | <https://github.com/dokimasia/assert-spec/issues/24> |
| `testing/quick` builds a complex value from two floats and generates `uintptr` | <https://github.com/golang/go/blob/go1.27.3/src/testing/quick/quick.go#L79-L104> |
| gofuzz fills `complex64` and `complex128` from two floats and `uintptr` as an unsigned integer | <https://github.com/google/gofuzz/blob/v1.2.0/fuzz.go#L463-L489> |
| rapid's `Make` generates `uintptr` and refuses the complex kinds | <https://github.com/flyingmutant/rapid/blob/v1.3.0/make.go#L98-L139> |
| Hypothesis 6.168.3 derives `complex_numbers()` from `complex` and `fractions()` from `Fraction` | <https://github.com/HypothesisWorks/hypothesis/blob/v6.168.3/hypothesis/src/hypothesis/strategies/_internal/types.py#L893-L894> |
| Hypothesis 6.168.3 generates a fraction from its denominator first | <https://github.com/HypothesisWorks/hypothesis/blob/v6.168.3/hypothesis/src/hypothesis/strategies/_internal/core.py#L1739-L1820> |
| Hypothesis 6.168.3 builds a complex number from two floats | <https://github.com/HypothesisWorks/hypothesis/blob/v6.168.3/hypothesis/src/hypothesis/strategies/_internal/core.py#L2194-L2278> |
