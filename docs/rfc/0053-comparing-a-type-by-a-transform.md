---
rfc: 0053
title: Comparing the values of a type by a transform
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-02
updated: 2026-11-02
discussion: https://github.com/dokimasia/assert-spec/issues/29
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0053: Comparing the values of a type by a transform

## Summary

`equal` compares structurally, so it compares every field that a value
keeps, also the state of an implementation. In Go, two protobuf messages
with the same fields differ in their cached size and their message info,
and `equal` fails on them with a record whose got and want render as the
same text. This proposal adds the modifier `equate-by(f)`:

- `f` is a transform of the values of one type.
- Under the modifier, a value of that type compares by its transform, with
  the comparison and the other modifiers of the call.
- The modifier applies at the top, in an element of a list, in a key and a
  value of a map and in a field of a record.
- The record of `equal` and of `not-equal` states the result of the
  transform in place of got and want when the transform matches them, so
  the diff of a failure lists the differences of the results.

The caller supplies the transform, so no implementation depends on a
serialization library. A Go caller passes `prototext.Format` of the protobuf
runtime as the transform of its messages.

## Motivation

The issue reproduces the defect with `go.dokimi.dev/assert` v0.14.1,
`google.golang.org/protobuf` v1.36.12 and go1.27.2. Two messages of
`structpb.NewStruct` with the same fields compare equal under `proto.Equal`
and fail `assert.Equal` once `proto.Size` has run on one of them.

A message of the Go protobuf runtime keeps the state of its implementation
in unexported fields: the cached size, the unknown fields and the pointer to
its message info. `proto.Size`, `proto.Marshal` and every reflective read
set that state. A store that reads each resource into a new message through
`protoreflect` returns messages whose state differs from the messages that
a test wrote. The specs of such a store fall back to
`assert.True(t, proto.Equal(got, want), msg)`, which does not state a diff.

The other languages compare a message by the fields of its schema:

- A Python message implements `__eq__`.
- A Java message implements `equals`.
- prost derives `PartialEq` for a Rust message.

A type with a cache of its own has the same defect in every language whose
`equal` reads private state.

### Prior art

- go-cmp's `cmp.Transformer` converts the values of one type into values of
  another type before `cmp.Equal` compares them. It does not apply a
  transformer to its own result at the same place, and applies it again
  deeper in the result.
- `protocmp.Transform` of `google.golang.org/protobuf/testing/protocmp`
  converts each `proto.Message` into a `protocmp.Message` of its fields, so
  `cmp.Diff` lists the fields that differ.
- go-cmp's `cmp.Comparer` takes the equality of one type.
- AssertJ's recursive comparison takes the equality of one type in
  `withEqualsForType`, and of named fields in `withEqualsForFields`.

## Detailed design

### The modifier

```yaml
relaxations:
  "equate-by":
    summary: >
      A value of the type of the transform's argument compares by the
      transform's result, under the comparison and the other modifiers of
      the call. The modifier applies wherever the comparison meets such a
      value: at the top, in an element of a list, in a key and a value of a
      map and in a field of a record.
```

The rules of the modifier:

- The transform takes one value of its type and returns a value that the
  comparison can compare.
- A value matches when its type is the type of the transform's argument. In
  Go, a value matches an interface type when the type of the value
  implements the interface.
- At one place at most one transform applies. The comparison compares the
  result as it is, and applies the transforms again to the parts of the
  result. Two transforms that map the types of each other do not apply in
  turn at one place.
- The last `equate-by` of a call whose type matches a value applies.
- A panic or an exception of the transform passes through the call.
- The transform must not change its argument, and its result must not
  contain its argument.

The modifier applies to every assertion that takes `equate-empty`, because
each of them compares values as `equal` compares them, and to the property
forms of those assertions. The transform applies before `by-identity`, and
the results compare under `by-identity` as every other value does.

### The record

The record of `equal` states the result of the transform in place of want
and got when the transform matches them, and the record of `not-equal` in
place of got. The diff of a failure then lists the differences of the
results. Every other record states its values as the call received them.

### The languages

```go
// EquateBy makes a value of type T compare by f(value), for the call it is
// passed to. It panics for a nil f.
func EquateBy[T, R any](f func(T) R) Option
```

```python
def equate_by(kind: type[T], f: Callable[[T], object]) -> Option:
    """Make a value of kind compare by f(value), for the call it is passed to."""
```

```typescript
/** Makes a value that `is` accepts compare by f(value), for the call it is passed to. */
export function equateBy<T>(is: (value: unknown) => value is T, f: (value: T) => unknown): Option;
```

```java
public static <T> Option equateBy(Class<T> type, Function<? super T, ?> f);
```

Rust declines the modifier, as it declines the other three. Its assertions
compare through `PartialEq`, and a type states its equality there.

An `Option` of Go has no state today. `EquateBy` keeps its transform, so
the doc comment of `Option` states that the option is safe for concurrent
use when its transform is.

Go hands a value to the transform also when the value is in an unexported
field, as the comparison reads that field without the modifier.

A Go caller compares protobuf messages by their text:

```go
assert.Equal(t, got, want, "the stored book is the written book", assert.EquateBy(prototext.Format))
```

Within one process, `prototext.Format` writes two messages with the same
fields as the same text. It writes the fields in the order of their
declaration, the entries of a map in the order of their keys, and the
unknown fields too. Its output can change from one build of a program to
the next, and both sides of a comparison come from one build. The diff of
two texts lists the lines of the fields that differ.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `equate-by` | `EquateBy` | `equate_by` | Declined | `equateBy` | `Option.equateBy` | `Option.equateBy` |

### Conformance

A transform is a function, and a corpus case cannot state a function, so no
vector pins the modifier. Each language tests these behaviours in its own
tests:

- Two values of the type that differ in private state and have the same
  result compare equal.
- A value compares by its result at the top, in an element, in a key and a
  value of a map and in a field.
- At one place at most one transform applies, and the transforms apply
  again to the parts of a result.
- The last `equate-by` of a call whose type matches a value applies.
- The record of `equal` states the transform of want and of got.

### Version

The modifier adds a name and does not change a meaning. Definition 14.1.0
adds it, and every overlay extends 14.1.0. The Rust overlay declines it.

## Alternatives considered

### A. Compare every protobuf message by its fields by default

`equal` would compare each protobuf message as `proto.Equal` compares it.

**Why not:** in Go the module `go.dokimi.dev/assert` would require
`google.golang.org/protobuf`, and every test binary that imports assert
would link the protobuf runtime. The meaning of `equal` would depend on one
serialization library. A type with a cache that is no message would still
need a modifier.

### B. A module of assert-go with the transform of a message

A module `go.dokimi.dev/assert/protobuf` would export the transform of a
message into a map of its fields.

**Why not:** assert would depend on the protobuf runtime, in a module of
its own. `prototext.Format` of the runtime is already such a transform, so
a caller passes it.

### C. The equality of one type

A modifier `equate-with(f)` would take the equality of one type, as
`cmp.Comparer` and `withEqualsForType` do. A caller would pass `proto.Equal`.

**Why not:** the record would state the values themselves, with their
private state. Two messages whose fields differ would render a diff of the
cached size and the message info besides the field that differs.

### D. A comparison that skips the state of the protobuf runtime

Go's comparison would skip the unexported fields of the types of
`google.golang.org/protobuf/internal/impl`, found by their package path.

**Why not:** the rule would depend on the names of the internal package of
another module, which a release of that module can change.

## Drawbacks

- Each call that compares messages states the option.
- A transform that drops a field makes two values that differ in that field
  compare equal.
- A Go `Option` keeps state for the first time.
- The record of `equal` states the results, so `Failure.Want` of Go returns
  the result of the transform.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/29> |
| The modifier `by-identity`, whose reach this modifier takes | [RFC-0023](0023-comparing-references-by-identity.md) |
| go-cmp's `Transformer` and `Comparer` | <https://pkg.go.dev/github.com/google/go-cmp/cmp> |
| `protocmp.Transform` | <https://pkg.go.dev/google.golang.org/protobuf/testing/protocmp> |
| AssertJ's recursive comparison | <https://assertj.github.io/doc/#assertj-core-recursive-comparison-comparators> |
