---
rfc: 0052
title: The replay of valid cases
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-02
updated: 2026-11-02
discussion: https://github.com/dokimasia/assert-spec/issues/30
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0052: The replay of valid cases

## Summary

A run replays a case only when the case fails, and the engine compares the
fingerprints that a body observes in that replay alone. A body whose subject
decides outside the engine passes while its cases pass, so the engine does
not compare its fingerprints. This proposal adds the option
`prop.confirm(every)`:

- A run replays each valid case whose count is a multiple of `every`, right
  after the case, from its choices.
- The replay compares the requests, the fingerprints and the verdict, as the
  replay of a failing case does.
- A difference ends the run as flaky, with the replayed case as its
  counterexample.
- The call records of the replay have the new phase `confirm`.

Definition 14.0.0 adds the option, the phase and four vectors.

## Motivation

`case.observe` records a fingerprint of the subject. The engine compares the
fingerprints of a case when it replays a failing case before shrinking, and
at no other time. A property over a subject that iterates a map or reads the
wall clock passes as long as its cases pass. The difference shows only once
a case fails, and the failure then ends as flaky.

On assert-go v0.14.1, each run of the body of the issue observes the number
of runs so far, so no replay repeats a fingerprint:

```go
var runs uint64

func TestPassing(t *testing.T) {
	prop.ForAll(t, "each step observes the checksum of the run so far", func(c *prop.Case) {
		c.Draw(prop.Integer(0, 10), "step")
		runs++
		c.Observe(runs)
	}, prop.Seed(1))
}
```

`TestPassing` passes. The same body with a failure at its end ends as flaky,
with the divergence "the fingerprint at 0, recorded 12, replayed 13".

A deterministic simulation observes a checksum after each step, so that the
first step at which two runs differ fails. Without a replay of a valid case,
the simulation of a machine that iterates a map passes. A caller can run the
whole property twice with one seed, which doubles the cost of every case and
does not identify the case that differs.

### Prior art

- FoundationDB's TestHarness2 runs a share of its simulation tests a second
  time with the same seed and compares the two runs. The share is 5% by
  default, and `--unseed-check-ratio` sets it.
- AFL++ calibrates each new test case of its queue with 7 runs, the value of
  `CAL_CYCLES` in its `config.h`. It flags each edge of the coverage map whose
  count differs between the runs as unstable, and reports the share of
  stable edges as the stability.
- Hypothesis replays a failing example. It raises `FlakyFailure` for a
  failure that a later call does not repeat, and `FlakyStrategyDefinition`
  for generation that differs.

The definition's replay of a failing case is the mechanism of Hypothesis.
FoundationDB and AFL++ also run inputs that pass a second time. This
proposal replays a valid case from its choices, so a difference has the
position, the label and the step of a divergence.

## Detailed design

### The option

```text
prop.confirm(every)
```

A run counts its valid cases from 1, and replays each valid case whose count
is a multiple of `every`:

- The replay runs right after the case, before the next case runs.
- It runs the body on the choices of the case, outside the case tree, as the
  replay of a failing case runs.
- It compares the bounds of each request first, then each observed
  fingerprint, then the verdict. A replay that fails differs from a valid
  case. A replay that is rejected or skips does not fail, so its verdict does
  not differ.
- A difference ends the run as flaky. The detail of the run has the
  replayed case as its counterexample, a null failure, null choices and the
  difference as its divergence.
- A replay that ends with a fault ends the run with that fault, as a case in
  any phase does.
- The replay is no case of the run. It counts as neither a valid nor a
  rejected case.
- An example of values has no choices, so a run does not replay it. It
  counts as a valid case.

The option itself has three rules:

- `every` is a positive int. Each language refuses a count below 1 where it
  builds the option, and Go panics.
- The last `confirm` of a call applies.
- A run without the option does not replay a valid case.

### Which runs count

Each call that runs the cases of a property counts its own valid cases from
1:

- a run of the phases of `prop-for-all` or of a property form, with its
  examples and its stored cases
- the run of a replay token, whose case is valid case 1 when it passes
- a campaign, over every case of its budget
- each call of the fuzz bridge, also the replay of the stored cases on the
  fuzz target

The case of a fuzz input is the only case of its call, so `every` above 1
replays no input. A caller who confirms each input states `confirm(1)`.

A run on more workers replays the cases that a run on one worker replays,
each right after its case in the order of a run on one worker.

### The phase

`recording.md` adds the phase `confirm`: the replay of a valid case under
`prop.confirm`, right after the case. The calls of the replay are numbered
as the calls of every other run of the body are.

### The cost

Each replay is one more run of the body, so `confirm(16)` adds a sixteenth to
the cost of the valid cases and `confirm(1)` doubles it. A run without the
option runs as before, and the allocation ceilings of a run apply to it.

We keep the option off by default, because a default replay would add its
cost to every run. Every recorded run would also gain the calls of the
replays.

### The languages

```go
// Confirm makes a run replay each valid case whose count is a multiple of
// every, right after the case, from its choices. A replay that requests
// other bounds, records another fingerprint or fails ends the run as Flaky.
// It panics for every below 1.
func Confirm(every int) Option
```

```python
def confirm(every: int) -> Option:
    """Make a run replay each valid case whose count is a multiple of every,
    right after the case, from its choices."""
```

```rust
/// Makes a run replay each valid case whose count is a multiple of `every`,
/// right after the case, from its choices.
pub fn confirm<T>(every: usize) -> Options<T>
```

```typescript
/** Makes a run replay each valid case whose count is a multiple of every, right after the case, from its choices. */
export function confirm(every: number): Option;
```

```java
public static Option confirm(int every);
```

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `prop.confirm` | `prop.Confirm` | `prop.confirm` | `prop::confirm` | `prop.confirm` | `Prop.confirm` | `Prop.confirm` |

### Conformance

The body `observes-its-calls` draws an integer in [0, 9] and observes the
number of its calls so far. These vectors pin the option:

- `behaviour/reports-a-valid-case-whose-replay-observes-another-fingerprint`:
  under `confirm` 1, the replay of the simplest case observes 2 where the
  case observed 1. The run is flaky after one valid case, with the divergence
  of the fingerprint at 0.
- `behaviour/passes-the-same-body-without-confirm`: without the option, the
  same body passes its ten inputs.
- `recording/records-the-replay-of-every-fifth-valid-case`: ten cases under
  `confirm` 5. The fifth and the tenth valid case are runs 6 and 13, and
  their replays are runs 7 and 14 with the phase `confirm`.
- `recording/records-the-replay-of-a-valid-case-that-observes-another-fingerprint`:
  the body `observes-its-calls` under `confirm` 1. The call of the simplest
  case and the call of its replay pass, and the property fails.

A vector cannot state an example of values, a campaign, a fuzz input or a
fault. Each language tests these behaviours in its own tests:

- A valid example of values is not replayed.
- The case of a replay token is replayed under `confirm(1)`.
- A campaign replays each valid case whose count is a multiple of `every`.
- A fuzz input is replayed under `confirm(1)` and not under `confirm(2)`.
- A replay that ends with a fault ends the run with that fault.
- A count below 1 is refused.

### Version

The option and the phase add names, and a run without the option is
unchanged. Definition 14.0.0 adds them beside the memo rule of RFC-0051, and
every overlay extends 14.0.0.

## Alternatives considered

### A. Replay every valid case

Every run would replay each valid case, as `confirm(1)` does.

**Why not:** it doubles the cost of every valid case of every run. The call
records of every recorded run would gain a replay of each case, and every
recording vector would change.

### B. Run the whole property twice

A run would run its phases a second time with the same seed and compare the
two runs, as FoundationDB compares two runs of a simulation.

**Why not:** it doubles the cost of every run, as the issue states. A
difference between two runs does not identify a case, so the run could not
state the request or the fingerprint that differs, nor its label and its
step.

### C. Replay a random share of the valid cases

A run would replay each valid case with a probability, as FoundationDB
checks 5% of its tests.

**Why not:** the draw would need a stream of the seed of its own. The count
replays the same cases in every language, so the recording vectors pin the
calls of each replay without a new stream.

### D. Replay the cases that join a campaign's pool

A campaign would replay each case that it adds to its pool, as AFL++
calibrates each new entry of its queue.

**Why not:** a run of the phases has no pool, and a fuzz input joins none.
The count applies to every call that runs cases.

## Drawbacks

- Each replay costs one more run of the body.
- A replay compares the requests, the fingerprints and the verdict alone. A
  body that does not observe a fingerprint passes its replay unless its
  requests or its verdict change.
- A seed replays the same positions in every run. A difference that shows
  in other cases needs a smaller `every`.
- Under the fuzz bridge, `every` above 1 replays no input.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/30> |
| The replay of a failing case before shrinking, and the flaky outcome | [RFC-0010](0010-properties-over-generated-inputs.md) |
| Campaigns | [RFC-0012](0012-machines-simulation-and-campaigns.md) |
| The phases of a recorded run | [RFC-0016](0016-recording-every-assertion-call.md) and `spec/recording.md` |
| FoundationDB's TestHarness2 and its determinism check | <https://github.com/apple/foundationdb/blob/main/contrib/TestHarness2/README.md> |
| AFL++'s calibration cycles | <https://github.com/AFLplusplus/AFLplusplus/blob/stable/include/config.h> |
| AFL++'s stability | <https://aflplus.plus/docs/faq/> |
| Hypothesis's flaky errors | <https://hypothesis.readthedocs.io/en/latest/reference/api.html> |
