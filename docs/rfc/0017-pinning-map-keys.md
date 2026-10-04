---
rfc: 0017
title: Pinning map keys
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-10-04
updated: 2026-10-04
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0017: Pinning map keys

## Summary

`contains` states that a key compares as `equal` compares, and `equal`
compares two maps by their entries. The corpus checks both rules with
string keys alone. The target languages' own map lookups disagree on
three other keys: a NaN, a negative zero and null. Version 3.0.0 adds 12
corpus cases that pin each of them under `contains`, `not-contains`,
`equal` and `not-equal`, by default and under `equate-nans`.

## Motivation

Each language's map lookup matches a key by the language's own
equality. Measured on 2026-10-04, none of them matches every key as the
definition does:

| Lookup | NaN key, NaN needle | -0 key, +0 needle | Null key, null needle |
|---|---|---|---|
| The definition | Not found. Found under `equate-nans` | Found | Found |
| Go 1.27.1, a map index | Not found, under `equate-nans` too | Found | Found |
| Node 26.10.0, `Map.has` | Found | Found | Found |
| Java 27, `HashMap.containsKey` | Found | Not found | Found |
| Python 3.14.8, `in` on a `dict` | Found when the needle is the key's own object | Found | Found |

A library that passes the question to its language's lookup passes
every case that the corpus states today. It still reports a different
result for these keys in each language. A test that asserts that a map
contains NaN passes in JavaScript and Java and fails in Go. That is the
drift RFC-0001 exists to catch. RFC-0014 pinned the answers of this
kind that it found, and map keys were not among them.

## Detailed design

### The rules the cases pin

The definition already states each rule, and the cases make each one a
check:

- A key compares as `equal` compares. A NaN key matches no needle, a
  NaN needle included. Under `equate-nans`, a NaN needle matches a NaN
  key.
- A -0 key matches a +0 needle, because floats compare by value.
- A null key matches a null needle.
- Two maps are equal when a one-to-one matching pairs each entry of one
  with an entry of the other whose key and value are equal. A map with a
  NaN key equals no map without `equate-nans`, itself included.

### The cases

A JSON object's keys are strings, so a map with a NaN, negative zero or
null key states its entries:

```json
{
  "type": "map",
  "entries": [[{ "type": "float", "value": "NaN" }, { "type": "int", "value": 1 }]]
}
```

| Case | Arguments | Options | Expect |
|---|---|---|---|
| `contains/a-nan-key-is-not-found` | `{NaN: 1}`, NaN | | fail |
| `contains/a-nan-key-is-found-under-equate-nans` | `{NaN: 1}`, NaN | `equate-nans` | pass |
| `contains/a-negative-zero-key-matches-zero` | `{-0: 1}`, 0 | | pass |
| `contains/a-null-key-is-found` | `{null: 1}`, null | | pass |
| `not-contains/a-nan-key-is-not-contained` | `{NaN: 1}`, NaN | | pass |
| `not-contains/a-nan-key-is-contained-under-equate-nans` | `{NaN: 1}`, NaN | `equate-nans` | fail |
| `not-contains/a-null-key-is-contained` | `{null: 1}`, null | | fail |
| `equal/maps-with-a-nan-key-differ` | `{NaN: 1}`, `{NaN: 1}` | | fail |
| `equal/maps-with-a-nan-key-are-equal-under-equate-nans` | `{NaN: 1}`, `{NaN: 1}` | `equate-nans` | pass |
| `equal/a-negative-zero-key-equals-a-zero-key` | `{-0: 1}`, `{0: 1}` | | pass |
| `not-equal/maps-with-a-nan-key-differ` | `{NaN: 1}`, `{NaN: 1}` | | pass |
| `not-equal/maps-with-a-nan-key-are-equal-under-equate-nans` | `{NaN: 1}`, `{NaN: 1}` | `equate-nans` | fail |

The cases state no detail. The runner still checks that a failure's
record contains exactly the fields that the assertion declares. The
order in which a record lists a map's entries is not part of this
change.

Rust's standard maps need keys that implement `Eq` and `Hash`, or `Ord`,
and `f64` implements none of them. The six cases with a float key and
no relaxation carry a skip for Rust. Rust declines `equate-nans`, so the
other four float cases do not apply to it.

### Version

A pinned answer fails an implementation that gave a different one, so
the definition moves to 3.0.0 under the versioning rule. Every overlay
extends 3.0.0.

## Alternatives considered

### A. Each language's own lookup

The definition would state that a key matches as the language's own map
matches it.

Rejected because the same test would then pass in one language and fail
in another, for each key in the motivation's table.

### B. Leave map keys unpinned

Rejected because only a case fails a build, and every lookup measured
above breaks the rule for at least one key.

## Drawbacks

- An implementation whose language's lookup disagrees needs a key
  comparison of its own. For a key that its language cannot hash by the
  definition's rule, it matches entries in quadratic time.
- An implementation whose corpus runner decodes no map with entries
  gains that decoding.
- Rust declares six skips.

## Open questions

None.

## Unresolved and future work

None.

## References

| What | Where |
|---|---|
| The rule for a key | `spec/assertions.yaml`, `contains`, and RFC-0014, "The answers the corpus pins" |
| A map with entries | `spec/encoding.md` |
| The versioning rule | `README.md`, "Versioning" |
| JavaScript's key equality | ECMAScript, SameValueZero |
| Java's key equality | `java.lang.Double.equals` |
| Python's membership test | The Python Language Reference, "Membership test operations" |
