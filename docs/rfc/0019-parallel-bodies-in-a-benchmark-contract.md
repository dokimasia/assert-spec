---
rfc: 0019
title: Parallel bodies in a benchmark contract
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-05
updated: 2026-10-05
discussion: https://github.com/dokimasia/assert-go/issues/5
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0019: Parallel bodies in a benchmark contract

## Summary

A benchmark that measures contention runs one body on two or more
threads at once. The benchmark contract measures one loop on one thread,
and no ceiling covers the allocations or the latency of a parallel body.
This adds one member to the contract, `run-parallel`. The contract
starts its workers, releases them together, and measures every iteration
of every worker. Each ceiling keeps its meaning per iteration: a latency
is one iteration's duration on its worker, and an allocation count is
the run's allocations divided by its iterations. Go, Rust, Java and
Kotlin supply the member. Python and TypeScript decline it, because
neither measures contention between threads. Definition 4.0.0 adds it.

## Motivation

### Parallel bodies have no ceiling

Go's `testing.B.RunParallel` runs a body on `GOMAXPROCS` goroutines,
and each goroutine calls `testing.PB.Next` in place of `B.Loop`. The Go
contract drives `testing.B.Loop`, so it has no loop to measure under
`RunParallel`. A benchmark of that kind publishes its allocations through
`b.ReportAllocs` and states no ceiling, and a regression passes the
gate. In one code base, the documentation of these parallel benchmarks
states that a contract cannot measure them:

- concurrent stamps into a fact store, and concurrent reads of stamped
  facts
- concurrent adds of distinct packages to one graph
- concurrent reports into one diagnostics sink

Inside a `B.Loop` loop, testing sets `b.N` to 0, and `RunParallel`
returns at once when `b.N` is 0. A parallel body runs only in the `b.N`
mode, in which testing calls the benchmark function once for each `b.N`
it tries and reports the last call.

### A count around RunParallel counts testing's own work

A probe on Go 1.27.1 at a `GOMAXPROCS` of 4 counted the allocations
around `RunParallel` in each call that testing made of one benchmark
function, over three runs. Its body inserted distinct keys into a map
under a mutex:

| `b.N` | Allocations | Per iteration, rounded down |
|---|---|---|
| 1 | 17 to 18 | 17 to 18 |
| 100 | 26 | 0 |
| 10,000 | 99 to 105 | 0 |
| 1,000,000 | 8,219 to 8,227 | 0 |
| 12,932,772 to 14,833,036 | 65,631 to 106,154 | 0 |

The first call counts the goroutines, closures and handles that
`RunParallel` allocates, and the map's first insert, in one iteration.
Testing reports the last call alone.

## Detailed design

### Workers, iterations and ceilings

`run-parallel` runs one body on W workers:

- The workers take iterations from one shared count until they have run
  N iterations in all. A worker that is quicker runs more of them.
- N is the run's iteration count. In Go it is `b.N`, as for
  `RunParallel`. In the other languages the caller states it.
- W is `GOMAXPROCS` in Go, as for `RunParallel` with a parallelism of 1,
  and `-cpu` sets it for each run. In the other languages the caller
  states it.
- The measurement starts once every worker has started and waits to be
  released, and it ends with the last iteration of the last worker.
  Starting and stopping the workers is outside the measurement, as the
  setup before a sequential loop is.

The four ceilings keep the meaning they have for a sequential body:

| Ceiling | What it bounds for a parallel body |
|---|---|
| `bench-max-latency` | The p99 of the durations of all iterations of all workers. Each worker times its own iterations |
| `bench-max-mean` | The mean of the same durations |
| `bench-max-allocs` | The allocations made during the measurement, divided by N and rounded down |
| `bench-max-bytes` | The bytes allocated during the measurement, divided by N and rounded down |

A mean latency per iteration is what a caller of the subject waits for
under contention. Go's `ns/op` for a parallel benchmark is the wall time
divided by N, which is about the mean latency divided by W. Testing
keeps publishing `ns/op` beside the contract's numbers, so a Go reader
sees both.

A contract that states a warm-up runs it on the workers before the
measurement: n iterations in all, taken from the same shared count. A
caller whose iterations consume inputs built before the run builds n
inputs more.

A body that raises on a worker ends the run. The contract waits for the
other workers, publishes nothing and checks no ceiling. It then raises
again, on the caller's thread, what the lowest-numbered worker that
raised has raised, as the concurrency driver does for its clients.

### The run that the ceilings cover in Go

A Go contract checks its ceilings on the run that testing reports, and
on no earlier run. Testing starts another run only when three
conditions are all true:

- The run took less than `-benchtime`.
- The run ran fewer than 10^9 iterations.
- The benchmark has not failed.

Under `-benchtime=Nx`, the run of N iterations is the last. `End`
applies the first two conditions to its own run:

- It stops the timer first. The time it compares is then the time that
  testing compares.
- It reads `-benchtime` through the `flag` package. It calls
  `testing.Init` first, which registers the flag in a program that runs
  benchmarks without `go test`.
- It publishes its numbers in every run. Testing deletes the metrics of
  a run when the next run starts, and the report shows the last run's
  numbers.

A run that fails ends the runs as well. Testing reports no measurement of
a failed benchmark, so `End` checks the ceilings of a failed run only when
its count or its time makes it the last.

Rust, Java and Kotlin run a parallel body once per call. That run is the
run that the ceilings cover.

### Go

The Go member takes its body as `testing.B.RunParallel` takes one. A
benchmark moves to a contract when `c.RunParallel` replaces
`b.RunParallel` and the contract's own handle replaces `testing.PB`:

```go
func BenchmarkGetParallel(b *testing.B) {
	store := loadedStore(b)

	c := bench.Start(b).MaxLatency(50 * time.Microsecond).MaxAllocs(0)
	defer c.End()

	c.RunParallel(func(pb *bench.PB) {
		for pb.Next() {
			_, _ = store.Get(id)
		}
	})
}
```

```go
// RunParallel runs body on GOMAXPROCS goroutines, which run b.N
// iterations in all, and measures every iteration. Each goroutine
// receives a PB of its own.
//
// RunParallel panics for a benchmark that is no *testing.B, after the
// contract has run its body, and when a body returns before Next reports
// false. Loop panics after RunParallel, because a benchmark function
// measures a loop or a parallel body.
func (c *Contract) RunParallel(body func(*PB))

// PB hands out the iterations of one goroutine of a parallel body.
type PB struct {
	// unexported fields
}

// Next reports whether the goroutine runs another iteration. Each call
// ends the iteration that the call before it started.
func (pb *PB) Next() bool
```

`testing.PB` has no exported constructor, and a caller cannot time its
iterations. The contract states a handle of its own for that reason.
The Go implementation names it `PB`, after the handle of `testing`.

### Rust, Java and Kotlin

The languages whose harness runs the loop take the worker count, the
iteration count and the body:

```rust
Contract::new(&seat, "a get under contention allocates nothing")
    .max_latency(Duration::from_micros(50))
    .max_allocs(0)
    .run_parallel(8, 1_000_000, || {
        store.get(id);
    })
    .check();
```

```rust
/// Run `body` on `workers` threads, which run `iterations` iterations in all,
/// and measure every iteration.
///
/// # Panics
///
/// When `workers` is 0.
#[must_use]
pub fn run_parallel<F: Fn() + Sync>(self, workers: usize, iterations: usize, body: F) -> Self
```

```java
new Contract(seat, "a get under contention allocates nothing")
    .maxLatency(Duration.ofMillis(1))
    .maxBytes(0)
    .runParallel(8, 1_000_000, () -> store.get(id))
    .check();
```

```java
/// Run the body on the given number of threads, which run the given number of
/// iterations in all, and measure every iteration.
///
/// @throws IllegalArgumentException when workers is below 1 or iterations is negative
public Contract runParallel(int workers, int iterations, Raises.Body body)
```

In Rust the body borrows the caller's store, because the workers are
scoped threads. Java sums `ThreadMXBean.getThreadAllocatedBytes` over
the workers' threads, and the allocations of another thread in the
process do not enter that sum.

### No setup per iteration

Go counts the allocations of the whole process, and Rust counts the
bytes of the whole process. With either counter, the allocations of one
worker's setup cannot be told apart from another worker's measured
iteration. For that reason `excluding` and `measuring` have no parallel
form.
A caller builds the inputs before the run and hands them out by a shared
index:

```go
entries := freshEntries(b.N)
var next atomic.Int64

c.RunParallel(func(pb *bench.PB) {
	for pb.Next() {
		_ = log.Append(entries[next.Add(1)-1])
	}
})
```

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `contract.run-parallel` | `RunParallel` | | `run_parallel` | | `runParallel` | `runParallel` |

Go takes its name from `testing.B.RunParallel`. Rust names its
sequential runner `run`, so its parallel runner is `run_parallel`.

### Who supplies it

| Language | Stance | Basis |
|---|---|---|
| Go | supplies it | Goroutines, and `runtime.ReadMemStats` before the release and after the last worker |
| Rust | supplies it | Scoped threads, and `CountingAllocator`, with the limit that its ceilings already state |
| Java, Kotlin | supply it | Platform threads, and `ThreadMXBean.getThreadAllocatedBytes` summed over the workers |
| Python | declines it | The default build of CPython runs Python code on one thread at a time under the global interpreter lock, so a worker's latency includes its wait for that lock. `tracemalloc` reports one level of traced memory for the whole process, so no measurement attributes bytes to concurrent iterations |
| TypeScript | declines it | JavaScript runs every worker on one thread. Workers would interleave only where the body awaits, so a parallel body would measure the queue of the event loop and not contention |

The notes of the naming table state each decline. They already state
why four languages decline `excluding`.

### Conformance

A parallel run's numbers depend on the machine and on the scheduler, so
no corpus case can state one. The completeness gate checks the name.
Each implementation tests the behaviour: a body that allocates once per
iteration on every worker fails `max-allocs` of 0, a body that allocates
nothing passes it, and in Go an earlier run of a benchmark function
checks no ceiling.

### Version

Adding a member of the surface table is a minor version change.
Definition 4.0.0 adds this member. The same release adds the label and
the step to the divergence of a flaky run. Its vectors then state fields
that no implementation reported, so the release is a major version.
Every overlay extends 4.0.0.

## Alternatives considered

### A. Delegate to RunParallel and count around it

The Go contract would call `testing.B.RunParallel` and read the counters
before and after it, which takes the fewest lines.

**Why not:** the count includes the goroutines, closures and handles
that `RunParallel` allocates, 17 to 18 allocations in a run of one
iteration in the probe. A caller cannot time an iteration of a
`testing.PB` either, so the contract could not state a latency ceiling.

### B. Check every run of a b.N benchmark

Each call of the benchmark function would check its own ceilings, which
does not need a rule about which run testing reports.

**Why not:** in the probe, the run of one iteration counted 17 to 18
allocations per iteration, and every later run counted 0 after rounding.
A ceiling that every run meets is no tighter than the cost of the first
run's one iteration. Testing reports the last run, which that ceiling
describes loosely.

### C. Bound the wall time per iteration with max-mean

`bench-max-mean` would bound the wall time divided by N, the number that
Go's `ns/op` reports for a parallel benchmark. The request in the
discussion proposes this.

**Why not:** it changes what `bench-max-mean` means for one kind of
body. With W workers the number is about the latency divided by W, so a
lock that serialises every call passes a ceiling that each call exceeds
W times over. JMH's average-time mode averages each thread's time per
operation for the same reason. A floor on throughput is a different
assertion, and this proposal adds none.

### D. A run that the Go contract ramps itself

The Go contract would ramp N itself inside testing's first run, measure
once, and override `ns/op` through `ReportMetric`. It would not need a
rule about testing's later runs.

**Why not:** callers build their inputs from `b.N` before the run, as
the shared-index example does. A contract that chose N itself would hand
out iterations past the inputs that the caller built.

### E. Concurrent tasks in TypeScript and Python

TypeScript and Python would run W asynchronous loops on their event
loop, which an asynchronous subject can be measured under.

**Why not:** tasks on one event loop interleave only where the body
awaits, so a parallel body would measure the queue of the event loop in
two languages and contention between threads in four, under one name.

### F. Refuse max-latency for a parallel body

The request in the discussion offers this as one option, to avoid a
shared lock in the timing.

**Why not:** each worker times its own iterations into a buffer of its
own. No timing takes a lock. The p99 costs one clock read per
iteration, the same cost as for a sequential body.

## Drawbacks

- The rule for another run is internal to the `testing` package. A Go
  release that changed it would make the contract check a run that
  testing does not report, or no run at all. The Go implementation's
  tests detect such a change. A body that exceeds a ceiling fails in
  them.
- The Go contract reads `-benchtime` through the `flag` package to apply
  that rule.
- A Go report shows two figures for time: testing's `ns/op` and the
  contract's `mean-ns/op`. They differ by about W.
- `testing.B.SetParallelism` does not change the contract's workers.
  Testing keeps the parallelism in an unexported field.
- Each worker keeps one duration per iteration, 8 bytes per iteration in
  all.
- Go counts the allocations of the whole process, so a goroutine outside
  the body that allocates during the run raises the count, as it does
  for a sequential body.
- A parallel body takes no setup per iteration, so a caller who
  consumes inputs builds them before the run.
- Python and TypeScript decline the member, so a contract over a
  parallel body does not port to either.
- The contract gains one member, a row of four names in the naming
  table.

## Unresolved and future work

- A floor on throughput is not proposed here.
- A worker count other than `GOMAXPROCS` in Go is not proposed here.

## References

| What | Where |
|---|---|
| `testing.B.RunParallel`, its `b.N` check and its goroutines | Go 1.27.1, `src/testing/benchmark.go`, lines 950 to 989 |
| `testing.B.Loop`, which sets `b.N` to 0 inside its loop | Go 1.27.1, `src/testing/benchmark.go`, lines 414 to 438 |
| Testing's rule for another run, and the run under `-benchtime=Nx` | Go 1.27.1, `src/testing/benchmark.go`, lines 331 to 362 |
| `ResetTimer`, which deletes the metrics of a run | Go 1.27.1, `src/testing/benchmark.go`, lines 163 to 183 |
| JMH's average-time result, which averages the time per operation of each thread | <https://github.com/openjdk/jmh/blob/master/jmh-core/src/main/java/org/openjdk/jmh/results/AverageTimeResult.java> |
| `getThreadAllocatedBytes(long[])` | OpenJDK 27, `com.sun.management.ThreadMXBean` |
| The global interpreter lock of the default build | CPython 3.14.8: `sys._is_gil_enabled()` returns true |
| The probe of the runs of one parallel benchmark | Go 1.27.1 on linux/amd64, `GOMAXPROCS` of 4, 2026-10-05 |
