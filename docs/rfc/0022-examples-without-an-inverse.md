---
rfc: 0022
title: Examples without an inverse, and any number of examples in one option
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-06
updated: 2026-10-06
discussion: https://github.com/dokimasia/assert-spec/issues/3
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0022: Examples without an inverse, and any number of examples in one option

## Summary

A property form takes an example only of an input whose generator runs
backwards. A form over an input built with `map`, `bind` or `composite`
ends before its first case, because the engine cannot compute the
example's choices. Under this proposal such an example runs on its
values: a case without choices, which does not shrink. Its failure is the
run's counterexample as found, with no replay token.

A form over one input also gains `examples`, one option that states any
number of examples, one value per case. `example` keeps its meaning, and
remains the option of the forms over two and three inputs.

The generator vocabulary of the vectors gains `map`, so a vector can state
an input without an inverse.

## Motivation

### A composite input takes no example

A property over two related inputs states its domain with `composite`
when the bounds of one draw depend on the other. A caller pins a known
input with `example`. The definition states the example by its choices:
the engine runs the input's generator backwards, and decoding the
computed choices returns the value. `map`, `bind` and `composite` apply a
function that the engine cannot invert, so a form over such an input
takes no example at all:

```go
type growth struct{ have, n int }

prop.Equal(t, grow, reference, "growth doubles the capacity or takes the request",
	prop.Using(prop.Composite(func(c *prop.Case) growth {
		have := c.Draw(prop.Integer(0, 64), "have")
		return growth{have: have, n: c.Draw(prop.Integer(have+1, have+256), "n")}
	})),
	prop.Example(growth{have: 50, n: 75}))
```

The property ends before its first case with `prop.Equal:
Example[0][0]: composite has no inverse`. A caller who knows that the
boundary row `have` 50, `n` 75 matters can pin it only by fixing one
input as a constant, and the property then covers one capacity.

### One option per example

`example` states one case, with one value per generated argument. A form
over one input takes one option per example, so a property with seven
known inputs reads `prop.Example(1), prop.Example(2), …,
prop.Example(17)`. One option with two values fails when the property is
built, because the form generates one argument.

## Detailed design

### An example of an input without an inverse

The form still computes each example's choices by running the input's
generator backwards. The inverse now tells two refusals apart:

| Refusal | When | What happens |
|---|---|---|
| The value is outside the domain | An invertible generator cannot produce the value, such as a string longer than its `max_size` | The property fails when it is built |
| No inverse | A generator on the way applies a function that the engine cannot invert | The example runs on its values |

A generator has no inverse when it is built with `map`, `bind` or
`composite`, or when the part that would produce the value has none:

- A `filter`, a collection, an `optional`, a record and a variant pass on
  the refusal of the generator inside them.
- A `one-of` and a `recursive` run backwards through the first
  alternative whose inverse succeeds. When none succeeds and one of them
  has no inverse, they report no inverse.

An example that runs on its values is a case without choices:

- Each draw of a generated argument returns the example's value for it,
  in the argument order, and the case records no choice for it.
- The case runs in the phase `example`, in the order of the options, as
  every example does. Its calls are recorded under that phase.
- A passing case counts as a valid case.
- A failing case is not replayed, shrunk or explained. The run ends as a
  counterexample as found: `counterexample` states the example's draws,
  each with its value and with `any-value-fails` and `nearest-passing`
  null, `failure` states its failure, `choices` is null and `others` is
  empty.
- The run writes no store entry for it. An entry records choices, and the
  example's values are already in the test's source.

A value that `example` states is not checked against a domain when its
input has no inverse. The engine has no way to tell whether the generator
produces it.

### Any number of examples in one option

```text
examples[T](values...T) -> Option
    Runs a property form over one input first on one case per value, in
    order, as example with that one value runs it.
```

A form that generates two or three arguments, `commutative` and
`associative`, fails when the property is built when it takes `examples`,
and the failure names the option. `example` and `examples` run in the
order of the options, and each `examples` runs its values in order.

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `prop.examples` | `prop.Examples` | `prop.examples` | `prop::examples` | `prop.examples` | `Prop.examples` | `Prop.examples` |

### Go

```go
// Examples makes the property form over one input that it is passed to run
// a case of each value before its stored cases, in order, as Example of that
// one value does.
func Examples[T any](values ...T) FormOption
```

`Example` keeps its signature. The engine's inverse reports a generator
without an inverse with a fault of the kind `ErrNoInverse`, which wraps
`ErrCannotInvert`.

### The vectors

The generator vocabulary gains `map`:

```json
{"gen": "map", "of": {"gen": "integer", "min": 0, "max": 9}, "subject": "identity"}
```

`map` decodes a value of `of`, makes its choices and opens no span of its
own, and returns what the function of the subject kind returns for the
value. The subject kinds are those of the definition's subjects table
that a form's function takes: `identity`, `is-non-negative`,
`returns-null`, `drops-the-first`, `prepends-zero`, `sorts` and
`wraps-in-a-and-b`. `map` has no inverse. A map of an integer is an
integer for the explain phase: its nearest passing value is the map of
the integer one step towards its target.

`map` joins the generator ids, so it has the vectors that every generator
has. A forms vector takes `generator` in place of `shape`, as a generation
vector does, and an optional `examples`: a list of typed literals, one per
case, which the runner passes through `examples`. These vectors are added:

| Vector | Pins |
|---|---|
| Two decoding vectors of `map` | Its value is the function of the value of `of`, from the choices of `of` |
| A generation vector of `map` | It draws what its source draws |
| Two shrinking vectors of `map`, one that fails and one that passes | The shrinker edits the choices of `of` |
| An inverse vector of `map` | It refuses a value that `of` produces |
| `prop-true` with three passing examples | The examples count as valid cases |
| `prop-true` with a failing second example | The run fails at the example after one valid case, and shrinks it |
| `prop-true` over `map` with a failing example | The example runs on its value, outside the domain of `of`, and fails as found with no token |
| `prop-true` over a `one-of` of an integer and a `map` with a failing example | No alternative produces the value and the map has no inverse, so the one-of has none |
| `prop-equal` over `map` with a passing example | A case without choices passes |

### Version

Adding a helper is a minor version change. Running an example that used
to fail when its property was built is a minor change too. Definition
5.2.0 adds `examples`, the runs of an example without an inverse, and the
generator `map` of the vectors.

## Alternatives considered

### A. An inverse that the caller passes to `composite`

`composite` would take a second function, which returns the values of the
labelled draws for a value. The engine would run each draw's generator
backwards from those values.

**Why not:** every composite then needs a second function that agrees
with the first. The engine finds a disagreement only when an example
decodes to another value. The second function covers neither `map` nor `bind`,
because they take no labelled draws. Shrinking an example also adds less
than shrinking a generated case, because the caller already knows that
the example's input matters.

### B. An example as a `Draws` case

The example would be stated as the entries of `Draws`: a label and a
typed literal per draw.

**Why not:** a typed literal states a value of the encoding, and the
value of a composite is a type of the caller's own, such as a struct. The
draw would receive a map or a record in place of that type.

### C. `examples` of tuples for the forms over two and three inputs

`examples` would take one tuple per case.

**Why not:** a tuple of values of one type is not a type in every
language, and `example` already states one case of two or three values.

## Drawbacks

- **A failing example without an inverse does not shrink.** The record
  shows the example as the caller stated it, which can be larger than the
  part of it that matters.
- **Its failure has no replay token and no store entry.** The example is
  in the test's source, so every run tries it again, but a replay variable
  cannot select it.
- **The vocabulary of the vectors grows by one generator,** which every
  conformance runner builds from the functions of its subjects.
- **The inverse distinguishes two refusals,** which adds one kind of
  fault to each implementation's inverse.

## Unresolved and future work

- An inverse for `map` that the caller states is not proposed here.

## References

| What | Where |
|---|---|
| Hypothesis, explicit examples, which run on their values and do not shrink | <https://hypothesis.readthedocs.io/en/latest/reference/api.html> |
| fast-check, the `examples` setting of a property | <https://fast-check.dev/docs/configuration/user-definable-values/> |
