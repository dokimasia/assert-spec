---
rfc: 0054
title: The mean number of steps of a concurrent section
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-03
updated: 2026-11-03
discussion: https://github.com/dokimasia/assert-spec/issues/31
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0054: The mean number of steps of a concurrent section

## Summary

`steps.concurrent` sets the most steps of a concurrent section, and no
option sets their mean. Each further step of a section is a continue flag
whose average is the average length of a collection of 0 to `concurrent`
elements. That average adds at most 5 to the minimum, so a section averages
5 steps for every maximum of 10 or more. This proposal adds the option
`steps.concurrent-mean`, which sets the average of the section's continue
flags as `steps.mean` sets it for the sequential steps.

## Motivation

A check that proves a race through a planted defect needs clients whose
steps overlap often. The issue measures a machine with one action and
three clients on assert-go at 48658cd. Over 106 cases the clients 1 and 2
took 379 steps under a maximum of 16, and 406 steps under maximums of 64
and 256. A larger maximum does not raise the mean.

dokimi's check of a causal history plants a read that returns the result
of another read that overlaps it. With 5 steps per section the defect
raced in 1 to 4 of 100 cases, and falsification proved it at 94 of 100
seeds. A pinned read and a causal read that race only where two reads of
different keys overlap were proven at 33 and 30 of 40 seeds.

A second call of `steps` in one case does not help. It runs a second
sequential part before a second section, and it mixes two runs in one
history.

## Detailed design

### The option

`steps.concurrent-mean` takes a count `n` of at least 0. Each free continue
flag of a concurrent section is a coin of `n` in `n + 1`, by the collection
rule with minimum 0, the maximum `concurrent` and the average `n`. A flag at the maximum still stops the section, so a mean above the
maximum continues on almost every flag up to the maximum.

A machine without the option keeps the average length of a collection of 0
to `concurrent` elements, which is `min(5, ceil(concurrent / 2))`. Every
run without the option takes the choices that it takes today. Every stored
counterexample and replay token of such a run replays unchanged.

A count below 0 is refused as the other counts of a machine are. A language
panics or throws at the option, with the message of its other options.

### The corpus

A machines vector states the option in its setup as `concurrent-mean`. The
vector `racy-counter/a-concurrent-mean-of-0-stops-each-section-before-the-race`
runs the racy counter with a mean of 0. Each flag outside the edge phase
stops the section, so no section takes the two increments that race, and
the run passes where the default run finds the race in its first case.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `steps.concurrent-mean` | `stateful.ConcurrentMean` | `stateful.concurrent_mean` | `stateful::concurrent_mean` | `stateful.concurrentMean` | `Stateful.concurrentMean` | `Stateful.concurrentMean` |

```go
// ConcurrentMean sets the mean number of steps of a concurrent section. It
// panics for n below 0.
func ConcurrentMean(n int) Option
```

### Version

The option adds a name and a setup key, and does not change a meaning.
Definition 14.2.0 adds it, and every overlay extends 14.2.0.

## Alternatives considered

### A. Raise the default mean of a section

The section would average more steps for every machine.

**Why not:** every run of a machine with two clients or more would take
other choices, and every stored counterexample and replay token of such a
machine would stop replaying.

### B. Derive the mean from `concurrent`

The section would average a fixed share of its maximum.

**Why not:** the maximum then sets two things, and a caller who wants a
long tail with a short mean cannot state it. `steps.mean` and `steps.max`
already set the two separately for the sequential steps.

### C. A mean that the bound clamps

A mean above `concurrent` would take `concurrent`.

**Why not:** `steps.mean` is not clamped by `steps.max`, and the flag at
the maximum already stops the section. A clamp would make the two options
read differently.

## Version

Accepted for definition 14.2.0.
