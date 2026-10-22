---
rfc: 0037
title: The values of a generator under the option using
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-22
updated: 2026-10-22
discussion: https://github.com/dokimasia/assert-spec/issues/19
supersedes: RFC-0035, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0037: The values of a generator under the option using

## Summary

`prop.values(generator, seed, n)` decodes each draw of `of` with the
registration or the shape of its type. A run of `prop.for-all` or
`prop.fuzz` that takes `prop.using` decodes the same draw with the
generator that `using` states. This proposal lets `values` take the
options of `using`:

- Each option makes its generator the generator of its type in the call,
  as it does in a run.
- A call without options returns the values that it returns in 10.0.0.
- A call fails for an option that states another setting.
- TypeScript declines the options, as its runs decline `using`.

Definition 10.1.0 adds the options.

## Motivation

A benchmark takes its inputs from `values`, and a property often checks
the same callable in a run that states `using`. The benchmark and the
property then draw from different domains. assert-go at 37ff68d shows the
difference for an enumeration over `int`:

```go
type status int

const (
	pending status = iota + 1
	paid
	shipped
)

type order struct {
	Status status
	Lines  int
}

members := prop.SampledFrom(pending, paid, shipped)
prop.ForAll(t, "each order has a declared status", func(c *prop.Case) {
	o := c.Draw(prop.Of[order](), "order")
	// …
}, prop.Using(members), prop.Seed(42), prop.Hermetic())

orders := prop.Values(prop.Of[order](), 42, 100)
```

- Each order of the run has one of the three statuses.
- 96 of the 100 orders of `Values` have a status outside the three, such
  as `{Status:-1 Lines:-7183301636059021450}`.

A caller can register the generator of the type with `prop.register`. A
registration applies to the whole test process. A second registration of
one type fails, so two packages of one test binary cannot both narrow the
type. `using` narrows the type for one run. `values` does not take it.

In fast-check, `sample(generator, params)` takes the same type of
parameters as `assert`. A sample and a run with the same parameters then
draw from one domain.

## Detailed design

### The options

```text
values(generator, seed, n, options...) -> list of n values
    Returns n values of generator for seed, as definition 10.0.0 states.
    Each option of using makes its generator the generator of its type in
    the call.
```

- The stated generators apply as they apply in a run. A draw of `of` of a
  stated type decodes with the stated generator. A draw of `of` of any
  other type decodes each value of a stated type inside it with the stated
  generator. Inside the stated generator of a type, a draw of `of` of that
  type decodes without the stated generator.
- Every other generator, such as `prop.integer(0, 9)`, decodes as it does
  without the options.
- A later option of one type replaces an earlier one.
- The call fails for an option that states a setting other than `using`,
  before it decodes a case. `values` does not run a property, so no other
  setting of a run applies to it.
- A draw whose type the reader refuses under the stated generators fails
  the call, as a failure of the generator does.
- The values of one seed under one set of options form one sequence, as
  they do for a call without options.

### The languages

```go
// Values returns n values of g for seed. Each option of Using makes its
// generator the generator of its type, as it does in a run.
//
// # Panics
//
// Values panics for n below 0, for an option that states a setting other
// than Using, and when g rejects more than ten cases for each value.
func Values[T any](g Generator[T], seed uint64, n int, opts ...Option) []T
```

```python
def values(generator: Generator[T], seed: int, n: int, *options: Option) -> list[T]:
    """Return n values of generator for seed under the options of using.

    Raises:
        ValueError: n is not an int of 0 or more, seed is not an int in
            [0, 2**64), an option is not an option of using, or the
            generator rejects more than 10n cases.
    """
```

```rust
/// Returns `n` values of `generator` for `seed`. The generators that
/// `options` states through `using` apply as they apply in a run.
///
/// # Panics
///
/// Panics when a setting of `options` other than `using` differs from its
/// default, and when the generator rejects more than ten cases for each
/// value.
pub fn values<T: 'static>(generator: &Generator<T>, seed: u64, n: usize, options: Options) -> Vec<T>;
```

- Rust has no variadic function, and a run takes its settings as one
  `Options` value. A Rust call without options passes `Options::default()`.
  The builder keeps no record of the settings that a caller states, so a
  setting stated at its default value passes the check.
- Java and Kotlin take the options of `Prop.using` as trailing arguments of
  `Prop.values`.
- TypeScript declines the options. The TypeScript compiler erases every
  type, so a call has no type to give a generator to. Its overlay limits
  `prop.using` to the input of a property form, and the limit names
  `prop.values` beside `forAll` and `fuzz`.

### Names

The naming table does not change. `prop.values` and `prop.using` keep
their names.

### Conformance

No vector covers the options, because the executable reference has no
`using`. Each implementation that takes the options tests them in its own
specs:

- A call decodes each draw of `of` of a stated type with the stated
  generator, also inside a derived value.
- Inside the stated generator of a type, a draw of `of` of that type
  decodes without the stated generator.
- A call with an option of another setting fails.

### Version

A call without options keeps its meaning, so the definition moves to
10.1.0. Every overlay extends 10.1.0.

## Alternatives considered

### A. A map from each type to its generator

`values` would take a map from each type to the generator of the type.

**Why not:** `using` already states the generator of a type, and it takes
the type from the generator. A map would spell the same thing a second
way, and its keys would need a type token in Go and Rust.

### B. Every option of a run

`values` would take every option of a run, and ignore an option that
states a phase of a run, such as `cases` or `shrink`.

**Why not:** the call would ignore such an option, and the caller would
not learn it. A caller who passes `seed` would expect it to replace the
seed argument.

### C. The values of a run that takes `using`

A harness would collect the values of a run of `for-all` that takes
`using`, before its timed loop.

**Why not:** the run records a property assertion. It also tries the
simplest case and the boundary cases before its random cases, so its
values depend on the phases of the run and not on the seed alone.

## Drawbacks

- `values` gains a parameter in Go, Python, Rust, Java and Kotlin. A Rust
  call without options passes `Options::default()`.
- A call with an option of another setting fails when it runs, not when it
  compiles.
- TypeScript declines the options. A TypeScript benchmark narrows a type
  through the generator that it passes to `values`.
- No vector covers the options, so the specs of each library alone test
  them.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/19> |
| The helper `values` | RFC-0035 |
| The option `using` | RFC-0011 |
| fast-check's `sample` | <https://github.com/dubzzz/fast-check/blob/main/packages/fast-check/src/check/runner/Sampler.ts> |
