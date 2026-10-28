---
rfc: 0044
title: A seat that observes every call
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-28
updated: 2026-10-28
discussion: https://github.com/dokimasia/assert-go/issues/77
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0044: A seat that observes every call

## Summary

An assertion reports to its seat only when the call fails. The library
writes a call that passes into the call records, which a test's seat and a
recorder keep. A seat of another library has no way to learn whether an
assertion with a given contract ran. This proposal adds an optional member
of the seat:

- `seat.observe-call(call)` receives each assertion call, whatever its verdict.
  `call` states the assertion's id and the contract.
- A seat observes exactly the calls that a recorded run records, the calls
  in a body included, whatever the switch states.
- An assertion on a seat without the member does not allocate for it.

Definition 13.1.0 adds the member, the type of the call and the type
`observer` of Go, Java and Kotlin.

## Motivation

### A check that asserts nothing passes

dokimi runs generated checks on a handle, a seat that wraps the seat of the
test. A check whose decisive assertion never runs passes. An example is an
assertion of the zero value beside an error, on a subject whose calls never
fail. dokimi has to find such a vacuous check, and it needs to know which
assertions a check called.

The handle cannot learn it:

- An assertion reports to the seat only when it fails, through `fail`,
  `record` or `report`.
- The library writes a passing call into the call records. A test's seat
  writes them into the artifact when `DOKIMI_ASSERT_RECORD` is `1`, and a
  recorder keeps them. assert-go keeps them in an unexported type that a seat of the
  module embeds, so a seat of another module cannot keep them.
- The artifact is complete after the process ends. dokimi decides on each
  check while the test runs.

### Prior art

- JUnit 5 reports a test whose assumption failed as aborted, not as passed.
- QuickCheck's `cover` with `checkCoverage` fails a property whose cases do
  not meet a labelled condition often enough.

Both make a test that checked too little visible. Neither covers a single
assertion that never ran.

## Detailed design

### The member

```text
Seat
  helper()
  fail(message)
  record(message)
  report(failure, aborting)
  report-fault(fault, ending)
  observe-call(call)
  skip(reason)
  clock() -> Clock
  cancellation() -> cancellation handle
```

`observe-call(call)` receives one assertion call:

| Field | Value |
|---|---|
| `assertion` | The id of the assertion, as `assertions.json` names it |
| `contract` | The caller's message, unchanged |

A seat need not state the member. Go, Java and Kotlin state it on the type
`observer`, which a seat may implement, as they state `report-fault` on
`fault-reporter`. Python and TypeScript state it as an optional member of
the seat. Rust gives it a default that does nothing.

The member is not named `observe`. A case of a property is a seat, and its
member `case.observe` records a fingerprint. Python and TypeScript find an
optional member of a seat by its name, so a member `observe` would make
every case an observer of its own fingerprints.

### Which calls a seat observes

A seat observes exactly the calls that a recorded run records, as
`recording.md` states them:

- Every assertion call, whatever its verdict: `pass`, `fail`, `error` or
  `skip`.
- No call of a helper that is no assertion, such as `fault`.
- The calls in the body of a property, of `eventually` and of `rejects`, as
  the calls of the body's runs. A property passes the calls of its cases in
  the order of a run on one worker, as it records them.

The first seat of the chain of the test that states the member observes
the calls, as the first seat with `report` receives a failure. The seat of
a body passes each call in the body to the observer of the assertion that
ran the body.

A seat observes the calls whatever `DOKIMI_ASSERT_RECORD` states. A
property on a seat with an observer keeps the calls of its cases, as a
recorded property keeps them.

### The order

The seat observes each call once, before it receives the failure, the
fault or the skip of that call. An aborting assertion that ends its test
through `fail` has been observed by then. The seat observes a call in a
body when the assertion that ran the body takes the body's calls, so it
receives the calls of a property's cases in the order of a run on one
worker.

### The cost

An assertion on a seat without the member does not allocate for it. The
assertion finds no observer along the chain and does not build a call. An
assertion on a seat with an observer builds the call from two strings that
the caller passed.

The allocation ceilings of the assertions apply to a seat without the
member.

Rust cannot tell whether a seat overrides a default method. An assertion
in Rust that runs a body therefore keeps the calls of the body on every
seat, and drops them after the seat has observed them. A call outside a
body allocates nothing for the observer.

### The languages

```go
// Observer is a TB that observes each assertion call, a passing one
// included. The first Observer of a seat's chain receives each call that a
// recorded run records, whatever DOKIMI_ASSERT_RECORD states.
type Observer interface {
	ObserveCall(call Call)
}

// Call is one assertion call: the id of the assertion and the contract
// that the caller passed.
type Call struct {
	Assertion string
	Contract  string
}
```

```python
@dataclass(frozen=True, slots=True)
class Call:
    """An assertion call, with the id of the assertion and the contract."""

    assertion: str
    contract: str


class Seat(Protocol):
    def observe_call(self, call: Call) -> None: ...  # optional
```

```rust
/// An assertion call, with the id of the assertion and the contract.
pub struct Call<'c> {
    pub assertion: &'static str,
    pub contract: &'c str,
}

pub trait Seat: Send + Sync {
    /// Observes one assertion call. The default does nothing.
    fn observe_call(&self, call: &Call<'_>) {}
}
```

```typescript
/** An assertion call, with the id of the assertion and the contract. */
export interface Call {
  readonly assertion: string;
  readonly contract: string;
}

interface Seat {
  /** Observes one assertion call, a passing one included. */
  observeCall?(call: Call): void;
}
```

Java and Kotlin name the call `AssertionCall`, because `Call` is the call of
a history there:

```java
public interface Observer {
  void observeCall(AssertionCall call);
}

public record AssertionCall(String assertion, String contract) {}
```

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `observer` | `Observer` | | | | `Observer` | `Observer` |
| `seat.observe-call` | `ObserveCall` | `observe_call` | `observe_call` | `observeCall` | `observeCall` | `observeCall` |
| `assertion-call` | `Call` | `Call` | `Call` | `Call` | `AssertionCall` | `AssertionCall` |
| `assertion-call.assertion` | `Assertion` | `assertion` | `assertion` | `assertion` | `assertion` | `assertion` |
| `assertion-call.contract` | `Contract` | `contract` | `contract` | `contract` | `contract` | `contract` |

Python, Rust and TypeScript decline `observer`, as they decline
`fault-reporter`: their seats state the member themselves.

### Conformance

A seat is an input of a test, so no vector pins the member. Each language
tests these behaviours in its own tests:

- A passing call, a failing call, a call that ends with a fault and a call
  that skips are each observed once, with their assertion and contract.
- A failing call is observed before the seat receives its failure.
- The observer of a property's seat receives the calls in the property's
  cases, in the order of a run on one worker, with recording off.
- A call of `fault` is not observed.
- An assertion on a seat without the member meets its allocation ceiling.

### Version

The member and the type add names. They do not change the meaning of an
existing name. Definition 13.1.0
adds the five rows.

## Alternatives considered

### A. Export the call records to every seat

A seat outside the library would keep the call records as a seat of the
library does. It would decode their JSON.

**Why not:** a seat would decode an encoding to learn two strings. The call
records exist only under the switch or on a recorder, and a seat would
depend on their encoding, which a major version can change.

### B. Read the artifact after the run

dokimi would read the call records of the artifact once the run ends.

**Why not:** the artifact is complete only after the process ends, and only
when the switch is on. dokimi decides on each check while the test runs,
such as in the falsification of a suite.

### C. A verdict in the call

The call would state the verdict beside the assertion and the contract.

**Why not:** a seat receives the failure of a call that fails through
`report`, and its fault through `report-fault`. The need is to know that an
assertion ran. A field that a seat can learn from the other members would
be a second source of the same fact.

## Drawbacks

- The seat gains a member, every language gains a type, and Go, Java and
  Kotlin gain an interface.
- A property on a seat with an observer keeps the calls of its cases, which
  costs memory, as a recorded property does.
- An observer of a property receives the calls of every case, of the shrink
  and of the explanation, up to thousands of calls.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/77> |
| The calls that a recorded run records | RFC-0016 and `spec/recording.md` |
| The member `report-fault` and the type `fault-reporter` | RFC-0033 |
| JUnit 5's assumptions | <https://docs.junit.org/current/writing-tests/assumptions.html> |
| QuickCheck's `checkCoverage` | <https://hackage.haskell.org/package/QuickCheck/docs/Test-QuickCheck.html> |
