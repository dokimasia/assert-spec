---
rfc: 0061
title: A composite in a trace
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-10
updated: 2026-11-10
discussion: https://github.com/dokimasia/assert-go/issues/100
supersedes: RFC-0011, RFC-0012 and RFC-0060, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0061: A composite in a trace

## Summary

A case records each draw when the draw ends. A composite draws other
values before it ends, so its counterexample lists the entries of those
draws first and the entry of the composite after them. The replay of a
trace takes the entries in the order of the requests, where the draw of
the composite comes first. The composite then takes the entry of its first
draw and refuses it. A stored case whose action draws through a composite
runs its choices, and a change of the actions loses its defect.

This proposal replays a composite as the case records it:

- A draw of a composite takes no entry when it starts. The draws inside
  it take their own entries.
- When the composite ends, it takes the next entry by its label alone and
  does not read its value. The entry may lack a value.

Definition 16.4.0 adds the replay of a composite and a machine subject
that pins it.

## Motivation

### A stored case of a composite loses its defect

A machine draws the input of its action `put` as a pair through a
composite, which draws `a` and then `b`. Its stored case records the
step, then `a`, `b` and `pair`. One more action gave the stored choices
another meaning, and the run reported:

```text
prop.ForAll: testdata/prop/TestTrace.9301bad4e717ec95.json: the stored case decodes to other values than it records, and the run tested those: counterexample[1].label: the draw labelled "pair" takes the entry labelled "a"
```

The replay of RFC-0060 refused the entry at the draw of the pair, the
first request of the step. The defect then had no regression case.

### The record of a composite is already complete

The draws inside a composite record their values as every draw does.
The composite computes its value from those values, so a replay that
takes them reproduces the composite. Only the order in which the replay
takes the entries differs from the order in which the case wrote them.

## Detailed design

### The record

A case records a draw when its generator returns, in every language. A
composite records its draw after the draws inside it:

```json
[
  { "step": "put" },
  { "label": "a", "value": { "type": "int", "value": 7 } },
  { "label": "b", "value": { "type": "int", "value": 3 } },
  { "label": "pair", "value": { "type": "list", "of": "int", "value": [7, 3] } }
]
```

A store keeps the entries of format 1 and 2 as RFC-0010 and RFC-0060
state them, so the record does not change.

### The replay

A trace replays the draws of a composite in the order of the record:

- A draw of a composite takes no entry when it starts.
- Each draw inside the composite takes the next entry, as RFC-0012
  states for a draw.
- When the composite ends, it takes the next entry. The entry must be a
  draw entry with the label of the composite. The replay does not read
  its value, so the entry may lack one.

A composite inside a composite follows the same rules, so the replay takes
the entries of the inner composite before the entry of the outer one. A
composite past the last entry takes no entry, and its draws take their
targets.

A trace that the body cannot follow refuses an entry as RFC-0012 states.
The entry at the end of a composite gives one more refusal: a step entry,
or a draw entry with another label than the composite's. The reason is
`label`, as for any other draw.

`map`, `filter` and `bind` keep the rule of RFC-0011. A draw of one of
them takes its entry when it starts, and `map` and `bind` refuse it,
because they have no inverse.

### The reference

The executable reference adds a composite generator. Its value is what a
function returns from the draws that it makes on the case, inside a span
labelled `composite`. It has no inverse. The vocabulary of a vector's
generator does not name it, because a vector does not state a function. A
machine subject draws through it.

### Conformance

The machine subject `pair-fails-at-7-and-3` has the actions `noop`,
which does nothing, and `put`. The input of `put` is a composite drawn
under `pair`, which draws an integer in [0, 9] under `a` and then one
under `b`, and returns the list of the two. `put` fails with the identity
`pair` for the list [7, 3].

The machines vectors of the subject pin these behaviours:

- A trace of a composite in the order of the record fails at its first
  case.
- A trace whose entry at the end of the composite has another label is
  refused at that entry.
- A stored case of other actions replays its counterexample through the
  composite and fails before any case of the seed.
- A stored case replays the same way when the entry of its composite
  lacks a value.

### Version

A trace of a composite failed the test before definition 16.4.0. No
vector pins that refusal, so no vector changes what it expects.
Definition 16.4.0 adds the replay, the composite of the reference and the
subject.

### What this supersedes

This proposal supersedes these parts of earlier designs:

- RFC-0011 fails a draw of `Draws` whose generator cannot run backwards.
  A composite no longer fails, and replays its draws.
- RFC-0012 lets every draw of a trace take the next entry when it starts.
  A composite takes its entry when it ends.
- RFC-0060 lists `composite` among the generators whose stored case does
  not replay its counterexample. A stored case of a composite replays it.

## Alternatives considered

### A. The entry of a composite at its request

A case would record the entry of a composite before the entries of its
draws, at the position of its request.

**Why not:** the order of every counterexample with a composite would
change, and so would every detail that pins one. The stores of earlier
definitions would keep entries in the other order, which no replay could
tell apart.

### B. No entry for a composite

A case would record the draws inside a composite and no entry of its own.

**Why not:** a counterexample would no longer state the value of the
composite, the value that a reader of a failure looks for first. Both A
and B change the record, and the replay can follow the record as it is.

### C. The recorded value of a composite checked at its end

The replay would compare the value that the composite returns with the
value that its entry records.

**Why not:** many languages have no typed literal for the value of a
composite. Go records a struct with unexported fields as an empty map. A
check would refuse such a composite on every replay. The
draws inside the composite already decide its value.

## Drawbacks

- A trace of a composite whose function draws other values after a change
  of the function takes the entries in another order, and the replay
  refuses an entry or decodes other values.
- `map` and `bind` still have no inverse, so a stored case that draws
  through them runs its choices.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/100> |
| The store and its format 1 | RFC-0010 |
| The option `Draws` and the generators that run backwards | RFC-0011 |
| Traces and the counterexample of a machine | RFC-0012 |
| The steps of a stored case | RFC-0060 |
