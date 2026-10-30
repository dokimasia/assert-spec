---
rfc: 0050
title: The result of a run
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-30
updated: 2026-10-30
discussion: https://github.com/dokimasia/assert-go/issues/84
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0050: The result of a run

## Summary

A call of `prop-for-all` returns nothing to its caller. A run that passes
does not report a record, and a run that fails reports its record to the
seat alone. A tool that runs many properties cannot read the result of
each run. This proposal adds the option `prop.on-result(f)` and the type
`run-result`:

- `f` receives the result of the run once, after the run ends and before
  the call reports its verdict.
- The result has one member for each of the eleven fields of the detail of
  the run.
- A run that a fault ends does not hand a result.
- The allocation ceilings of a run apply to a call without the option.

Definition 13.6.0 adds the option, the type and its eleven members.

## Motivation

dokimi's conform runs each property check of a suite through
`prop-for-all`. It writes one suite record for each application of the
suite, and the record has the fields `checks[].cases` and
`checks[].counterexample` for each property check. conform passes one seed
to every run through `seed`, so it knows the seed. It cannot read the other
two values:

- A run that passes does not report a record. Its call record contains the
  detail. A test's seat writes the call records into the artifact only
  when `DOKIMI_ASSERT_RECORD` is `1`, and the artifact is complete only
  after the process ends.
- A run that fails reports its record to the seat. An aborting seat ends
  the call at the failure: Go's `Fatalf` ends the goroutine of the test,
  and Python, Java and Kotlin raise. The test runner receives the failure
  as text.
- A recorder keeps the record of a failing run, and its test passes. conform
  runs each check for its verdict, so it cannot run the check on a
  recorder.

No language offers another way to read the result of a run, because the
definition has none.

### Prior art

- QuickCheck's `quickCheckWithResult` returns a `Result`. Each of its
  constructors has `numTests` and `numDiscarded`, and `Failure` adds
  `usedSeed` and `failingTestCase`.
- fast-check's `check` returns `RunDetails`, with `failed`, `numRuns`,
  `numSkips`, `seed` and `counterexample`. In version 3.23.2, its parameter
  `reporter` hands the `RunDetails` of a run of `assert` to a function in
  place of the reporter that throws on a failure.

Both return the counts, the seed and the counterexample of a run as values.
fast-check's `reporter` decides the verdict. This proposal leaves the
verdict with the assertion, because the definition fixes that an assertion
reports what it found to its seat.

## Detailed design

### The option

```text
prop.on-result(f)
```

`f` takes one argument, the result of the run. A call of a property with
the option calls `f` once:

- The call calls `f` after its run ends and before it reports its verdict.
  The notes of the failing case, the call record, the observation of the
  call, the failure and the skip all come after `f` returns.
- The call calls `f` on its own thread, whatever the number of workers.
- A run that a fault ends does not call `f`, and neither does a call that a
  fault ends before its run. The call ends with the fault as it does
  without the option.
- An error that `f` raises passes through the call. The call then does not
  report a verdict.
- The last `on-result` of a call applies, as the last `around` does.
- `f` must not change the result. The result contains the values of the
  record that the call reports after `f` returns.

The option applies to each call that runs the cases of a property:

- a call of `prop-for-all`
- a call of a property form
- each call that the fuzz bridge makes, such as the call of an input

A null `f` is a misuse, and each language refuses it where it builds the
option. Go panics.

### The result

`run-result` has one member for each field of the detail of a run:

| Member | Value |
|---|---|
| `outcome` | How the run ended |
| `cases` | The number of valid cases |
| `rejected` | The number of rejected cases |
| `seed` | The seed of the run |
| `counterexample` | The entries of the failing case: its draws and its steps, in request order |
| `failure` | The failure record of the failing case |
| `choices` | The replay token of the failing case |
| `others` | The other failures of a counterexample |
| `divergence` | What differed first in a flaky run |
| `coverage` | The requirement that the run refuted or left unmet |
| `reason` | The reason of a skipped run |

- Each member has the value of the field of its name in the detail of the
  run, as `recording.md` defines the detail for every outcome. A member that
  the outcome does not use is null, as in the detail.
- The result of a passing run has its outcome, its counts and its seed.
  Every other member is null.
- The seed has the type that `prop.seed` takes, so a caller can pass the
  seed of a result to `prop.seed`. The detail of a call record has the seed
  as a decimal string, because a JSON number cannot keep 64 bits in every
  language.
- The other members have the types that the language gives their fields in
  the detail of a failure record.

### The cost

- The allocation ceilings of a run apply to a call without the option.
- A call with the option builds the result from the values that the run
  computed for its detail.

### The languages

```go
// OnResult hands the result of the run to f, after the run ends and before
// the call reports its verdict. A run that a fault ends does not hand a
// result. It panics for a nil f.
func OnResult(f func(Result)) Option

// Result is the result of one run of a property: the fields of the detail
// of the run, as Go values.
type Result struct {
	Outcome        Outcome
	Cases          int
	Rejected       int
	Seed           uint64
	Counterexample []Entry
	Failure        *assert.Failure
	Choices        string
	Others         []Other
	Divergence     *Divergence
	Coverage       *Shortfall
	Reason         string
}
```

Go has no null string, so a `Result` has the empty string for a token and
for a reason that the outcome does not use.

```python
def on_result(f: Callable[[Result], None]) -> Option:
    """Hand the result of the run to f, after the run ends and before the
    call reports its verdict."""
```

```rust
/// Hands the result of the run to `f`, after the run ends and before the
/// call reports its verdict.
pub fn on_result<T>(f: impl Fn(&RunResult) + Send + Sync + 'static) -> Options<T>
```

```typescript
/** Hands the result of the run to f, after the run ends and before the call reports its verdict. */
export function onResult(f: (result: Result) => void): Option;
```

```java
public static Option onResult(Consumer<RunResult> f);
```

Go, Python and TypeScript name the type `Result`. Rust, Java and Kotlin name
it `RunResult`:

- Rust's prelude declares `Result`. A glob import of a module that declares
  a type of that name hides the prelude's type.
- Kotlin imports `kotlin.Result` into every file. An import of a type of
  that name hides it in the file.
- Java shares the names of Kotlin.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `prop.on-result` | `prop.OnResult` | `prop.on_result` | `prop::on_result` | `prop.onResult` | `Prop.onResult` | `Prop.onResult` |
| `run-result` | `prop.Result` | `prop.Result` | `prop::RunResult` | `prop.Result` | `RunResult` | `RunResult` |
| `run-result.outcome` | `Outcome` | `outcome` | `outcome` | `outcome` | `outcome` | `outcome` |
| `run-result.cases` | `Cases` | `cases` | `cases` | `cases` | `cases` | `cases` |
| `run-result.rejected` | `Rejected` | `rejected` | `rejected` | `rejected` | `rejected` | `rejected` |
| `run-result.seed` | `Seed` | `seed` | `seed` | `seed` | `seed` | `seed` |
| `run-result.counterexample` | `Counterexample` | `counterexample` | `counterexample` | `counterexample` | `counterexample` | `counterexample` |
| `run-result.failure` | `Failure` | `failure` | `failure` | `failure` | `failure` | `failure` |
| `run-result.choices` | `Choices` | `choices` | `choices` | `choices` | `choices` | `choices` |
| `run-result.others` | `Others` | `others` | `others` | `others` | `others` | `others` |
| `run-result.divergence` | `Divergence` | `divergence` | `divergence` | `divergence` | `divergence` | `divergence` |
| `run-result.coverage` | `Coverage` | `coverage` | `coverage` | `coverage` | `coverage` | `coverage` |
| `run-result.reason` | `Reason` | `reason` | `reason` | `reason` | `reason` | `reason` |

### Conformance

A function that a test passes is an input of the test, so no vector pins
the option. Each language tests these behaviours in its own tests:

- A passing run hands a result with its outcome, its counts and its seed,
  and with null in every other member.
- A failing run hands a result whose members equal the fields of the detail
  of its failure record.
- `f` returns before an aborting seat receives the failure.
- A skipped run hands a result with the reason of the skip.
- A run that a fault ends does not hand a result.
- A run on four workers calls `f` once, on the thread of the call.
- A property form and a call of the fuzz bridge hand the result of their
  runs.
- The last `on-result` of a call applies.
- A null `f` is refused.

### Version

The option, the type and its members add names and change the meaning of
no name. Definition 13.6.0 adds the thirteen rows, and every overlay
extends 13.6.0.

## Alternatives considered

### A. A result that the call returns

`prop-for-all` would return the result of its run.

**Why not:** an aborting seat ends the call at the failure, so a failing
run would return nothing in Go, Python, Java and Kotlin. A tool needs the
counterexample of exactly that run. A return value would also change the
signature of `prop-for-all` and of every form in every language.

### B. A member of the seat

A seat would gain a member `observe-run(result)`, as it has
`observe-call`.

**Why not:** the member would receive the result of each property that runs
on the seat, also of a property in the body of another property or of
`rejects`. A tool runs one property for each check and needs the result of
that call. Each language would gain a member of the seat, and Go, Java and
Kotlin would gain an interface.

### C. The detail in the observed call

The `assertion-call` that an observer receives would gain the verdict and
the detail.

**Why not:** we left the verdict out of the call in RFC-0044, because a
seat learns it from `report` and `report-fault`. An observer would also
receive the detail of every call in every case of a property, and each
call on an observer would allocate for it.

### D. The call records of a recorder

A tool would run each property on a recorder and decode its call record.

**Why not:** a recorder keeps the record of a failing run, and the test of
the check passes. The call record is JSON, so a tool would decode an
encoding to learn two numbers. We rejected the same decoding in
alternative A of RFC-0044.

### E. The detail as a map

`f` would receive the detail as a failure record contains it: a map from
the name of each field to its value.

**Why not:** a caller in Go, Rust, Java, Kotlin and TypeScript would cast
each value of the map to its type. Each language has the types of the
values, and a member of the result has its type without a cast.

## Drawbacks

- Every language gains an option and a type of eleven members, and the
  naming table gains thirteen rows.
- The result shares its values with the record of the call. A function
  that changes them changes the record that the seat receives.
- Rust, Java and Kotlin spell the type `RunResult`, and Go, Python and
  TypeScript spell it `Result`.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/84> |
| The detail of a run on every outcome | RFC-0016 and `spec/recording.md` |
| The option `seed` and the seed of a run | RFC-0010, RFC-0049, and `prop.seed` in `spec/naming.yaml` |
| The observer of a call | RFC-0044 |
| QuickCheck's `quickCheckWithResult` | <https://hackage.haskell.org/package/QuickCheck/docs/Test-QuickCheck.html> |
| fast-check's `RunDetails` | <https://github.com/dubzzz/fast-check/blob/main/packages/fast-check/src/check/runner/reporter/RunDetails.ts> |
| fast-check's `reporter` in version 3.23.2 | <https://github.com/dubzzz/fast-check/blob/v3.23.2/packages/fast-check/src/check/runner/configuration/Parameters.ts> |
