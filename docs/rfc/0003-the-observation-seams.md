---
rfc: 0003
title: The observation seams
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-30
updated: 2026-10-02
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0003: The observation seams

## Summary

An assertion in this standard sees one thing: what a call returned. That
is not enough for anything about order or concurrency. This adds two
seams, a history and a concurrency driver, and states what each one
records.

The history records invocations and completions in one order that every
client shares. A completion states whether the call took effect, took no
effect, or ended without an outcome. Each invocation names the keys it
touches. The history reads no clock, so it works the same under the
platform clock, under a controlled clock and inside a simulation.

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

The implementations already use real threads where they must, and
they have nowhere to record what happened. An assertion that wants to
know whether two operations overlapped has to be handed that fact,
because nothing in the standard remembers it.

A checker can conclude from a history only what the history's order
shows.

A recorder that timestamps each call with the platform clock can report
that a call started after another finished when it did not. On an Apple M3
Pro, a timestamp taken before an atomic load was executed after it, and a
read appeared to start after a write it had not observed. A checker that
reads that order reports a violation that did not happen.

A recorder that synchronizes every client on a shared log adds the
synchronization that a buggy subject lacks. Lowe's first recorder did this,
and missed memory consistency bugs that his per-thread recorder found.

A history also has to record what happened to a call that never returned. A
call that timed out may have taken effect or not. A history that records
it as a failure lets a checker assume it had no effect, which produces a
violation whenever it did.

## Detailed design

### The history

```text
History
  new() -> History
      An empty history.
  invoke(client, operation, arguments, keys) -> Call
      Records an invocation by client and returns its call. keys lists
      the keys the call touches, as typed literals. An empty list means
      every key. Fails when client has a call that is still open.
  events() -> [Event]
      Every event, in recording order.

Call
  ok(value)
      Records that the call returned value and took effect.
  fail(error)
      Records that the call returned error and took no effect.
  unknown(error)
      Records that the call ended without an outcome, such as a timeout,
      a lost reply or a crash.
  Each fails when the call already has a completion.

Event
  index        the event's position in recording order, from 0
  kind         invoke, ok, fail or unknown
  call         the index of the call's invocation event
  client       the client that made the call
  process      the process that made the call
  operation, arguments, keys     on an invocation
  value, error                   on a completion
```

A history is safe for concurrent use. Clients record into it from any
thread.

Each client starts on a process of its own. A call that completes as
`unknown` may still be in progress inside the subject, so its process
never completes another call. The client's next invocation starts on a
new process. Processes are numbered in the order of their first
invocation. Every process has at most one open call, and its calls form a
sequence, which is the form of history that the definition of
linearizability assumes.

A call that has no completion when a checker reads the history is
pending. A checker treats a pending call as `unknown`.

### Recording order

Every invocation and every completion takes the next index from one
counter that all clients share. The counter's increment is sequentially
consistent: an atomic read-modify-write, or an increment under a lock. A
client records the invocation before the call to the subject starts, and
the completion after the call returns.

Call a precedes call b when a's completion index is below b's invocation
index. The history reports such a precedence only when a returned before b
started, so it never reports one that did not happen. Calls whose events
interleave are concurrent, and a checker may order them either way.

Under a simulation, every client runs on the simulation's one thread, and
the counter records the scheduler's order.

### Histories recorded elsewhere

```text
from-intervals(entries) -> History
    Builds a history from calls recorded with a start time and an end
    time on one clock. Each entry states the client, operation,
    arguments, keys, completion kind, value or error, start and end. An
    entry without an end is pending. Fails when two entries of one client
    overlap.
```

`from-intervals` orders the events by time. At an equal time, an
invocation comes before a completion, so two calls that share an instant
are concurrent. Among invocations, or among completions, at one time, the
entries keep their given order. Treating each interval as closed is the
only reading under which a monotonic clock, which can return one value
twice, produces no false precedence.

`from-intervals` requires every time to come from one clock, because calls
timed on different hosts put the hosts' clock skew into the order.

### Memory

A history stores two events per call, so its memory grows with the number
of calls. A machine of the property engine bounds the calls of one case by
its step limits. A hand-written test bounds them by its loop.

### Direct and decided properties

Assertions over a history come in two kinds:

- **Direct properties** read the events and check a rule over them.
  Whether a client's reads ever went backwards is a scan. So is whether one
  client's writes took effect in the order that client issued them. These
  need no search, and cover the four session guarantees, causal ordering,
  ordering between named operations, and whether an already-open read saw
  a concurrent write.
- **Decided properties** ask whether the history admits an order that a
  correctness condition allows. The linearizability checker searches for
  an order that a sequential model accepts. The isolation checks read a
  history with one call per transaction, derive the dependencies its reads
  reveal, and look for the cycles an isolation level forbids.

The seam is the same for both. What differs is what reads it.

### The concurrency driver

```text
concurrently(clients, body) -> [Outcome]
    Starts clients copies of body at once, the i-th with client number i,
    from 0, waits for every one of them, and returns what each returned,
    in client order.

Outcome
  client, value, error
```

`concurrently` runs one body from several callers at once and reports what
each saw. Assertions about concurrent safety compare the outcomes. A body
that also needs order records its calls into a history. A machine of the
property engine starts the clients of a concurrent section on real threads
through it.

The driver states no policy about scheduling. It starts the callers,
waits for all of them, and reports. A subject that breaks only under one
interleaving in a thousand passes most runs. The machines of the property
engine take the schedule from the test case instead.

### Roles

Several relations need more than one callable: a delete and the read that
proves it, a writer and the reader that confirms it, an acquire and its
release. These need no machinery, because the caller passes both. What
they need is a convention, so that the same relation names its parts the
same way in every language.

The convention is that a relation naming several callables takes them in
the order the law reads. `delete-removes` takes the delete then the read,
because the law is "delete, then read misses".

### Judgements are in assertions

Neither seam decides anything. The history records calls and the driver
runs callers. Every judgement is in an assertion, so each seam is small
enough to implement five times.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The event kinds and fields. One recording order from a sequentially consistent counter. Invocation before the subject's call, completion after it. A new process after `unknown`. A pending call reads as `unknown`. `from-intervals`' order, with closed intervals |
| Named | The history, the call, the event and their members, `from-intervals`, the driver and its outcome |
| Declared | The recorder's limit, in a language whose threads can run on more than one core: its synchronization can hide a missing barrier in the subject |
| Free | How a language stores events. Whether the counter is an atomic or a lock. How a history renders |

### Names

| Id | Go | Python | Rust | TypeScript | Java, Kotlin |
|---|---|---|---|---|---|
| `history` | `history.History` | `history.History` | `history::History` | `history.History` | `History` |
| `history.new` | `history.New` | `History()` | `History::new` | `new History()` | `new History()` |
| `history.invoke` | `History.Invoke` | `History.invoke` | `History::invoke` | `History.invoke` | `History.invoke` |
| `history.events` | `History.Events` | `History.events` | `History::events` | `History.events` | `History.events` |
| `history.from-intervals` | `history.FromIntervals` | `history.from_intervals` | `history::from_intervals` | `history.fromIntervals` | `History.fromIntervals` |
| `call` | `history.Call` | `history.Call` | `history::Call` | `history.Call` | `Call` |
| `call.ok` | `Call.OK` | `Call.ok` | `Call::ok` | `Call.ok` | `Call.ok` |
| `call.fail` | `Call.Fail` | `Call.fail` | `Call::fail` | `Call.fail` | `Call.fail` |
| `call.unknown` | `Call.Unknown` | `Call.unknown` | `Call::unknown` | `Call.unknown` | `Call.unknown` |
| `event` | `history.Event` | `history.Event` | `history::Event` | `history.Event` | `Event` |
| `history.concurrently` | `history.Concurrently` | `history.concurrently` | `history::concurrently` | `history.concurrently` | `History.concurrently` |
| `outcome` | `history.Outcome` | `history.Outcome` | `history::Outcome` | `history.Outcome` | `Outcome` |

That is 12 rows, 72 names. The fields of an event and an outcome are named
with their types. A type's id is bare, a member's id is the type's id and
the member, and a function of the `history` package has the package's id
before its own, as in the naming table's types, members and helpers.

### Versioning

| Change | Version |
|---|---|
| Adding the history, the driver and their names | Minor |
| A new event field | Minor |
| A new completion kind, or a change to the recording order or to how `from-intervals` orders entries | Major; a checker's verdict on the same calls can change |

## Alternatives considered

### A. One seam carrying both

A single object recording calls and running callers would be one thing to
pass rather than two. The seat is already passed to every assertion and
could provide them.

Rejected because the two are wanted independently. A test asserting that
a client's reads never go backwards needs a history and no concurrency at
all. Merging them means every implementation builds both before any
relation using either can be stated.

### B. Record history by wrapping the subject automatically

A recording proxy around the subject would spare the caller from
declaring what to record. That is what a generator would emit anyway.

Rejected because it needs the subject to be an interface the library can
wrap, which is a language-specific capability the standard cannot assume.
A generator is free to emit the wrapping. The standard states the seam it
wraps onto.

### C. Record an interval of clock times per call

Each entry contains the time its call was invoked and the time it
returned, and a checker derives precedence from the times.

Rejected for both clocks a test has:

- **The platform clock** can report a precedence that did not happen on a
  processor with weak memory ordering, as the reproduction on an Apple M3
  Pro showed. The Go memory model states no order between `time.Now()` and
  memory operations.
- **A controlled clock** moves only when a test advances it, so the calls
  of one step share one instant and every pair overlaps. A checker then
  accepts almost any history.

`from-intervals` keeps clock times for histories recorded outside the
seam, and its contract states the clock they must come from.

### D. A private log per client, merged by timestamp

Lowe records each thread's events in a private log with a timestamp and
merges the logs afterwards. The recorder adds no synchronization between
clients, and it found a missing barrier in a shared variable in 679 ms.

Rejected as the standard's recorder, because its correctness depends on
the clock's accuracy on each machine. Lowe states that it "may work less
well on other machines", and the arm64 reproduction shows how it fails.
The cost of the counter, a hidden missing barrier, is declared in each
language's overlay where it applies. A test that looks for missing
barriers needs a tool that controls memory ordering, which a recorder is
not.

### E. A failure as a returned value

`returns(value)` alone, with an error as one more value, would keep one
completion.

Rejected because it cannot tell an error that guarantees no effect from an
error after which the call may have taken effect. A checker that reads
every error as "no effect" reports a violation for each timed-out write
that did take effect.

## Drawbacks

Two seams is two interfaces in five languages before any relation using
them can be stated. Both cost that whether or not the relations needing
them are ever specified.

The counter synchronizes the clients. A subject that depends on a missing
barrier can pass under the recorder and fail in production. Every
implementation that runs threads on more than one core declares this in
its overlay.

The concurrency driver finds only what an unassisted schedule finds. A
subject that breaks under one interleaving in a thousand passes most runs.

A history grows by two events per call, and a long hand-written test can
record more calls than a checker can search.

Keys are the caller's statement. A call that touches a key it does not
declare makes a partitioned check wrong, and nothing in the seam detects
it.

The naming table grows by 12 rows, 72 names.

## Unresolved and future work

Whether the four session guarantees are one member taking a version field
or four members sharing a mechanism. They differ only in which pair of
operations they order, and the catalogue they come from gives all four
the same parameter.

## References

- Session guarantees, which the direct properties over a history state:
  Terry, Demers, Petersen, Spreitzer and Theimer,
  <https://doi.org/10.1109/pdis.1994.331722>
- Linearizability and pending invocations: Herlihy and Wing,
  <https://doi.org/10.1145/78969.78972>
- A shared log that masks memory bugs, and per-thread logs: Lowe,
  <https://doi.org/10.1002/cpe.3928>, §7.1
- Reordered timestamps on arm64: the maintainer's reproduction in the
  comments of Porcupine issue #40, whose own page returns 404,
  <https://api.github.com/repos/anishathalye/porcupine/issues/40/comments>
- Completions as `ok`, `fail` and `info`, and crashed processes: Knossos,
  <https://github.com/jepsen-io/knossos>
- The evidence behind the recorder: Research-0004
- The checker that reads the history: RFC-0004
- Machines, which record into the history and start clients through the
  driver: RFC-0012
- The isolation checks, which read a history of transactions: RFC-0015
