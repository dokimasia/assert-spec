---
rfc: 0058
title: A helper that skips its test
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-06
updated: 2026-11-06
discussion: https://github.com/dokimasia/assert-spec/issues/33
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0058: A helper that skips its test

## Summary

A Go helper that takes a seat cannot skip its test. `assert.TB` has
`Helper`, `Fatalf` and `Errorf`. `*testing.T`, `*testing.B`, `*testing.F`,
`*prop.Case` and the seat that `Rejects` hands its check have `Skipf`. The
library does not export a function that calls it. This proposal adds the
helper `skip(seat, reason)`:

- The helper skips the test through the member `seat.skip`, which RFC-0040
  states.
- On a seat without the member, the helper ends the call with a fault, as
  the helper `cleanup` ends one. The test does not skip.
- Go, Python, TypeScript, Java and Kotlin add the helper. Rust declines it,
  because its trait `Seat` gives the member a default.

Definition 16.1.0 adds the helper.

## Motivation

### A helper cannot skip its test

Helpers take the seat, so that one helper serves the seat of a test, a case
of a property, a recorder and the seat of a check under `rejects`. Some of
them need a capability of the environment, such as a server that a
developer starts before the tests. Where the environment lacks it, the
helper skips the test. In Go, `assert.TB` does not declare a member for the
skip.

A test kit of a service connects to the servers of a local compose stack.
CI does not start the stack, so the kit skips its test when the variables
of the stack are unset. One helper of the kit serves a test and the case of
a property, so it takes `assert.TB`. It does not compile with assert
v0.17.0:

```go
func stream(tb assert.TB) string {
	tb.Helper()
	addr := os.Getenv("HERMES_NATS_ADDR")
	if addr == "" {
		tb.Skipf("the local stack does not run: run make integration-go")
	}
	return addr
}
```

```text
vet: ./kit_test.go:17:6: tb.Skipf undefined (type assert.TB has no field or method Skipf)
```

The kit can take `testing.TB` instead. A case of a property then cannot
call the helper. The kit can also declare an interface that adds `Skipf` to
`assert.TB`. The compiler then refuses a recorder and a seat that wraps a
`*testing.T` without a `Skipf` of its own.

### The libraries look for the member in code of their own

Go finds `Skipf` along the seats that `Unwrap` returns where `rejects` and
a property pass a skip to their seat. conform's handle wraps a seat. It
repeats the search and ends the check with a fault on a seat without
`Skipf`. A helper outside the library cannot call the search.

## Detailed design

### The helper

`skip(seat, reason)` skips the test of the seat through its member
`seat.skip`. The rules of the member apply:

| Seat | The helper |
|---|---|
| The seat of a test of the platform | Skips the test with the reason, where the runner can skip a running test |
| A case | Ends the run of the property as skipped, as RFC-0038 states |
| The seat that `rejects` hands its check | Ends the check. `rejects` then ends its call as skipped when the check did not fail before the skip, as RFC-0040 states |
| A recorder and any other seat without the member | Ends the call with a fault. The test does not skip |

The helper does not return where the member ends the test, the case or the
check. On a seat without the member, the helper ends the call as the
language ends a call with a fault. The seat receives the fault as it
receives the fault of the helper `cleanup`. A test fails, and a recorder
keeps the fault among its faults.

A test of a helper reads the skip on a recorder through `rejects`. It runs
the helper as the check of `rejects` on the recorder. The call record of
`rejects` then states the verdict `skip` and the reason.

### The languages

```go
// Skipf formats its arguments as fmt.Sprintf does, and skips the test of tb
// with the text as the reason. It calls the method Skipf of tb, or of the
// first seat of the chain of tb that has the method, as [TB] states.
// *testing.T, *testing.B, *testing.F, a *prop.Case and the seat that
// [Rejects] hands its check have the method. A chain without the method ends
// the call with a fault, as [Fault] ends one, and the test does not skip.
func Skipf(tb TB, format string, args ...any)
```

```python
def skip(seat: Seat, reason: str) -> None:
    """Skip the test, the case or the check of seat with reason.

    The call ends with a fault on a seat without the member skip.
    """
```

```typescript
/** Skips the test, the case or the check of seat with reason, and ends the call with a fault on a seat without the member. */
export function skip(seat: Seat, reason: string): void;
```

```java
public final class Check {
  /// Skips the test, the case or the check of seat with reason, through the
  /// member skip of the interface Skipper. A seat that is not a Skipper ends
  /// the call with a fault, as Check.fault ends one.
  public static void skip(Seat seat, String reason) { ... }
}
```

Kotlin takes the same function. A Rust helper calls the member of the trait
`Seat` on any seat, and the default of the member writes the reason to the
standard error and returns.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `skip` | `Skipf` | `skip` | | `skip` | `Check.skip` | `Check.skip` |

- Go names the helper `Skipf` after the member of `testing.TB`, and the
  helper takes a format and its arguments as the member does. It finds the
  member along the seats that `Unwrap` returns, as `Cleanup` finds
  `Cleanup`.
- Python and TypeScript state the member as an optional member of the seat.
  Their helper ends the call with a fault on a seat without the member, as
  their helper `cleanup` does.
- Java and Kotlin state the member on the interface `Skipper`, as they state
  `report-fault` on `FaultReporter`. Their helper takes any seat, beside
  `Check.fault`.
- Rust gives the member a default on the trait `Seat`, so a helper calls the
  member on any seat. Rust declines the helper, as it declines `cleanup`.

### The rule in `conformance.md`

The Fixed tier gains a rule after the rule of how a seat skips its test:

> **How a helper skips its test.** The helper `skip` skips the test of its
> seat through `seat.skip`, as the rule of how a seat skips its test states.
> On a seat without the member it ends the call with a fault, and the test
> does not skip. Languages that give the member a default on every seat
> decline the helper. A skip is an input of a test, so no vector pins the
> helper. Each language checks it in its own tests.

### Conformance

A seat is an input of a test, so no vector pins the helper. Each language
tests these behaviours in its own tests:

- The helper skips the test of a seat that has the member, with the reason.
- On a case, the helper ends the run of the property as skipped.
- On the seat that `rejects` hands its check, the helper ends the check, and
  `rejects` ends its call as skipped.
- On a seat without the member, the helper ends the call with a fault.
- In Go, the helper finds the member along the seats that `Unwrap` returns.

### Version

The helper adds a name. It does not change the meaning of an existing name.
Definition 16.1.0 adds the row, and every overlay extends 16.1.0. The
overlay of Rust declines the helper.

## Alternatives considered

### A. `Skipf` in Go's TB

`assert.TB` would declare `Skipf(format string, args ...any)`, which
`*testing.T`, `*testing.B` and `*testing.F` already have.

**Why not:** every seat would have to implement it. A recorder does not run
a test that it could skip. RFC-0047 rejects `Cleanup` in `TB` for the same
reason.

### B. No effect on a seat without the member

The helper would return on a seat without the member, as `rejects` returns
when its own seat lacks the member.

**Why not:** a helper skips because the environment lacks a capability. If
the call returned, the code after it would run without that capability. The
test would then fail for a reason that it does not state, or pass although
it did not check anything. `rejects` can return on such a seat, because the
check has ended and the call record of `rejects` states the skip. The
helper does not write a call record.

### C. A recorder that skips

The recorder would state `seat.skip`, keep the reason and return it from a
new member.

**Why not:** a test of a helper already reads the skip and its reason on a
recorder, through the call record of `rejects`. The member would add a name
in six languages and no capability. RFC-0040 keeps the recorder without the
member, so that a call of `rejects` whose check skips returns on a
recorder.

## Drawbacks

- Go, Python, TypeScript, Java and Kotlin gain a helper. The naming table
  gains a row.
- A helper that skips on a seat without the member fails its test with a
  fault. Under jest the seats lack the member, so a TypeScript test whose
  helper skips fails there.
- In Go, the seat of an attempt of `eventually` has no `Skipf`. An attempt
  whose helper skips fails with the fault, and `eventually` tries again
  until its timeout.
- The helper and `rejects` treat a seat without the member in two ways. The
  helper ends the call with a fault. `rejects` returns, and its call record
  states the skip.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/33> |
| The member `skip` of the seat, and the skip of a check under `rejects` | RFC-0040 |
| The skip of a case | RFC-0038 |
| The helper `cleanup` | RFC-0047 |
| The helper `fault` | RFC-0033 |
| `Skipf` and `SkipNow` of `testing.TB`, which end the test through `runtime.Goexit` | `src/testing/testing.go` in Go 1.27.3 |
