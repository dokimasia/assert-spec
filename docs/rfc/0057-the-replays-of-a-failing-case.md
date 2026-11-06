---
rfc: 0057
title: The replays of a failing case
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-05
updated: 2026-11-05
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0057: The replays of a failing case

## Summary

A run replays a failing case once before it shrinks the case. The run shrinks a failure that the replay reproduces, and ends as flaky for a failure that the replay does not reproduce. The verdict of one replay is the same for a failure that reproduces in 9 runs of 10 and for one that reproduces in 1 run of 10. This proposal adds the option `prop.replays(n)` and two fields of the detail of a run:

- A run replays a failing case `n` times before it shrinks the case, once by default.
- The run shrinks the case when one or more replays reproduce the failure, and ends as flaky when none does.
- The detail states `replays`, the number of replays, and `reproduced`, how many of them reproduced the failure.

Definition 16.0.0 adds the option, the two fields, two members of the result of a run, a named body and four vectors.

## Motivation

### One replay is one sample

A body whose subject runs on threads that the platform schedules fails under some interleavings and passes under others. Examples are a subject that starts threads of its own, a component whose goroutines run in a `testing/synctest` bubble, and code on an executor of the platform. For a failure that reproduces in a share `p` of the runs, one replay shrinks the case with probability `p`. The run ends as flaky with probability `1 − p`.

The definition measured this cost for `steps.repeat`, which repeats every case of a concurrent section on real threads. On a Go probe over goroutines, a `repeat` of 1 ended 34 of 200 failing seeds as flaky, against 2 at a `repeat` of 4 and none at 16. A body outside such a section has no count of replays at all.

### The detail does not state how often a failure reproduces

A counterexample states that its one replay reproduced the failure, and a flaky outcome states the difference of that replay. Neither states a share. So a failure that reproduces in 1 run of 10 and a failure that reproduces in 9 runs of 10 have the same detail. A person who reads the record does not learn how often a run of its replay token shows the failure.

### Prior art

- `steps.repeat` runs a case of a concurrent section on real threads up to `repeat` times, 4 by default, and fails it when any run fails. A case that fails once and then passes its `repeat` replays ends as flaky.
- Maven Surefire's `rerunFailingTestsCount` runs a failing test again until it passes or the reruns are used up. A test that passes on a rerun counts as flaky, and the build succeeds.
- Hypothesis replays a failing example, and raises `FlakyFailure` when the replay passes.

Surefire runs tests that a team expects to pass, so it reads one passing rerun as success. A property engine searches for a defect. So this proposal reads a failure that one replay reproduces as a counterexample, as `repeat` does.

## Detailed design

### The option

```text
prop.replays(n)
```

A run that replays a failing case before it shrinks the case runs `n` replays:

- Each replay runs the body on the choices of the case, outside the case tree, as the replay before shrinking runs today. The replays run one after the other.
- Each replay compares the bounds of each request, then each observed fingerprint, then the verdict with those of the failing case. A replay reproduces the failure when its requests and its fingerprints are the same, and it fails with the identity of the failure.
- A replay that passes, skips, is rejected or fails with another identity does not reproduce the failure.
- The run runs every replay, also after one of them has reproduced the failure, so the count states a share.
- When one or more replays reproduce the failure, the run shrinks the case, as it shrinks a case that its one replay reproduced. When none does, the run ends as flaky, and its divergence is the difference of the first replay.
- A replay that ends with a fault ends the run with that fault, as a case in any phase does.

The option itself has three rules:

- `n` is a positive int. Each language refuses a count below 1 where it builds the option, and Go panics.
- The last `replays` of a call applies.
- A run without the option replays a failing case once, as it does today.

### Which runs replay

A run replays a failing case wherever it replays one today: in a run of the phases of `prop-for-all` or of a property form, its stored cases included, and in a campaign. These runs report their failing case without a replay, as they do today, so they run none:

- a run with a shrink budget of 0
- a run of a replay token
- a run whose failing case is an example of values, which has no choices

A run on more workers can run the replays at once. It reports what a run on one worker reports, and it records the calls of the replays in the order of a run on one worker. Each shrink candidate runs once, as it does today.

### The detail

The detail of a run gains two fields, after `reason`:

| Field | Value |
|---|---|
| `replays` | The number of replays of the failing case before the shrink. Null for a run that replayed no failing case |
| `reproduced` | How many of those replays reproduced the failure, from 0 to `replays`. Null where `replays` is null |

- A counterexample that the run replayed states a `reproduced` from 1 to `replays`.
- A flaky outcome that the replays ended states a `reproduced` of 0.
- Every other outcome states null for both fields. So does a flaky outcome that a divergence of the body ended, and a flaky outcome that a replay under `prop.confirm` ended.
- The fields state the replays of the failure that the run reports as its counterexample. An entry of `others` states no replays.

A counterexample that 3 of its 10 replays reproduced ends its detail with `"reason": null, "replays": 10, "reproduced": 3`.

The result of a run gains the members `replays` and `reproduced`, one for each new field. The call records of each replay have the phase `replay`, and the calls of the replays are numbered as the calls of every other run of the body.

### The languages

```go
// Replays makes a run replay a failing case n times before it shrinks the
// case. The run shrinks the case when one or more replays reproduce the
// failure, and ends as Flaky when none does. It panics for n below 1.
func Replays(n int) Option
```

```go
type Result struct {
	// The eleven fields of the detail of a run are unchanged.

	// Replays is the number of replays of the failing case before the
	// shrink, and 0 for a run that replayed no failing case.
	Replays int
	// Reproduced is how many of the replays reproduced the failure.
	Reproduced int
}
```

Go states a count that the outcome does not use as 0. A run that replays a failing case states at least 1 replay, so the 0 of `Replays` is not a count of replays.

```python
def replays(n: int) -> Option:
    """Make a run replay a failing case n times before it shrinks the case."""
```

```rust
/// Makes a run replay a failing case `n` times before it shrinks the case.
pub fn replays<T>(n: usize) -> Options<T>
```

```typescript
/** Makes a run replay a failing case n times before it shrinks the case. */
export function replays(n: number): Option;
```

```java
public static Option replays(int replays);
```

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `prop.replays` | `prop.Replays` | `prop.replays` | `prop::replays` | `prop.replays` | `Prop.replays` | `Prop.replays` |
| `run-result.replays` | `Replays` | `replays` | `replays` | `replays` | `replays` | `replays` |
| `run-result.reproduced` | `Reproduced` | `reproduced` | `reproduced` | `reproduced` | `reproduced` | `reproduced` |

That is three rows and 18 names.

### Conformance

The behaviour bodies gain the named body `fails-on-even-calls`. Its one draw is an integer in [0, 10^9]. It fails with the identity `even` when the value is above 1,000 and the call is even, counting the calls of the body from 1.

These vectors pin the option:

- `behaviour/shrinks-a-failure-that-one-replay-of-three-reproduces`: the body `fails-on-even-calls` under `replays` 3. The failing case is an even call, so its replays are an odd, an even and an odd call. The run shrinks the case, and states 3 replays and 1 reproduction.
- `behaviour/reports-a-failure-that-no-replay-of-three-reproduces`: the body `fails-once` under `replays` 3. The run is flaky, with 3 replays, 0 reproductions and the divergence of the first replay.
- `behaviour/counts-a-reproduction-in-each-of-three-replays`: a body that fails above 1,000 under `replays` 3. The run states 3 replays and 3 reproductions.
- `recording/records-each-replay-before-the-shrink`: a body that fails above 1,000 under `replays` 2. The calls of the two replays have the phase `replay`, and the calls of the shrink follow them.

Each other vector that pins the detail of a run gains the two fields, and `make render` writes them. A failing run states 1 replay and 1 reproduction, and `fails-once` and `fails-then-skips` state 1 replay and none.

A vector cannot state a campaign, a fault or a run on more workers with a body that differs between runs. Each language tests these behaviours in its own tests:

- A campaign replays each failure that it shrinks `n` times.
- A replay that ends with a fault ends the run with that fault.
- A run on more workers reports the counts of a run on one worker.
- The result of a run states the two counts.
- A count below 1 is refused.

### The cost

Each failing run costs `n − 1` more runs of the body than it does today. The shrink budget of 2,000 runs does not count the replays. It does not count the one replay of today either. A passing run is unchanged, and the allocation ceilings of a run apply to it.

### Version

`replays` and `reproduced` change the detail of a run. RFC-0010 makes a change to a detail field a major version. Definition 16.0.0 adds the option and the fields, and every overlay extends 16.0.0. A run without the option replays a failing case once, and every stored case and replay token replays unchanged.

## Alternatives considered

### A. Repeat each shrink candidate

The shrinker would run each candidate up to `n` times and accept it when any run fails with the identity, as `steps.repeat` runs every case of a section on real threads.

**Why not:** a candidate that does not fail then costs `n` runs, so the shrink budget of 2,000 runs tests about 2,000 / `n` such candidates. On the Go probe of `repeat`, a `repeat` of 4 took a median of 34 shrink runs against 15 at 1, and a `repeat` of 16 took 3.4 times the runs of 4. A subject whose failures must shrink to a minimal case runs under the task scheduler, whose replay is exact.

### B. Stop at the first replay that reproduces

The run would stop its replays once one of them reproduces the failure.

**Why not:** `reproduced` would then state that one replay reproduced the failure, and not the share of the replays that did. The share is what tells a failure of 1 run in 10 from a failure of 9 runs in 10.

### C. A threshold of reproductions

The run would shrink the case only when a stated number of replays reproduce the failure.

**Why not:** the threshold is a second parameter, and no measurement fixes its value. The detail states both counts, so a caller who wants a threshold reads them through the result of the run.

### D. More than one replay by default

A run would replay a failing case three times by default.

**Why not:** every failing run of a body that does not vary between runs would cost two more runs, and gain nothing. The default keeps every run as it is today.

### E. One field with an object

The detail would gain one field `replays` with an object of `runs` and `reproduced`.

**Why not:** the object needs a type in the result of a run with two members of its own, three rows in the naming table against two. The flat fields `replays` and `reproduced` state the same counts.

### F. A run option that repeats every case

A run option would repeat every case of a run, as `steps.repeat` repeats every case of a section on real threads.

**Why not:** each valid case would cost `n` runs. The replays of a failing case cost `n` runs once per failing run.

## Drawbacks

- Each failing run costs `n − 1` more runs of the body.
- A shrink candidate runs once, so a failure that reproduces in a share of the replays can shrink to a larger case than a failure that reproduces each time.
- The detail of every run gains two fields. Each vector that pins a detail changes, and each corpus runner reads the fields. The definition takes a major version.
- `replay` and `replays` are two options with similar names. `replay(token)` runs one recorded case, and `replays(n)` sets the replays of a failing case.
- The naming table grows by three rows and 18 names.

## References

| What | Where |
|---|---|
| The replay of a failing case before shrinking, the flaky outcome and the detail of a run | [RFC-0010](0010-properties-over-generated-inputs.md) |
| `steps.repeat`, and its measurements on goroutines | [RFC-0012](0012-machines-simulation-and-campaigns.md) |
| The result of a run | [RFC-0050](0050-the-result-of-a-run.md) |
| The replay of valid cases | [RFC-0052](0052-the-replay-of-valid-cases.md) |
| Maven Surefire, rerun failing tests | <https://maven.apache.org/surefire/maven-surefire-plugin/examples/rerun-failing-tests.html> |
| Hypothesis's flaky errors | <https://hypothesis.readthedocs.io/en/latest/reference/api.html> |
