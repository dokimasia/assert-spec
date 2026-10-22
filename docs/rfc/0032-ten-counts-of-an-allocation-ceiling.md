---
rfc: 0032
title: Ten counts of an allocation ceiling
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-22
updated: 2026-10-22
discussion: https://github.com/dokimasia/assert-spec/issues/12
supersedes: RFC-0030, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0032: Ten counts of an allocation ceiling

## Summary

`max-allocs` and `max-allocs-with-setup` take a count again when it exceeds
the ceiling, and fail when three counts exceed it. Go builds the cache of a
type assertion lazily, so a callable that asserts types allocates now and
then for thousands of calls. Three counts fail such a callable in 4% of
processes. This proposal raises the number of counts from three to ten:

- A count that exceeds its ceiling is taken again, up to ten counts in all.
- A ceiling of 0 keeps its slack of one allocation over the 100 counted
  calls.
- A callable that meets its ceiling at the first count runs 100 counted
  calls, as before. A callable that fails runs 1,000 counted calls in place
  of 300.

Definition 10.0.0 makes the change.

## Motivation

### Go builds the cache of a type assertion now and then

Go builds the cache of a type assertion, or of a type switch to an interface
type, when a call site misses it. In about one of 1,024 such calls the
runtime builds a larger cache with `mallocgc` (`typeAssert` and
`interfaceSwitch` in `runtime/iface.go` of Go 1.27.2, lines 485 and 579).
`runtime.MemStats.Mallocs` counts each build. A callable that asserts types
that its process has not asserted before then allocates now and then for
thousands of calls. In its steady state it does not allocate at all.

`errs.Classify` of `go.thesmos.sh/core` walks a join of three wrapped errors
with such assertions, also through `errors.Is`. Its test states a ceiling of
0, and it failed on macOS and on Windows in CI on 2026-10-16:

```text
classify_test.go:411: Classify of a join must not allocate: want 0, got 0, total 2
```

The test binary failed the case in 14 of 300 processes on Linux. A memory
profile at a rate of 1 attributes every allocation of the counted calls to
the builds of these caches.

### The builds continue long after the warm-up

300 new processes each warmed `errs.Classify` once and then counted 100
batches of 100 calls:

- The 10,000 calls allocated 8 to 16 times, with a median of 11.
- The last batch that allocated was batch 49 at the median and batch 87 at
  the 90th percentile.
- 296 of the 300 processes allocated again after batch 10. A warm-up of
  1,000 calls does not settle the caches.

The batches of these processes give the failures of each rule:

| Rule | Processes that fail, of 300 |
|---|---|
| A slack of 1 and three counts, as definition 8.0.0 states | 12 |
| A slack of 1 and five counts | 0 |
| A slack of 1 and ten counts | 0 |
| A slack of 2 and three counts | 0 |

Definition 8.0.0 chose three counts for the noise of a test process: a
first count of 1 or 2 that fell to 0 in a later count. The builds of these
caches are noise of the same kind with a longer tail.

## Detailed design

### The count

A count calls the callable once to warm it, and counts the heap allocations
of the 100 calls after it. Their total is `a`.

- A count meets a ceiling of 0 when `a` is at most 1.
- A count meets a ceiling c above 0 when the average per call, rounded to
  the nearest whole number, is at most c.
- The assertion passes at the first count that meets its ceiling. It takes
  at most ten counts, and fails when none of them meets the ceiling.
- The detail of a failure states the count with the lowest total.

Only the number of counts changes. The warm-up, the slack, the rounding and
the detail fields of definition 8.0.0 do not change.

| Totals of the counts | Ceiling of 0 in 9.0.0 | Ceiling of 0 in 10.0.0 |
|---|---|---|
| 0 or 1 at the first count | Passes | Passes |
| 2, then 1 | Passes at the second count | Passes at the second count |
| 2, 2, 2, then 1 | Fails after three counts | Passes at the fourth count |
| 2 or more in each of ten counts | Fails after three counts | Fails after ten counts |

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
    exceeds the ceiling is taken again, and the assertion fails when ten
    counts exceed it. got is the rounded average and total the
    allocations of the count with the lowest total.
  detail_fields: [want, got, total]
```

The summary of `max-allocs-with-setup` refers to the counts of
`max-allocs`, so its text does not change. `prop-max-allocs` and
`prop-max-allocs-with-setup` run their assertion on each generated input,
so they take up to ten counts for each input.

### What does not change

- `bench-max-allocs` measures the loop that the harness runs once, and
  rounds its average. A second loop would change the iterations that the
  harness reports.
- The builds and the runs in which a language checks no ceiling, as its
  overlay states them.

### The languages

Go and Rust keep the signatures of both assertions. The documentation of
Go's `MaxAllocs` states that it "stops the test when ten counts exceed it".
Each count in Go sets `GOMAXPROCS` to 1, as before. Rust counts the
allocations of the calling thread, and its counts follow the same rule.
Python, TypeScript, Java and Kotlin declare both assertions absent.

### Conformance

No corpus case can state a count of allocations. Each implementation tests
the count with these callables. They replace the cases of definition 8.0.0
that state three counts:

- A callable that allocates twice in each of its first nine counts and once
  in its tenth count passes a ceiling of 0.
- A callable that allocates twice in each of ten counts fails a ceiling of
  0 after ten counts, with `total` 2.

### Version

A change of what an existing assertion means is a major version change.
Definition 10.0.0 changes `max-allocs`, `max-allocs-with-setup` and their
forms.

## Alternatives considered

### A. Five counts

None of the 300 processes failed with five counts.

**Why not:** the measurements cover one callable with four sites that
assert types. A test binary whose callables assert at more sites builds
more caches, and their builds continue for more calls. Ten counts leave a
margin for those. A callable that meets its ceiling at the first count runs
no more calls than before.

### B. A slack of 2 with three counts

None of the 300 processes failed with this rule either.

**Why not:** a ceiling of 0 would admit two allocations in every count of
100 calls. A callable that allocates on 2% of its calls in its steady state
would then pass a ceiling of 0. A slack of 1 with more counts admits the
noise and keeps the ceiling of the steady state strict.

### C. A longer warm-up

The assertion would warm the callable with 1,000 calls before each count.

**Why not:** 296 of the 300 processes allocated again after batch 10, so a
warm-up of 1,000 calls does not settle the caches. A warm-up long enough for
batch 87 costs 8,700 calls on every pass. Ten counts cost extra calls only
after a count fails.

### D. Caches that the assertion empties before each count

**Why not:** Go has no API that resets the caches of type assertions. They
last as long as the process.

## Drawbacks

- **Time.** A failing assertion counts up to 1,000 calls in place of 300.
  A slow callable makes a failing test more than three times slower.
- **Growth.** A callable whose allocations decline over its first 1,000
  calls passes a ceiling of 0 once one count admits it. A ceiling of 0
  states that a call does not allocate in its steady state, as in
  definition 8.0.0.
- **One callable.** The measurements rest on one callable, measured on one
  Linux machine. The failures of its test on macOS and Windows show the same
  builds on both systems.

## References

| What | Where |
|---|---|
| The issue, its probe and its measurements | <https://github.com/dokimasia/assert-spec/issues/12> |
| Three counts with a slack of one allocation | RFC-0030 |
| The builds of the caches of type assertions | `typeAssert` and `interfaceSwitch` in `src/runtime/iface.go` of Go 1.27.2 |
