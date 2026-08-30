---
rfc: 0003
title: The observation seams
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-30
updated: 2026-08-30
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0003: The observation seams

## Summary

Three relations the standard cannot state have nothing to do with each
other, and the same absence blocks all three: an assertion sees nothing
but a return value. This adds three seams, a clock, a history and a
concurrency driver, and says what each one answers.

Thirty-two relations from the shape catalogue are waiting on one of the
three. Thirteen want a history, ten want concurrent callers, four want a
clock.

## Motivation

An assertion in this standard sees exactly one thing: what a call
returned. That is enough for a comparison and enough for the relations
that run a subject twice on one thread.

It is not enough for anything about time, order or concurrency. Whether
an entry expires after its lifetime is a question about a clock. Whether
a client's reads ever go backwards is a question about a sequence of
observations. Whether a counter is safe under load is a question about
callers running at once. None of the three can be asked through a return
value.

The implementations already reach for real time and real threads where
they must, and it costs them. Every retrying assertion in all five
languages sleeps against the wall clock, which makes a suite using them
slow and makes it flaky on a loaded machine. A controlled clock removes
both, and it is the only way a relation about expiry becomes checkable at
all rather than approximated by waiting.

## Detailed design

### The clock

```
Clock
  now() -> Instant
  sleep(duration)
  advance(duration)          on a controlled clock only
```

Assertions read time through the clock rather than from the platform.
Where a test supplies none, the clock is the real one and behaviour is
what it is today.

A controlled clock moves only when a test advances it, which is what
makes an expiry relation statable: put a value with a lifetime, advance
past the lifetime, require the read to miss. Against a real clock the
same test either sleeps for the lifetime or does not check anything.

The retrying assertions change with it. `eventually` against a controlled
clock advances rather than sleeps, so a test that waits five seconds runs
in microseconds and cannot be made flaky by a slow machine.

This is a change to existing members, not only an addition. `eventually`,
`eventually-true`, `completes-within` and `honours-deadline` all read the
platform clock today and would read the seam instead.

### The history

```
History
  invoke(client, operation, arguments) -> Call
  Call.returns(value)
  entries() -> [Entry]

Entry
  client, operation, arguments, value
  invoked_at, returned_at
```

A history records what happened, with enough to reconstruct order: who
called, what they called, what came back, and the interval each call
occupied. The interval is what separates a history from a log, and it is
what lets a checker distinguish calls that overlapped from calls that did
not.

Assertions over a history come in two kinds, and only the first is
proposed here.

**Direct properties** read the entries and check a rule over them.
Whether a client's reads ever went backwards is a scan. So is whether
writes by one client landed in the order that client issued them. These
are cheap, need no search, and cover the four session guarantees, causal
ordering, ordering between named operations, and whether an already-open
read saw a concurrent write.

**Decided properties** ask whether some ordering of the history exists
that a sequential model would have produced. That is a search, and it is
a separate proposal.

The seam is the same for both. What differs is what reads it.

### The concurrency driver

```
Concurrently
  run(callers, body) -> [Outcome]
  Outcome
    value, error, started_at, finished_at
```

Runs one body from several callers at once and reports what each saw,
with intervals. Assertions about concurrent safety compare the outcomes;
assertions that also need ordering feed the outcomes into a history.

The driver states no policy about scheduling. It starts the callers,
waits for all of them, and reports. A subject that only breaks under a
particular interleaving is not what this finds, and saying so is more
honest than implying a guarantee the driver cannot give.

### Roles

Several relations need more than one callable: a delete and the read that
proves it, a writer and the reader that confirms it, an acquire and its
release. These need no machinery, because the caller passes both. What
they need is a convention, so that the same relation names its parts the
same way in every language.

The convention is that a relation naming several callables takes them in
the order the law reads. `delete-removes` takes the delete then the read,
because the law is "delete, then read misses".

### What the seams do not do

None of the three decides anything. The clock reports time, the history
records calls, the driver runs callers. Every judgement stays in an
assertion, which is what keeps the seams small enough to implement five
times.

## Alternatives considered

### A. Let each implementation reach for its own platform facilities

Go has a testing clock in the standard library's orbit, Kotlin has a test
dispatcher that controls virtual time, Rust has one in tokio. Each
language's users know their own.

Rejected because a relation stated against a platform facility is a
different relation in each language, and the corpus could never check
it. The point of the standard is that a test means the same thing
everywhere, and a clock that means "tokio's clock" in one language and
"real time" in another breaks that at the first expiry test.

### B. One seam carrying all three

A single object supplying time, recording calls and running callers would
be one thing to pass rather than three. The seat is already passed to
every assertion and could carry them.

Rejected because the three are wanted independently. A test asserting
expiry wants a clock and no history. Merging them means every
implementation implements all three before any relation using any of them
can be stated, which is three times the work before the first payoff.

### C. Record history by wrapping the subject automatically

A recording proxy around the subject would spare the caller from
declaring what to record. That is what a generator would emit anyway.

Rejected because it needs the subject to be an interface the library can
wrap, which is a language-specific capability the standard cannot assume.
A generator is free to emit the wrapping; the standard states the seam it
wraps onto.

## Drawbacks

Three seams is three interfaces in five languages before any relation
using them can be stated, and the clock is a change to four existing
assertions rather than an addition beside them.

The clock is contagious. An assertion reading it is only controllable if
the subject reads it too, and the standard cannot make a subject do that.
A test whose subject calls the platform clock directly gets a controlled
clock in the assertion and a real one in the code under test, which is
worse than either alone. The standard can say so and cannot prevent it.

The concurrency driver finds only what an unassisted schedule finds. A
subject that breaks under one interleaving in a thousand passes. Tools
that explore the interleaving space exist and this is not one.

A history that records every call costs memory proportional to the run.
For the direct properties that is bounded by the test; for anything
driven by a generator it is not, and nothing here bounds it.

## Unresolved and future work

Whether the four session guarantees are one member taking a version field
or four members sharing a mechanism. They differ only in which pair of
operations they order, and the catalogue they come from gives all four
the same parameter.

Whether the history should record failures as well as returns. A call
that errored occupies an interval and may matter to an ordering property,
and nothing here says whether it is an entry.

How a history is bounded when something other than a hand-written test is
driving it.

## References

- Session guarantees, which the direct properties over a history state:
  Terry, Demers, Petersen, Spreitzer and Theimer,
  <https://doi.org/10.1109/pdis.1994.331722>
- Linearizability, for why an entry carries an interval rather than a
  point: Herlihy and Wing,
  <https://doi.org/10.1145/78969.78972>
