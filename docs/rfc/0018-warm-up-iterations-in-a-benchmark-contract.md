---
rfc: 0018
title: Warm-up iterations in a benchmark contract
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-05
updated: 2026-10-05
discussion: https://github.com/dokimasia/assert-go/issues/4
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0018: Warm-up iterations in a benchmark contract

## Summary

A benchmark contract measures every iteration from the first. The first
iterations of a body allocate and run differently from the later ones,
so a short run checks its ceilings against a cost that a long run
amortises. This adds one member to the contract, `warmup`. The contract
runs a stated number of iterations of the body before the measurement
starts, and no ceiling and no published number covers them. The default
is 0, so a contract that states no warm-up measures what it measures
today. All six languages supply the member, and definition 4.0.0 adds
it.

## Motivation

### The first iterations build what later iterations reuse

Go caches the itab of an interface conversion at each conversion site.
The generated code reads the site's cache first. On a miss, the runtime
looks the itab up and updates the cache in about 1 call of 1,024, so the
site allocates its cache after a random number of executions. For one
concrete type the cache is one allocation of 48 bytes. A probe of one
site on Go 1.27.1 built the cache after 7 to 3,295 executions in 20 runs,
each time as 1 allocation of 48 bytes, and did not allocate afterwards.

The compiler gives every inlined copy of a conversion a cache of its own.
In the same probe, a site whose cache existed allocated nothing in
200,000 calls. A second inlined copy of the same function then allocated
its own 48 bytes in its first 200,000 calls.

A JVM interprets a method until it has run often enough to compile, and
the compiled code can remove an allocation that the interpreter makes.
Over three runs, a probe on JDK 27 measured the bytes per call of a
method that allocates a record that does not escape. It read
`ThreadMXBean.getThreadAllocatedBytes`, the counter that the Java
contract reads:

| Calls | Bytes per call |
|---|---|
| 1 to 10 | 428 |
| 11 to 11,110 | 16 |
| 11,111 to 111,110 | 0.18 to 1.00 |
| 111,111 to 2,111,110 | 0 |

A Java contract that states `maxBytes(0)` over the first 1,000 iterations
of this method measures about 20 bytes per iteration. Once compiled, the
method does not allocate.

### A short run divides that cost by few iterations

The Go contract divides the allocations of its loop by the iterations
and rounds the quotient down. A run of many iterations rounds one
allocation away. A run of one iteration, which `-benchtime=1x` gives,
fails a ceiling of zero on it, and the contract's documentation states
this.

A benchmark that ranges 200,000 declarations through an inlined iterator
under `MaxAllocs(0)` fails at `-benchtime=1x` with one allocation of 48
bytes, the cache of the conversion site in its loop body. A call of the
body before `bench.Start` runs another inlined copy of that site, so it
does not build the loop's cache. The benchmark warms the site by writing
its first iteration into the loop's condition:

```go
for first := true; first || c.Loop(); first = false {
```

That idiom works in Go alone. It also hides the warm-up from a reader of
the contract, who sees the ceilings in one place and the window they
cover in another.

### One window of iterations in every language

A warm-up decides which iterations every ceiling covers. The definition
fixes what a ceiling covers. A warm-up that each language added on its
own, with its own default, would make one contract cover different
iterations in each language.

## Detailed design

### The warm-up iterations

`warmup(n)` states n warm-up iterations:

- The contract runs the body n times before the first measured
  iteration. A warm-up iteration runs the whole body, including the
  setup that `excluding` or `measuring` runs for it.
- No ceiling covers a warm-up iteration, and no number that the contract
  publishes counts one. The p99 latency, the mean latency, the
  allocations and the bytes cover the measured iterations alone.
- The iteration count that a caller states, or that the harness sets,
  counts the measured iterations alone. A Go benchmark under
  `-benchtime=1x` runs n warm-up iterations and one measured iteration.
- The default is 0.
- A count below zero is a usage error. A warm-up stated after the body's
  first iteration is a usage error too. Go reports a usage error with a
  panic, and the other languages raise an exception.
- A body that fails or raises during the warm-up ends the run as it does
  during the measurement.

### Inline loops in Go and Python

Go and Python write the loop themselves, so the warm-up runs inside that
loop:

```go
c := bench.Start(b).Warmup(1).MaxAllocs(0)
defer c.End()

for c.Loop() {
	_, _ = store.Get(id)
}
```

`Loop` returns true for its first n calls without timing them, reading a
counter or calling `testing.B.Loop`. Its next call reads the allocation
counters and calls `testing.B.Loop` for the first time. That first call
resets testing's own timer and allocation counters, so testing's `ns/op`
and `allocs/op` leave the warm-up out as well. `Excluding` runs its work
in a warm-up iteration and takes nothing out, as it does before the loop
today.

```python
c = bench.Contract(seat).warmup(1_000).max_latency(0.00005)

for _ in c.loop(10_000):
    store.get(id)

c.check()
```

`loop` yields 11,000 times and measures the last 10,000 iterations.

### Closures in Rust, TypeScript, Java and Kotlin

Rust, TypeScript, Java and Kotlin hand the harness a closure, so the
harness runs the warm-up before it times the first iteration:

```rust
Contract::new(&seat, "a get allocates nothing")
    .warmup(1_000)
    .max_allocs(0)
    .run(10_000, || {
        store.get(id);
    })
    .check();
```

```java
new Contract(seat, "get allocates nothing once compiled")
    .warmup(200_000)
    .maxBytes(0)
    .loop(10_000, () -> store.get(id))
    .check();
```

```typescript
const contract = new Contract(seat, "a get takes under 2 ms at p99").warmup(1_000).maxLatency(2);
await contract.loop(10_000, () => store.get(id));
contract.check();
```

`run`, `loop` and `measuring` run the body when the caller calls them,
so `warmup` comes before them in the chain. `measuring` builds and
consumes one input per warm-up iteration before it builds the measured
inputs, so the warm-up keeps one input in memory at a time.

### Signatures

Go takes the count as an `int`, the type of `b.N` and of the count that
`testing.AllocsPerRun` takes. Every other language takes it in the type
of the iteration count that its `loop` or `run` already takes:

```go
// Warmup states n iterations that Loop runs before the first measured
// one, and returns the receiver. No ceiling covers them, and End
// publishes nothing about them.
//
// Warmup panics for a negative n, and after the contract has run its
// body.
func (c *Contract) Warmup(n int) *Contract
```

```python
def warmup(self, iterations: int) -> Contract:
    """State iterations that loop runs before the measured ones, and chain.

    Raises:
        ValueError: iterations is negative, or loop has started.
    """
```

```rust
/// State iterations that `run` and `measuring` run before the measured ones.
///
/// # Panics
///
/// When `run` or `measuring` has already run.
#[must_use]
pub fn warmup(self, iterations: usize) -> Self
```

```typescript
/**
 * State iterations that `loop` and `measuring` run before the measured ones.
 *
 * @throws RangeError when iterations is not a whole number of 0 or more,
 *   or when the contract has already run its body.
 */
warmup(iterations: number): this
```

```java
/// State iterations that `loop` and `measuring` run before the measured ones.
///
/// @throws IllegalArgumentException when iterations is negative
/// @throws IllegalStateException when the contract has already run its body
public Contract warmup(int iterations)
```

### How many iterations a warm-up needs

The count depends on what the first iterations build:

| What the first iterations build | Warm-up that leaves it out |
|---|---|
| A Go conversion site that one iteration executes k times | One iteration. The site remains without its cache with probability (1023/1024)^k, below 3.3 × 10^-9 for k of 20,000 or more |
| A Go conversion site that one iteration executes once | About 20,000 iterations, for the same bound |
| A JVM method that the measured iterations call | Enough calls to compile it: in the probe, more than 111,110 |

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `contract.warmup` | `Warmup` | `warmup` | `warmup` | `warmup` | `warmup` | `warmup` |

JMH spells the word as one, in its `@Warmup` annotation, so every
language spells the member alike.

### Who supplies it

All six languages supply it. A warm-up runs the body and reads no
counter, so no language lacks what it needs.

### Conformance

A warm-up changes what a ceiling measures, and a measurement depends on
the machine. No corpus case can state one, as no case states the four
ceilings. The completeness gate checks the name. Each implementation
tests the behaviour: a body that allocates on its first call alone fails
`max-allocs` of 0 over one measured iteration, and passes it with a
warm-up of one.

### Version

Adding a member of the surface table is a minor version change.
Definition 4.0.0 adds this member. The same release adds the label and
the step to the divergence of a flaky run. Its vectors then state fields
that no implementation reported, so the release is a major version.
Every overlay extends 4.0.0.

## Alternatives considered

### A. A default of one warm-up iteration

`max-allocs` warms its callable with one call before it counts, as
`testing.AllocsPerRun` does. A contract that warmed one iteration by
default would not need a new member, and the benchmark in the motivation
would pass with no change at its call site.

**Why not:** a default changes what every existing contract measures,
and one iteration is the wrong count for two of the three cases in the
preceding table. A Go site that one iteration executes once needs about
20,000 iterations, and the JVM method in the probe needed more than
111,110 calls. The member is needed in either design, so the default
decides only whether existing contracts change. Evidence that most
contracts state a warm-up of one would reverse this.

### B. A warm-up measured in time

JMH warms a benchmark for 5 iterations of 10 seconds by default, and
Criterion warms for 3 seconds. A duration adapts to how fast the body
runs, and a JIT compiler compiles on background threads, which a count
of calls does not wait for.

**Why not:** a Go site builds its cache after a number of executions,
not after a span of time. A count runs the same iterations on every
machine, so a contract that passes on a fast machine runs the same
warm-up on a slow one. `-benchtime=1x` also exists to make a run short,
and a fixed duration would dominate such a run. A JIT implementation
that measures a count leaving compiled code uninstalled on CI hardware
would reverse this.

### C. A warm-up that the caller writes

A caller calls the body before the contract runs: before `bench.Start`
in Go, or before `run` in the languages whose harness runs the loop.

**Why not:** in Go the compiler inlines the body into the caller's
warm-up and into the loop separately, and each copy builds its own
cache, as the probe showed. The loop-condition idiom warms the right
copy in Go and has no counterpart in a closure. In every language the
warm-up is then outside the contract, where a reader of the ceilings
does not see which iterations they cover.

## Drawbacks

- The contract gains one member, a row of six names in the naming
  table.
- A warm-up runs the body n more times. A body of 1 millisecond with a
  warm-up of 1,000 adds one second to the run.
- `measuring` runs its setup n more times.
- A caller chooses n, and the right n depends on the runtime: 1 for a Go
  site that one iteration executes many times, about 20,000 for a site
  that it executes once, and enough calls for a JIT to compile.
- On a JIT runtime a count of calls only approximates when compilation
  finishes, because the compiler runs on background threads. A count
  that suffices on a fast machine can be too small on a slow one.
- A warm-up leaves out the cost of the first iterations. A body that
  allocates on its first iteration and never again passes a ceiling of
  zero. A benchmark of that first iteration states no warm-up.
- The closure languages detect a warm-up stated after the run only when
  the code runs, because `run(...).warmup(n)` compiles.

## Unresolved and future work

- A warm-up stated as a duration is not proposed here.

## References

| What | Where |
|---|---|
| `runtime.typeAssert`, its update of the cache in 1 call of 1,024, and the cache's allocation | Go 1.27.1, `src/runtime/iface.go`, lines 485 to 544 |
| `testing.B.Loop`, which resets the timer and the allocation counters on its first call | Go 1.27.1, `src/testing/benchmark.go`, lines 414 to 438 |
| `testing.AllocsPerRun`, which calls its function once before it counts | Go 1.27.1, `src/testing/allocs.go`, lines 26 and 27 |
| JMH's default warm-up: 5 iterations of 10 seconds | <https://github.com/openjdk/jmh/blob/master/jmh-core/src/main/java/org/openjdk/jmh/runner/Defaults.java> |
| Criterion's default warm-up time of 3 seconds | <https://github.com/bheisler/criterion.rs/blob/master/src/lib.rs> |
| The probes of one conversion site and of two inlined copies | Go 1.27.1 on linux/amd64, 2026-10-05 |
| The probe of a method whose record does not escape | OpenJDK 27 on linux/amd64, 2026-10-05 |
