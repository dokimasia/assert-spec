---
rfc: 0009
title: An allocation ceiling in a test
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-09-26
updated: 2026-09-26
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0009: An allocation ceiling in a test

## Summary

This adds `max-allocs`: the heap allocations that a callable makes per
call, after one call that warms it, stay within a ceiling. It is the
test form of `bench-max-allocs`, so the ordinary test run checks an
allocation contract instead of a benchmark run that a pre-merge gate
does not start. Go and Rust supply it. Python, Java, Kotlin and
TypeScript declare it absent, for the reasons they declare
`bench-max-allocs` absent. The definition moves to version 1.1.0.

## Motivation

A library that promises zero allocations on a hot path checks the
promise where it checks everything else: in its tests, on every run. Go's
standard library does this in `bytes`, `fmt`, `net/netip` and `log/slog`,
each through `testing.AllocsPerRun` inside an ordinary test.

A benchmark contract is the only place the standard states an
allocation ceiling, and a benchmark runs only when a caller asks for
one. The pre-merge check of the Go repositories that use this library
is ergon's `check`. It runs vet, lint, the tests and coverage, and it
runs no benchmark. Nothing checks a contract written as
`bench.Start(b).MaxAllocs(0)` before a merge, so a regression that
breaks it merges.

A Go caller who wants the check in a test today writes
`testing.AllocsPerRun` and compares the result with `Equal`. The failure
then reports two numbers and no ceiling, and the call is outside the
standard, so no other implementation states the same check.

The Go caller also meets a second problem. A build with the race
detector, msan or asan changes what allocates:

- Under the race detector, `sync.Pool.Put` drops a quarter of the items
  it is given, so a pooled path allocates in that build and in no other.
- The Go compiler's own allocation test counts 8 allocations under
  `-race` where the ordinary build makes 1, with no pool involved.

Go's standard library skips its allocation tests in those builds. A
caller who writes the check by hand has to find that out, and the
ledger that prompted this change found it through a red `-race` run.

## Detailed design

### The assertion

```yaml
"max-allocs":
  arity: 3
  summary: >
    A callable makes at most a stated number of heap allocations per
    call. One call warms it first, and the count is the average over
    the calls after it, rounded down.
  detail_fields: [want, got]
```

The arguments are the callable, the ceiling and the message. `want` is
the ceiling and `got` is the count per call. A count equal to the
ceiling passes, as it does for `bench-max-allocs`.

A callable that fills a pool or a cache on its first call allocates on
that call and on no later one. The definition leaves the first call out
of the count, because the contract concerns the steady state.

`testing.AllocsPerRun` divides as integers and rounds the count down. The
definition states that rounding. An implementation that rounded another
way would fail a callable that Go passes. Each implementation chooses the
number of calls after the warm-up, as it chooses the batch size of a
benchmark.

The assertion is in the root namespace, beside the other assertions
about a callable. `bench` states ceilings on a benchmark iteration, and
this one states a ceiling on a call in a test.

### Names

| Language | Name |
|---|---|
| Go | `MaxAllocs` |
| Python | `max_allocs` |
| Rust | `max_allocs` |
| TypeScript | `maxAllocs` |
| Java | `maxAllocs` |
| Kotlin | `maxAllocs` |

A language that declares the assertion absent still carries a name, as
it does for `bench-max-allocs`, so a later implementation does not
choose one of its own.

### Who supplies it

| Language | Stance | Basis |
|---|---|---|
| Go | supplies it | `testing.AllocsPerRun`, over the runtime's cumulative allocation counter |
| Rust | supplies it | `CountingAllocator`, with the limit `bench-max-allocs` already states: nothing counts until the test binary installs it |
| Python | declares it absent | CPython counts no allocations, only the memory alive at one moment |
| Java, Kotlin | declare it absent | the JVM reports bytes allocated per thread and no count of allocations |
| TypeScript | declares it absent | V8 reports no allocation count |

Each absence states the same measurement that the language's overlay
already states for `bench-max-allocs`.

### Builds that allocate differently

The Go implementation checks no allocation ceiling in two kinds of
build:

- A build with the race detector, msan or asan, which a build tag
  identifies.
- A build whose `-gcflags` turn off optimisation (`-N`) or inlining
  (`-l`), as a debugger's build does. The binary's build information
  records those flags, and `runtime/debug.ReadBuildInfo` returns them to
  a test binary. With inlining off, a constructor that returns a pointer
  allocated once per call where the ordinary build allocated nothing.

In either build the assertion calls the callable as an ordinary build
does, so a test that reads what the callable changed still reads it,
and it reports nothing. The benchmark contract publishes its allocation
and byte counts without checking their ceilings. The Go overlay states
this as a limit on `max-allocs`, `bench-max-allocs` and
`bench-max-bytes`.

A skip would stop the whole test in that build, and the checks after
the call would not run. No other assertion stops a test that it did not
fail, so this one passes instead of skipping.

### Conformance

The corpus cannot reach `max-allocs`. A count of allocations depends on
the runtime, and the same callable allocates differently in each
language. The benchmark ceilings are outside the corpus for the same
reason. The completeness gate checks that each supplying language has
the assertion. Each implementation tests its behaviour itself.

### Version

Adding an assertion is a minor version. The definition moves from 1.0.0
to 1.1.0, and every overlay extends 1.1.0. Each implementation moves to
1.1.0 when it syncs. Until then its drift issue records the gap.

## Alternatives considered

### A. The benchmark contract alone

Leave allocation ceilings to `bench-max-allocs`.

Rejected because a gate that runs no benchmark then checks no allocation
contract, and the motivation shows that such a gate is the common case.

### B. A Go helper outside the naming table

Add a function to assert-go's `bench` package and leave the standard
unchanged.

Rejected because RFC-0007 puts every public item a caller types in the
naming table, so that no implementation invents a name the others do not
share. A public function outside the table recreates the drift RFC-0007
removed.

### C. A row in the naming table's helpers

Name the function in the table, as the golden scrubbers are named, and
declare it absent where a language cannot supply it.

Rejected because it states something that must be true and fails when it
is not, which is the first test an assertion meets. The scrubbers
configure a comparison and fail nothing.

### D. Skip in an instrumented build

Skip the test with the reason, as Go's standard library skips its own
allocation tests.

Rejected for the reason under builds that allocate differently. The
standard library skips a test whose only purpose is the count. An
assertion is one call among others in a caller's test.

### E. A test form of the byte ceiling as well

Add `max-bytes` beside `max-allocs`.

No caller has asked for it, so this RFC does not propose it. Java,
Kotlin and Python could supply it, and it can follow on its own when a
caller needs it.

## Drawbacks

- Four of the six languages declare the assertion absent, as they do
  `bench-max-allocs`. A test that states it does not port to them.
- In Go, a run with the race detector, msan or asan, or with
  optimisation or inlining off, checks no allocation ceiling. A suite
  that runs only with `-race` checks none.
- Rounding down passes a callable whose allocations average below one
  per call against a ceiling of none. Over 100 counted calls, a callable
  that allocates on 99 of them passes.
- Go recognises a build with optimisation or inlining off only through
  the `-gcflags` that its build information records.

## Unresolved and future work

- A test form of the byte ceiling, when a caller needs one.

## References

- `testing.AllocsPerRun`, its warm-up call and its integer division, Go
  1.27.1: `src/testing/allocs.go`
- `sync.Pool.Put` under the race detector, Go 1.27.1:
  `src/sync/pool.go`, lines 104 to 108
- Allocation tests that the standard library skips under the race
  detector, Go 1.27.1: `src/fmt/fmt_test.go`, line 1527, and
  `src/database/sql/sql_test.go`, line 5283
- The compiler's allocation test, skipped under the race detector, msan
  and asan, which counts 8 allocations under `-race` where the ordinary
  build makes 1, Go 1.27.1: `src/cmd/compile/internal/test/free_test.go`,
  lines 20 to 24
- `runtime/debug.ReadBuildInfo` in a test binary, Go 1.27.1: a probe on
  2026-09-26 read `-gcflags="all=-N -l"`, `-gcflags="-l"` and
  `-race="true"` from binaries that `go test` built with those flags, and
  counted 0 allocations per call for a constructor returning a pointer
  in an ordinary build and 1 with `-gcflags=-l`
- RFC-0007, which puts every public item in the naming table, and
  RFC-0008, which fixes what a benchmark ceiling covers
