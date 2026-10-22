---
rfc: 0036
title: Whether a run checks allocation ceilings
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-22
updated: 2026-10-22
discussion: https://github.com/dokimasia/assert-spec/issues/17
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0036: Whether a run checks allocation ceilings

## Summary

`max-allocs` passes without a count in a build that allocates differently
from the build that a project releases, such as a build with Go's race
detector. A
caller cannot tell such a pass from a pass of the count. This proposal adds
the helper `allocs-checked`, which reports whether the run checks
allocation ceilings, and the reason when it does not:

- `max-allocs`, `max-allocs-with-setup` and their forms keep their
  contracts.
- A language that declares `max-allocs` absent returns false with a reason
  of its own.

Definition 10.0.0 adds the helper.

## Motivation

### A pass without a count looks like a pass

The definition lets a language pass `max-allocs` without a count in a
build whose counts do not describe the code. Go checks no ceiling in four
kinds of build and run:

- a build with the race detector, msan or asan
- a build whose `-gcflags` turn off optimisation (`-N`) or inlining (`-l`)
- a test binary that a mutation run instrumented
- a run that writes the test log of `go test`

A test that proves a ceiling through `rejects` then gets a false result in
such a run. On assert-go v0.5.0 this test passes with
`go test -count=1` and fails with `go test -race -count=1`, because the
check of the ceiling passes on the implementation that it is meant to
reject:

```go
var sink []byte

func overBudget() { sink = make([]byte, 64) }

func TestCeilingRejectsOverBudget(t *testing.T) {
	assert.Rejects(t, "a ceiling of 0 rejects a function that allocates on every call", func(tb assert.TB) {
		assert.MaxAllocs(tb, overBudget, 0, "the function allocates nothing per call")
	})
}
```

A harness that falsifies generated checks reports such a ceiling as a
check that cannot fail. The harness also cannot report the ceiling as
unchecked, because it cannot tell a pass from a skipped count.

### A harness that repeats the rules of the library breaks silently

A harness today reads the build tags of the race detector, msan and asan,
the `-gcflags` in the build information, the variable
`DOKIMI_MUTATE_INSTRUMENTED` and the flag of the test log. Each rule that
the library adds later breaks that copy without a failure. assert-go
already decides the rule in one internal function, `AllocationsCounted`.

## Detailed design

### The helper

```text
allocs-checked() -> (checked, reason)
    Reports whether max-allocs, max-allocs-with-setup and their forms check
    their ceilings in this run. Where they do not, reason states the build
    or the run, such as "a build with the race detector". Where they do,
    reason is empty.
```

- The result is the same for every call in one process.
- A language whose benchmark contract checks `bench-max-allocs` and
  `bench-max-bytes` under the same rule states so in the documentation of
  the helper. Go does.
- A language that declares `max-allocs` absent returns false, with a reason
  that states why the language counts no allocations.

### The languages

| Language | Returns false when |
|---|---|
| Go | The build or the run is one of the four kinds that the overlay of Go names. The reason names it |
| Rust | The test binary does not install `CountingAllocator` as its global allocator |
| Python | Always: CPython counts no allocations |
| TypeScript | Always: V8 exposes no allocation count |
| Java, Kotlin | Always: the JVM counts bytes per thread and no allocations |

```go
// AllocsChecked reports whether MaxAllocs, MaxAllocsWithSetup, their
// property forms and the allocation ceilings of a benchmark contract check
// their ceilings in this run. Where they do not, reason states the build
// or the run, such as "a build with the race detector".
func AllocsChecked() (checked bool, reason string)
```

```rust
/// Returns `Ok(())` when `max_allocs`, `max_allocs_with_setup`, their
/// property forms and the allocation ceilings of a benchmark contract check
/// their ceilings in this test binary, and the reason otherwise.
///
/// # Errors
///
/// Returns the reason when the test binary does not install
/// `bench::CountingAllocator` as its global allocator.
pub fn allocs_checked() -> Result<(), &'static str>;
```

```python
def allocs_checked() -> tuple[bool, str]:
    """Return False and the reason: CPython counts no allocations."""
```

```typescript
/** Returns false and the reason: V8 does not expose an allocation count. */
export function allocsChecked(): { readonly checked: boolean; readonly reason: string };
```

Rust returns a `Result`, because a reason exists only where the run does
not check the ceilings. A harness in Go reads the helper before it
falsifies a check of a ceiling:

```go
if checked, reason := assert.AllocsChecked(); !checked {
	report.Unchecked(check.ID, reason)
	return
}
```

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `allocs-checked` | `AllocsChecked` | `allocs_checked` | `allocs_checked` | `allocsChecked` | `Check.allocsChecked` | `Check.allocsChecked` |

The helper is a member of the root namespace, beside the assertions.

### Conformance

A build is an input of a test, so no vector pins it. Each language tests
the helper in its own tests:

- In an ordinary build the helper returns true, and a rejection of an
  over-budget callable passes.
- Go tests the reason of each build and run in a child process, as its
  tests of `MaxAllocs` already do.
- A language that declares `max-allocs` absent returns false with its
  reason.

### Version

Adding a row to the naming table is a minor version change. Definition
10.0.0 adds `allocs-checked`, beside the major changes of the same release.

## Alternatives considered

### A. A skip in place of a pass

`max-allocs` would skip the test in a build that it does not check.

**Why not:** a skip stops every check after it in the caller's test. Go's
overlay states the rule: "The assertion passes rather than skipping,
because a skip would stop every check after it in the caller's test."

### B. A failure in place of a pass

`max-allocs` would fail in a build that it does not check.

**Why not:** every test with a ceiling would then fail under the race
detector, and a project that runs its tests under `-race` would turn its
ceilings off.

### C. A record that states the skipped count

The call record of `max-allocs` would state that the count did not run.

**Why not:** a harness reads the outcome of a check through `rejects` and
the records of the check, and a record of a passing call states no detail.
A harness calls the helper before it runs the check.

## Drawbacks

- The naming table gains one row, and each language gains one helper.
- A language that declares `max-allocs` absent provides a helper that always
  returns false.
- The reason is the language's own text, so a harness compares the boolean
  and shows the reason without parsing it.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/17> |
| A ceiling in a build that allocates differently | RFC-0009 |
| The builds and runs in which Go checks no ceiling | The limit on `max-allocs` in `overlays/go.json` |
| `AllocationsCounted` of assert-go | `internal/matcher/allocs.go` |
| Go's own tests of the race detector and of optimisation | `internal/race.Enabled` and `internal/testenv.OptimizationOff` in Go 1.27.3 |
