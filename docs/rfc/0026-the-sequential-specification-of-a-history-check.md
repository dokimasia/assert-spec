---
rfc: 0026
title: The sequential specification of a history check
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-06
updated: 2026-10-06
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0026: The sequential specification of a history check

## Summary

A history check takes a model: a type with the members `init`, `step`
and `equal`, whose `step` returns the states that may follow a state
when an operation takes effect. Porcupine declares the same type with
the same members, so the standard's API reads as a port of one checker.
The definition of linearizability supplies the terms instead. A history
is linearizable when its calls have an order, a linearization, that
respects their real-time order and that the object's sequential
specification accepts.

This proposal names the API after that definition. Definition 7.0.0
makes these changes:

- **The type `model` becomes `spec`,** with the members `initial`, `next`
  and `equal`.
- **The type `op` becomes `operation`.** Its members `name`, `args`,
  `known` and `output` join the naming table.
- **`operation` gains `returned`.** It reports whether the call may have
  returned a value: true for a call whose output is unknown, and
  otherwise whether its output equals the value.
- **`history.model-from` becomes `history.spec-from`,** and the member
  `model` of a machine becomes `spec`.
- **The section `models` of the definition becomes `specs`,** and a
  vector of `linearizable` names its spec under the key `spec`.

## Motivation

### The API matches one checker's API

Porcupine 1.3.1 declares `NondeterministicModel` with the members `Init`,
`Step`, `Equal` and `Hash`. Its `Step` returns "all possible next states"
of a state. Go's `history.Model` has the same four members with the same
meanings, and the other languages name the members of `model` the same
way.

Herlihy and Wing define linearizability in their own terms: a history,
the invocation and the response of each call, the real-time order of two
calls, a linearization, and the sequential specification of an object.
An API in those terms reads as the definition that it checks.

### Every spec states the rule for an unknown output

A call whose outcome is unknown, and a pending call, may have taken
effect with any output. Every spec of a read states the same condition: accept the state when the output is unknown, or when the
known output equals the state. In Go:

```go
if !op.Known || op.Output == s {
    return []int{s}
}
```

assert-go states the condition in 9 places: its README, the package doc,
two specs of its tests, and five conditions of four of the definition's
named specs. The comparison `op.Output == s` compiles only for a state of
a comparable type. A spec of a list or a map writes a comparison of its
own.

### `step` and `op`

`step` names both a transition of a spec and a step of a machine. A step
of a machine runs one action, and a counterexample lists the steps of
its case. `op` is the one abbreviation among the type names of the
naming table.

## Detailed design

### Names

| Old id | New id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|---|
| `model` | `spec` | `history.Spec` | `history.Spec` | `history::Spec` | `history.Spec` | `Spec` | `Spec` |
| `model.init` | `spec.initial` | `Initial` | `initial` | `initial` | `initial` | `initial` | `initial` |
| `model.step` | `spec.next` | `Next` | `next` | `next` | `next` | `next` | `next` |
| `model.equal` | `spec.equal` | `Equal` | `equal` | `equal` | `equal` | `equal` | `equal` |
| `op` | `operation` | `history.Operation` | `history.Operation` | `history::Operation` | `history.Operation` | `Operation` | `Operation` |
| none | `operation.name` | `Name` | `name` | `name` | `name` | `name` | `name` |
| none | `operation.args` | `Args` | `args` | `args` | `args` | `args` | `args` |
| none | `operation.known` | `Known` | `known` | `known` | `known` | `known` | `known` |
| none | `operation.output` | `Output` | `output` | `output` | `output` | `output` | `output` |
| none | `operation.returned` | `Returned` | `returned` | `returned` | `returned` | `returned` | `returned` |
| `machine.model` | `machine.spec` | `Spec` | `spec` | `spec` | `spec` | `spec` | `spec` |
| `history.model-from` | `history.spec-from` | `history.SpecFrom` | `history.spec_from` | `history::spec_from` | `history.specFrom` | `History.specFrom` | `History.specFrom` |

The other names of a history, its checks and a machine do not change:
`History`, `invoke`, `ok`, `fail`, `unknown`, `linearizable`, the limits
of a search, `Machine`, `Action`, `steps` and the scheduler.

### The members of a spec

| Member | Meaning |
|---|---|
| `initial` | Returns the state of the object before any call |
| `next` | Returns the states that may follow a state when an operation takes effect, in the order the search tries them, and none when the spec rejects the operation in that state |
| `equal` | Reports whether two states are interchangeable. It is optional, and states compare with the standard's `equal` without it |

`initial` remains a function. A spec's state can be of a mutable type,
such as a list, and each search starts from a state of its own.

### The members of an operation

An operation is a call as a spec sees it: its `name` and its `args`, and
its `output` when `known` is true. `known` is true for a call that
completed as `ok`, and false for a call whose outcome is unknown and for
a pending call.

`returned(v)` reports whether the call may have returned `v`:

- It returns true when `known` is false. The call may have taken effect
  with any output.
- It returns whether `output` equals `v` otherwise. It compares the two
  as `equal` compares them, without a relaxation.

The read of a register is then one condition:

```go
case "read":
    if op.Returned(s) {
        return []int{s}
    }
```

### The definition's data

- The section `models` of `assertions.yaml` becomes `specs`. Its
  summaries, and the summaries of the machine subjects, say "spec".
- A vector of `linearizable` names its spec under the key `spec`, in
  place of `model`.
- The record of a check keeps its ten fields, `partition` and
  `partitions` among them.

### Phrasing

The definition and every implementation describe a check in these terms:

| Term | Meaning |
|---|---|
| Sequential specification, or spec | The initial state of an object and the states that each operation may leave |
| Real-time order | Call a precedes call b when a completed before b was invoked |
| Linearization | An order of calls that respects their real-time order and that the spec accepts |
| Partition | The calls that share keys, directly or through other calls. A check linearizes each partition apart from the others |

| Now | Then |
|---|---|
| Checks the recorded history against a consistency model: linearizability with respect to a sequential model | Checks that a recorded history is linearizable: that its calls have an order that respects their real-time order and that the object's spec accepts |
| Every partition of the history has an order of its calls that keeps the history's precedence and that the model accepts | The calls of each partition of the history have a linearization that the spec accepts |

### Go

```go
// Spec is the sequential specification of an object: its state before any
// call, and the states that an operation may leave. S is the type of a
// state.
type Spec[S any] struct {
	// Initial returns the state before any call.
	Initial func() S
	// Next returns the states that may follow state when op takes effect,
	// and none when the spec rejects op in state.
	Next func(state S, op Operation) []S
	// Equal reports whether two states are interchangeable.
	Equal func(a, b S) bool
	// Hash returns a hash of state that every state equal to it shares.
	Hash func(state S) uint64
}

// Operation is a call as a spec sees it.
type Operation struct {
	// Name is the call's operation.
	Name string
	// Args are the call's arguments.
	Args []any
	// Known reports whether the call completed as OK.
	Known bool
	// Output is what the call returned when Known is set, and nil otherwise.
	Output any
}

// Returned reports whether the call may have returned v: true when its
// output is not known, and otherwise whether its output equals v as
// assert.Equal compares them.
func (o Operation) Returned(v any) bool

// SpecFrom returns the spec that the subject's own sequential behaviour
// states.
func SpecFrom(factory func() Subject) Spec[[]Operation]

func Linearizable[S any](tb assert.TB, h *History, s Spec[S], contract string, opts ...Option)
```

`stateful.Machine` takes the spec of its subject as `Spec history.Spec[S]`.
The register of Go's README:

```go
history.Linearizable(t, h, history.Spec[int]{
	Initial: func() int { return 0 },
	Next: func(s int, op history.Operation) []int {
		switch op.Name {
		case "write":
			return []int{op.Args[0].(int)}
		case "read":
			if op.Returned(s) {
				return []int{s}
			}
		}
		return nil
	},
}, "the register is linearizable")
```

### Version

Renaming a member breaks every implementation and every caller, so the
change is a major version. Definition 7.0.0 makes it, and every overlay
extends 7.0.0.

## Alternatives considered

### A. `specification` in full

**Why not:** the name is unambiguous, and long in every struct literal
and every machine.

### B. `object`

**Why not:** the name reads as the object under test, not as its
specification.

### C. `model` with new members

**Why not:** the type keeps the name that a reader matches to the
checker first.

### D. A `next` that returns an output with each state

`next` would return the pairs of an output and a state, and the check
would compare the recorded output with each pair's.

**Why not:** a spec whose output is free, such as a read of any member
of a set, would list every member as an output. A predicate on the
output, such as membership, states the same rule in one condition.

### E. `initial` as a state

**Why not:** a state of a mutable type would be shared by every search
of the check. A spec that changes it by mistake changes every search
after it.

### F. The keys `models` and `model` of the corpus unchanged

**Why not:** the definition would name one concept twice, once in the
API and once in its data.

## Drawbacks

- **Every implementation renames seven rows and adds five.** Every spec
  that a caller wrote changes its type, its two functions and the name
  of its operation's member.
- **Each language's conformance runner reads the section `specs` and the
  key `spec`.**
- **`returned` compares with `equal`, which treats two types as
  unequal.** An output of `int64` does not equal a state of `int`.
- **`spec` also names a specification document,** such as this
  repository. The API uses the word for a sequential specification
  alone.

## References

| What | Where |
|---|---|
| Linearizability, the real-time order of two calls, and the sequential specification of an object | Herlihy and Wing, "Linearizability: a correctness condition for concurrent objects", ACM TOPLAS 12(3), 1990 |
| `NondeterministicModel` and its members | Porcupine 1.3.1, `model.go`, <https://github.com/anishathalye/porcupine> |
| The check of a history and the model it takes | RFC-0004 |
| Machines and their model | RFC-0012 |
