---
rfc: 0003
title: The observation seams
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-08-30
updated: 2026-10-04
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

The driver starts several clients at once, waits for them up to a
deadline, and reports what each one returned.

Research-0002 classifies 23 relations that need the seams: thirteen need
a history and ten need concurrent callers. Among them are the four
session guarantees, causal order, order between named operations,
transactional isolation and safety under concurrent callers. The
linearizability checker of RFC-0004 reads a history too. A relation that
takes several callables needs neither seam, because RFC-0002 fixes the
order of its callables.

Time is the other thing an assertion cannot see in a return value.
RFC-0006 specifies the clock that supplies it.

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
  invoke(client, operation, args, keys) -> Call
      Records an invocation by client and returns its call. keys lists
      the keys the call touches. An empty list means every key.
  events() -> [Event]
      The recorded events in recording order, without a gap.

Call
  ok(output)
      Records that the call returned output and took effect.
  fail(error)
      Records that the call returned error, took no effect, and returned
      nothing that a model checks.
  unknown(error)
      Records that the call ended without an outcome, such as a timeout,
      a lost reply or a crash.

Event
  index        the event's position in recording order, from 0
  kind         invoke, ok, fail or unknown
  call         the index of the call's invocation event
  client       the client that made the call
  process      the process that made the call
  operation    the operation, on an invocation
  args         the arguments, on an invocation
  keys         the keys the call touches, on an invocation
  output       what the call returned, on an ok completion
  error        the error, on a fail or an unknown completion
```

A history is safe for concurrent use. Clients record into it from any
thread.

`events()` returns the events with the indices 0 to n − 1, for the largest
n whose events are all stored. A reading while clients record never has a
gap. A call that a reading shows without a completion is pending, and a
checker treats a pending call as `unknown`.

Each client starts on a process of its own. A call that completes as
`unknown` may still be in progress inside the subject, so its process
never completes another call. The client's next invocation starts on a
new process. Processes are numbered in the order of their first
invocation. Every process has at most one open call, and its calls form a
sequence, which is the form of history that the definition of
linearizability assumes.

### What `fail` means

A checker removes a call that completed with `fail`. `fail` is therefore
for an error after which the call took no effect and returned nothing that
a model checks, such as a refused connection. An error that reports what
the subject observed is an output. A compare-and-set that refuses because
the value differs records `ok` with the output false. The model then checks
that the value differed, and a compare-and-set that refuses wrongly fails
the check. Porcupine's etcd test records a refused compare-and-set as an
output of false, and its model checks it.

### Values and keys

The history keeps the arguments, outputs and errors it receives, and does
not copy them. A caller records a copy of a value that the subject or the
test changes afterwards. A subject that returns its own state and changes
it later otherwise changes the recorded history.

Two keys are one key when their typed literals are equal, so the integer
1 and the float 1.0 are two keys. Every key has a typed literal.

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

In a simulation, the clients run as tasks on the simulation's one thread,
and the counter records the order that its scheduler chose.

### Histories recorded elsewhere

```text
from-intervals(entries) -> History or error
    Builds a history from calls recorded with a start time and an end
    time on one clock. Each entry states the client, operation, args,
    keys, completion kind, output or error, start and end. An entry
    without an end is pending.
```

`from-intervals` orders the events by time. At an equal time, an
invocation comes before a completion, so two calls that share an instant
are concurrent. Among invocations, or among completions, at one time, the
entries keep their given order. Treating each interval as closed is the
only reading under which a monotonic clock, which can return one value
twice, produces no false precedence.

A time is an integer read from one clock. `from-intervals` compares times
and never subtracts them. Calls timed on different hosts put the hosts'
clock skew into the order, so every time comes from one clock. The process
rule of `invoke` applies: after an entry whose kind is `unknown`, the
client's next entry starts on a new process.

`from-intervals` reads entries from outside the test, so it returns an
error for an entry that its rules refuse: two entries of one client that
overlap, and an entry that ends before it starts. An entry without an end
overlaps every later entry of its client.

### Memory

A history stores two events per call, so its memory grows with the number
of calls. A machine case with RFC-0012's defaults takes at most 100
sequential steps and 16 concurrent ones, which record 232 events when each
step makes one call. A hand-written test bounds its events by its loop.

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
concurrently(clients, within, body) -> [Outcome]
    Starts clients copies of body, the i-th with client number i, from 0.
    Releases them together once every copy has started, and waits until
    every copy has returned or within has passed on the platform clock.
    Returns one outcome per client, in client order.

Outcome
  client      the client number
  finished    whether the body returned before within passed
  output      what the body returned, when it finished
  error       the error the body returned, when it finished
```

`concurrently` runs one body from several callers at once and reports what
each saw. Assertions about concurrent safety compare the outcomes. A body
that also needs order records its calls into a history.

The release puts the clients' first calls close together. Without it, the
first client can finish a short body before the last one has started, and
the run tests no concurrency.

A client that is still running when `within` passes has an outcome with
`finished` false, so a deadlock ends in a reported outcome. Its thread runs
on, because a thread cannot be stopped from outside, and the history shows
its open call as pending, which a checker reads as `unknown`. A check for
leaked threads after the call reports the thread. The deadline reads the
platform clock, because a hung client does not advance a controlled clock.

The driver catches a panic in a body, waits for the other clients up to
`within`, and then raises again, on the caller's thread, the panic of the
lowest-numbered client that panicked. An uncaught panic on a client's
thread would end the process without the other clients' outcomes.

The driver states no policy about scheduling. A subject that breaks only
under one interleaving in a thousand passes most runs. A machine of the
property engine runs the clients of a concurrent section through the
driver on real threads, and repeats the case, because the operating
system's schedule does not replay. In a simulation, the task scheduler
runs the clients as tasks and takes the schedule from the case. Each
language declares which of the two its concurrent sections support, as
RFC-0012 states.

### Relations with several callables

A relation that takes several callables, such as a delete and the read
that proves it, or an acquire and its release, needs neither seam. The
caller passes every callable, in the order its law reads, as RFC-0002
fixes for `after-close`.

### Judgements are in assertions

Neither seam decides anything. The history records calls and the driver
runs callers. Every judgement is in an assertion, so each seam is small
enough to implement five times.

### Failure handling

| Condition | Behaviour |
|---|---|
| `invoke` for a client whose call is still open | A usage error: a panic in Go, an exception in the other languages |
| A second completion of one call | A usage error |
| A key without a typed literal | A usage error |
| `concurrently` with fewer than one client, or a negative `within` | A usage error |
| `from-intervals` with two overlapping entries of one client, or an entry that ends before it starts | An error that names the entry |
| A call without a completion when a checker reads the history | Pending, which a checker reads as `unknown` |
| `events()` while clients record | The events up to the first index whose event is not yet stored |
| A body that is still running when `within` passes | An outcome with `finished` false. The thread runs on, and its open call is pending in the history |
| A body that panics | Raised again on the caller's thread, after the other clients, as the panic of the lowest-numbered client that panicked |

A usage error reports a bug in the test's own code. `from-intervals`
reads data from outside the test, so it returns an error instead.

### Conformance

The vectors state a script of calls and the events it records:

```json
{ "id": "history/a-client-continues-on-a-new-process-after-unknown",
  "script": [
    { "invoke": 0, "client": 0, "operation": "write", "args": [{ "type": "int", "value": 1 }], "keys": [{ "type": "string", "value": "x" }] },
    { "unknown": 0, "error": "the reply was lost" },
    { "invoke": 1, "client": 0, "operation": "read", "args": [], "keys": [{ "type": "string", "value": "x" }] },
    { "ok": 1, "output": { "type": "int", "value": 1 } }
  ],
  "events": [
    { "index": 0, "kind": "invoke", "call": 0, "client": 0, "process": 0, "operation": "write", "args": [{ "type": "int", "value": 1 }], "keys": [{ "type": "string", "value": "x" }] },
    { "index": 1, "kind": "unknown", "call": 0, "client": 0, "process": 0, "error": "the reply was lost" },
    { "index": 2, "kind": "invoke", "call": 2, "client": 0, "process": 1, "operation": "read", "args": [], "keys": [{ "type": "string", "value": "x" }] },
    { "index": 3, "kind": "ok", "call": 2, "client": 0, "process": 1, "output": { "type": "int", "value": 1 } }
  ] }
```

A script entry with `invoke` opens a call under a number of the script,
and an entry with `ok`, `fail` or `unknown` completes the call it names.
Each implementation runs the script through its history and compares the
events in this JSON form, with `args`, `keys` and `output` as typed
literals and `error` as the error's text. RFC-0004's corpus states its
histories as such scripts.

The vectors:

| Kind | Each case states | And pins | Count |
|---|---|---|---|
| Recording | A script of two clients' calls, with `ok`, `fail` and `unknown` completions and a pending call | The events, their calls and their processes | 4 |
| From intervals | Entries at equal times, invocations at one time in a given order, and an `unknown` entry followed by its client's next entry | The events | 4 |
| Usage errors | A second open call of one client, and a second completion of one call | The script entry that raises the usage error | 2 |
| Interval errors | Two overlapping entries of one client, and an entry that ends before it starts | The entry that `from-intervals` names in its error | 2 |

That is 12 cases, in `corpus/history/seam.json`, with their inputs in
`corpus/history/seam.yaml`. `make render` computes the events with an
executable reference in `tools/`.

A schedule is no data that a vector can state. Each implementation tests
in its own suite the driver's release, its deadline and the panic it
raises again, a reading without a gap, and a key without a typed literal.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The event kinds, the fields and their JSON form. One recording order from a sequentially consistent counter. Invocation before the subject's call, completion after it. A new process after `unknown`. A pending call reads as `unknown`. A reading without a gap. Keys equal when their typed literals are equal. `from-intervals`' order, with closed intervals, its process rule and its errors. The usage errors. The driver's release, its deadline on the platform clock, its outcomes, and the panic it raises again |
| Named | The history, the call, the event and their members, `from-intervals`, the driver and its outcome |
| Declared | The recorder's limit, in a language whose threads can run on more than one core: its synchronization can hide a missing barrier in the subject. The overlays of Go, Java, Kotlin and Rust state it as the limit `history`, and the validator requires it of them |
| Free | How a language stores events. Whether the counter is an atomic or a lock. How a history renders. How a language raises a usage error |

### Names

| Id | Go | Python | Rust | TypeScript | Java, Kotlin |
|---|---|---|---|---|---|
| `history` | `history.History` | `history.History` | `history::History` | `history.History` | `History` |
| `history.new` | `history.New` | `History()` | `History::new` | `new History()` | `new History()` in Java, `History()` in Kotlin |
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
| A change to an event's JSON form, or to the driver's release, deadline or outcomes | Major |

## Alternatives considered

### A. One seam for both

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

### F. A driver without a deadline

`concurrently` waits for every client, however long that takes, and the
test framework's own time limit ends a test that hangs.

Rejected because a deadlock is the failure that a test of concurrent
callers looks for. A framework's time limit ends the test without the
outcomes of the clients that finished and without a reading of the
history, and not every framework has one.

### G. Copy each value when it is recorded

The history copies every argument and output, or encodes it as a typed
literal, when it records an event.

Rejected because a copy of an arbitrary value needs each language's own
deep copy, and an encoding would hand a model typed literals where it
reads native values. The caller knows which of its values can change, and
copies those.

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

A client that runs past the deadline keeps its thread, which runs on until
its call returns.

The history keeps the values it receives. A value that changes after it is
recorded changes the history, unless the caller records a copy.

A history grows by two events per call, and a long hand-written test can
record more calls than a checker can search.

Keys are the caller's statement. A call that touches a key it does not
declare makes a partitioned check wrong, and nothing in the seam detects
it.

The naming table grows by 12 rows, 72 names.

## Unresolved and future work

None.

## References

- Session guarantees, which the direct properties over a history state:
  Terry, Demers, Petersen, Spreitzer and Theimer,
  <https://doi.org/10.1109/pdis.1994.331722>
- Linearizability and pending invocations: Herlihy and Wing,
  <https://doi.org/10.1145/78969.78972>
- A shared log that masks memory bugs, and per-thread logs: Lowe,
  <https://doi.org/10.1002/cpe.3928>, §7.1
- Reordered timestamps on weakly-ordered processors: Porcupine's README,
  which states the warning since commit `b6694c6` of 2025-12-20,
  <https://github.com/anishathalye/porcupine/commit/b6694c6>, and the
  maintainer's reproduction on an Apple M3 Pro in the comments of issue
  #40, <https://api.github.com/repos/anishathalye/porcupine/issues/40/comments>
- A refused compare-and-set as a checked output: Porcupine v1.3.1,
  `porcupine_test.go`, lines 249 and 366,
  <https://github.com/anishathalye/porcupine/blob/v1.3.1/porcupine_test.go>
- Completions as `ok`, `fail` and `info`, and crashed processes: Knossos,
  <https://github.com/jepsen-io/knossos>
- The relations that need the seams, and their count: Research-0002
- The evidence behind the recorder: Research-0004
- The order of a relation's callables: RFC-0002
- The clock: RFC-0006
- The checker that reads the history: RFC-0004
- Machines, which record into the history and start clients through the
  driver: RFC-0012
- The isolation checks, which read a history of transactions: RFC-0015
