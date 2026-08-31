---
rfc: 0006
title: The clock
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-31
updated: 2026-08-31
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0006: The clock

## Summary

Four assertions read the platform clock, and all five implementations
sleep against it. This puts time behind a seam a test can supply, so
those four run in microseconds and cannot be made flaky by a busy
machine.

## Motivation

`eventually`, `eventually-true`, `completes-within` and
`honours-deadline` all spend real time, and today that is the only kind
of time they know.

That costs twice. A suite using them is slow in proportion to the
timeouts its author chose, and a timeout generous on a laptop still
fails on a loaded continuous-integration machine. The usual response is
to widen it, which buys reliability with more waiting and delays the next
failure rather than preventing it.

There is a bug of this shape in shipped code, found while writing the
Rust implementation's tests. `completes-within` spawned a watcher that
slept for the whole ceiling and then joined it, so a call with a ten
second ceiling took ten seconds whether the body returned at once or not.
The behaviour suite went from 10.06 seconds to 0.06 once the watcher
waited on a condition instead. Nothing about that mistake is specific to
Rust. A library with no clock of its own has sleeping and little else.

The other reason is that some relations cannot be stated at all without
one. Whether an entry stops being readable once its lifetime has elapsed
is a question about a clock. Against a real one, a test either sleeps for
the lifetime or checks nothing.

## Detailed design

### The seam

```
Clock
  now() -> Instant
  sleep(duration)
```

A controlled clock carries one more:

```
  advance(duration)
```

An assertion that reads time reads it here. Where a test supplies no
clock, it gets the platform one and behaviour is what it is today, so
nothing a caller has written stops working.

### What advancing means

A controlled clock moves only when a test advances it. `now` answers what
it was last set to, and `sleep` returns once the clock has passed the
duration rather than once the wall has.

That is what makes an expiry relation statable: put a value with a
lifetime, advance past the lifetime, require the read to miss. And it is
what makes retrying cheap: `eventually` against a controlled clock
advances between attempts, so a body that settles on the third attempt
costs three attempts rather than two intervals of real waiting.

### The four assertions that change

Each keeps its signature. What changes is where the time comes from.

| Assertion | Reads the clock for |
|---|---|
| `eventually` | the deadline, and the wait between attempts |
| `eventually-true` | the deadline, and the backoff |
| `completes-within` | the elapsed measurement, and the ceiling |
| `honours-deadline` | the handle it hands the subject |

`honours-deadline` is the one that changes least. It already hands the
subject a handle that says the time has run out, and the handle does not
need a clock to say so. What the clock gives it is the ability to say so
at a stated moment rather than immediately.

### Where the clock comes from

The seat carries it. Every assertion already takes a seat, so no
signature changes and no assertion grows an argument:

```
Seat
  helper()
  fail(message)
  record(message)
  clock() -> Clock      the platform clock unless a test supplies one
```

A test wanting control constructs a seat with a controlled clock and
passes it as it already passes a seat.

### What it does not do

The clock reports time and nothing else. It does not schedule, does not
run callers, and decides nothing about whether anything failed.

It also cannot reach the subject. An assertion reading a controlled clock
while the code under test reads the platform one gives a test two
different notions of now, which is worse than either alone. The standard
can say so and cannot prevent it, and a subject that takes its own clock
is the only thing that fixes it.

## Alternatives considered

### A. Let each implementation use its platform's testing clock

Kotlin has a test dispatcher controlling virtual time, Rust has one in
tokio, Go has conventions around a `Clock` interface. Each language's
users already know their own.

Rejected because a relation stated against a platform facility means
something different in each language, and the corpus could never check
it. A test that advances tokio's clock and a test that advances Kotlin's
are not the same test, and an expiry case would have to be skipped
everywhere or written five times.

### B. Pass the clock as an argument rather than through the seat

An explicit argument is more honest about what an assertion reads, and it
does not widen the seat.

Rejected because it changes four signatures the naming table already
states, and because it puts a clock in the hands of every caller who does
not want one. The seat is the thing a test already threads through, and
it already carries the other choice a test makes about how assertions
behave.

### C. Make the clock required rather than defaulted

A seat with no clock could be a compile error, forcing every caller to
choose.

Rejected because the choice has an obvious default and most callers want
it. Requiring it would make the common case noisier to buy strictness
nobody asked for.

### D. Skip it and let callers shorten their timeouts

A suite that uses short timeouts is fast without any of this.

Rejected because a short timeout is what makes a suite flaky. The
tension between a timeout long enough to be reliable and short enough to
be quick is exactly what a controlled clock removes, and shortening
timeouts trades one failure mode for the other.

## Drawbacks

The seat gains a member, and a seat is the one interface every consumer
implements who wants to plug this into something. An existing custom seat
stops compiling in the languages where the seat is an interface rather
than a duck type.

Four assertions change their internals, and they are the four with the
most timing-dependent tests. Getting the change wrong makes a retry loop
spin rather than wait, which is worse than the sleeping it replaces.

A controlled clock is only as useful as the subject's cooperation. A test
whose subject calls the platform clock directly gets no benefit and may
get confusion, and nothing here detects that.

Five implementations gain a type they did not have. One design exists to
copy, in a Go project next door, and the other four write their own from
it. Rust has a controlled clock available in tokio, but the core crate is
synchronous and does not depend on tokio, so it gets no help there.

## Unresolved and future work

Whether `sleep` on a controlled clock should return immediately or wait
for another thread to advance it. The first is what a single-threaded
test wants and the second is what a test driving a background worker
wants, and they are not the same.

Whether the clock should be able to run at a multiple of real time
rather than only stepping. A subject with its own timers may need to
observe time passing rather than jumping.

Whether an assertion that reads the clock should say so in the
definition, so a generator can tell which ones need a controlled one.

## References

- The observation seams this is one of:
  `docs/rfc/0003-the-observation-seams.md`
