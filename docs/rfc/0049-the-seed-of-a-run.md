---
rfc: 0049
title: The seed of a run
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-29
updated: 2026-10-29
discussion: https://github.com/dokimasia/assert-go/issues/82
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0049: The seed of a run

## Summary

A run of a property that states no `seed` takes its seed from the
environment: the variable `DOKIMI_ASSERT_PROP_SEED`, the contract in a
mutation run or under the profile `ci`, or a random draw. Each library
makes that choice inside its property engine. A tool that runs many
properties under one seed cannot make the same choice. This proposal adds
the helper `prop.run-seed(seat, contract)`. It returns the seed that a run
of `contract` takes without `seed`, in a run that is not hermetic.

Definition 13.5.0 adds the helper.

## Motivation

dokimi's conform runs many properties in one application of a suite, and
the suite record of the application states one seed. A rerun with that
seed has to repeat every property run of the application, so conform
passes one seed to each run through `seed`. conform cannot choose that
seed as prop chooses it:

- It cannot tell that it runs in a process of a mutation run. assert-go
  reads `DOKIMI_MUTATE_MUTANT` in internal code.
- It would read `DOKIMI_ASSERT_PROP_SEED` and `DOKIMI_ASSERT_PROP_PROFILE`
  itself, and repeat the rules of each and the faults of a malformed
  value.

A copy of the rules would drift from prop. A mutation run of a suite would
then draw random seeds for its property runs, and the verdict of a mutant
would change between two runs of one tree.

## Detailed design

```text
prop.run-seed(seat, contract) -> seed
```

The helper returns the first seed of this list. The list is the list of a
run that is not hermetic, without the seed that `seed` states:

1. The seed that `DOKIMI_ASSERT_PROP_SEED` states.
2. The seed derived from the contract, in a mutation run and under the
   profile `ci`.
3. A random seed, a new one for each call.

- The helper reads the environment at each call, as a run does.
- A malformed `DOKIMI_ASSERT_PROP_SEED`, and a profile that the definition
  does not name, end the call with the fault that a run reports for the
  value. The operation of the fault is the helper, and the helper returns
  0.
- The helper does not write a call record, because it is not an
  assertion.

A caller that passes the result to `seed` in each of its runs gives every
run the seed that its first run would have taken. The record of each run
states that seed, so the caller can report it in a record of its own.

```go
// RunSeed returns the seed that a run of contract takes without the option
// Seed: the seed that DOKIMI_ASSERT_PROP_SEED states, the seed that a
// mutation run and the profile ci derive from the contract, or a random
// seed. A malformed variable ends the call with a fault, and RunSeed
// returns 0.
func RunSeed(tb assert.TB, contract string) uint64
```

```python
def run_seed(seat: Seat, contract: str) -> int:
    """Return the seed that a run of contract takes without the option seed."""
```

```rust
/// Returns the seed that a run of `contract` takes without the option
/// `seed`.
pub fn run_seed(seat: &dyn Seat, contract: &str) -> u64
```

```typescript
/** Returns the seed that a run of contract takes without the option seed. */
export function runSeed(seat: Seat, contract: string): bigint;
```

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `prop.run-seed` | `prop.RunSeed` | `prop.run_seed` | `prop::run_seed` | `prop.runSeed` | `Prop.runSeed` | `Prop.runSeed` |

### Conformance

The environment is an input of a test, so no vector pins the helper. Each
language tests these behaviours in its own tests:

- The helper returns the seed of `DOKIMI_ASSERT_PROP_SEED`.
- Under the profile `ci`, and in a process of a mutation run, it returns
  the seed derived from the contract.
- Without either, two calls can return different seeds.
- A malformed seed and an unknown profile end the call with a fault of
  the helper.
- A run under `seed(run-seed(contract))` states the same seed as a run of
  `contract` without `seed`, under `DOKIMI_ASSERT_PROP_SEED` and under the
  profile `ci`.

### Version

The helper adds a name and changes the meaning of no name. Definition
13.5.0 adds the row, and every overlay extends 13.5.0.

## Alternatives considered

### A. A helper without a seat

The helper would take the contract alone, as the request in the
discussion proposes.

**Why not:** a malformed variable is a fault, and every helper of these
libraries that refuses its environment ends its call through the seat. A
helper without a seat would have to panic or return an error, unlike the
property runs that report the same faults.

### B. A seed of the suite as an option of prop

A run would take the option `suite-seed`, and every run under one value of
the option would share one seed.

**Why not:** the tool still has to choose the value, and the choice is
the rule that this helper exports. The option would add a second way to
state a seed.

### C. Readers of the variables

The libraries would export a reader of each variable and of the
mutation run.

**Why not:** a tool would still repeat the order of the rules, which is
what drifts.

## Drawbacks

- One helper in six languages, and one row in the naming table.
- Without a seed in the environment, each call returns a new random seed.
  A caller that calls it once for each run gets a different seed for each
  run, as runs without `seed` do.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/82> |
| The seed of a run, the profiles and a mutation run | RFC-0010 |
| The option `seed` | `prop.seed` in `spec/naming.yaml` |
