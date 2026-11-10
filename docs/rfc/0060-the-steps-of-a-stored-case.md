---
rfc: 0060
title: The steps of a stored case
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-10
updated: 2026-11-10
discussion: https://github.com/dokimasia/assert-go/issues/98
supersedes: RFC-0010, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0060: The steps of a stored case

## Summary

An entry of the store records the draws of its case and none of the steps
of a machine. A run replays the entry's choices, and a machine takes the
index of each action from them. One more action gives each stored index
another meaning. The case then decodes to other values than its entry
records, and the run loses the defect that the entry recorded. This
proposal records the steps and replays them:

- An entry of format 2 records the counterexample of a machine as the
  machine states it: draw entries and step entries in request order. A
  runner writes format 2 for a counterexample with a step entry, and
  format 1 for every other counterexample.
- The run replays the counterexample of an entry when the case of its
  choices does not fail and decodes to another counterexample than the
  entry records. It runs the counterexample as a trace, as `prop.draws`
  runs one.
- When the body cannot follow the trace, the case of the choices counts.
  The run then notes the entry as RFC-0010 states.

Definition 16.3.0 adds format 2 and the replay through the counterexample.

## Motivation

### A stored case of a machine loses its defect

A simulation of a pool gained the action `resolve`. Each of its stored
cases then decoded to other steps, and the run reported each of them:

```text
system_sim_test.go:19: prop.ForAll: testdata/prop/TestSimulation.327740f3d55c2cf6.json: the stored case decodes to other values than it records, and the run tested those
```

Each entry records the draws of its case by their labels and values, such
as `client`, `volume` and `op`. No entry records an action, so no entry
can state which steps its case took.

### A machine's counterexample already replays

RFC-0012 states a machine's counterexample as a list of draw entries and
step entries in request order. `prop.draws` runs such a list as a trace. A
step entry turns back into the choices of one step by the name of its
action, so a trace keeps its meaning when the list of actions changes. The
store keeps the draw entries of the list and drops its step entries.

## Detailed design

### Format 2

An entry of format 2 has the seven fields of format 1. The fields `store`
and `counterexample` have another form:

| Field | Form |
|---|---|
| `store` | The format, 2 |
| `counterexample` | One object per entry of the case's counterexample, in request order. A draw entry records its `label`, and its `value` when a typed literal states the value. A step entry records the name of its action as `step` |

A step entry has one of three sets of keys:

- `step` alone, for a sequential step
- `step` and `client`, for a step of a concurrent section
- `step` and `drain`, for a step of the drain

`step` is a string, `client` is an integer from 0 to 2^31 − 1, and `drain`
is true. An entry of a queue that loses a value on wrap:

```json
{
  "store": 2,
  "definition": "16.3.0",
  "property": "the queue behaves like a slice",
  "identity": { "assertion": "linearizable", "file": "queue_test.go", "line": 31 },
  "choices": "prop1:AAIAAQABAAEAAAAAAAEAAAABAAEAAQ",
  "counterexample": [
    { "label": "capacity", "value": { "type": "int", "value": 2 } },
    { "step": "put" },
    { "label": "v", "value": { "type": "int", "value": 0 } },
    { "step": "put" },
    { "label": "v", "value": { "type": "int", "value": 1 } },
    { "step": "get" }
  ],
  "found": "2026-11-10"
}
```

A runner writes format 2 for a counterexample with a step entry, and format
1 for every other counterexample. The stores of properties without a
machine then keep files that every runner of an earlier definition replays.

### The verdict on a file

| Verdict | The file |
|---|---|
| Replay | An entry of format 1 or 2 for the property |
| Other | An entry of format 1 or 2 for another property of the test |
| Skip | An entry whose `store` is above 2, or whose token states a version above 1 |
| Damaged | Any other file |

A file is damaged in the cases that RFC-0010 states, and in two more:

- An entry of format 1 has a step entry.
- An entry of format 2 has a step entry out of its form.

A runner of an earlier definition gives a file of format 2 the verdict
skip, and notes the file.

### The replay of a stored case

The run tries the choices of each entry in the stored phase, as RFC-0010
states. The case of the choices states the entry's counterexample when its
own counterexample has the same entries in order:

- The draw entries have the same labels.
- Each draw entry has the same value where the entry records one, as two
  typed literals compare.
- For an entry of format 2, the step entries have the same actions,
  clients and drain marks.

An entry of format 1 does not record step entries, so the steps of its
case do not count. A case that fails counts as the case of its entry,
whatever it decodes to.

The run replays the counterexample of the entry when the case of the
choices does not fail and states another counterexample. It runs the
counterexample as a trace, as `prop.draws` runs one:

- The case of the trace counts in place of the case of the choices when it
  fails, and when it takes every entry of the trace.
- The case of the choices counts when the body refuses an entry of the
  trace, and when the case of the trace leaves an entry untaken. A draw
  entry without a value is an entry that the body refuses.

The case of the choices and the case of the trace are both calls of the
body in the phase `stored`. A run records the calls of the case of the
choices. It records the calls of the case of the trace when that case
counts.

A run notes each entry whose case of the choices does not state its
counterexample. The note states that the run replayed the counterexample,
or that it tested the values that the choices decode to. In the second
case the note also states the refusal of the trace. A note is the
language's own, and no vector pins it.

### Conformance

A vector states each stored case as its choices and the counterexample
that its entry records, as every entry of a store records one:

```yaml
settings:
  seed: "1"
  cases: 1
  stored:
    - choices: [2, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0]
      counterexample:
        - {label: capacity, value: {type: int, value: 2}}
        - {step: put}
        - {label: v, value: {type: int, value: 0}}
        - {step: put}
        - {label: v, value: {type: int, value: 1}}
        - {step: get}
```

The vectors pin these behaviours:

- The store vectors pin format 2 for a counterexample with a step entry,
  the verdict on files of format 2, and the verdict skip on a file of
  format 3.
- The machines vectors run the queue that loses a value on wrap under
  three stored cases. The first decodes to other steps, replays its
  counterexample and fails. The second has a step of an action that the
  machine lacks, so the run tests its choices. The third records draws alone, as an
  entry of format 1 of a machine does. Its trace leaves entries untaken, so
  the run tests its choices.
- A behaviour vector stores a case of a property without a machine whose
  choices decode to another value than its entry records. The run replays
  the entry's value.

### Version

A runner of an earlier definition skips an entry of format 2. The replay
through the counterexample changes the run of a stored case that decodes
to other values alone. Definition 16.3.0 adds both. The vector
`store/skips-an-entry-of-a-later-format` states format 3, so its verdict
stays skip for every runner.

### What this supersedes

This proposal supersedes two parts of RFC-0010:

- A replay whose choices decode to other values than its entry records now
  replays the entry's counterexample, where the body can follow it.
- A runner skips an entry whose `store` is above 2, where it skipped an
  entry above 1.

## Alternatives considered

### A. Format 2 for every entry

A runner would write format 2 for every counterexample.

**Why not:** a runner of an earlier definition skips every entry of format
2. It would no longer replay the entries of properties without a machine.
Format 1 states such an entry in full.

### B. The steps as draws of format 1

A machine would record each step as a draw whose label names the action,
such as `step put`, and the format would stay 1.

**Why not:** a draw of the body can have the same label, so a reader could
not tell a step from a draw. A draw entry has no field for the client or
the drain mark either. The step entries of a trace already state all three.

### C. The counterexample before the choices

A run would replay the counterexample of every entry as a trace, and its
choices only when the body cannot follow the trace.

**Why not:** a trace needs generators that run backwards and a typed
literal for each value. The choices replay every case. Only a case whose
decoding changed needs its counterexample.

### D. A rewrite of an entry whose choices decode to other values

The runner would replace such an entry with an entry of the choices of the
case of the trace.

**Why not:** RFC-0010 never removes or changes an entry. A person deletes
an entry, as a person updates a golden file. The run notes the entry, and
the shrink of a failing case of the trace stores an entry of its own.

## Drawbacks

- A stored case whose choices decode to other values runs twice: once from
  its choices and once as a trace.
- A runner of an earlier definition skips the entries of format 2. It no
  longer replays the stored cases of a machine that a later runner wrote.
- A trace needs generators that run backwards. An entry whose case draws
  through `map`, `filter`, `bind` or `composite` does not replay its
  counterexample, and the run tests the values that its choices decode to.
- An entry of format 1 that a machine wrote does not record its steps. A
  change of the machine's actions still loses its defect.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/98> |
| The store, its format 1 and the replay of its entries | RFC-0010 |
| The option `draws` and the generators that run backwards | RFC-0011 |
| Traces and the counterexample of a machine | RFC-0012 |
