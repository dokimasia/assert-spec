---
rfc: 0035
title: The values of a generator for a seed
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-22
updated: 2026-10-22
discussion: https://github.com/dokimasia/assert-spec/issues/16
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0035: The values of a generator for a seed

## Summary

A caller takes the values of a generator only inside a property: a body
draws each value from its case. This proposal adds the helper
`prop.values(generator, seed, n)`, which returns n values of a generator
for a seed:

- Value after value, it takes the value of each random case of the seed in
  order, and leaves out a case that the generator rejects.
- One seed gives the same values in every language, as the generation and
  shapes vectors pin them.
- A caller that asks for more values keeps the first ones.
- The call does not record an assertion, write a stored case or read a
  variable of the engine.

Definition 10.0.0 adds the helper.

## Motivation

### A benchmark needs the same inputs in every run

A benchmark that compares two runs needs the same inputs in both runs.
Inputs from a generator also cover more paths of a callable than one
literal does. The definition gives a caller the values of a generator only
inside `prop.for-all`, `prop.fuzz` and the property forms. assert-go v0.5.1
documents that "A generator never reads a random source", and no exported
function of `prop` yields a value without a case.

A benchmark today passes a literal or the zero value of each parameter, so
it measures one path. A harness can also collect the values of a run of
`ForAll` before its timed loop:

```go
var ids []string
prop.ForAll(b, "collects the inputs of the benchmark", func(c *prop.Case) {
	ids = append(ids, c.Draw(prop.Of[string](), "id"))
}, prop.Seed(42), prop.Cases(100), prop.Workers(1), prop.Hermetic())
```

That run records a property assertion that does not check the callable.
It also tries the simplest input and the bounds of each integer generator
before its random cases, so the values depend on the phases of a run and
not on the seed alone.

### The corpus already states these values

The generation vectors pin the first cases that a seed generates for each
generator: "Case i draws from the random source initialised with the seed
plus i." The shapes vectors pin the same for every shape. The reference
engine computes these values, and a caller cannot ask for them.

## Detailed design

### The helper

```text
values(generator, seed, n) -> list of n values
    Returns n values of generator for seed. Case k, from 0, draws from the
    random source of seed plus k, as a random case of a run does. The
    value of each case that the generator does not reject is the next
    value, until there are n of them.
```

- A case that the generator rejects does not give a value. A `filter`
  whose attempts all fail rejects its case, and so does a case past 8,192
  choices.
- The call fails when the generator rejects more than 10n cases, ten for
  each of the n values. A run of a property gives up at the same ratio.
- The values of one seed form one sequence. `values(g, s, m)` is the first
  m values of `values(g, s, n)` for any m up to n.
- The call does not take the simplest case, a boundary case or a stored
  case. It does not shrink, record an assertion, write a stored case or
  read the variables `DOKIMI_ASSERT_PROP_*`.
- A generator of a type, `of`, takes its registration or its shape, as in
  a run without `using`.
- An n of 0 returns an empty list, and the call decodes no case.

### The languages

```go
// Values returns n values of g for seed: the values of the random cases of
// seed, in order, without the cases that g rejects. Two calls with one seed
// return the same values, and a call with a larger n returns the same first
// values.
//
// # Panics
//
// Panics for n below 0, and when g rejects more than 10n cases.
func Values[T any](g Generator[T], seed uint64, n int) []T
```

```rust
/// Returns `n` values of `generator` for `seed`: the values of the random
/// cases of `seed`, in order, without the cases that the generator rejects.
///
/// # Panics
///
/// Panics when the generator rejects more than 10n cases.
pub fn values<T: 'static>(generator: &Generator<T>, seed: u64, n: usize) -> Vec<T>;
```

```python
def values(generator: Generator[T], seed: int, n: int) -> list[T]:
    """Return n values of generator for seed.

    Raises:
        ValueError: n is below 0, seed is outside [0, 2**64), or the
            generator rejects more than 10n cases.
    """
```

```typescript
/**
 * Returns n values of generator for seed.
 *
 * @throws RangeError for n below 0 or a seed outside [0, 2^64).
 * @throws Error when the generator rejects more than 10n cases.
 */
export function values<T>(generator: Generator<T>, seed: bigint | number, n: number): T[];
```

Java and Kotlin name the helper `Prop.values`.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `prop.values` | `prop.Values` | `prop.values` | `prop::values` | `prop.values` | `Prop.values` | `Prop.values` |

### Conformance

The generation and shapes vectors pin the helper without a new vector.
Each runner calls `values(g, seed, k)` for each generation vector and each
shapes vector, where k is the number of the vector's cases that are not
rejected. The call returns the values of those cases, in order. A vector
that rejects more than ten cases for each of its values fails the call,
and no vector does so today.

Each implementation also tests the failure of a generator that rejects
every case.

### Version

Adding a row to the naming table is a minor version change. Definition
10.0.0 adds `prop.values`, beside the major changes of the same release.

## Alternatives considered

### A. The values of a run of `for-all`

**Why not:** a run records a property assertion, and its simplest and
boundary cases come before its random cases. Its values depend on the
phases of the run, and a change of the phases would change the inputs of
every benchmark.

### B. One value per call, as rapid's `Example`

rapid gives a generator the method `Example(seed ...int) V`, which returns
one value for a seed.

**Why not:** a benchmark needs many values. A caller that derives a seed
for each value repeats what the random cases of a seed already state, and
a method on the generator adds a member to the generator type in every
language.

### C. A seed from the variable of the engine

The helper would read `DOKIMI_ASSERT_PROP_SEED` when the caller states no
seed.

**Why not:** two runs of a benchmark need the same values. A seed that a
variable can change makes one benchmark measure other inputs in each
environment.

### D. A value for a rejected case

The helper would return a value for each of the first n cases, and fail at
the first rejected case.

**Why not:** a filtered generator rejects some of its cases by design. A
call that failed at the first rejection would refuse every filtered
generator.

## Drawbacks

- The naming table gains one row, and each language gains one helper.
- A generator that rejects most of its cases fails the helper, where a run
  of a property would give up with the outcome `rejected`.
- Value k depends on the cases before it that the generator rejected, so a
  change of a filter changes the values after its first rejected case.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/16> |
| The generation and shapes vectors | `corpus/prop/generation.yaml` and `corpus/prop/shapes.yaml` |
| The ratio at which a run gives up | RFC-0010 |
| rapid's `Generator.Example` | <https://pkg.go.dev/pgregory.net/rapid#Generator.Example> |
| fast-check's `fc.sample` | <https://fast-check.dev/docs/core-blocks/runners/> |
