---
rfc: 0059
title: An action that every case keeps
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-08
updated: 2026-11-08
discussion: https://github.com/dokimasia/dokimi/issues/76
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0059: An action that every case keeps

## Summary

With swarm on, a case makes one choice per action before its steps, and
keeps each action with probability 1/2. No field of an action keeps it out
of the swarm. A machine whose subject moves forward through some of its
actions then takes half of its cases without each of them. This proposal
adds the field `action.keep`:

- Every case keeps an action with `keep` set, without a swarm choice.
- The swarm makes its choices for the other actions as it makes them now.
- A machine without the field takes the choices that it takes now.

Definition 16.2.0 adds the field.

## Motivation

A simulation of a distributed system runs its active phase as the
sequential steps of a machine. Its actions deliver a pending message,
advance the time to the next timer, strike the faults and make the calls of
the clients. The simulation of sharder on the package sim of dokimi-go has
34 such actions. A probe ran 200 cases of it at each mean of 30, 300 and
3,000 steps, with sim v0.9.0:

- The median case delivered no message in its active phase at each mean.
- No case of the 600 had a cell that served while its actions and its
  faults ran.
- The falsification of sharder missed 2 of 11 planted defects at a mean of
  30, and 1 of 11 at means of 1,000 and 2,000. Each missed defect needs a
  cell that serves.

The swarm causes two parts of this:

- The swarm disables the delivery in half of the cases, and the advance of
  the time in half of the cases. A case without the delivery strikes its
  faults and makes its calls against a system that does not move.
- A case keeps about 17 of the 34 actions. Each has the weight 1, so a case
  that keeps the delivery takes it in about one of 17 steps.

A weight solves the second part. No field solves the first. The swarm
decides before the steps, and the index of a step chooses among the kept
actions alone.

Swarm testing omits features of a test, so that a feature that prevents a
bug, or that competes for the steps of a case, is absent from some cases.
The delivery of a message and the advance to a due timer are no features of
a test. They are the progress of the subject. The definition already calls
"a ready task, a pending message and a due timer" drain actions, which the
drain takes whether the swarm kept them or not. The sequential steps take
such an action only when the swarm kept it.

## Detailed design

### The field

```text
Action
  keep -> bool                optional, false by default; true keeps the action in every case
```

With swarm on, a case keeps an action with `keep` set without a swarm
choice. A sequential step lists the action whenever it is enabled. A
concurrent section takes its steps as it takes the steps of every kept
action. With swarm off, every case keeps every action. The field then has
no effect.

### The swarm

The swarm makes one choice per action without `keep`, in the order of the
actions, as the swarm makes it now. Each action with `keep` counts as kept
before the first choice:

- Each choice of a machine with an action with `keep` set is one coin of
  1 in 2.
- No choice of such a machine takes the bounds [1, 1].
- The place of a choice is the position of its action among all the
  actions of the machine.

A machine without an action with `keep` set makes the choices that it
makes now. Every stored counterexample and replay token of such a machine
replays unchanged. A machine whose actions all have `keep` set does not
make a swarm choice.

The field leaves the other rules of the swarm as they are:

- The edge phase keeps every action.
- A shrink moves each choice towards 0. The minimal case keeps the actions
  with `keep` set and the other actions that its failure needs.
- A trace keeps the actions that its step entries name, and every action
  with `keep` set.
- An action with both `drain` and `keep` set takes the steps of the drain
  as every drain action takes them.

### The corpus

A machines vector states the field in its setup as `keep`, the list of the
names of the actions that have it. The vector
`queue-loses-on-wrap/a-kept-put-takes-no-swarm-choice` runs the queue that
loses a value on wrap with `keep: [put]`. Its case makes one swarm choice,
for `get`, and its run fails as the run of the queue without the setup
fails.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `action.keep` | `Keep` | `keep` | `keep` | `keep` | `keep` | `keep` |

```go
// Keep marks an action that every case keeps. The swarm does not choose
// whether to keep it.
Keep bool
```

### Version

The field adds a name and a setup key, and does not change a meaning.
Definition 16.2.0 adds it, and every overlay extends 16.2.0.

## Alternatives considered

### A. The swarm keeps every drain action

The swarm would keep every action with `drain` set without a choice.

**Why not:** the drain then takes such an action after the sequential
steps, until none is enabled or `max` steps ran. A simulation that recovers
from its faults in `settle` would take up to `max` more steps under the
faults in force. An advance of the time that is always enabled would take
all the `max` steps.

### B. A swarm of the caller

A caller would turn swarm off and choose the actions of each case itself.

**Why not:** the caller would copy the swarm and its conditioning. A trace
would not keep the actions that its step entries name, because the choices
of the caller are no swarm choices of the machine.

### C. A weight alone

The delivery could take a weight that matches the weights of the other
actions.

**Why not:** the index chooses among the kept actions. Half of the cases
still disable the delivery.

## Version

Accepted for definition 16.2.0.

## References

| What | Where |
|---|---|
| Issue 76 of dokimi, the active phase of a case of sharder ends before its cells serve | <https://github.com/dokimasia/dokimi/issues/76> |
| RFC-0012, machines, simulation and campaigns | 0012-machines-simulation-and-campaigns.md |
| Groce, Zhang, Eide, Chen and Regehr, "Swarm Testing", ISSTA 2012 | <https://agroce.github.io/issta12.pdf> |
