---
rfc: 0062
title: A draw through a composite in a trace
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-13
updated: 2026-11-13
discussion: https://github.com/dokimasia/assert-go/issues/102
supersedes: RFC-0011, RFC-0012 and RFC-0061, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0062: A draw through a composite in a trace

## Summary

A one-of, a list, an optional, a filter or a recursive can produce the
value of a composite inside it. The draws of the composite record their
entries before the entry of the outer draw, as RFC-0061 states for a
composite itself. The replay of a trace takes the entry of the outer draw
when the draw starts, so the outer draw takes the entry of the first inner
draw and refuses it. A stored case whose action draws through such a
generator runs its choices, and a change of the actions loses its defect.

This proposal replays a draw through a composite as the case records it:

- The draw takes the first draw entry with its label from the next entry
  on, up to the next step entry.
- The value of that entry runs backwards through the generator. Each
  composite inside it makes no choice, and its draws take the entries
  before the entry of the outer draw.
- The outer draw takes its entry once it decodes.
- A one-of and a recursive pick a branch through a composite only when no
  other branch produces the value.

Definition 16.5.0 adds the replay and two machine subjects that pin it.

## Motivation

### A stored case of a one-of or a list of composites loses its defect

A simulation of a pool draws the calls of a volume through a one-of of
composites, and the operations of a batch through a list of a composite.
Two new actions change the weight of an action and the choices of the
swarm, so 8 of its 11 stored cases decode to other values. Each of the 8
then replays its counterexample, and each replay stops at a refusal:

```text
counterexample[18].label: the draw labelled "call" takes the entry labelled "key"
counterexample[10].label: the draw labelled "operations" takes the entry labelled "key"
```

The defects of the 8 cases then have no regression case. A machine whose
action draws its pair through a one-of of the composite of RFC-0061, or
through a list of one pair, fails in the same way.

### The record already states each value

The draws inside the composites record their values, and the entry of the
outer draw records the structure around them: the alternative of a
one-of, the number of items of a list, and whether an optional is
present. Only the order in which the replay takes the entries differs
from the order in which the case wrote them.

## Detailed design

### The record

A case records a draw when its generator returns, in every language, as
RFC-0061 states. A one-of of the pair of RFC-0061 records the draws of
the composite and then its own entry:

```json
[
  { "step": "put" },
  { "label": "a", "value": { "type": "int", "value": 7 } },
  { "label": "b", "value": { "type": "int", "value": 3 } },
  { "label": "pair", "value": { "type": "list", "of": "int", "value": [7, 3] } }
]
```

A list of pairs records the draws of each pair in the order of the list,
and then the list. The record and the formats of the store do not change.

### The entry of a draw

A draw through a composite is a draw whose generator has a composite
inside a one-of, an optional, a list, a dict, a filter or a recursive, at
any depth. Every other draw takes the next entry when it starts, as
RFC-0012 states, so its refusals do not change.

A draw through a composite takes the first draw entry with its label from
the next entry on, up to the next step entry or the end of the trace.
That is the next entry when the next entry has the label. The draw then
runs the value of that entry backwards through its generator:

| Result | The draw |
|---|---|
| The value runs backwards through a composite inside the generator | Takes the entry once it decodes. The draws of the composite take the entries before it |
| The value runs backwards without a composite, and the entry is the next entry | Takes the entry when it starts, as before |
| The value runs backwards without a composite, and the entry is a later one | Refuses the next entry with the reason `label` |
| No entry has the label | Refuses the next entry with the reason `label` |
| The entry states no value | Refuses the entry with the reason `value` |
| The generator cannot produce the value | Refuses the entry with the reason `value` |

A composite drawn on its own keeps the rule of RFC-0061: it takes no entry
when it starts, and it takes the next entry by its label alone once it
decodes.

### A composite inside a generator

The value of a composite inside a generator runs backwards to no choice.
The composite then decodes as it does in any case, and each of its draws
takes its own entry by the rules above. The other generators keep their
inverses around it:

- **one-of and recursive:** the first branch that produces the value
  without a composite, or else the first branch that produces it through
  a composite. A one-of of an integer and a composite runs an integer
  entry through the integer, and every other value through the
  composite.
- **list and optional:** a flag for each item and the stop, or the
  presence, from the recorded value. The items take the place of their
  composites in order.
- **filter:** the source's inverse. The filter does not test the
  recorded value of a composite, because a record of a composite may not
  state the parts that the predicate reads. The decode still filters the
  value that the composite returns.
- **unique list:** the elements through a composite are not compared, for
  the same reason. The decode still discards a repeated element.
- **dict:** a dict whose keys or values contain a composite does not run
  backwards, and the draw refuses its entry with the reason `value`. The
  value of a map does not state the order in which the case drew its
  entries, and the draws of the composites follow that order.

`map` and `bind` keep the rule of RFC-0011. A draw of one of them takes
its entry when it starts and refuses it, because they have no inverse.

### The choices of nested draws

The choices of a draw serve the requests of its own generator. A draw
inside it serves its requests from its own entry, and the requests of the
outer generator continue after the inner draw ends. A list of pairs
serves its first flag, then the draws of the first pair take their
entries, and the list serves its next flag. A request without a choice
left takes its target, as before.

### The end of a draw through a composite

When the draw through a composite decodes, its entry must be the next
entry. The draws inside take the entries before it in order, so each
entry is taken once and in the order of the record. When the draws inside
take fewer entries, the next entry has another label, and the draw
refuses it with the reason `label`. When a draw inside takes the entry of
the outer draw, which shares its label, the outer draw refuses that entry
with the reason `label`.

### The reference

The executable reference marks the place of each composite among the
steps that a value emits, and returns the choices around those places.
`Tracing` keeps one queue of choices for each open draw, and takes the
entry of a draw through a composite when the draw ends.

### Conformance

Two machine subjects extend `pair-fails-at-7-and-3` of RFC-0061. Each has
the actions `noop`, which does nothing, and `put`, and records no call:

- `one-of-pair-fails-at-7-and-3` draws the input of `put` under `pair`
  through a one-of of an integer in [0, 9] and the composite pair. `put`
  fails with the identity `pair` for the integer 7 and for the list
  [7, 3].
- `pairs-fail-at-7-and-3` draws the input of `put` under `pairs` through
  a list of 0 to 3 composite pairs. `put` fails with the identity `pair`
  when the list has the pair [7, 3].

The machines vectors of the subjects pin these behaviours:

- A run of each subject shrinks to its minimal steps: a put of the
  integer 7, and a put of a list of the one pair [7, 3].
- A trace through the composite alternative of a one-of replays the draws
  of the composite and fails at its first case.
- A trace of the integer alternative takes its entry when the draw
  starts.
- A trace whose composite leaves an entry before the entry of the one-of
  is refused at that entry.
- A trace of a list of two pairs replays the draws of both.
- A stored case of other actions replays its list of pairs and fails
  before any case of the seed.

### Version

A trace through a composite was refused before definition 16.5.0. No
vector pins that refusal, so no vector changes what it expects.
Definition 16.5.0 adds the replay and the two subjects.

### What this supersedes

This proposal supersedes these parts of earlier designs:

- RFC-0011 fails a draw of `Draws` whose generator cannot run backwards.
  A generator that runs backwards only through a composite inside it no
  longer fails, and replays the draws of the composite.
- RFC-0012 lets every draw of a trace take the next entry when it starts.
  A draw through a composite takes the first entry with its label, and
  takes it when it ends.
- RFC-0061 keeps the rule of RFC-0011 for `filter`. A filter of a
  composite runs backwards through the composite and does not test the
  recorded value.

## Alternatives considered

### A. The entry of the outer draw at its request

A case would record the entry of a one-of or a list before the entries of
the draws inside it.

**Why not:** RFC-0061 rejects the same change for a composite. Every
counterexample with such a draw would change its order, and the stores of
earlier definitions would keep entries that no replay could tell apart.

### B. The entry of the outer draw by its label at its end

The outer draw would take no entry when it starts, as a composite does,
and its own requests would take their targets.

**Why not:** a target is the simplest choice. A one-of would always pick
its first alternative, and a list would always have its minimum number of
items, so a replay would decode other values than the record states.

### C. A count of the inner entries in the record

Each draw entry would record the number of entries that the draws inside
it wrote, in a format 3 of the store.

**Why not:** the stores of earlier definitions lack the count, so their
stored cases would still refuse. The record already states the structure
in the value of the outer entry.

### D. Each alternative tried in turn

A one-of of two composites would decode its first alternative, and decode
the next one when the entries refuse the first.

**Why not:** the function of a composite, the body and the machine would
run more than once in one case, and a case cannot undo what they did.

## Drawbacks

- A draw inside a composite that shares the label of the outer draw makes
  the outer draw find that inner entry first. The replay then refuses an
  entry or decodes other values.
- A one-of of two composites replays its first composite. When the draws
  of the first composite have other labels than the entries, the replay
  refuses an entry.
- A dict through a composite does not replay, and its stored case runs
  its choices.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/102> |
| The option `Draws` and the generators that run backwards | RFC-0011 |
| Traces and the counterexample of a machine | RFC-0012 |
| A composite in a trace | RFC-0061 |
