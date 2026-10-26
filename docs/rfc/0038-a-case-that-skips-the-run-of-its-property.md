---
rfc: 0038
title: A case that skips the run of its property
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-24
updated: 2026-10-24
discussion: https://github.com/dokimasia/assert-spec/issues/20
supersedes: RFC-0010 and RFC-0016, in part
superseded-by: RFC-0040, in part
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0038: A case that skips the run of its property

## Summary

A body can reject one case with `assume`, and it has no way to skip the
run of its property. This proposal adds the member `skip` to the case:

- The case ends at the call and runs its cleanups. The run ends with a
  seventh outcome, `skipped`, and neither shrinks nor stores the case.
- The detail of the run gains the field `reason`, and the call record of
  the property states the verdict `skip`.
- The seat skips the test where its test runner can skip a running test.
- Once the run has found a failing case, a case that skips counts as a
  case that does not fail, so a skip cannot hide a counterexample.

Definition 11.0.0 adds the member, the outcome, the field and the verdict.

## Motivation

A property whose environment lacks a capability rejects every case, and
the run fails. On assert v0.6.0, a property whose every case calls
`c.Assume(false)` fails with the outcome `rejected` after 785 rejected
cases:

```go
prop.ForAll(tb, "a property whose environment lacks a capability", func(c *prop.Case) {
	_ = c.Draw(prop.String(), "key")
	c.Assume(false)
})
```

```text
"verdict":"fail", "detail":{"outcome":"rejected","cases":0,"rejected":785, …}
```

dokimi-go issue 6 asks for a call that lets the factory of a subject skip
a check that the file system of the run does not support. theke's file
system needs direct I/O for the suite of its direct files, and tmpfs and
btrfs refuse direct I/O with `errors.ErrUnsupported`. The spec of theke
skips that suite today with `t.Skip` on the outer test. Under a check
that runs once, the seat of the factory is a `*testing.T`, whose `Skipf`
skips the check. Under a property, the seat is the case, so the factory
can only reject each case, and the check fails.

The factory gets `errors.ErrUnsupported` when it creates the subject,
inside a case. An option of the run cannot express it, because an option
is fixed before the first case runs.

## Detailed design

### The member

```text
Case
  skip(reason)
      Ends the run of the property as skipped, with reason. The case ends
      at the call and runs its cleanups. Once the run has found a failing
      case, a case that skips ends as a case that does not fail.
```

`skip` ends the case with a signal of the engine, as `assume` does. A body
must let that signal pass. The cleanups of the case run after the body
ends, as they run for every other end of a case.

### The run

Until the run finds a failing case, a case that skips ends the run:

- The run starts no further case. A run on more than one worker takes the
  results in the order of a run on one, so it ends at the same case and
  discards the cases that workers started after it.
- The outcome is `skipped`. `cases` counts the valid cases before the
  case that skipped, and `rejected` the rejected ones. The case that
  skipped counts as neither.
- The run does not shrink, explain or store the case.
- A skip ends the run in every phase before the first failure: an
  example, a stored case, the simplest case, a random, prefix, edge or
  coverage case, and the case of a replay token.

Once the run has found a failing case, a skip does not end the run. A case
that skips then ends as a case that does not fail:

- The replay before shrinking that skips makes the run `flaky`. The
  divergence states the verdict, with null as the replayed side, as for a
  replay that passes.
- A shrink candidate that skips is not accepted.
- A filling of the explain phase that skips does not fail the way the
  failure fails.
- The boundary step of the explain phase that skips is not a value that
  passes, so the counterexample does not report a nearest passing value
  for it.

The shrinker moves each value towards its target. Without this rule, a
body that skips for one small value, such as an empty input, would turn a
failure that the run found into a skipped test.

A fuzz target runs one case for each input of the fuzzer. A case that
skips skips that input, through the seat of the target.

### The outcome and the detail

| `outcome` | When | What the record names |
|---|---|---|
| `skipped` | A case called `skip` before the run found a failing case | The reason |

A run that ends as `passed` passes the test, and one that ends as
`skipped` skips it where the runner can skip a running test. Every other
outcome fails the test.

The detail of a run gains one field:

| Field | Value |
|---|---|
| `reason` | For `skipped`: the reason that `skip` states. Null for every other outcome |

Every property form states the detail of a run, so every form gains the
field as well. A form runs its own body, which never skips, so its
`reason` is always null.

### The call record

The call record of a property whose run is `skipped` states the verdict
`skip` and the detail of the run:

| `verdict` | The call |
|---|---|
| `skip` | The run of a property ended at a case that called `skip`. The test skips where its runner can skip a running test |

The calls of the cases before the skip are recorded under the property,
as for every other run. The case that skipped records the calls it made
before the call of `skip`.

### The seat

The property sends the skip to its seat after it writes its call record:

- A seat whose test can skip skips the test with the reason.
- Any other seat, such as a recorder, keeps the call record, and the
  property returns.

| Language | What skips the test |
|---|---|
| Go | The first seat of the seat's chain with `Skipf(format string, args ...any)`, such as `*testing.T`, `*testing.B` and `*testing.F` |
| Python | `unittest.SkipTest` with the reason, which unittest and pytest both report as a skipped test |
| TypeScript | `skip(note)` of vitest's test context, through the seat of the fixture `test` |
| Java, Kotlin | `Assumptions.abort(reason)` of JUnit 5.9 or later |
| Rust | Nothing. libtest has no call that skips a running test |

Rust and a TypeScript test under jest record the verdict `skip`, and the
test passes. Each overlay states it as a limit of `case.skip`.

### The languages

```go
// Skipf formats its arguments as fmt.Sprintf does, and ends the run of the
// property as skipped with the message as its reason. The case ends at the
// call and runs its cleanups. Once the run has found a failing case, a case
// that skips ends as a case that does not fail.
func (c *Case) Skipf(format string, args ...any)
```

```python
def skip(self, reason: str) -> NoReturn:
    """End the run of the property as skipped, with reason.

    The case ends at the call and runs its cleanups. Once the run has found
    a failing case, a case that skips ends as a case that does not fail.
    """
```

```rust
/// Ends the run of the property as skipped, with `reason`. The case ends
/// at the call and runs its cleanups. Once the run has found a failing
/// case, a case that skips ends as a case that does not fail.
pub fn skip(&self, reason: &str) -> !;
```

```typescript
/**
 * Ends the run of the property as skipped, with reason. The case ends at
 * the call and runs its cleanups. Once the run has found a failing case, a
 * case that skips ends as a case that does not fail.
 */
skip(reason: string): never;
```

Java takes `void skip(String reason)`, and Kotlin `fun skip(reason: String):
Nothing`.

### Names

| Id | Go | Python | Rust | TypeScript | Java, Kotlin |
|---|---|---|---|---|---|
| `case.skip` | `Case.Skipf` | `Case.skip` | `Case::skip` | `Case.skip` | `Case.skip` |

A case is a seat, so Go names the member `Skipf`, the member of
`testing.TB` that skips a test with a formatted reason. Go names the
member `note` `Logf` for the same reason.

### Conformance

A body of the corpus states its skips as it states its failures:

```json
{ "draw": { "gen": "integer", "min": 0, "max": 1000 },
  "skips": [ { "reason": "unsupported",
               "when": { "kind": "equals", "value": { "type": "int", "value": 1000 } } } ],
  "fails": [ { "identity": "big", "when": { "kind": "at-least", "n": 101 } } ] }
```

The body classifies the case, then rejects it, then skips it with the
reason of the first `skips` entry whose predicate is true, then fails it,
in that order. The body `fails-then-skips` states what no predicate can. It draws an integer in [0, 10^9] and fails with the identity `once`
the first time it draws a value above 1,000. Every later call draws its
value and then skips with the reason `after`.

The vectors pin these behaviours:

| File | Vector | Pins |
|---|---|---|
| `behaviour.json` | A body that skips every case | The outcome `skipped` at the simplest case, with no valid case |
| `behaviour.json` | A body that skips one value | The valid cases before the skip |
| `behaviour.json` | A stored failure whose shrink tries a value that skips | The counterexample, which the skip does not replace |
| `behaviour.json` | `fails-then-skips` | The outcome `flaky`, with null as the replayed verdict |
| `recording.json` | A body that skips one value | The verdict `skip`, and the calls of the cases before the skip |

The validator requires a behaviour vector for every outcome, so
`skipped` needs one.

### Version

The outcome `skipped`, the field `reason` and the verdict `skip` change an
outcome, a detail field and the call record. RFC-0010 makes a change to an
outcome or a detail field a major version, so the definition moves to
11.0.0. Every overlay extends 11.0.0.

## Alternatives considered

### A. Reject every case

The body would call `assume(false)` in every case, as it can today.

**Why not:** the run ends as `rejected` and fails the test. A property that
never ran its body on a valid input has not passed, so a run that rejects
every case fails. A skip states that the run cannot check
the property in its environment. A rejection cannot state that.

### B. A skip that rejects the one case

`skip` would reject the case, as `T.Skip` of rapid v1.3.0 does. rapid
marks such a case invalid. It fails the test when it skips too many cases.

**Why not:** that is `assume` under a second name. A run whose environment
lacks a capability still fails.

### C. An option that skips the run

The run would take an option, such as a predicate that the run checks
before its first case.

**Why not:** the factory gets `errors.ErrUnsupported` when it creates the
subject, inside a case. An option is fixed before the first case runs, so
the body would have to probe the environment a second time outside every
case.

### D. A skip that ends the run in every phase

A skip would end the run whenever a case calls it, also during the shrink
of a failure. Hypothesis re-raises `unittest.SkipTest` and the skip
exception of pytest from every case, and stops its engine.

**Why not:** a shrinker moves each value towards its target. A body that
skips for an empty input would turn a failure that the run found into a
skipped test, and the record would hide the counterexample.

### E. The verdict pass with the outcome skipped

The property's call record would state the verdict `pass`. Its detail
would state the outcome `skipped`.

**Why not:** a reader that counts verdicts would count a skipped property
as a passing one. The verdict states what happened to the call, and a
skip is neither a pass nor a failure.

## Drawbacks

- The definition moves to a major version. Every implementation, and
  every reader of call records, handles a new verdict, a new outcome and
  a new detail field.
- Rust and a TypeScript test under jest cannot skip a running test. The
  test passes there, and the call record states the skip.
- A run that skips after valid cases checked fewer cases than it asked
  for. The detail states the count, and the test skips.
- A replay of a failure that skips reports `flaky` with null as the
  replayed verdict, the same as a replay that passes.
- The corpus gains a body key, a named body and five vectors, which every
  implementation builds natively.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/20> |
| The property and its outcomes | RFC-0010 |
| The call record and its verdicts | RFC-0016 |
| rapid v1.3.0, `T.Skip` and `T.SkipNow` | <https://github.com/flyingmutant/rapid/blob/v1.3.0/engine.go#L807-L894> |
| Hypothesis, the skip exceptions that stop its engine | <https://github.com/HypothesisWorks/hypothesis/blob/5057a16cd9/hypothesis/src/hypothesis/core.py#L775-L792> |
| vitest, `skip` of the test context | <https://vitest.dev/guide/test-context#skip> |
| JUnit 5.9, `Assumptions.abort` | <https://docs.junit.org/current/api/org.junit.jupiter.api/org/junit/jupiter/api/Assumptions.html> |
