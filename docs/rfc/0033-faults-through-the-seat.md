---
rfc: 0033
title: Faults through the seat
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-22
updated: 2026-10-22
discussion: https://github.com/dokimasia/assert-spec/issues/14
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0033: Faults through the seat

## Summary

A call ends with the verdict `error` when the library refuses an argument
or its environment. The seat takes a failure record through `report`, and
no member of the seat takes the fault itself. Each library ends its own
calls with a fault through internal code, and a library built on the seat
can only send the text of a fault through `fail`. This proposal adds four
rows to the naming table:

- The member `seat.report-fault` takes a fault as the error it is.
- The type `fault-reporter` states that member in Go, Java and Kotlin,
  whose interfaces have no defaults, as `reporter` states `report`.
- The helper `fault` ends the call of a helper with an error.
- The member `recorder-seat.faults` returns each fault that a recorder
  received.

A library passes each fault of its own to the seat as `fault` passes a
fault. Definition 10.0.0 adds the rows.

## Motivation

### A library built on the seat has no way to end a call with a fault

The conformance runner `go.dokimi.dev/conform` is a library built on the
seat. The handle of a check is a seat, and its methods `Reference`,
`Second`, `Restart` and `Advance` need an option of the application. A
check that calls `Restart` without the option `Restartable` ends without a
verdict on its subject. conform writes the text of the fault and calls
`Fatalf` of the seat, at four places:

```go
h.Fatalf("%[1]s calls Restart without the option conform.Restartable. "+
	"Pass the option to the application:\n"+
	"\tconform.Restartable(func(h *conform.Handle[%[2]v], s %[2]v) %[2]v { … })",
	h.check.ID, reflect.TypeFor[S]())
```

assert-go ends its own calls through the internal function `End`, which
passes the fault to the first seat of the chain that implements the
internal interface `FaultReporter`, and sends the writer's text of the
fault through `Fatalf` of any other chain. conform repeats the second
branch of `End` by hand, so its fault exists only as text:

- A seat that takes a fault as the error it is never receives a fault of
  conform.
- The seat receives a fault of conform in the same form as a failure that a
  check reports through `Fatalf`.
- A test of conform can compare only the text of a fault.

### Each library ends a call with a fault in its own way

| Language | A fault of the library |
|---|---|
| Go | Passed to the first `FaultReporter` of the seat's chain, an internal interface, and otherwise sent as text through `Fatalf` |
| Rust | Sent as text through `fail` |
| Python | Raised as the internal `FaultError` |
| TypeScript | Thrown as the internal `Fault` |

A recorder in Rust receives a fault as the text of a failure without a
record. A test of an assertion then sees the same outcome for a fault and
for a message that a check sends through `fail`.

## Detailed design

### The member

```text
Seat
  helper()
  fail(message)
  record(message)
  report(failure, aborting)
  report-fault(fault, ending)
  clock() -> Clock
  cancellation() -> cancellation handle
```

`report-fault(fault, ending)` receives a fault as the error it is:

- `ending` is true for a fault that ends the call, and false for a fault
  that the call notes and runs on past. A property's store that cannot
  write an entry is such a fault: the run keeps its verdict.
- The seat that states the member determines what a fault does, as its
  `fail` determines what a failure does.

A seat need not state the member. Go, Java and Kotlin state it on the type
`fault-reporter`, which a seat may also implement. Python and TypeScript
state it as an optional member of the seat. Rust gives the member a
default on the trait `Seat`.

### The helper

```text
fault(seat, error)
    Ends the call of a helper with error, a fault. A seat that states
    report-fault receives error with ending true. Any other seat ends the
    call as the language ends a call with a fault. fault writes no call
    record, because the call is no call of an assertion.
```

The language's way to end a call with a fault for a seat without the
member:

| Language | A seat without the member |
|---|---|
| Go | Receives the writer's text of the fault through `Fatalf` |
| Rust | Receives the text of the fault through `fail`, in the default of the member |
| Python | The helper raises the fault |
| TypeScript | The helper throws the fault |
| Java, Kotlin | The helper throws the fault |

A recorder and any other seat that states the member return from it, so
`fault` may return. The helper that called `fault` then returns.

### The faults of a library

A library passes each fault of its own to the seat as `fault` passes a
fault. A seat that states the member receives the fault with `ending`
true, and any other seat ends the call as the preceding table states. The
call record states the verdict `error` and the text of the fault, as
before.

The library passes a fault that a call notes to the member with `ending`
false. A seat without the member receives it as each language notes a
fault today:

| Language | A noted fault on a seat without the member |
|---|---|
| Go | The writer's text of the fault in the log of the seat, through `Logf` |
| Rust | The text of the fault on the standard error, in the default of the member |
| Python | A warning of the module `warnings` |
| TypeScript | A message of `console.warn` |

### The recorder

`recorder-seat.faults` returns each fault that the recorder received
through `report-fault`, in order, ending or not. An ending fault fails the
recorder, as a failure that stops does, and the text of the fault becomes
the recorder's message. The recorder keeps a noted fault without failing.

A test of a library then compares the error:

```go
rec := assert.NewRecorder()
restartWithoutOption(rec)
assert.Length(t, rec.Faults(), 1, "the check ends with one fault")
assert.ErrorIs(t, rec.Faults()[0], conform.ErrOption, "the fault names the missing option")
```

### Go

```go
// FaultReporter is a TB that takes a fault as the error it is, rather than
// as the writer's text of it, as a Reporter takes a failure's record.
type FaultReporter interface {
	ReportFault(err error, ending bool)
}

// Fault ends the call of a helper with err, a fault. It passes err to the
// first seat of tb's chain that satisfies FaultReporter, with ending true,
// and sends the writer's text of err through Fatalf of tb for a chain
// without one. Fault does not write a call record. It may not return.
func Fault(tb TB, err error)

// ReportFault keeps err among the faults of the recorder. A fault with
// ending true fails the recorder, as Fatalf does.
func (r *Recorder) ReportFault(err error, ending bool)

// Faults returns the faults that the recorder received, in order.
func (r *Recorder) Faults() []error
```

`Fault` is the public form of the internal `End`, and `FaultReporter` the
public name of the internal interface. A helper that ends its call
returns after `Fault`:

```go
if h.restart == nil {
	assert.Fault(h, fmt.Errorf("%w: %s calls Restart without conform.Restartable", ErrOption, h.check.ID))
	return
}
```

### Rust

```rust
pub trait Seat: Send + Sync {
    /// Receives a fault: an error that ends the call without a verdict when
    /// `ending` is true, and that the call notes and runs on past when it is
    /// false. The default sends the text of an ending fault through `fail`,
    /// and prints the text of any other fault to the standard error.
    #[track_caller]
    fn report_fault(&self, fault: Arc<dyn Error + Send + Sync>, ending: bool) { /* … */ }
}

/// Ends the call of a helper with `error`, a fault, through
/// `seat.report_fault(error, true)`. It does not write a call record.
#[track_caller]
pub fn fault(seat: &dyn Seat, error: impl Error + Send + Sync + 'static);

impl Recorder {
    /// Returns the faults that the recorder received, in order.
    pub fn faults(&self) -> Vec<Arc<dyn Error + Send + Sync>>;
}
```

A fault is an `Arc`, so the recorder keeps it and a test downcasts it with
`downcast_ref`. A fault of the library is an error whose text is the text
that a seat received through `fail` before.

### Python

```python
def fault(seat: Seat, error: BaseException) -> None:
    """End the call of a helper with error, a fault."""


class Recorder:
    def report_fault(self, fault: BaseException, ending: bool) -> None: ...
    @property
    def faults(self) -> list[BaseException]: ...
```

A seat states `report_fault` as a method. `fault` calls the method of a
seat that has it. For any other seat, `fault` raises `error`.

### TypeScript

```typescript
interface Seat {
  /** Takes a fault as the error it is. */
  reportFault?(fault: Error, ending: boolean): void;
}

/** Ends the call of a helper with error, a fault. */
export function fault(seat: Seat, error: Error): void;

class Recorder {
  reportFault(fault: Error, ending: boolean): void;
  get faults(): readonly Error[];
}
```

`fault` calls `reportFault` of a seat that states it. For any other seat,
`fault` throws `error`.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `fault-reporter` | `FaultReporter` | | | | `FaultReporter` | `FaultReporter` |
| `seat.report-fault` | `ReportFault` | `report_fault` | `report_fault` | `reportFault` | `reportFault` | `reportFault` |
| `recorder-seat.faults` | `Faults` | `faults` | `faults` | `faults` | `faults` | `faults` |
| `fault` | `Fault` | `fault` | `fault` | `fault` | `Check.fault` | `Check.fault` |

Python, Rust and TypeScript decline `fault-reporter`, as they decline
`reporter`: their seats state the member themselves.

### Conformance

A fault is an input of a test, so no vector pins it. Each language tests
these behaviours in its own tests:

- `fault` passes its error to a recorder with `ending` true, and the
  recorder returns the same error from `faults`.
- `fault` on a seat without the member ends the call as the language's row
  of the table states.
- A recorder receives a fault of the library as the error it is, and the
  call record states the verdict `error`.
- A recorder receives a fault that a call notes with `ending` false, and
  the fault does not fail the recorder.

### Version

Adding rows to the naming table is a minor version change. Definition
10.0.0 adds the four rows, beside the major changes of the same release.

## Alternatives considered

### A. Text through `fail`

A library built on the seat would keep sending the text of a fault through
`fail`, as conform does today.

**Why not:** the fault then exists only as text. A test compares strings,
a seat that takes errors never receives one, and a falsification harness
cannot tell a fault from a failure.

### B. A failure record of a reserved assertion

A fault would be a failure record whose assertion is a reserved id, such
as `fault`, with the error's text in its detail.

**Why not:** a failure record states the detail that an assertion declares,
and a fault ends a call without a verdict. A record of a fault would make
every reader of records tell two kinds apart, and its detail would contain
the text of the error and not the error.

### C. A panic or an exception in every language

Every language would raise the fault, as Python and TypeScript do.

**Why not:** a recorder could not keep it. In Go, a panic that the test
does not recover stops the whole test binary, so no test after it runs.

### D. A member without `ending`

The member would take only the faults that end a call.

**Why not:** Go already passes a noted fault to the same member, and a
recorder of a test of a property would then lose the faults of its store.

## Drawbacks

- The naming table gains four rows. Each language gains a member of the
  seat, a member of the recorder and a helper, and Go, Java and Kotlin gain
  a type.
- Rust's trait `Seat` gains a member with a default. A seat of a caller's
  own that overrides it determines what a fault does.
- Python and TypeScript pass a fault to the member of a seat that states
  it, and raise the fault for any other seat.
- Each library routes its own faults through the member, so a recorder now
  receives a fault of the library as a fault and not as a failure.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/14> |
| `End` and `FaultReporter` of assert-go v0.5.1 | `internal/matcher/end.go` and `internal/matcher/seat.go` |
| The four calls of `Fatalf` in conform | `conform/handle.go` of dokimasia/dokimi-go at 15f33fa |
| The verdict `error` | `spec/recording.md` |
