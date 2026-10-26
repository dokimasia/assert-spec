---
rfc: 0039
title: A stated recursive generator of its own type
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-26
updated: 2026-10-26
discussion: https://github.com/dokimasia/assert-spec/issues/21
supersedes: RFC-0037, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0039: A stated recursive generator of its own type

## Summary

Inside the stated generator of a type, a draw of `of` of that type decodes
without the stated generator. A type whose values come from a stated
generator alone, such as an interface of Go, then has no value that
contains another value of the type. This proposal makes one exception:

- Inside the extension of a `recursive` generator of values of a type `T`,
  where the run states the generator of `T`, a draw of `of` decodes each
  value of `T` with the generator of the position that `recursive` passes
  to the extension.
- The leaf budget of `recursive` ends the recursion. Once a value has drawn
  `max_leaves` values from the base, each further position takes the base.
- The exception applies at every depth of the extension, inside the stated
  generators of other types too, so a cycle of two types ends as well.
- Every other stated generator keeps the rule of RFC-0037.

Definition 12.0.0 states the exception.

## Motivation

dokimi's suite generator states an implementation of each interface that
the inputs of a callable take, through `using`. The implementation returns
the results that the case draws for each method. For this interface the
stated generator of `Node` draws `of` of `[]Node` for the results of
`Children`:

```go
// Node is a node of a tree.
type Node interface {
	// Children returns the children of the node.
	Children() []Node
}

nodes := prop.Recursive(prop.Just[Node](leaf{}), func(prop.Generator[Node]) prop.Generator[Node] {
	return prop.Composite(func(c *prop.Case) Node {
		return branch{children: c.Draw(prop.Of[[]Node](), "children")}
	})
})
prop.ForAll(t, "draws a tree", func(c *prop.Case) {
	_ = c.Draw(prop.Of[Node](), "node")
}, prop.Seed(7), prop.Using(nodes))
```

On assert-go at 987000d the first case draws the base and passes. The
second case draws the extension, and its draw of `of` of `[]Node` reads
`Node` without the stated generator:

```text
failure at node_test.go:26: prop: Of[[]probe.Node]: []probe.Node[]: probe.Node has no variants, which RegisterVariants states
```

The same rule stops a function type that returns itself, such as
`type StateFn func(*Lexer) StateFn`, and two interfaces whose methods
return each other. Inside the stated generator of the first, the stated
generator of the second decodes without both.

A caller can compose the recursion today. The extension draws `list(self)`
in place of `of` of `[]Node`, and the same run passes. That covers a
position of `T`, a list of `T` and a map of `T`. A struct or a pointer
that contains `T` needs the caller to compose the struct field by field.
The caller then repeats the shape reader, and the constraints of the
struct's fields no longer apply. dokimi generates the stated generators,
and it would have to generate that composition for every type that
contains an interface.

## Detailed design

### The rule

A run states the generator of a type `T` with `using`. A `recursive`
generator `R` of values of `T` decodes inside that stated generator, as
the stated generator itself or as a part of it, such as the generator
that a `filter` or a `map` of `R` wraps.

While `R` decodes an extension, a draw of `of` of any type decodes each
value of `T` that the type contains with the generator of the position
that `R` passed to the extension. A draw of `of` of `T` itself is such a
draw.

| Draw | Before | After |
|---|---|---|
| `of` of `T` inside the extension of `R` | `T` without its stated generator | The position generator of `R` |
| `of` of a type that contains `T`, inside the extension of `R` | Each `T` without its stated generator | Each `T` from the position generator of `R` |
| `of` of `T` inside the base of `R` | `T` without its stated generator | Unchanged |
| `of` of `T` inside any other stated generator of `T` | `T` without its stated generator | Unchanged |

The position generator takes the base or the extension at each position,
as RFC-0010 states for `recursive`. Once one value of `R` has drawn
`max_leaves` values from the base, every further position takes the base,
so the value is finite. The base is outside the rule, because a position
that takes the base must end the recursion.

### Depth and cycles

The rule applies while the extension decodes, at every depth:

- A draw inside a `list`, a `composite` or another generator that the
  extension decodes follows the rule.
- A draw inside the stated generator of another type `U`, which the
  extension decodes through a draw of `of`, follows the rule for `T`. The
  run's rule for `U` applies as before.

Two interfaces `A` and `B` whose methods return each other end when the
run states a `recursive` generator for one of them. Inside the extension
of the generator of `A`, each `B` decodes with the stated generator of
`B`. Inside that, each `A` decodes with the position generator of `A`,
whose budget ends the cycle. When the run states a `recursive` generator
for both, each keeps its own budget, and each ends.

### Inverses and stored cases

A draw runs backwards under the same rule. An entry of `draws` or an
example whose value contains `T` runs each `T` inside the extension back
through the position generator of `R`. The position generator refuses a
value as RFC-0022 states for `recursive`. An extension built with
`composite` has no inverse, so an example of such a value runs on its
values.

A stored case of a run that states a `recursive` generator replays under
the rule, so its choices decode to other values than under 11.0.0.

### The languages

The signatures of the languages do not change. The rule changes what a
draw of `of` decodes:

| Language | The draw | The recursive generator |
|---|---|---|
| Go | `prop.Of[T]()` | `prop.Recursive(base, extend, opts...)` |
| Python | `prop.of(t)` | `prop.recursive(base, extend, max_leaves=...)` |
| Rust | `prop::of::<T>()` | `prop::recursive(base, extend)` |
| Java, Kotlin | `Prop.of(T.class)` | `Prop.recursive(base, extend)` |

TypeScript declines `using` outside the input of a property form, as its
overlay states, because the compiler erases every type. Its runs have no
stated generator of a type, so the rule does not apply.

### Names

The naming table does not change.

### Conformance

The executable reference has no `using`, so no vector covers the rule.
Each implementation that takes `using` tests the rule in its own specs:

- A stated `recursive` generator of an interface whose extension draws
  `of` of a list of the interface generates values that contain other
  values of the interface, and the run passes.
- A struct field and an optional of `T` inside the extension take the
  position generator.
- A value never draws more than `max_leaves` values from the base.
- Inside the base, and inside a stated generator that is no `recursive`
  generator, a draw of `of` of `T` decodes without the stated generator.
- A cycle of two interfaces ends.

### Version

The rule changes how a draw of `of` decodes choices inside a stated
`recursive` generator, so stored cases and replay tokens of such a run
decode to other values. RFC-0010 makes such a change a major version, so
the definition moves to 12.0.0. Every overlay extends 12.0.0.

## Alternatives considered

### A. Compose the recursion in the caller

The extension would draw `list(self)`, `optional(self)` and the other
positions itself, as it can today.

**Why not:** a struct or a pointer that contains `T` needs the caller to
compose the struct field by field, which repeats the shape reader and
drops the constraints of the fields. dokimi would generate that
composition for each type that contains an interface.

### B. A stated generator that draws itself

Inside the stated generator of `T`, a draw of `of` of `T` would decode
with the stated generator, for every stated generator.

**Why not:** a stated generator such as
`using(of(Order).filter(valid))` would draw itself without end. RFC-0037
keeps that rule for a reason, and only `recursive` has a budget that ends
the recursion.

### C. A deferred generator

The library would add `deferred`, a generator that names another
generator that a later line defines, as Hypothesis's `deferred` and
rapid's `Deferred` do. The stated generator of `T` would draw its own
deferred generator.

**Why not:** it adds a generator to the definition and to the naming
table, and it does not bound a value. rapid's documentation states that a
generator of a recursive type may not terminate. `recursive` already
exists and has a budget.

### D. Register the variants of the interface

`register-variants` would state an implementation of the interface as a
variant. The shape reader would read the variant's payload.

**Why not:** a registration applies to the whole test process. A second
registration of one type fails. dokimi states an implementation for each
callable that it tests. An implementation whose results the case draws is
no type with a shape.

## Drawbacks

- The definition moves to a major version. Every implementation of
  `using` changes the meaning of a draw inside a stated `recursive`
  generator. Stored cases of such runs decode to other values.
- The rule is an exception to the rule of RFC-0037. A reader of a stated
  generator has to know whether it is `recursive`.
- The engine tracks the position generator of each `recursive` generator
  whose extension is decoding, for every draw of `of` inside it.
- No vector covers the rule, so the specs of each library alone test it.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/21> |
| The generator `recursive` and the versions of the definition | RFC-0010 |
| The option `using` and the recursion of a shape | RFC-0011 |
| Examples without an inverse | RFC-0022 |
| The rule inside a stated generator | RFC-0037 |
| Hypothesis, `recursive` and `deferred` | <https://hypothesis.readthedocs.io/en/latest/reference/strategies.html> |
| rapid, `Deferred` | <https://pkg.go.dev/pgregory.net/rapid#Deferred> |
