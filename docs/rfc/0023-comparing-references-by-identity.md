---
rfc: 0023
title: Comparing references by identity
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-06
updated: 2026-10-06
discussion: https://github.com/dokimasia/assert-spec/issues/4
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0023: Comparing references by identity

## Summary

`equal` compares structurally, and `not-equal`, `contains`,
`not-contains`, `permutation` and `no-duplicates` compare as `equal`
compares. So a reference equals any other reference to an equal
value, and no assertion of the standard can state that two references
refer to different objects, such as the buffers that an allocator hands
out. This proposal adds the modifier `by-identity` to those six
assertions. Under it, a reference equals another reference only when
both refer to the same object. A value that is no reference compares as
before.

The typed-literal encoding gains `reference`, so a corpus case can state
two objects of equal values, and one object twice.

## Motivation

### Two allocations compare as one

An allocator hands out buffers, and no two buffers in use may be the same
memory. The natural check is `no-duplicates` over the buffers. Under the
standard's equality, two buffers of equal content are duplicates, and two
fresh allocations of one value always are:

```go
a, b := new(int), new(int)
assert.NoDuplicates(t, func() ([]*int, error) { return []*int{a, b}, nil },
	"two allocations are two pointers")
```

The check fails, and names the second pointer as the duplicate of the
first, although `a == b` is false. A test that needs the check converts
each reference to an integer address first, as Go's `reflect.Value.Pointer`
does. TypeScript, whose references have no integer form, has no such
conversion.

### Every target language has identity

Each language compares references by identity with one operator: `==` on
Go pointers, `==` on Java references, `===` in Kotlin and TypeScript, `is`
in Python, and `std::ptr::eq` in Rust. testify's `Same`, JUnit's
`assertSame` and Jest's `toBe` assert identity of two values. None of them
states identity for the elements of a collection, which is what the
allocator's check needs.

## Detailed design

### The modifier

A relaxation widens what counts as equal for one call. `by-identity`
narrows it for references, so the definition's section of relaxations
becomes the section of the modifiers of a comparison:

```yaml
relaxations:
  "by-identity":
    summary: >
      A reference equals another reference only when both refer to the
      same object, whatever the object's value. A value that is no
      reference compares as without it. The modifier applies wherever the
      comparison meets a reference: at the top, in an element of a list, in
      a value of a map and in a field of a record. What a reference is in
      each language is stated where the encoding states the reference
      literal.
```

The section keeps its key, `relaxations`, in the assertion table, the
naming table and the overlays, because renaming a key is a major change.
The comment above it states that a modifier widens or narrows.

`by-identity` applies wherever the comparison meets a reference: at the
top, in an element of a list, in a value of a map and in a field of a
record. It combines with `equate-empty` and `equate-nans`, which apply to
the values that are no references.

| Assertion | Under `by-identity` |
|---|---|
| `equal`, `not-equal` | got and want are the same object, or contain the same objects where they contain references |
| `contains`, `not-contains` | the haystack has the needle itself as an element |
| `permutation` | got has want's objects, each as often |
| `no-duplicates` | no object appears twice |

The property forms of `equal`, `not-equal`, `contains`, `not-contains`
and `permutation` take the modifier as they take every relaxation of
their assertion.

### The references of each language

| Language | References | Same object |
|---|---|---|
| Go | Pointers, maps, slices, channels and functions | The same address. Two slices are the same object when they start at the same address and have the same length |
| Python | Every object but `None`, a `bool`, an `int`, a `float`, a `str`, `bytes` and a `tuple`, whose items compare one by one | `is` |
| Java, Kotlin | Every object but a `String` and the box of a primitive | `==` in Java, `===` in Kotlin |
| TypeScript | Objects, arrays and functions | `===` |
| Rust | Declined | |

Rust's assertions compare through `PartialEq`, as its overlay states for
`equate-empty` and `equate-nans`, and a caller compares two references
with `std::ptr::eq`. Its overlay declines `by-identity` with that reason.

A Go function compares by its code pointer without the modifier as well,
as the standard states for every comparison of two functions.

### The literal

```json
{"type": "reference", "id": "a", "value": {"type": "int", "value": 1}}
```

Within one corpus case, every `reference` of one `id` is one object, and
each states the same value. An implementation decodes the first literal of
an id to a new object of the value, and each later literal of the id to
that object. In Go, the object is a pointer to the value. A record states
a reference as the literal of the value it refers to. The record is kept
after the objects of its run are gone.

The validator refuses these literals:

- a `reference` whose value is null
- two literals of one id in one case that state different values
- a `reference` in a record

### The subjects

`no-duplicates` takes a callable. Its cases name two new subjects:

```yaml
"yields-one-object-twice":
  summary: >
    Yields one object twice. The object's value is 1.
"yields-two-equal-objects":
  summary: >
    Yields two objects, and the value of each is 1.
```

### The corpus

| Assertion | Cases |
|---|---|
| `equal` | One object passes under `by-identity`. Two objects of equal values fail under it, and pass without it |
| `not-equal` | Two objects of equal values pass under `by-identity`, and one object fails under it |
| `contains` | A list of the object passes under `by-identity`, and a list of an equal object fails under it |
| `not-contains` | A list of an equal object passes under `by-identity` |
| `permutation` | The same objects in another order pass under `by-identity`, and an equal object in place of one fails under it |
| `no-duplicates` | `yields-two-equal-objects` passes under `by-identity` and fails without it, and `yields-one-object-twice` fails under it |

The corpus grows by these 13 cases, from 182 to 195.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `by-identity` | `ByIdentity` | `by_identity` | Declined | `byIdentity` | `Option.BY_IDENTITY` | `Option.BY_IDENTITY` |

### Go

```go
// ByIdentity makes a pointer, a map and a slice equal another only when
// both are the same object, for the call it is passed to: the same address,
// and for a slice the same length as well. It applies at every depth: at
// the top, in an element, in a map's value and in a field. A value that is
// no reference compares as without it, and a function compares by its code
// pointer under every rule.
func ByIdentity() Option
```

`assert` and `expect` each declare it beside `EquateEmpty` and
`EquateNaNs`. The equality of `internal/equality` gains the rule.
`permutation` and `no-duplicates` match their elements with that equality,
so under the rule they match objects.

### Version

Adding a modifier and a literal type is a minor version change: no case
that exists states either. Definition 5.2.0 adds both.

## Alternatives considered

### A. The assertions `same` and `not-same`

testify, JUnit and Jest state identity as assertions of two values.

**Why not:** they cover `equal` and `not-equal`, and the allocator's check
needs identity for the elements of a collection, in `no-duplicates` and
`permutation`. A pair of assertions per comparison would add eight.

### B. A second section of modifiers beside the relaxations

The modifiers that narrow a comparison would get a section of their own.

**Why not:** the naming table, the overlays and every conformance runner
read one section of modifiers already. A second section duplicates that
reading in six languages, for one modifier.

### C. Identity at the top of the values alone

`by-identity` would compare got and want, or the elements of a
collection, by identity, and compare whatever they contain as `equal`
compares.

**Why not:** a record that refers to a buffer, such as a Go struct with a
pointer field, would then compare by the buffer's content. Two records that
refer to different buffers would be equal under the modifier, and a caller
who asks for identity asks it of every reference that the comparison
meets.

## Drawbacks

- **The references differ by language.** The table is part of the
  definition, and a value that is a reference in one language, such as a
  Python list, is a value in another, such as a Go array.
- **A list compares by identity under the modifier,** because a list is a
  reference in Go, Python, Java, Kotlin and TypeScript. `equal` under
  `by-identity` passes for a list and that list itself. A caller who checks
  the objects of two lists in order compares the lists element by element.
- **A record states the values of the objects that it compares,** so the
  record of two equal objects that differ by identity states two equal
  values.
- **Rust declines the modifier,** so the corpus cases of `by-identity`
  are skips in Rust.
- **The relaxations section now contains a modifier that narrows,** and
  its key no longer describes every member.

## Unresolved and future work

- Identity for the results that `deterministic`, `idempotent` and the
  other relations compare is not proposed here.

## References

| What | Where |
|---|---|
| testify v1.12.0, `Same` and `NotSame` | <https://github.com/stretchr/testify/blob/v1.12.0/assert/assertions.go> |
| go-cmp v0.7.0, the equality of pointers | <https://github.com/google/go-cmp/blob/v0.7.0/cmp/compare.go> |
| JUnit 5, `assertSame` | <https://docs.junit.org/current/api/org.junit.jupiter.api/org/junit/jupiter/api/Assertions.html> |
| Jest, `toBe` | <https://jestjs.io/docs/expect#tobevalue> |
