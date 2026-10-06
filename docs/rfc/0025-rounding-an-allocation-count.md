---
rfc: 0025
title: Rounding an allocation count to the nearest whole number
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-06
updated: 2026-10-06
discussion: https://github.com/dokimasia/assert-spec/issues/6
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0025: Rounding an allocation count to the nearest whole number

## Summary

`max-allocs` and `max-allocs-with-setup` divide the allocations of the
counted calls by the number of calls, and round the quotient down. Go's
benchmark contract rounds the count of `bench-max-allocs` the same way.
Rounding down passes a callable that allocates on every counted call but
one. A pool whose stock serves one counted call makes a leak look exactly
like that.

This proposal rounds the quotient to the nearest whole number, and a half
rounds up, in all three assertions:

- A callable fails its ceiling when it allocates past the ceiling on half
  of its calls or more.
- The runtime's own allocations during a counted loop measured 0 or 1 over
  100 calls, and at most 39 over 2,000,000 iterations. Both are below half
  an allocation per call.
- `bench-max-bytes` keeps rounding down.

Definition 6.0.0 makes the change.

## Motivation

### A pool's stock hides a leak

This callable takes a value from a pool and never returns it:

```go
var (
	pool = sync.Pool{New: func() any { return new([64]byte) }}
	kept *[64]byte
)

// takes takes a value from the pool and never returns it.
func takes() { kept = pool.Get().(*[64]byte) }
```

With two values in the pool, the warm-up call takes one, and the first
counted call takes the other. Each of the 99 counted calls after them
allocates. Under Go 1.27.1 at a `GOMAXPROCS` of 1:

```text
testing.AllocsPerRun(100, takes) = 0
allocations of the 100 calls after a warm-up: 99
```

99 allocations over 100 calls round down to 0. A ceiling of 0 then passes
the leak. Values that earlier tests returned to a pool form such a stock.
The test that counts cannot see them.

### A benchmark rounds every stock away

A stock of one value serves one of a benchmark's millions of iterations.
The leak allocates on each iteration after it. The count is then N − 1
allocations over N iterations, which rounds down to 0 for every N.

### Rounding down follows Go's own count

The definition rounds down because `testing.AllocsPerRun` divides as
integers, and an implementation that rounded another way would fail a
callable that Go's own count passes. The assertion states a ceiling per
call. Rounding down gives away up to one allocation per call, which is a
whole allocation on every call of a leak.

## Detailed design

### The count

The count of each of the three assertions is the allocations of the
counted calls divided by the number of calls, rounded to the nearest whole
number. A half rounds up. In integer arithmetic over a total `a` and `n`
calls, the count is `(2a + n) / (2n)`, with the division rounding down. A
count equal to the ceiling passes, as before. `got` in the record's detail
is the rounded count.

| Allocations over 100 calls | Rounded down | Rounded to the nearest |
|---|---|---|
| 0 to 49 | 0 | 0 |
| 50 to 99 | 0 | 1 |
| 100 to 149 | 1 | 1 |
| 150 to 199 | 1 | 2 |

### The assertions

```yaml
"max-allocs":
  arity: 3
  summary: >
    A callable makes at most a stated number of heap allocations per
    call. One call warms it first, and the count is the average over
    the calls after it, rounded to the nearest whole number, with a
    half rounded up.
  detail_fields: [want, got]

"max-allocs-with-setup":
  arity: 4
  summary: >
    A callable makes at most a stated number of heap allocations per
    call on an input that a setup builds before each call. The setup is
    not counted. One setup and one call warm both first, and the count
    is the average over the calls after them, rounded to the nearest
    whole number, with a half rounded up.
  detail_fields: [want, got]

"bench-max-allocs":
  arity: 1
  package: bench
  summary: >
    The allocations per iteration stay within a ceiling. The count is
    the average over the measured iterations, rounded to the nearest
    whole number, with a half rounded up.
  detail_fields: [want, got]
```

`prop-max-allocs` and `prop-max-allocs-with-setup` run their assertion
on each generated input, so they count the same way.

### The runtime's allocations during a counted loop

Go reads the allocations of the whole process, so the runtime's own
allocations during a loop enter the count. These measurements ran under
Go 1.27.1 on linux/amd64:

| Loop | Runs | Allocations beyond the body's |
|---|---|---|
| 100 calls of a body that allocates nothing, at a `GOMAXPROCS` of 1 | 1,911,680 | 1 in one run, 0 in every other |
| The same, while another goroutine forces collections | 279,211 | 0 |
| The same, while a ticker ticks every millisecond | 17,237 | 0 |
| One second of `testing.B.Loop` over a body that allocates nothing, at a `GOMAXPROCS` of 4 | 20 | 1 in two runs, 0 in the others |
| 2,000,000 iterations of a body that allocates once, in a process that has collected before | 10 | 0 to 13 |
| The same, with the process's first collection inside the loop, at a `GOMAXPROCS` of 4 | 5 | 7 to 22 |
| The same, at a `GOMAXPROCS` of 32 | 5 | 22 to 39 |

The runtime's share grows with the collections that the body's own
allocations start. The first collection of a process starts one mark
worker goroutine for each processor. Every measured share is at most 0.01
allocations per call, far under the half that rounding to the nearest
admits.

### What does not change

`bench-max-bytes` keeps rounding down, because rounding down a byte
average drops less than one byte per iteration. A value that leaks on 99
of 100 iterations adds 99% of its size to the average. A leaked value of
2 bytes or more then exceeds the ceiling by at least one byte.

The warm-up, the number of counted calls and the builds in which Go
checks no ceiling do not change.

### Go

`MaxAllocs` counts as `testing.AllocsPerRun` counts. It sets `GOMAXPROCS`
to 1 and warms the callable with one call. It reads
`runtime.ReadMemStats` before and after the 100 counted calls, and rounds
the total itself, because `testing.AllocsPerRun` returns only the
quotient rounded down.

```go
// MaxAllocs calls fn once to warm it and counts the heap allocations of the
// next 100 calls. It stops the test when their average, rounded to the
// nearest whole number, exceeds ceiling. A half rounds up.
func MaxAllocs(tb TB, fn func(), ceiling uint64, msg string)

// MaxAllocsWithSetup calls setup and fn once to warm them. It then counts
// the heap allocations of 100 calls of fn, each on an input that a call of
// setup builds outside the count, and stops the test when their average,
// rounded to the nearest whole number, exceeds ceiling. A half rounds up.
func MaxAllocsWithSetup[T any](tb TB, setup func() T, fn func(T), ceiling uint64, msg string)
```

The other two counts follow the same rule:

- `expect` declares both functions with the count of `assert`.
- The benchmark contract publishes its quotient as before, and compares
  `math.Round` of the quotient with the ceiling. `math.Round` rounds a
  half away from zero, which is up for a count.

### Rust

Rust counts the allocations of the calling thread, so another thread's
allocations do not enter its count. It rounds the same way.

### Conformance

No corpus case can state a count of allocations. Each implementation
tests the rounding with two callables:

- One that allocates on 50 of 100 counted calls fails a ceiling of 0.
- One that allocates on 49 of 100 counted calls passes it.

### Version

Changing what an existing assertion means is a major version change.
Definition 6.0.0 changes `max-allocs`, `max-allocs-with-setup` and
`bench-max-allocs`, and the forms of the first two. Every overlay extends
6.0.0.

## Alternatives considered

### A. A fixed slack beside the exact total

The total of the counted calls would be at most the ceiling times the
calls, plus a slack of a few allocations for the runtime.

**Why not:** 2,000,000 iterations of a body that allocates once measured
up to 13 allocations beyond the body's. They measured up to 39 when the
process's first collection fell inside the loop at a `GOMAXPROCS` of 32.
The runtime's share grows with the collections that the body starts, so
a slack of a few fails such a benchmark. A slack that covers 32
processors admits 39 leaked allocations over the 100 calls of
`max-allocs`, and the slack that a machine needs depends on its processor
count.

### B. Rounding up

Any allocation during the loop would raise the count above the
ceiling's.

**Why not:** a runtime allocation that a collection makes would fail a
ceiling of 0 that the callable meets.

### C. The batch with the fewest allocations

The count would come from the batch of calls with the fewest
allocations, which leaves out a runtime allocation that hits one batch.

**Why not:** a pool's stock serves the first batch, so the batch with the
fewest allocations is the batch whose calls the stock hides.

### D. Rounding down, and pools emptied before the count

A caller would run two collections before each count. Two collections
empty every `sync.Pool`, and a setup of `max-allocs-with-setup` can run
them.

**Why not:** a callable that leaks through a pool it does not export
passes a caller who does not know of the pool.

## Drawbacks

- **A callable that allocates past its ceiling on fewer than half of its
  calls passes.** Rounding down passed it on any number of calls short of
  every call.
- **A ceiling measured under rounding down rises by one where the
  average's fraction is a half or more.** A call that averages 1.6
  allocations measured 1 and measures 2. An implementation's own ceilings
  change with it.
- **An average whose fraction is near a half reads either of two counts
  from run to run.** Under rounding down, an average just below a whole
  number does the same. The ceiling is then the higher of the two.
- **Go's `MaxAllocs` no longer calls `testing.AllocsPerRun`,** so a call
  inside a parallel test no longer panics. Its test does not run in
  parallel, as for `max-allocs-with-setup`.

## Unresolved and future work

- A test form of the byte ceiling is not proposed here.

## References

| What | Where |
|---|---|
| `testing.AllocsPerRun`, its warm-up call and its integer division | Go 1.27.1, `src/testing/allocs.go` |
| `gcBgMarkStartWorkers`, which starts a mark worker goroutine for each processor at the first collection | Go 1.27.1, `src/runtime/mgc.go`, lines 1688 to 1712 |
| The measurements | Go 1.27.1 on linux/amd64, an AMD Ryzen 9 9950X3D, 2026-10-06 |
