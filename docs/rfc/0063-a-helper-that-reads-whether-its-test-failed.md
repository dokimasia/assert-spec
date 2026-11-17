---
rfc: 0063
title: A helper that reads whether its test failed
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-16
updated: 2026-11-16
discussion: https://github.com/dokimasia/assert-spec/issues/38
supersedes: RFC-0047, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0063: A helper that reads whether its test failed

## Summary

A Go helper that takes a seat cannot read whether its test failed.
`assert.TB` has `Helper`, `Fatalf` and `Errorf`. `*testing.T`,
`*testing.B`, `*testing.F` and `assert.Recorder` have `Failed`, and the
library does not export a function that calls it. This proposal adds the
member `seat.failed` and the helper `failed(seat)`:

- The member is true once the seat has received a failure, or a fault that
  ended a call.
- In a cleanup, the seat also counts the error or the panic that ended its
  test, its case or its body. A cleanup that keeps the data of a failed
  test then reads the outcome of the test.
- Go's `testing` runs the cleanups of a test without parallel subtests
  before it marks a test that panicked failed. The Go overlay declares that
  limit.
- The recorder's member `recorder-seat.failed` is its `seat.failed`, and
  its meaning does not change.
- In Go, Python and TypeScript, the helper `failed` reads the member on any
  seat. On a seat without the member, the helper ends the call with a
  fault.
- Rust, Java and Kotlin decline the helper. Their seat gives the member a
  default, which ends the call with the same fault.
- A Rust seat passes itself to each of its cleanups, so a cleanup reads the
  member in Rust too.

Definition 16.6.0 adds the member and the helper.

## Motivation

### A cleanup cannot read the outcome of its test

Helpers take the seat, so that one helper serves the seat of a test, a
case of a property, a recorder and the seat of a check under `rejects`.
Some helpers create data that a developer reads after a failed test.

A test kit of a database store clones a database of a local stack for each
test, and drops the clone in a cleanup. When the test fails, the kit keeps
the clone, so that a developer reads the rows that the test left. The suite
of the store builds its subject from the handle of a check of a
conformance kit, so the kit takes `assert.TB`. Its cleanup does not compile
with assert v0.23.0:

```go
func kept(tb assert.TB) bool {
	tb.Helper()

	return tb.Failed()
}
```

```text
vet: ./probe_test.go:9:12: tb.Failed undefined (type assert.TB has no field or method Failed)
```

The kit can take `testing.TB` instead. The factory of the conformance kit
then cannot call it. The kit can also look for a seat with `Failed` along
the seats that `Unwrap` returns. That search repeats the search of the
library's `Skipf`.

### The recorder alone has the member

`recorder-seat.failed` is true once a recorder has failed. The seat of a
test has the same state in every language. The definition has no member
for it:

| Language | Seat of a test | Where the state of the test is |
|---|---|---|
| Go | `*testing.T`, `*testing.B` and `*testing.F` | `Failed`, which `testing.TB` declares |
| Python | The collector of the fixture `seat` | The exception of the call phase, which the plugin's wrapper of `pytest_runtest_call` receives before it runs the cleanups |
| TypeScript | The collector of the fixture of `@dokimi/assert/vitest` | The state `fail` of the task, which vitest sets before it cleans up the fixtures |
| Rust | `Collector` | `std::thread::panicking()`, which the drop of the collector reads before it runs the cleanups |
| Java, Kotlin | `SeatExtension` | `ExtensionContext.getExecutionException()`, which `afterTestExecution` reads before it runs the cleanups |

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
  cleanup(function)
  failed -> bool
  clock() -> Clock
  cancellation() -> cancellation handle
```

`failed` is false until the seat fails. A seat fails when it receives a
failure through `fail`, `record` or `report`, or a fault that ends a call.
A noted fault does not fail the seat. After the seat fails, the member is
true for the rest of its test. Any thread may read the member, because a
seat is safe for concurrent use.

The seat of a test, a case and the seat of a body also fail when their
body ends with an error or a panic. The seat records that end before it
runs its cleanups, so a cleanup reads it. A language whose test runner
does not let its seat read that end declares a limit on the member. The
body itself reads only the failures and the faults that the seat has
received.

### The member of each seat

| Seat | `failed` is true when |
|---|---|
| The seat of a test of the platform | The test received a failure, or a fault that ended a call. In a cleanup, also when the test ended with an error or a panic, except in Go for a test without parallel subtests. In Go, also when a subtest failed, because `testing` marks the parent failed |
| A case | The case received a failure, or a fault that ended a call in its body. In a cleanup of the case, also when the body ended with an error or a panic |
| The seat that `rejects` hands its check | The check received a failure, or a fault that ended a call. In a cleanup of the check, also when the check ended with an error or a panic |
| The seat of an attempt of `eventually` | The attempt received a failure, or a fault that ended a call. In a cleanup of the attempt, also when the attempt ended with an error or a panic |
| The recorder | The recorder received a failure, or a fault that ended a call, as `recorder-seat.failed` states |
| `Standard`, and any other seat without the member | The helper `failed` ends the call with a fault |

The seat of a test records the end of its test before its cleanups run,
with one gap in Go:

- Go's `testing` marks a test that panicked failed before its cleanups
  only when the test has parallel subtests. In Go 1.27.4, `doPanic` calls
  `Fail` before `runCleanup`. For a test without parallel subtests, a
  deferred call of `tRunner` runs the cleanups first, before the deferred
  call that recovers the panic. The runtime has no call that reports a panic
  in progress, so the library cannot read the panic in the cleanup. The Go
  overlay declares a limit on `seat.failed`.
- Python's plugin receives the exception of the call phase at the `yield`
  of its wrapper of `pytest_runtest_call`, under pytest 9.1.1 and pluggy
  1.6.0. It marks the collector failed before its `finally` runs the
  cleanups. The exception of a skip or of an expected failure does not
  fail the collector.
- vitest 4.1.12 and vitest 5.1.0 set the state of the task to `fail` when
  the test function throws or rejects, and clean up the fixtures after
  that. The fixture reads the state before it runs the cleanups of its
  collector.
- The jest adapter supplies no seat of a test, because jest runs no
  `beforeEach` and no `afterEach` for a `test.concurrent` test. A jest test
  passes a seat that it builds, and the member of that seat counts the
  failures and the faults that the seat received.
- The drop of a Rust collector reads `std::thread::panicking()` before it
  runs the cleanups.
- `SeatExtension` reads `ExtensionContext.getExecutionException()` in
  `afterTestExecution`, before it runs the cleanups.

A helper keeps the data of a failed test through the member:

```go
func scratch(tb assert.TB) string {
	tb.Helper()
	dir, err := os.MkdirTemp("", "store-*")
	assert.NoError(tb, err, "the scratch directory exists")
	assert.Cleanup(tb, func() {
		if !assert.Failed(tb) {
			os.RemoveAll(dir)
		}
	})
	return dir
}
```

### The helper

A seat may lack the member in Go, Python and TypeScript. The helper
`failed(seat)` returns the member of the seat. On a seat without the
member, the helper ends the call with a fault. A helper that acts on the
outcome then stops, instead of acting on an outcome that the seat did not
state.

Rust, Java and Kotlin give the member a default on the seat. The default
ends the call with the same fault. A helper in these languages reads the
member on any seat.

```go
// Failed reports whether the test of tb has failed. It calls the method
// Failed of tb, or of the first seat of the chain of tb that has the method,
// as [TB] states. *testing.T, *testing.B, *testing.F, a *prop.Case, a
// [Recorder], and the seats of the bodies of [Rejects] and [Eventually]
// have the method. A chain without the method ends the call with a fault.
func Failed(tb TB) bool
```

```python
def failed(seat: Seat) -> bool:
    """Return whether the test, the case or the body of seat has failed.

    The call ends with a fault on a seat without the property failed.
    """
```

```typescript
interface Seat {
  /** True once the test, the case or the body of the seat has failed. */
  readonly failed?: boolean;
}

/** Returns whether the test of seat has failed, and ends the call with a fault on a seat without the member. */
export function failed(seat: Seat): boolean;
```

```rust
pub trait Seat: Send + Sync {
    /// Returns whether the test, the case or the body of the seat has failed.
    /// The default ends the call with a fault.
    fn failed(&self) -> bool { ... }
}
```

```java
public interface Seat {
  /// Returns whether the test, the case or the body of the seat has failed.
  /// The default ends the call with a fault, as Check.fault ends one.
  default boolean failed() { ... }
}
```

### The cleanup of a Rust seat

A Rust cleanup is a boxed closure with the lifetime `'static`, so it cannot
borrow the seat that runs it. rustc 1.99.1 refuses a cleanup that calls
`failed` on the seat of its helper. So each Rust seat passes itself to each
of its cleanups:

```rust
pub trait Seat: Send + Sync {
    /// Registers `f` to run when the test, the case or the body of the seat
    /// ends. The seat passes itself to `f`, so `f` reads `failed` and calls
    /// assertions on the seat. The default ends the call with a fault, and `f`
    /// does not run.
    fn cleanup(&self, f: Box<dyn FnOnce(&dyn Seat) + Send>) { ... }
}
```

A Rust helper then keeps the data of a failed test as the Go helper does:

```rust
use dokimi_assert::Seat;
use std::path::PathBuf;

fn scratch(seat: &dyn Seat) -> PathBuf {
    let dir = std::env::temp_dir().join("store-scratch");
    std::fs::create_dir_all(&dir).expect("the scratch directory exists");
    let kept = dir.clone();
    seat.cleanup(Box::new(move |seat| {
        if !seat.failed() {
            let _ = std::fs::remove_dir_all(&kept);
        }
    }));
    dir
}
```

In definition 16.5.0 the closure of a Rust cleanup takes no argument. The
Rust library has no release that contains the member, so the change breaks
no released caller.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `seat.failed` | `Failed` | `failed` | `failed` | `failed` | `failed` | `failed` |
| `failed` | `Failed` | `failed` | | `failed` | | |

- Go names the member `Failed`, which `testing.TB` declares. The helper
  finds the method along the seats that `Unwrap` returns, as `Skipf` finds
  `Skipf`.
- Python and TypeScript have the member as an optional read-only property
  of the seat, because their recorders state `failed` as a property.
- Rust, Java and Kotlin give the member a default on the seat, and a
  helper reads the member on any seat. These languages decline the helper
  `failed`, as they decline `cleanup`.
- `recorder-seat.failed` keeps its names. The recorder's member is its
  `seat.failed`.

### The rule in `conformance.md`

The Fixed tier gains a rule after the rule of how a helper skips its test:

> **How a seat reports that it failed.** The member `seat.failed` is true
> once its seat has received a failure, or a fault that ended a call. A
> noted fault does not count. The seat of a test, a case and the
> seat of a body record an error or a panic that ended their body before
> they run their cleanups. A cleanup then reads that end. A language whose
> test runner does not let its seat read that end declares a limit on the
> member.
> The helper `failed`
> returns the member, and ends the call with a fault on a seat without it.
> Languages that give the member a default on every seat decline the
> helper. The outcome of a test is an input of a test, so no vector pins
> the member. Each language checks it in its own tests.

### Conformance

The outcome of a test is an input of a test, so no vector pins the member.
Each language tests these behaviours in its own tests:

- The member is false before a failure. It is true after a failure through
  `fail`, `record` or `report`, and after a fault that ended a call.
- A noted fault leaves the member false.
- A cleanup of a test, a case, a check and an attempt whose body raised an
  error or panicked reads true. In Go, a cleanup of a test without parallel
  subtests that panicked reads false, as the overlay declares.
- In Go, the member of a test is true after a subtest failed.
- The helper ends the call with a fault on a seat without the member.
- In Go, the helper finds the member along the seats that `Unwrap` returns.
- In Rust, a cleanup reads the member of the seat that it receives.

### Version

The member and the helper add names. They do not change the meaning of an
existing name. Definition 16.6.0 adds the two rows, and every overlay
extends 16.6.0. The overlays of Rust, Java and Kotlin decline the helper,
and the overlay of Go limits the member. The Rust form of `seat.cleanup`
passes the seat to its function, and its name does not change.

## Alternatives considered

### A. `Failed` in Go's `TB`

`assert.TB` would declare `Failed() bool`, which `*testing.T`, `*testing.B`
and `*testing.F` already have.

**Why not:** every seat would have to implement it, also a seat that has
no test of its own, such as the seat of a generated check body. The
definition keeps `Cleanup` and `Skipf` out of `TB` for the same reason.

### B. False on a seat without the member

The helper would return false on a seat without the member.

**Why not:** the kit would drop the clone of a failed test on such a seat,
and the developer would not learn why. A false return hides that the seat
cannot state the outcome. The helpers `skip` and `cleanup` end the call
with a fault on such a seat for the same reason. A caller that needs an
answer on every seat reverses this verdict.

### C. The outcome as an argument of the cleanup

`cleanup` would pass the outcome to its function, as vitest's
`onTestFinished` passes the context of the test, whose result states it.

**Why not:** every language would gain a second form of `cleanup`. A
helper that reads the outcome outside a cleanup, such as one that writes a
note at the end of a check, still could not read it. The member serves both
callers.

### D. A cleanup that runs only on failure

A helper `cleanup-on-failure(seat, function)` would run its function only
when the test failed, as vitest's `onTestFailed` does.

**Why not:** the kit needs both branches. It drops the clone on a pass and
keeps it on a failure, so it would register two functions whose order the
seat fixes. The member is the one capability that both forms need.

## Drawbacks

- The seat gains a member in six languages, and Go, Python and TypeScript
  gain a helper. The naming table gains two rows.
- Each seat of a test records the end of its test before its cleanups. The
  plugin of Python marks its collector in its wrapper of the call phase,
  and the fixture of TypeScript reads the state of the task. The Rust
  collector reads `std::thread::panicking()`, and `SeatExtension` reads the
  exception of the test.
- In the body, the member does not count an error that has not ended the
  body yet. A helper that reads the member in the body sees only the
  failures and the faults that the seat has received.
- Go's member of a test also counts the failures of its subtests and the
  races that the race detector reports, so it can be true where no
  assertion failed.
- In Go, a `*prop.Case` and the seats of the bodies of `Rejects` and
  `Eventually` gain the method `Failed`.
- In Go, a cleanup of a test without parallel subtests that panicked reads
  false. A kit that keeps the data of a failed test then drops the data of
  such a test.
- Every Rust cleanup takes its seat as an argument. Each registration in
  Rust changes from `move || …` to `move |seat| …`, or to `move |_| …` for a
  cleanup that does not read its seat. The Rust library has six
  declarations of `cleanup` and about 36 registrations in its specs.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/38> |
| The member `skip` of the seat, and the helper `skip` | RFC-0040 and RFC-0058 |
| The member `cleanup` of the seat, and the helper `cleanup` | RFC-0047 |
| A fault that ends a call, and a noted fault | RFC-0033 |
| `Fail`, `Failed` and `doPanic` of `testing` | `src/testing/testing.go` in Go 1.27.4 |
| The order of `failTask` and the cleanup of the fixtures in `runTest` | `dist/chunk-artifact.js` of `@vitest/runner` 4.1.12 |
| No `beforeEach` or `afterEach` for a concurrent test of jest | assert-typescript RFC-0004: <https://github.com/dokimasia/assert-typescript/blob/main/docs/rfc/0004-the-standard-on-jest-expect.md> |
| `ExtensionContext.getExecutionException()` | `junit-jupiter-api` 6.1.3 |
