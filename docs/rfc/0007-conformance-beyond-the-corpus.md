---
rfc: 0007
title: Conformance beyond the corpus
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-31
updated: 2026-08-31
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0007: Conformance beyond the corpus

## Summary

The corpus checks what seventeen assertions mean. For the other
twenty-four the standard checks that a name exists and nothing else, and
that is where every cross-language bug this project has found lived.

This states five additions: a corpus that can describe a subject rather
than only values, a rule that every assertion is driven both ways, a
stage that proves the tests can fail at all, a gate that checks shape
rather than only a name, and a naming table that covers the whole
surface rather than only the assertions.

## Motivation

Conformance rests on two mechanisms. The corpus states cases as data and
runs them against every implementation, which is what makes an assertion
mean the same thing everywhere. The completeness gate checks that every
name in the naming table exists.

Between them they cover less than they appear to. The corpus reaches
seventeen of the forty-one, because a case is data and the other
twenty-four take a callable, a handle or a duration. For those, the gate
confirms a member exists under the right name. Nothing confirms it does
anything.

That gap is not theoretical. `honours-cancellation` shipped broken in
Python, in TypeScript and in Kotlin, each time in a way that reported
nothing whatever it was handed. Python built it on a timeout that never
started the coroutine. TypeScript tested a signal that was aborted before
the call, so every rejection passed. Kotlin cancelled the job before it
ran. All three passed the completeness gate, because the member existed
under the right name. None was reachable by the corpus.

The same class turned up again while writing the fifth implementation:
`completes-within` in Rust waited for its own ceiling on every call, so
a ten second ceiling cost ten seconds whether the body returned at once
or not.

The gap grows faster than the set. The relation family adds twenty
members and the observation seams reach twenty-eight more, and not one of
those is expressible as data either. Twenty-four unreachable becomes
seventy-two.

## Detailed design

### Subjects as data

A corpus case states its arguments as typed literals. What it cannot
state is a callable, which is why the assertions taking one are
unreachable.

They are unreachable because the encoding has no word for a subject, not
because a subject is unspeakable. Most of what these assertions need is a
behaviour from a small fixed set:

```json
{
  "id": "honours-cancellation/reads-the-handle",
  "subject": { "kind": "reads-handle" },
  "expect": "pass"
}
```

```json
{
  "id": "honours-cancellation/ignores-the-handle",
  "subject": { "kind": "returns-ok" },
  "expect": "fail",
  "detail": { "reason": {"type": "string", "value": "cancelled"} }
}
```

The vocabulary is stated by the definition and is deliberately small:

| `kind` | What the subject does |
|---|---|
| `returns-ok` | Does the work and answers success |
| `reads-handle` | Polls the handle and answers whatever reason it gives |
| `fails-with` | Answers the stated failure, whatever it was asked |
| `raises` | Raises rather than answering |
| `settles-after` | Answers a failure `n` times, then success |
| `never-settles` | Answers a failure every time |
| `accumulates` | Changes observed state once per call |
| `sets` | Changes observed state on the first call only |
| `observes` | Answers what a named projection reads |

Each implementation carries a registry from `kind` to a native closure,
the way it already carries one from assertion id to a native call. A kind
it cannot build is a declared skip, the same as any other case.

Ten of the twenty-four take a subject and nothing else the encoding
lacks: `honours-cancellation`, `honours-deadline`, `nil-context-safe`,
`throws`, `not-throws`, `eventually`, `eventually-true`, `pure`,
`pairwise` and `rejects`.

That is ten of the twenty-four, and the fourteen it misses should be
named rather than hoped over.

Five are the error assertions, which take a failure value rather than a
callable. Those are unreachable for a different reason: the encoding has
seven types and none of them is an error. An error literal would reach
all five, and it is a separate extension to this one.

`completes-within` takes a subject and a duration, and the duration is
what stops it: a case stating one is a case whose answer depends on the
machine. Four benchmark ceilings have the same problem in a worse form.
The three golden assertions need a filesystem, and `no-task-leaks` needs
a runtime that can start something.

So this takes the unreachable set from twenty-four to fourteen, and an
error literal would take it to nine. The remaining nine want real time,
real files or a real runtime, and they stay with each implementation's
own tests.

### Both ways, every time

An assertion driven only by subjects that satisfy it is checked by a
suite that would pass if the assertion reported nothing at all. That is
what happened three times.

So: an assertion with any corpus case must have at least one stating
`pass` and one stating `fail`. The validator can check that, and it
fails the standard rather than an implementation, because a corpus that
only drives the happy path is the standard's own gap.

### The reporting seam has to matter

Every assertion reports through one function. Returning early from it
should break the suite, and how badly it breaks is a measurement of
whether the suite checks anything.

Run once with that function silenced. Require that a stated share of the
tests fail.

The measurement is worth having because it has already found real
weakness. Silencing the seam in each implementation:

| Implementation | Tests failing when the seam is silenced |
|---|---|
| Rust | 55 of 94 |
| Java | 126 of 287 |
| TypeScript | 163 of 432 |
| Python, before | **11 of 1466** |
| Python, after | 83 of 1466 |

Python's eleven was not a small number that happened to be small. Its
whole suite, corpus included, checked its verdicts by calling the library
under test, so silencing the seam silenced the checker along with the
subject and every case passed having checked nothing. Go's conformance
package had the same shape and the same result.

### A verdict is not written with the subject

That is the rule the measurement above turns into: **a conformance runner
states its verdict with the test framework, never with the library under
test.**

It reads oddly until it has cost you something. Driving the library with
itself is worth having elsewhere, and both repositories that had this
problem had it in the one place it mattered.

### The table names the whole surface

The naming table covers forty-one assertions and two relaxations. A Rust
consumer types seventy-four public items, so thirty-five of them are
names the standard has never seen.

They are not incidental. `Seat`, `Standard`, `Recorder` and `Collector`
are the seam every assertion reports through and the three seats the
whole design rests on. `flush`, `failed`, `message` and `messages` are
how a test reads what happened. `scrub_timestamps` and `should_update`
are how a golden file is used at all. None is named, so each
implementation invented its own.

They have already diverged. Every implementation but one calls the seam
`Seat` with members `helper`, `fail` and `record`. Go calls it `TB` with
`Helper`, `Fatalf` and `Errorf`.

Go is right to. Naming it `TB` with those members is what lets a
`*testing.T` satisfy it without a wrapper, and inventing `Seat` there
would make every caller adapt the thing their test framework already
hands them. That is a language earning its own answer, which is what the
overlay records everywhere else.

Nothing records it here, because the table has no row to disagree with.
An implementation that renamed `Recorder` tomorrow would break no gate
and fail no test.

So the table gains what a user types beyond the assertions:

| Section | What it names |
|---|---|
| `types` | The seam, the three seats, and each supporting type |
| `members` | What those types answer: `fail`, `record`, `flush`, `message` |
| `helpers` | Free functions beside the assertions, such as the scrubbers |

Each row works as the assertion rows do. A language naming something
differently states its name, and a language that has no equivalent
declares it absent in the overlay with a reason. Go's `TB` becomes a
recorded answer instead of an unrecorded difference.

This is also what makes a future addition checkable on the day it lands.
A clock is a type with three members, and putting it in the table is what
turns "we agreed to add a clock" into something a gate can fail on.

### The gate checks shape, not only a name

Every assertion states its `arity`, and no implementation compares that
number against the member it found. Go checks that the definition states
an arity at all, and separately that its own test tables carry that many
arguments, which is a different question. A member with the right name
and the wrong arguments passes everywhere today.

The gate should compare what it finds against what the definition states.
How far that goes depends on the language: Rust pins a full signature at
compile time and cannot look anything up at run time, while Python can
count parameters and check nothing else. The rule is that a gate checks
as much of the shape as its language allows, and says which.

## Alternatives considered

### A. Name only the assertions, as today

The assertions are what the standard is about, and the rest is each
library's business. A smaller table is easier to keep true.

Rejected because the rest is not each library's business. A test that
reads `seat.failed()` in one language and `seat.Failed()` in another is
a test that cannot be ported, and the whole claim is that these mean the
same thing everywhere. The seam is more central than any assertion, and
it is the one thing the table does not cover.

### B. Leave the twenty-four to each implementation

Every library has its own tests, and this session's per-family passes are
thorough. A standard that checked only what data can express would be
smaller and easier to keep true.

Rejected because those tests are where three implementations shipped the
same bug. Each suite was written by someone reading the same
documentation and making the same assumption, and being written five
times independently is what let it survive five times.

### C. Require a fixed share of tests to fail under the mutation

The table above suggests a number, and a number is enforceable.

Rejected as the primary rule, though the stage stays. A share can be
raised by adding cheap tests that fail loudly, which is a worse suite
scoring better. The stage is worth running and worth reading; the rule
worth enforcing is that a verdict is not written with the subject, which
is what a bad score indicates.

### D. Generate the per-implementation tests from the corpus

If a subject can be described, the tests could be emitted rather than
written, and every language would get the same coverage by construction.

Rejected here because it is a generator, and this standard states what a
library must do rather than producing the library. A generator reading
these descriptions is a reasonable thing to build, and it would read
exactly what this proposes.

## Drawbacks

The subject vocabulary is a second language inside the corpus, and it
grows. Every new assertion that takes a callable in a shape nobody
anticipated needs either a new `kind` or a declared skip, and a
vocabulary of thirty kinds is a specification nobody reads.

Nine kinds cover the assertions that exist. That number is a guess about
the ones that do not.

The mutation stage needs each implementation to expose a way to silence
its reporting seam, which is a test-only entry point in the library
rather than in its tests. That is a hole cut in the library for the
standard's benefit.

Arity checking is worth least where it is easiest. A dynamic language can
count parameters and learn little; a static one already knows and gets
the check from its compiler.

Corpus cases roughly double. Every assertion reachable by a subject needs
a passing and a failing case, and several need more than one of each.

Naming the whole surface roughly doubles the table too, and every row is
a commitment. A member named in the table cannot be renamed without a
version, which is a constraint the implementations have not been under
and will notice.

## Unresolved and future work

Whether a subject description should be able to name another assertion,
so `rejects` can state the check it drives to failure.

Whether the mutation stage belongs in the standard at all or in each
repository's own gate. It is a property of a test suite rather than of a
library, and the standard has so far described libraries.

What a kind means when a language has no equivalent. `raises` in Rust is
a panic and in Go a panic and in Python an exception, and those are not
the same thing, which the naming table already records for `throws`.

## References

- The typed-literal encoding a subject description sits beside:
  `spec/encoding.md`
- The overlay format, which is how an implementation declares a kind it
  cannot build: `spec/overlays.md`
