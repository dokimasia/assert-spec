---
rfc: 0008
title: What a benchmark measures
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-31
updated: 2026-08-31
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0008: What a benchmark measures

## Summary

A benchmark ceiling measures whatever the caller put in the loop body,
including the fixture built there. This gives the contract a way to say
which part of the body the ceiling is about, so a ceiling on an
operation is not quietly a ceiling on its setup as well.

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

### The contract says what it is measuring

`Contract` gains one member. The body it takes runs outside the
measurement, and what it returns is handed to the measured body:

```
Contract
  loop(iterations, body)             the measured body
  check()                            report every crossed ceiling
  measuring(setup, body)             setup outside, body inside
```

A case that today reads:

```rust
Contract::new(&seat, "settling stays cheap")
    .max_allocs(4)
    .run(10_000, || {
        let store = fresh_store();      // counted, and should not be
        store.settle();
    })
    .check();
```

reads instead:

```rust
Contract::new(&seat, "settling stays cheap")
    .max_allocs(4)
    .measuring(fresh_store, |store| store.settle())
    .check();
```

The setup runs for each iteration. What the measurement covers is the
second closure alone.

### Why a setup argument rather than a paused span

The obvious shape is a pause: stop the clock, build the fixture, start
it again. Go's `testing.B` offers exactly that, and its `StopTimer`
accumulates allocation counts as well as elapsed time, so the pause
covers both even though its documentation mentions only the timer.

Two things argue against copying it.

A pause can be left unbalanced, and an unbalanced one produces a wrong
number rather than an error. That is the same shape as the failures this
standard keeps finding: a measurement that reports confidently having
measured the wrong thing. A setup argument cannot be unbalanced, because
there is nothing to close.

The second is cost. Pausing per iteration means reading the allocation
counter twice per iteration, and reading it is not free. JMH offers
per-invocation setup and states the limit plainly: it is usable for
benchmarks taking more than a millisecond, because timestamping every
invocation saturates the system and the setup overhead dominates
anything smaller. An assertion library whose ceilings are for
microsecond operations cannot adopt a mechanism with a millisecond
floor.

A setup argument has neither problem. The harness runs setup for a batch
of iterations, measures the batch, and divides. Criterion takes this
shape for the same reason, and its `iter_batched` names the same case
this proposal is about: a routine that consumes its input and so needs a
fresh one each time.

### What the ceilings then mean

All four change together. `max-latency` and `max-mean` stop including
the setup's time, and `max-allocs` and `max-bytes` stop including its
allocations. A ceiling states what the operation costs.

The existing `loop` stays. A benchmark whose body needs no fixture is
the common case and gains nothing from a second closure.

### What it does not do

The setup is not measured and no ceiling is offered on it. A caller who
wants to know what the fixture costs writes a second benchmark whose
body is the fixture, which is what that question deserves.

Nesting is not offered. A setup that itself needs setup is a fixture
with a construction problem, and hiding it inside a benchmark harness
would not fix that.

## Alternatives considered

### A. Document that setup rides inside the number

The current answer. It costs nothing and it is honest about what the
tool does.

Rejected because the number still moves when the fixture changes, and
the reader who most needs to know is the one reading a green build six
months later.

### B. A paused span, as Go's testing.B offers

`pause()` and `resume()` on the contract, or a scoped `excluding(body)`
that cannot be left unbalanced.

Rejected for the cost rather than the shape. Reading the allocation
counter twice per iteration puts a floor under what can be measured, and
JMH's experience says that floor is around a millisecond. The scoped
form solves the balance problem and not the cost one.

Worth noting that the scoped form remains available later for a case a
setup argument cannot express, and adopting a setup argument now does
not rule it out.

### C. Hoist the setup and reuse the fixture

Build one fixture before the loop and reset it inside.

Rejected because it does not apply to the case that motivated this. An
operation that consumes its input has no reset that is cheaper than
construction, and where a reset does exist it is itself work inside the
measurement.

### D. Subtract a separately measured setup

Measure the setup alone, measure both together, subtract.

Rejected because two measurements of a system under different memory
pressure do not subtract. The fixture built inside a loop and the same
fixture built alone allocate differently, and the difference is not the
operation.

## Drawbacks

`Contract` gains a member, which is a row in the naming table and a
naming decision in six languages. The surface goes from two contract
members to three.

Each implementation grows a batched measurement path beside the one it
has. The measured paths that exist today are 31 lines in Rust, 25 in
Java and 11 in TypeScript, and a batched one is that shape plus a batch
loop, so this roughly doubles them. Five implementations, and the Kotlin
surface that shares Java's.

A batch holds its inputs in memory at once. A fixture that is large and
a batch that is generous can cost more memory than the benchmark it
measures, and the batch size becomes a number someone has to choose.
Criterion exposes that choice; this proposal does not, and a fixed batch
is wrong for someone.

The corpus cannot check any of this. The benchmark ceilings are among
the sixteen assertions it does not reach, because their answers depend
on the machine, so this rests on each implementation's own tests.

Two ways of writing a benchmark exist afterwards where one existed
before, and a reader has to know which one they are looking at.

## Unresolved and future work

What the member is called. `measuring` reads at a call site and sits
oddly beside `loop` and `check`. Criterion calls the same thing
`iter_batched`, JMH calls it a setup level, and Go has no name for it
because it has no such member. The naming table settles this in six
languages at once, and the canonical id is the part worth arguing about
rather than any one spelling.

Whether the batch size is fixed by the standard or chosen per
implementation. A fixed size makes two implementations comparable and is wrong for a
large fixture; a chosen one is right locally and makes the same benchmark mean slightly different things in two
languages.

Whether the measured body's return value is discarded or handed back to
the caller. Discarding it invites a compiler to remove the work, which
is what `black_box` exists for in Rust and what `Blackhole` exists for
in JMH. Neither is in the standard, and a ceiling on an operation the
optimiser deleted is a ceiling on nothing.

Whether TypeScript declines this or implements the latency half. It has
no allocation ceilings to correct, so its share is smaller, and an
overlay that says so is more honest than an implementation that quietly
covers half.

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
