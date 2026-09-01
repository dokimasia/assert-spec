---
rfc: 0003
title: The observation seams
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-30
updated: 2026-09-01
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0003: The observation seams

## Summary

An assertion in this standard sees one thing: what a call returned. That
is not enough for anything about order or concurrency. This adds two
seams, a history and a concurrency driver, and says what each one
answers.

Twenty-eight relations from the shape catalogue cannot be stated today.
Thirteen want a history and ten want concurrent callers. The remaining
five need no machinery at all, only a convention for naming the several
callables they take, so this states that convention beside the two seams.

Time is the other thing an assertion cannot see, and the standard already
has a clock. That one arrived on its own because it changed four
assertions that existed rather than only enabling new ones.

## Motivation

An assertion in this standard sees exactly one thing: what a call
returned. That is enough for a comparison and enough for the relations
that run a subject twice on one thread.

It is not enough for anything about order or concurrency. Whether a
client's reads ever go backwards is a question about a sequence of
observations. Whether a counter is safe under load is a question about
callers running at once. Neither can be asked through a return value.

The implementations already reach for real threads where they must, and
they have nowhere to record what happened. An assertion that wants to
know whether two operations overlapped has to be handed that fact,
because nothing in the standard remembers it.

## Detailed design

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
Whether a client's reads ever went backwards is a scan. So is whether one
client's writes took effect in the order that client issued them. These
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

Neither decides anything. The history records calls and the driver runs
callers. Every judgement stays in an assertion, which is what keeps the
seams small enough to implement five times.

## Alternatives considered

### A. One seam carrying both

A single object recording calls and running callers would be one thing to
pass rather than two. The seat is already passed to every assertion and
could carry them.

Rejected because the two are wanted independently. A test asserting that
a client's reads never go backwards needs a history and no concurrency at
all. Merging them means every implementation builds both before any
relation using either can be stated.

### B. Record history by wrapping the subject automatically

A recording proxy around the subject would spare the caller from
declaring what to record. That is what a generator would emit anyway.

Rejected because it needs the subject to be an interface the library can
wrap, which is a language-specific capability the standard cannot assume.
A generator is free to emit the wrapping; the standard states the seam it
wraps onto.

## Drawbacks

Two seams is two interfaces in five languages before any relation using
them can be stated. Both cost that whether or not the relations needing
them are ever specified.

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
