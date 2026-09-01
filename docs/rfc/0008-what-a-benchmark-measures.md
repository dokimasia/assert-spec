---
rfc: 0008
title: What a benchmark measures
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-08-31
updated: 2026-08-31
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0008: What a benchmark measures

## Summary

A benchmark ceiling covers whatever the caller put in the loop body,
including the fixture built there. This fixes what a ceiling means, so
per-iteration setup sits outside it, and lets a language mark that setup
the way it already writes a benchmark body rather than adopting one
shape for all five.

## Motivation

An operation that consumes its input needs a fresh input each time. A
store that settles cannot settle twice, so the fixture is rebuilt inside
the loop, and the four ceilings then pin build plus operation rather
than the operation.

All five implementations do this, for the same reason: each starts a
clock and an allocation counter, runs the body, and stops. There is no
seam inside that span.

| | Time measured over | Allocations measured over |
|---|---|---|
| Go | the whole body | the whole loop, divided by iterations |
| Python | the whole body | the whole loop, divided by iterations |
| TypeScript | the whole body | not counted; V8 answers neither |
| Java | the whole body | the whole loop, divided by iterations |
| Rust | the whole body | the whole loop, divided by iterations |

Python's `loop` states that allocation tracing starts at the loop rather
than at construction, so setup before the loop is not counted. That is
true and it is the easy half. Setup written before the loop was never
the difficulty, because a caller can hoist it. Setup that cannot be
hoisted is the case here.

Documenting that the setup rides inside the number is the current
answer, and it is weaker than it sounds. A ceiling covering both is not
merely imprecise: it changes meaning when the fixture changes. Make the
fixture cheaper and the ceiling gains slack nobody granted it, so a
regression in the operation hides under the difference. A check that
passes for a reason nobody stated is the failure this standard exists to
catch.

## Detailed design

### What a ceiling means

A ceiling covers the work the caller states as measured. Per-iteration
setup, where the caller says so, is not part of it. All four ceilings
change together: `max-latency` and `max-mean` stop including the setup's
time, `max-allocs` and `max-bytes` stop including its allocations.

That is the fixed part. How a caller says which work is setup is a
question about how each language writes a benchmark, and the two answers
below are both this meaning.

### Where the body is inline

Two of the five write a benchmark body inline. Go's runs under
`testing.B`, which owns the iteration count; Python's is driven by a
generator:

```go
c := bench.Start(b).MaxLatency(50 * time.Microsecond).MaxAllocs(2)
defer c.End()
for c.Loop() {
    store.Get(id)
}
```

```python
c = Contract(seat, "get stays quick").max_allocs(2)
for _ in c.loop(10_000):
    store.get(id)
c.check()
```

Setup is excluded in place, which keeps the loop as it reads today:

```go
for c.Loop() {
    var store *Store
    c.Excluding(func() { store = freshStore() })
    store.Settle()
}
```

```python
for _ in c.loop(10_000):
    store = c.excluding(fresh_store)
    store.settle()
```

Go's takes a function and answers nothing, because the fixture reaches
the measured work through a variable the caller already has, which is
how a Go closure passes anything out. Python's answers what the
function answered, because Python has no reason not to.

### Where the harness owns the loop

The other three hand the harness a closure:

```rust
Contract::new(&seat, "settling stays cheap")
    .max_allocs(4)
    .measuring(fresh_store, |store| store.settle())
    .check();
```

`measuring` takes a setup that answers the fixture and a body that
consumes it. The harness runs setup for a batch of iterations, measures
the batch, and divides.

### Why two rather than one

One shape for all five was the first answer and it is wrong in both
directions.

A setup that answers the fixture suits Rust, where a value moves out of
one closure and into the next. Go cannot express it as a method at all,
because a Go method may not introduce a type parameter, so it becomes
either a package-level function that abandons the chain and the inline
loop, or an `any` and a cast in every benchmark.

An `excluding` that answers nothing suits Go, where the fixture reaches
the body through a captured variable. Rust pays for that one instead:
two closures cannot hold the same variable mutably, so the fixture
arrives through an `Option` that every benchmark then unwraps.

Whichever single shape is chosen, one of the two languages writes worse
benchmarks than it does today to gain a feature about writing better
ones.

The naming table already carries this. `reporter` and `clocked` are
named by Go and Java and declined by the other three, because only a
language without interface defaults needs a second interface to say the
same thing. Two mechanisms for one meaning is the same arrangement:
`contract.excluding` is named by Go and Python and declined by the other
three, `contract.measuring` the reverse, and each overlay states why.

Which side a language falls on is not about the language. It is about
whether the caller writes the loop or the harness does, and that is
already decided by how each one writes a benchmark today.

Nothing is lost in conformance. The four benchmark ceilings are among
the sixteen assertions the corpus cannot reach, because their answers
depend on the machine, so both mechanisms rest on each implementation's
own tests either way.

### What it does not do

The setup is not measured and no ceiling is offered on it. A caller who
wants to know what the fixture costs writes a second benchmark whose
body is the fixture, which is what that question deserves.

The batch size is not exposed. It changes how precisely a number is
measured rather than what the number means, benchmark answers already
depend on the machine, and a knob nobody needs is a knob everyone reads.
Each implementation chooses one.

Nothing here addresses an optimiser deleting the measured work. That
exposure exists today in every implementation, this changes neither
direction of it, and the mechanisms that answer it are `black_box` in
Rust and `Blackhole` in JMH, neither of which the standard states.

## Alternatives considered

### A. Document that setup rides inside the number

The current answer. It costs nothing and it is honest about what the
tool does.

Rejected because the number still moves when the fixture changes, and
the reader who most needs to know is the one reading a green build six
months later.

### B. One mechanism, chosen for the closure languages

`measuring` everywhere, with Go reaching it through a package-level
generic function.

Rejected on what it does to a Go benchmark. Go's body is inline and its
contract is a chain; a package function takes the caller out of both to
fix a problem `testing.B` solves without leaving either. Python's body
is inline for a different reason and pays the same way.

### C. One mechanism, chosen for the inline languages

`excluding` everywhere, with the fixture threaded by capture.

Rejected for the mirror reason. Rust cannot hold one variable mutably in
two closures, so every Rust benchmark gains an `Option` and an unwrap.

### D. A pause and a resume, as testing.B offers

`StopTimer` and `StartTimer` on the contract. Go's own pair does stop
allocation counting as well as the clock, whatever its documentation
says.

Rejected because a pause can be left unbalanced and an unbalanced one
answers a wrong number rather than an error. That is the failure this
standard exists to catch, and a scoped form costs nothing to write
instead.

### E. Hoist the setup and reuse one fixture

Build one fixture before the loop and reset it inside.

Rejected because it does not apply to the case that motivated this. An
operation that consumes its input has no reset cheaper than
construction, and where a reset exists it is itself work inside the
measurement.

### F. Measure the setup separately and subtract

Measure setup alone, measure both together, subtract.

Rejected because two measurements of a system under different memory
pressure do not subtract. The fixture built inside a loop and the same
fixture built alone allocate differently, and the difference is not the
operation.

## Drawbacks

Two mechanisms exist for one meaning, and a reader moving between an
inline language and a closure one meets a different member. They read only the one their
language offers, but the standard now states two rows where it stated
none, and each overlay carries a decline.

`Contract` grows from two members to three in every language. That is
two rows in the naming table, six naming decisions counting Kotlin, and
a decline in every overlay.

Each implementation grows a second measured path beside the one it has.
The existing paths are 31 lines in Rust, 25 in Java and 11 in
TypeScript, and the new one is that shape plus a batch loop, so this
roughly doubles them.

A batch holds its inputs in memory at once. A large fixture and a
generous batch can cost more memory than the benchmark measures, and
because the batch size is not exposed, a caller who hits that has no way
to say so.

Two ways of writing a benchmark exist afterwards where one existed
before, and a caller has to know that a body needing no fixture wants
the simpler one.

## Unresolved and future work

Whether a caller ever needs the batch size. Fixing it is the right
default and the wrong answer for a fixture large enough to matter;
nobody has hit that yet, and exposing it before they do adds a knob to
every benchmark that does not need one.

## References

- Go's benchmark timer, whose `StopTimer` accumulates allocation counts
  as well as elapsed time:
  <https://pkg.go.dev/testing#B.StopTimer>
- The same, as implemented:
  <https://github.com/golang/go/blob/master/src/testing/benchmark.go>
- Criterion's batched iteration, for a routine that consumes its input:
  <https://docs.rs/criterion/latest/criterion/struct.Bencher.html>
- JMH's per-invocation setup, and the millisecond floor it states:
  <https://javadoc.io/static/org.openjdk.jmh/jmh-core/1.1.1/org/openjdk/jmh/annotations/Level.html>
- The issue this answers:
  <https://github.com/dokimasia/assert-go/issues/1>
