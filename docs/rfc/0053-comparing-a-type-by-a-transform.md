---
rfc: 0053
title: Comparing the values of a type by a transform
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
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
- The record states the transform of each such value, so a diff lists the
  fields that differ.
- The modifier applies at the top, in an element of a list, in a value of a
  map and in a field of a record, as `by-identity` does.

A Go module of its own, `go.dokimi.dev/assert/protobuf`, supplies the
transform of a protobuf message into its fields. The module
`go.dokimi.dev/assert` does not depend on it.

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
  another type before `cmp.Equal` compares them.
- `protocmp.Transform` of `google.golang.org/protobuf/testing/protocmp`
  converts each `proto.Message` into a `protocmp.Message` of its fields, so
  `cmp.Diff` names the fields that differ.
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
      value: at the top, in an element of a list, in a value of a map and
      in a field of a record. The record states the result in place of
      the value.
```

The rules of the modifier:

- The transform takes one value of its type and returns a value that the
  comparison can compare.
- A value matches when its type is the type of the transform's argument. In
  Go, a value matches an interface type when its dynamic type implements
  the interface.
- The comparison does not apply a transform to the result of the same
  transform. A result that contains a value of the type compares that value
  structurally.
- Two transforms of one type in one call refuse the call with a fault.
- The transform must not change its argument. An error that the transform
  raises ends the call with that error as a fault.

The modifier applies to `equal`, `not-equal`, `contains`, `not-contains`,
`permutation`, `no-duplicates`, and the property forms of the first five, as
`by-identity` applies. It combines with `equate-empty` and `equate-nans`,
which apply inside the results. Under `by-identity`, a result compares by
the values that it contains, because a transform creates its result.

### The record

The `want` and `got` of a failure state the result of the transform in
place of each value that it matches, at every depth. The result of a
transform of a message into its fields is a map, so the text writer's diff
names the fields that differ.

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
the doc comment of `Option` states that a transform makes an option keep
state, and that the option remains safe for concurrent use when the
transform is.

### The transform of a protobuf message

The module `go.dokimi.dev/assert/protobuf` requires
`google.golang.org/protobuf`. It exports one option:

```go
// Fields makes each proto.Message compare by the fields that its schema
// declares and that it has set, its unknown fields included, as
// proto.Equal compares two messages.
func Fields() assert.Option
```

`Fields` returns `assert.EquateBy` of a transform into a map from the name
of each field to its value. A message value of a field transforms the same
way. A list and a map of the schema transform into a Go slice and a Go map.
The unknown fields transform into their bytes under the key `unknown`, as
`proto.Equal` compares them.

```go
assert.Equal(t, got, want, "the stored book is the written book", protobuf.Fields())
```

The naming table lists the modifier. The transform of a message is a part
of the Go library that the table does not list, so an RFC of assert-go
decides its module and its name.

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
- A value compares by its result at the top, in an element, in a value of a
  map and in a field.
- The record states the result of each value that the transform matches.
- A result that contains a value of the type compares that value
  structurally.
- Two transforms of one type in one call end the call with a fault.

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

### B. The equality of one type

A modifier `equate-with(f)` would take the equality of one type, as
`cmp.Comparer` and `withEqualsForType` do. A caller would pass `proto.Equal`.

**Why not:** the record would state the values themselves, with their
private state. Two messages whose fields differ would render a diff of the
cached size and the message info besides the field that differs.

### C. A comparison that skips the state of the protobuf runtime

Go's comparison would skip the unexported fields of the types of
`google.golang.org/protobuf/internal/impl`, found by their package path.

**Why not:** the rule would depend on the names of the internal package of
another module, which a release of that module can change. It would also
compare the unknown fields as bytes in their internal form.

## Drawbacks

- Each call that compares messages states the option.
- A transform that drops a field makes two values that differ in that field
  compare equal.
- A Go `Option` keeps state for the first time.
- The protobuf module adds a module and a dependency to assert-go, though
  not to `go.dokimi.dev/assert`.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/29> |
| The modifier `by-identity`, whose reach this modifier takes | [RFC-0023](0023-comparing-references-by-identity.md) |
| go-cmp's `Transformer` and `Comparer` | <https://pkg.go.dev/github.com/google/go-cmp/cmp> |
| `protocmp.Transform` | <https://pkg.go.dev/google.golang.org/protobuf/testing/protocmp> |
| AssertJ's recursive comparison | <https://assertj.github.io/doc/#assertj-core-recursive-comparison-comparators> |
