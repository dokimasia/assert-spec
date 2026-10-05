---
rfc: 0020
title: An allocation ceiling that leaves out setup
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-05
updated: 2026-10-05
discussion: https://github.com/dokimasia/assert-go/issues/7
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0020: An allocation ceiling that leaves out setup

## Summary

`max-allocs` counts every allocation of the callable that it calls. A
call that consumes its input needs a fresh input each time, and a
callable that builds that input puts the build in the count. This adds
`max-allocs-with-setup`, an assertion whose setup builds each call's
input outside the count and hands it to the callable. One setup and one
call warm both first, and the count is the average over the calls after
them, rounded down, as for `max-allocs`. It has a property form. Go and
Rust supply both. Python, Java, Kotlin and TypeScript declare both
absent, for the reasons that they declare `max-allocs` absent.
Definition 4.0.0 adds both.

## Motivation

### Some ceilings run only under -bench

The benchmark contract leaves setup out of its ceilings with
`excluding` in Go and Python, and with `measuring` in the other
languages. A test has no counterpart. A ceiling over a call that
consumes its input is then written as a benchmark, which a run without
`-bench` does not check. The gate that runs before a merge runs the
tests and does not run a benchmark.

In one code base these ceilings run only under `-bench`:

- A workspace run that seals the graph it is given. Each iteration loads
  a new graph and empties the `sync.Pool`s outside the count, so the
  ceiling covers one cold run.
- The cold and the warm load of a frontend, each of which reopens the
  recorded state.
- An attach of directives to subjects that have none yet.
- Journal, selection, flush and annotation calls of a plugin facade,
  each of which consumes the state that its iteration rebuilt.

### A test cannot leave the setup out

`max-allocs` counts through `testing.AllocsPerRun` in Go, which reads
the runtime's counters once before its calls and once after them. It
has no interval in which an allocation does not count. A test that
states such a ceiling today builds the input either inside the callable
or before the count:

- Inside the callable, the build enters the count, and the assertion
  checks the sum of the build and the call.
- Before the count, all 101 inputs exist at once, and each call takes
  the next one. A setup cannot then run directly before its call, as a
  setup that empties a pool must.

## Detailed design

### The assertion

```yaml
"max-allocs-with-setup":
  arity: 4
  summary: >
    A callable makes at most a stated number of heap allocations per
    call on an input that a setup builds before each call. The setup is
    not counted. One setup and one call warm both first, and the count
    is the average over the calls after them, rounded down.
  detail_fields: [want, got]
```

Its arguments are the setup, the callable, the ceiling and the message.
The setup returns the input, and the callable takes it. `want` is the
ceiling and `got` is the count per call, as for `max-allocs`.

Each counted call has four steps:

1. The setup builds the input.
2. The assertion reads the allocation counter.
3. The callable runs on the input.
4. The assertion reads the counter again.

The count is the sum of the differences over the counted calls, divided
by the number of calls and rounded down. Each implementation chooses
that number, as it does for `max-allocs`. A count equal to the ceiling
passes.

A setup can do more than build: a Go setup that runs two garbage
collections empties every `sync.Pool`, so each counted call starts with
empty pools. A setup or a callable that panics or raises ends the
assertion with that panic or exception, as a raising callable ends
`max-allocs`.

### Go

```go
// MaxAllocsWithSetup calls setup and fn once to warm them. It then
// counts the heap allocations of 100 calls of fn, each on an input that
// a call of setup builds outside the count. It stops the test when their
// average, rounded down, exceeds ceiling.
func MaxAllocsWithSetup[T any](tb TB, setup func() T, fn func(T), ceiling uint64, msg string)
```

```go
assert.MaxAllocsWithSetup(t, freshStore, (*Store).Settle, 4,
	"settling a store allocates at most four times")
```

A method expression such as `(*Store).Settle` takes the input as its
first argument, and Go does not allocate a closure for it. The Go
implementation reads `runtime.ReadMemStats` around each counted call. It
sets `GOMAXPROCS` to 1 while it counts, as `testing.AllocsPerRun` does.
A probe measured 0.53 to 0.55 microseconds per read at that setting. The
200 reads of one assertion take about 0.11 milliseconds in all. The
counter covers the whole process. The test that calls the assertion
does not run in parallel with other tests, as for `max-allocs`.

### Rust

```rust
/// Fail when `body` makes more than `ceiling` heap allocations per call on an
/// input that `setup` builds outside the count.
#[track_caller]
pub fn max_allocs_with_setup<T, S: FnMut() -> T, F: FnMut(T)>(
    seat: &dyn Seat,
    setup: S,
    body: F,
    ceiling: u64,
    msg: &str,
)
```

```rust
check::max_allocs_with_setup(&seat, fresh_store, |store| store.settle(), 4,
    "settling a store allocates at most four times");
```

Rust counts the allocations of the calling thread, as its `max_allocs`
does. A test on another thread does not change the count.

### Builds that allocate differently

Go checks no ceiling of `max-allocs-with-setup` in the builds where it
checks none of `max-allocs`: a build with the race detector, msan or
asan, and a build whose `-gcflags` turn off optimisation or inlining. In
those builds it calls the setup and the callable as an ordinary build
does, and passes.

### The property form

`max-allocs` has a property form because it calls a callable that takes
an input. This assertion has one for the same reason.
`prop-max-allocs-with-setup` passes each generated input to the setup,
and the setup's result to the callable:

```go
func MaxAllocsWithSetup[T, I any](tb assert.TB, setup func(T) I, fn func(I), ceiling uint64,
	msg string, opts ...FormOption)
```

```go
prop.MaxAllocsWithSetup(t, buildGraph, (*Graph).Seal, 0,
	"sealing any graph allocates nothing")
```

`prop-max-allocs` cannot state this ceiling. It calls its function 101
times on one input, and a call that consumes its input cannot run twice
on it. The form runs one case at a time whatever `workers` is set to, as
`prop-max-allocs` does. In Go the count covers the whole process.

A form whose assertion takes a setup passes the generated input to the
setup and the setup's result to the callable. The rule for forms gains
that sentence.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `max-allocs-with-setup` | `MaxAllocsWithSetup` | `max_allocs_with_setup` | `max_allocs_with_setup` | `maxAllocsWithSetup` | `maxAllocsWithSetup` | `maxAllocsWithSetup` |
| `prop-max-allocs-with-setup` | `prop.MaxAllocsWithSetup` | `prop.max_allocs_with_setup` | `prop::max_allocs_with_setup` | `prop.maxAllocsWithSetup` | `Prop.maxAllocsWithSetup` | `Prop.maxAllocsWithSetup` |

Rendering adds the form's entry and its names by the forms rule. A
language that declares the assertion absent still names it, as it names
`max-allocs`.

### Who supplies it

| Language | Stance | Basis |
|---|---|---|
| Go | supplies both | `runtime.ReadMemStats` around each counted call |
| Rust | supplies both | `CountingAllocator`, with the limit that its `max-allocs` already states |
| Python | declares both absent | CPython counts no allocations, only the memory alive at one moment |
| Java, Kotlin | declare both absent | The JVM reports bytes allocated per thread and no count of allocations |
| TypeScript | declares both absent | V8 reports no allocation count |

Each absence states the measurement that the language's overlay already
states for `max-allocs`. The Go and Rust overlays state, for both
entries, the limits that they state for `max-allocs` and
`prop-max-allocs`.

### Conformance

A count of allocations depends on the runtime, so no corpus case can
state one, as for `max-allocs`. The number of assertions without corpus
cases grows from 21 to 22. The completeness gate checks that each
supplying language has the assertion and its form. Each implementation
tests the behaviour: a setup that allocates passes a ceiling of 0 with a
callable that does not, and a callable that allocates once per call
fails it.

### Version

Adding an assertion is a minor version change. Definition 4.0.0 adds the
assertion and its form, and the assertion table grows from 98 entries to
100. The same release adds the label and the step to the divergence of a
flaky run. Its vectors then state fields that no implementation
reported, so the release is a major version. Every overlay extends
4.0.0.

## Alternatives considered

### A. An option of max-allocs

`max-allocs` would take an optional setup, and the definition would keep
one assertion about allocations in a test.

**Why not:** in Rust a callable that takes an input has another type
than the `FnMut()` that `max_allocs` takes, so Rust needs a second
function either way. One assertion would also count by two rules,
depending on an argument that most calls leave out.

### B. A setup and a callable that share a captured variable

The setup would store the input in a variable that the callable reads,
as `excluding` hands a fixture to a Go benchmark. The request in the
discussion proposes these two callables for Go.

**Why not:** in Rust two closures cannot both borrow one variable
mutably, so the input would pass through a shared cell that every test
unwraps. The contract's `measuring` takes a setup that returns its input
for the same reason. With the input as a value, Go passes a method
expression and does not allocate a closure.

### C. Inputs built before the count

The test builds every input first, and each counted call takes the next
one. This works today without a new assertion.

**Why not:** all 101 inputs exist at once, and a large input can exceed
the memory of a test. A setup that empties a pool has to run directly
before its call, and an input built in advance cannot do that.

### D. A count of the setup alone, subtracted

The test counts the setup alone, then the setup and the call together,
and subtracts.

**Why not:** two counts under different memory states do not subtract.
A pool or a cache that the first count fills changes what the second
count allocates.

### E. The benchmark contract alone

The ceiling would remain a benchmark, with `excluding` or `measuring`.

**Why not:** the gate before a merge does not run a benchmark, so
nothing checks the ceiling before the merge.

### F. No property form

The assertion would join the 22 assertions without a form.

**Why not:** the form states a ceiling over generated inputs for a call
that consumes its input, which `prop-max-allocs` cannot state. The 22
assertions without a form retry, time, scope a block, compare a file or
a measurement, drive a check, check a history, read state without an
input, or coincide with another form. This assertion calls a callable
on an input, as `max-allocs` does.

## Drawbacks

- Four of the six languages declare the assertion and its form absent,
  as they declare `max-allocs`. A test that states it does not port to
  them.
- A slow setup runs 101 times per assertion. A setup of 10 milliseconds
  adds about a second. The property form runs it 101 times per case,
  10,100 times in a run of 100 cases.
- Go stops the world twice per counted call, 200 times per assertion,
  about 0.11 milliseconds in all at a `GOMAXPROCS` of 1.
- Go counts the allocations of the whole process. A goroutine that
  allocates between two reads raises the count, and the test does not
  run in parallel.
- Rounding down passes up to 99 stray allocations over 100 counted
  calls, as for `max-allocs`.
- The naming table gains two rows, 12 names, and the rule for forms
  gains a sentence.

## Unresolved and future work

- A test form of the byte ceiling with a setup is not proposed here, as
  none is proposed without one.

## References

| What | Where |
|---|---|
| `testing.AllocsPerRun`: one warm-up call, one count before and after, `GOMAXPROCS` of 1 | Go 1.27.1, `src/testing/allocs.go`, lines 20 to 48 |
| `testing.B.StopTimer`, which leaves allocations out of a benchmark's count | Go 1.27.1, `src/testing/benchmark.go`, lines 149 to 161 |
| `sync.Pool`'s cleanup, which moves the pools to a victim cache at one collection and drops them at the next | Go 1.27.1, `src/sync/pool.go`, lines 258 to 282 |
| Criterion's batched iteration, whose setup runs outside the timed routine | <https://docs.rs/criterion/latest/criterion/struct.Bencher.html> |
| JMH's per-invocation setup | <https://javadoc.io/static/org.openjdk.jmh/jmh-core/1.37/org/openjdk/jmh/annotations/Level.html> |
| The probe of `runtime.ReadMemStats` | Go 1.27.1 on linux/amd64, 2026-10-05: 0.53 to 0.55 microseconds per call at a `GOMAXPROCS` of 1, 3.0 to 3.4 at 4 |
