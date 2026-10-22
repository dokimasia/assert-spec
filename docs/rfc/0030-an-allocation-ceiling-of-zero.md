---
rfc: 0030
title: An allocation ceiling of zero
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-11
updated: 2026-10-11
discussion: https://github.com/dokimasia/assert-spec/issues/11
supersedes: none
superseded-by: RFC-0032, in part
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0030: An allocation ceiling of zero

## Summary

`max-allocs` and `max-allocs-with-setup` count the heap allocations of
100 calls, round the average to the nearest whole number, and compare it
with the ceiling. A ceiling of 0 then passes a callable that allocates on
49 of the 100 calls. This proposal changes the count of both assertions
and of their property forms:

- A ceiling of 0 admits one allocation over the 100 counted calls.
- A count that exceeds its ceiling is taken again. The assertion fails
  only when three counts in a row exceed the ceiling.
- The detail of a failure gains `total`, the allocations of the counted
  calls.
- A ceiling above 0 keeps the rounding, and so does `bench-max-allocs`.

Definition 8.0.0 makes the change.

## Motivation

### A ceiling of 0 passes a callable that allocates on a third of its calls

A ceiling of 0 states that a call does not allocate. Under the rounding
of definition 6.0.0, the average of 49 allocations over 100 calls rounds
to 0, and the ceiling passes. Two callables that allocate on a fixed
share of their calls, measured with Go 1.27.2 against
`go.dokimi.dev/assert` at 5d14331:

| Callable | Allocations of the 100 calls after a warm-up | `MaxAllocs` with a ceiling of 0 |
|---|---|---|
| Allocates on every fourth call | 25 | Passes |
| Allocates on every third call | 33 | Passes |

A path that allocates on a quarter of its calls then meets a
zero-allocation contract in its test.

### One count with a slack of one allocation fails real suites

Go counts the allocations of the whole process, so a count can include
an allocation that the callable did not make. The measurements of
definition 6.0.0 found one such allocation in 1,911,680 loops of a quiet
process. A test suite is not a quiet process. Four runs of assert-go's
own suite logged three counts of every check with a ceiling of 0:

| Assertion | Sites | Checks | First counts of 0 | Of 1 | Of 2 | Of 6 or 7 |
|---|---|---|---|---|---|---|
| `max-allocs` | 334 | 4,152 | 4,079 | 48 | 1 | 24 |
| `max-allocs-with-setup` | 5 | 2,836 | 2,836 | 0 | 0 | 0 |

The table leaves out the 19 sites of assert-go's own tests of the counting
rule, which allocate 49, 50 or 100 times on purpose.

- Each first count of 1 or 2 fell to 0 in a later count. The extra
  allocation came from the process, not from the callable.
- The counts of 6 and 7 came from six sites whose callables append to a
  slice, such as the method `Observe` of a property's case. Their first
  count covers the growth of the slice to 128 entries. Each later count
  allocated once, for the next doubling.
- One count with a slack of 1 failed the six sites in every run, and the
  check whose count was 2 in one run.
- Three counts with a slack of 1 failed none of them.

## Detailed design

### The count

A count calls the callable once to warm it, and counts the heap
allocations of the 100 calls after it. Their total is `a`.

- A count meets a ceiling of 0 when `a` is at most 1.
- A count meets a ceiling c above 0 when the average rounded to the
  nearest whole number is at most c: `(2a + 100) / 200 ≤ c`, with the
  division rounding down, as definition 6.0.0 states.
- The assertion passes at the first count that meets its ceiling. It
  takes at most three counts, and fails when none of them meets the
  ceiling.
- The detail of a failure states the count with the lowest total.

| Totals of the counts | Ceiling of 0 in 6.0.0 | Ceiling of 0 in 8.0.0 |
|---|---|---|
| 0 or 1 | Passes | Passes |
| 2 to 49, three times | Passes | Fails |
| 7, then 1 | Passes | Passes at the second count |
| 50 or more, three times | Fails | Fails |

The number of counted calls is 100 in every language. Go and Rust count
100 calls today. The slack of one allocation rests on that number, so
the definition fixes it.

### The assertions

```yaml
"max-allocs":
  arity: 3
  summary: >
    A callable makes at most a stated number of heap allocations per
    call. A count calls it once to warm it and counts the allocations of
    the 100 calls after it. A ceiling of 0 admits one allocation in all,
    and any other ceiling compares with the average per call, rounded to
    the nearest whole number, with a half rounded up. A count that
    exceeds the ceiling is taken again, and the assertion fails when
    three counts exceed it. total is the allocations of the counted
    calls.
  detail_fields: [want, got, total]

"max-allocs-with-setup":
  arity: 4
  summary: >
    A callable makes at most a stated number of heap allocations per
    call on an input that a setup builds before each call. The setup is
    not counted. A count calls the setup and the callable once to warm
    both and counts the allocations of the 100 calls after them, with
    the ceilings, the counts and total of max-allocs.
  detail_fields: [want, got, total]
```

`want` is the ceiling. `got` is the rounded average of the count with
the lowest total, and `total` is that count's allocations. A ceiling of
0 that fails on 25 allocations states `got` 0 and `total` 25, so the
reader sees the 25.

`prop-max-allocs` and `prop-max-allocs-with-setup` run their assertion
on each generated input, so they count the same way. The record of a
failing case is the record of its assertion, with `total`.

### What does not change

- `bench-max-allocs` keeps the rounding for every ceiling. A benchmark
  runs its loop once per run, and the harness sets the number of
  iterations. A fixed slack would mean something else at each number,
  and the contract cannot repeat the measured loop without changing what
  `testing.B` reports.
- `bench-max-bytes` keeps rounding down.
- The warm-up call, the builds in which Go checks no ceiling, and the
  rounding of a ceiling above 0 do not change.

### Go

`MaxAllocs` and `MaxAllocsWithSetup` keep their signatures:

```go
// MaxAllocs calls fn once to warm it and counts the heap allocations of the
// next 100 calls. A ceiling of 0 admits one allocation in all, and any other
// ceiling compares with their average, rounded to the nearest whole number.
// It counts again when a count exceeds ceiling, and stops the test when
// three counts exceed it.
func MaxAllocs(tb TB, fn func(), ceiling uint64, msg string)

// MaxAllocsWithSetup calls setup and fn once to warm them. It then counts the
// heap allocations of 100 calls of fn, each on an input that a call of setup
// builds outside the count, and checks the count as MaxAllocs does.
func MaxAllocsWithSetup[T any](tb TB, setup func() T, fn func(T), ceiling uint64, msg string)
```

A passing assertion takes one count when its first count meets the
ceiling, and a failing one takes three. In the measurements, 4,127 of the
4,152 checks of `max-allocs` took one count. Each count sets `GOMAXPROCS`
to 1, as the count of definition 6.0.0 does.

### Rust

Rust counts the allocations of the calling thread, so no other thread
enters a count. It counts the same way.

### Conformance

No corpus case can state a count of allocations. Each implementation
tests the count with these callables:

- A callable that allocates once in each count passes a ceiling of 0.
- A callable that allocates on 2 of the 100 calls in every count fails a
  ceiling of 0, with `total` 2.
- A callable that allocates on 49 of the 100 calls fails a ceiling of 0.
- A callable whose first count allocates 7 times and whose later counts
  allocate once passes a ceiling of 0.
- A callable that allocates 149 times in each count passes a ceiling of
  1, and one that allocates 150 times fails it.

These cases replace the case of definition 6.0.0 in which 49 allocations
pass a ceiling of 0.

### Version

Changing what an existing assertion means is a major version change.
The detail of both assertions gains a field, which changes their records
too. Definition 8.0.0 changes `max-allocs`, `max-allocs-with-setup` and
their forms. Every overlay extends 8.0.0.

## Alternatives considered

### A. One count with a slack of one allocation

A ceiling of 0 would fail when one count of 100 calls allocates more than
once, and a ceiling above 0 would keep the rounding. The discussion
requests this rule.

**Why not:** it failed the six sites with a growing slice in every run of
the measurements, and the check whose count was 2 in one run. Their
tests state a ceiling of 0 for a callable that allocates only to grow,
and each later count of them allocated once.

### B. One count with a larger slack

A ceiling of 0 would admit a few allocations, such as 3 or 8.

**Why not:** a slack that covers the first count of a growing slice
admits 7 leaked allocations over 100 calls, which is a leak on 7% of the
calls. The four runs bound the noise of one machine, and nothing bounds
it on another.

### C. The rounding of definition 6.0.0

The count would remain the rounded average.

**Why not:** a ceiling of 0 then passes a callable that allocates on 49 of
its 100 calls, as the motivation shows.

### D. Three counts for bench-max-allocs as well

The benchmark contract would repeat its measurement when the count
exceeds the ceiling.

**Why not:** the harness runs the loop and sets the number of iterations,
and the contract measures the loop that the harness runs. A second loop
would change the iterations and the times that `testing.B` reports.

### E. The pools emptied before each count

A count would run two collections first, which empty every `sync.Pool`.

**Why not:** definition 6.0.0 rejected this for the same reason that
applies here. A callable that leaks through a pool that it does not
export passes a caller who does not know of the pool.

## Drawbacks

- **Time.** A failing assertion counts 300 calls instead of 100, so a slow
  callable makes a failing test three times slower.
- **Growth.** A callable whose allocations decline over its first 300
  calls passes a ceiling of 0 once one count admits it. A ceiling of 0
  then states that a call does not allocate in its steady state.
- **One machine.** The slack and the counts rest on measurements on one
  Linux machine. CI runs assert-go's 339 sites with a ceiling of 0 on
  Linux, macOS and Windows on every push, so a noisier platform shows as
  a failing check.
- **Ceilings above 0.** A ceiling above 0 still admits up to 49
  allocations beyond the ceiling over 100 calls.
- **Benchmarks.** `bench-max-allocs` still passes a ceiling of 0 for a
  body that allocates on fewer than half of its iterations.
- **Records.** Every implementation's record of both assertions changes,
  because the detail gains `total`.

## References

| What | Where |
|---|---|
| The rounding to the nearest whole number, and the runtime's allocations in a quiet process | RFC-0025 |
| The probe of the discussion, run again with Go 1.27.2 against `go.dokimi.dev/assert` at 5d14331 | 25 and 33 allocations over 100 calls, and `MaxAllocs` with a ceiling of 0 passes both |
| The measurements of the suite | Four runs of assert-go's tests at 5d14331, with a copy of `internal/matcher/allocs.go` that logged three counts of every check. Go 1.27.2 on linux/amd64, an AMD Ryzen 9 9950X3D, 2026-10-11 |
| The number of counted calls in Rust | assert-rust, `dokimi-assert/src/matcher/allocations.rs`, `COUNTED_CALLS` |
