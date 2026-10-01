---
rfc: 0011
title: Property forms and inputs derived from types
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-10-01
updated: 2026-10-01
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0011: Property forms and inputs derived from types

## Summary

Every assertion that examines a value gets a property form under the
same name in the `prop` package. Where the assertion takes a value, the
property form takes a function, and the engine calls that function with
inputs it generates from the function's parameter type:

```go
prop.Equal(t, fastSort, referenceSort, "fastSort agrees with the reference")
prop.NoError(t, roundTrip, "every order survives encoding and decoding")
prop.InRange(t, Order.Total, 0, math.MaxInt64, "a total is never negative")
```

The generator for a type is not left to each language's reflection. A
language reads its type into a shape, and the definition maps every shape
to one generator. Two types with the same shape produce the same values
from the same seed in every language, and the corpus checks that. A
shape is data, so one language can write a type's shape to a file and
another can generate from the file. TypeScript, whose types are erased,
derives its inputs that way.

Every derived generator also runs backwards, from a value to the choices
that produce it. A known input, from a bug report or from production,
runs as an example and shrinks like a generated one. The counterexample
a run reports is an example the same run accepts.

This builds on the property engine proposed beside it: its choices,
generators, run, shrinker and store.

## Motivation

### A caller already knows the assertions

The property engine requires a caller to learn a second vocabulary: a run,
a case, draws and generators. A caller of this standard already knows
the assertions, and the most common properties are those assertions
stated for every input rather than one:

| Property | Today, for one input | As a property form |
|---|---|---|
| Two implementations agree | `assert.Equal(t, fast(x), ref(x), msg)` | `prop.Equal(t, fast, ref, msg)` |
| A function never fails on valid input | `assert.NoError(t, f(x), msg)` | `prop.NoError(t, f, msg)` |
| A function never panics | `assert.NotPanics(t, func() { f(x) }, msg)` | `prop.NotPanics(t, f, msg)` |
| A result is within bounds | `assert.InRange(t, f(x), lo, hi, msg)` | `prop.InRange(t, f, lo, hi, msg)` |
| An invariant | `assert.True(t, ok(x), msg)` | `prop.True(t, ok, msg)` |

A study of how developers at one company use property-based testing
interviewed 31 of them in 30 interviews. Differential properties, which
compare an implementation with a reference, were the most common: 17 of
the 30 interviews described them. Round-trip properties followed at 11,
and properties that only provoke a crash or an uncaught exception at 7.
The first is `prop.Equal` and the third `prop.NotPanics`. The second is
the relation family's `round-trip`, which gets a property form the same
way.

### Writing a generator is the cost

In the same study, 19 of the 30 interviews described generators written
by hand and 19 described generators derived from types. Participants
called writing generators tedious in 6 interviews and high-effort in 7.
The authors record as an observation that developers see writing
generators as a distraction and prefer derived generators.

A property form with a derived input needs no generator at all. A caller
writes one only when the type admits values the domain does not, and
then only for that type.

### Deriving from types already exists, and means something different everywhere

Hypothesis's `from_type`, proptest's derived `Arbitrary` and Kotest's
`checkAll` with only type parameters each turn a type into a generator,
and each does it by its own rules: which integer range a field gets,
whether a float field produces NaN, how deep a recursive type goes, in
which order fields are generated. A derived generator then produces
different values in each language for the same declared type. The
property engine fixes generation everywhere else, and deriving by each
language's rules would reopen the gap at the most convenient entry point.

The assertion set excluded anything that reads a language's type system,
because six type systems give six answers. This proposal keeps that
exclusion where it matters and moves it: reading a type is per language,
and what a type means as a domain is not.

## Detailed design

### Shapes

A shape is a language-neutral description of a type's values. Each
language reads its own types into shapes. The definition maps each shape
to a generator of the property engine, and that mapping is fixed.

| Shape | Parameters | Generator |
|---|---|---|
| `bool` | | `boolean` with p = 1/2 |
| `int` | `width` of 8, 16, 32 or 64, `signed` | `integer` over the width's whole range |
| `float` | `width` of 32 or 64 | `float` over the finite values; no NaN, no infinity |
| `string` | | `string` with the default alphabet |
| `bytes` | | `bytes` |
| `list` | `of` | `list` of `of` |
| `fixed-list` | `of`, `size` | `list` of `of` with `min_size` and `max_size` both `size` |
| `map` | `key`, `of` | `dict` of `key` to `of` |
| `optional` | `of` | `optional` of `of` |
| `record` | ordered `fields`, each a name and a shape | Each field in order, as one span |
| `enum` | ordered `variants`, each a name and an optional payload shape | `one-of` over the variants, then the payload |
| `literal` | ordered `values` | `sampled-from` over the values |

A shape may have constraints, which narrow its generator:

| Constraint | Applies to | Effect |
|---|---|---|
| `min`, `max` | `int`, `float` | Bounds the value |
| `min_size`, `max_size` | `string`, `bytes`, `list`, `map` | Bounds the size |
| `pattern` | `string` | Generates with `string-matching` |
| `alphabet` | `string` | Replaces the default alphabet |
| `allow_nan`, `allow_infinity` | `float` | Admits NaN or the infinities |

A derived float produces no NaN and no infinity unless a constraint
admits them. NaN is unequal to itself under this standard, so a default
that produced it would fail every `prop.Equal` over a float field for a
reason the caller did not ask about. A caller who tests NaN handling
admits NaN with a constraint.

A value of a recursive shape has a budget of 100 nodes, counted in the
order the nodes are generated, as Hypothesis's `recursive` bounds a
value by 100 leaves. Once a value has used its budget, every `optional`
of the recursive type is absent and every `list` and `map` of it is
empty, so a tree type terminates without a caller stating a bound. A
depth cut would not bound the size. A node with a list of children, at
the default average of 5, grows fivefold per level, to about 780 nodes
at depth 4.

The rule that makes the guarantee: **two types with the same shape,
meaning the same fields in the same order with the same constraints,
produce the same values from the same seed in every language.**

### Reading a type into a shape

Each language reads its types its own way. The mapping from a native type
to a shape is in the naming table, so the gate checks it. It is the only
part of derivation that a language decides.

| Language | Reads types through | Derives | Does not derive |
|---|---|---|---|
| Go | `reflect`, from a type parameter | `bool`, the sized integers, `float32`, `float64`, `string`, `[]byte`, slices, arrays, maps, structs, pointers as `optional` | Interfaces without registration, channels, functions. Unexported fields keep their zero value |
| Python | `typing.get_type_hints` | `bool`, `int`, `float`, `str`, `bytes`, `list`, `dict`, `tuple`, `Optional` and unions, `Literal`, `Enum`, dataclasses, `TypedDict`, `NamedTuple` | `Any`, and protocols without registration |
| Rust | A derive macro, at compile time | Primitives, `String`, `Vec`, `HashMap`, `BTreeMap`, `Option`, structs, enums | Trait objects. A type from another crate needs a newtype or a registration |
| Java | Reflection | Primitives and their boxes, `String`, `List`, `Map`, `Optional`, records, enums, sealed interfaces | A plain class, because reflection does not promise its fields' order |
| Kotlin | Kotlin reflection | Data classes in constructor order, sealed classes, enums, the collections | |
| TypeScript | Shape files only; types are erased at run time | Every type whose shape file another language wrote, or a person | Every type without a shape file |

Field order is declaration order, and it decides which choices a field
consumes. That is why Java's plain classes are not derived: two JVMs may
return their fields in different orders, and the same seed would then
produce different values.

Width follows the language's type. A Go `int` is a 64-bit `int` on a
64-bit platform. A Python `int` has no width, so it maps to a signed
64-bit `int`, and a caller who wants another width states it with a
constraint. A Java `int` is 32 bits. A Go struct and a Python dataclass
produce the same values only when their fields agree in width, and a
caller porting a test between them aligns the widths.

A type whose construction can fail, such as a Java record whose
canonical constructor validates its arguments, is built through that
constructor. A construction that throws fails the case, and the failure
is the constructor's error. The shrinker reduces it to the smallest input
the constructor refuses, which shows the caller the constraint the shape
needs, or that the type needs a registered generator. Hypothesis's
`builds` lets a constructor's exception fail the test the same way.
Rejecting the case instead would hide a constructor that throws on a
valid input.

### Shape files

A shape is data, so a language can write the shape of a type out and
another can generate from it:

```text
ShapeOf[T]() -> text
    The shape this language reads from T, as JSON in the format the
    corpus states shapes in.
OfShape(text) -> Generator
    The generator of a shape read from JSON. A record decodes to the
    language's plain map or object with the record's fields, a variant
    to its name and its payload, and every other shape to its usual
    value.
```

`ShapeOf` writes an optional `source` field with the language and the
qualified name of the type, such as
`{"language": "go", "type": "example.com/shop.Order"}`. A reader ignores
the field when it compares two shapes, so one type read in two languages
still has one shape. The field tells a reader of a copied file which
type to check it against.

A shape file is a golden file. A Go test compares the type's shape with
the file through the golden-file assertion. A change to the type then
fails the test until the file is updated:

```go
func TestOrderShape(t *testing.T) {
	golden.Match(t, "order.shape.json", prop.ShapeOf[Order](), golden.ShouldUpdate())
}
```

A TypeScript property reads the same file. From the same seed, it
generates the same orders as a Go property over `Order`:

```typescript
const orderShape = readFileSync("testdata/golden/order.shape.json", "utf8");

test("a total is never negative", ({ seat }) => {
  prop.inRange(seat, (o: Order) => total(o), 0, Number.MAX_SAFE_INTEGER,
    "a total is never negative", prop.using(prop.ofShape<Order>(orderShape)));
});
```

Shape files have these uses:

- TypeScript derives inputs for a type from a shape file that another
  language or a person wrote. A TypeScript property form takes its
  input's generator through `using`. TypeScript has no type to key a
  generator by.
- Services that exchange a message type test their encoders with the
  same inputs when they read one shape file.
- The corpus checks each language's reader. It lists a small set of
  fixture types, such as `order` with an id, a list of lines and an
  optional note. For each, it states the shape the type must read to.
  Each implementation declares the fixture types natively, as it builds
  named subjects. Its reader must produce the stated shape.

### Choosing a generator for a type

```text
Of[T]() -> Generator[T]
    The generator for T: a registered generator when one exists,
    otherwise the generator of T's shape.
Register[T](generator)
    Makes generator the one Of[T] returns, for the whole test process.
    A Register after the first property has started fails.
Using[T](generator) -> Option
    Makes generator the one a single property uses for T, at every
    occurrence of T in its inputs. It takes precedence over a
    registration.
```

A registration replaces the derived generator for every occurrence of the
type, including fields of other types. That is the place for a domain
type the type system cannot describe, such as an email address declared
as a string. Registrations happen before any property runs, in `init`,
`TestMain` or a pytest `conftest.py`. A `Register` after the first
property has started fails, so a test that runs in parallel never sees a
generator change. The test process differs by language: one test binary
per package in Go, a pytest process, and a test file's isolated
environment under vitest's default settings. In Go, a helper package
that registers generators in its own `init` applies them to every test
package that imports it.

`Using` is for a property that needs a narrower domain than the rest. A
test whose properties share one declares the options once and passes
them to each, as in `opts := []prop.Option{prop.Using[Email](email)}`.
A generator comes from `Using` first, then from a registration, then
from the type's shape.

`Of[T]` is an ordinary generator, so a body that draws explicitly can use
it too:

```go
prop.ForAll(t, "a transfer conserves money", func(c *prop.Case) {
	from := c.Draw(prop.Of[Account](), "from")
	to := c.Draw(prop.Of[Account](), "to")
	amount := c.Draw(prop.Integer[int64](1, 1_000_000), "amount")
	…
})
```

### From a value back to choices

Every shape's generator runs backwards. Given a value of the type, the
engine computes the choices that decode to it. The generators that run
backwards are those a shape uses, `boolean`, `integer`, `float`,
`string`, `bytes`, `list`, `dict`, `optional`, `sampled-from` and
`one-of` over named variants, together with `just` and `duration`. The
others cannot: `map`, `filter`, `bind` and `composite` apply a function
the engine cannot invert, and `string-matching`, `permutation`,
`recursive` and `one-of` without names admit more than one sequence of
choices for a value. Hypothesis 6.168.3 inverts its strategies the same
way internally, and raises `CannotInvert` for a strategy it cannot
invert.

```text
Example[T](value T) -> Option
    Runs a property form on value before any other case, as a case whose
    choices decode to value. A failing example shrinks like any other
    case.
Draws(json) -> Option
    Runs a prop-for-all body first on a case whose draws decode to the
    entries in json: a label and a typed literal per draw, in request
    order, in the format a store entry records its counterexample in.
```

Each draw of a `Draws` case computes its choices from the entry with its
label. A draw whose label differs from the next entry, or whose generator
cannot run backwards, fails the test before any other case runs, and the
failure names the label. When the entries run out, every further draw
takes its target, as a replay that runs out of choices does.

Examples have these uses:

- An input a caller already knows matters, such as the one from a bug
  report, runs on every run. When it fails, it shrinks to the part of it
  that matters.
- An input captured from production, such as a message that crashed a
  parser, becomes a test that shrinks, without a person reducing it by
  hand.
- A counterexample copied from a failure report or a store entry becomes
  a regression case in the test's source, independent of the store.
- A store entry can be written by hand as values. The engine computes its
  choices the first time it replays it.

The rule that makes this exact is that decoding the computed choices
returns the value. A map's entries are encoded in ascending key order,
so a map whose iteration order varies between runs, as Go's does, still
gives one sequence of choices. A value the generator cannot produce, such
as a string longer than its shape's `max_size`, makes `Example` fail when
the property is built, naming the field.

### Property forms

The property form of an assertion takes, in place of the value the
assertion examines, a function of one input. The engine derives the
input's generator from the function's parameter type, runs the function
on each generated input, and applies the assertion to the result. Every
other argument remains a value.

`equal` and `not-equal` are the exception: their `want` is also a
function of the same input. A property's expected value almost always
depends on the input, through a reference implementation or a formula,
and a constant `want` is a `prop.True` with a comparison in it.

```go
// Equal fails the test when got and want return different values for
// some input the engine generates for T, and reports the smallest such
// input it finds.
func Equal[T, U any](tb assert.TB, got, want func(T) U, msg string, opts ...Option)

// True fails the test when cond returns false for some generated input.
func True[T any](tb assert.TB, cond func(T) bool, msg string, opts ...Option)

// NoError fails the test when fn returns an error for some generated input.
func NoError[T any](tb assert.TB, fn func(T) error, msg string, opts ...Option)

// NotPanics fails the test when fn panics for some generated input.
func NotPanics[T any](tb assert.TB, fn func(T), msg string, opts ...Option)

// InRange fails the test when got returns a value outside [low, high]
// for some generated input.
func InRange[T, N any](tb assert.TB, got func(T) N, low, high float64, msg string, opts ...Option)
```

A function of more than one input is a function of one record. A Go
caller writes a struct. A language that can take a function of more than
one parameter, such as Python or Kotlin, may accept one, and generates
its parameters in order as the fields of a record. The two produce the
same choices, so the choice is a spelling and not a meaning.

A property form is a `prop-for-all` whose body calls the root assertion.
It reports a `prop-for-all` record: its `failure` is the root
assertion's record, and its counterexample is the derived input. It
aborts only, as `prop-for-all` does, and it takes the engine's options
after its message.

These assertions have a property form:

| Group | Assertions |
|---|---|
| Values | `equal`, `not-equal`, `true`, `false`, `nil`, `not-nil`, `length`, `empty`, `not-empty`, `contains`, `not-contains`, `contains-in-order`, `has-prefix`, `has-suffix`, `matches`, `close-to`, `in-range`, `pairwise` |
| Errors | `err-absent`, `err-present`, `err-is`, `err-is-not`, `err-as` |
| Raising | `throws`, `not-throws` |
| Behaviour | `pure`, `nil-context-safe`, `honours-cancellation`, `honours-deadline`, `max-allocs` |

That is 30. The rest have none, each for a stated reason:

| Assertion | Why it has no property form |
|---|---|
| `eventually`, `eventually-true` | They retry one body over time, and a property already runs a body many times |
| `completes-within` | A duration measured once per generated input is noise, not a property |
| `no-task-leaks` | It scopes a block, not an input |
| The golden-file and benchmark assertions | Their argument is a file or a measurement, not a value |
| `rejects` | It drives a check, not a subject |

`prop.MaxAllocs` checks an allocation ceiling for every generated input,
and shrinks to the smallest input that allocates more. It finds what a
check of one input misses: a codec, for example, that allocates only
when a field outgrows a buffer. The engine draws the input before it
counts, so its own allocations are not counted. The count covers the
whole process, so the form runs one case at a time whatever `workers` is
set to, and in Go the test that calls it does not run in
parallel, as for `assert.MaxAllocs`. Go's `max-allocs` calls the function
101 times, which is 10,100 calls for a run of 100 cases before any
shrinking. Where `max-allocs` is absent or not checked, its property
form is too: in Java, Kotlin, Python and TypeScript, partly in Rust, and
in Go builds with the race detector, msan or asan.

Members of the relation family take an input they pass to a callable.
When that family is accepted, each member's property form drops the
input argument and generates it from the callable's parameter type:
`prop.RoundTrip(t, codec.Encode, codec.Decode, msg)`.

### Names

The property form of an assertion takes the assertion's name in the
`prop` package: `prop.Equal` in Go, `prop.equal` in Python,
`prop::equal` in Rust, `prop.equal` in TypeScript and `Prop.equal` in
Java and Kotlin. The naming table states this as one rule, and rendering
expands it into a row per form, so the gate checks every one.

Beside them: `of`, `register`, `using`, `example`, `draws`, `shape-of`
and `of-shape`, each named in the table.

### The corpus

A shape is data, so the corpus states shapes and the values a seed must
produce from them:

```json
{ "id": "record/seed-42-first-three",
  "shape": { "shape": "record", "fields": [
      ["id", { "shape": "int", "width": 32, "signed": false }],
      ["name", { "shape": "string", "max_size": 8 }] ] },
  "seed": "42",
  "values": [ { "type": "record", "fields": [ ["id", {"type": "int", "value": 0}],
                                              ["name", {"type": "string", "value": ""}] ] } ] }
```

The values above are placeholders. Real vectors come from the executable
reference of the engine, and an implementation confirms them.

The typed-literal encoding gains two types for this: `record`, an ordered
list of named values, and `variant`, a name and an optional payload.
Neither existing type can state a value with fields of different types.

The corpus tests a property form through named subjects: a function kind from
a small vocabulary, such as `identity`, `increment`, `constant-zero` and
`panics-on-negative`, over a shape. Each form has a passing and a
failing case.

| Case kind | Count proposed |
|---|---|
| Shape to values | 2 per shape, 24 |
| Value to choices | 1 per shape, 12 |
| Fixture type to shape | 1 per shape, 12 |
| Draws to choices: a match, a label that differs, a generator that cannot run backwards, a value out of bounds | 4 |
| Property forms | 1 passing and 1 failing per form except `max-allocs`, which no corpus case can state, 58 |

## Alternatives considered

### A. Explicit generators only

Leave derivation out, as the property engine alone does. Every caller
then builds generators by hand.

**Why not:** without derivation, each call of a property form takes its
input's generator explicitly. A property form is then no shorter than a
`prop-for-all` with a draw, and loses the reason it exists.

### B. Let each language derive by its own rules

Each implementation reads types its own way and builds whatever
generator suits its ecosystem, as the established libraries do.

**Why not:** the same declared type would produce different values in
each language. Most callers would use a derived input, so the engine's
fixed generation would apply only to the callers who avoid the
convenient path.

### C. Explicit shapes everywhere

Drop type reading, and let callers state shapes as data in every
language, as TypeScript has to.

**Why not:** it is uniform and it loses the convenience this proposal
exists for. A Go caller would restate a struct's fields as a shape next
to the struct, and the two would drift.

This is what TypeScript does under this proposal, because its types are
not there to read. A shape file that another language writes from a type
spares a TypeScript caller the hand-written shape.

### D. Generate the shapes from a schema

Describe the types once, in a schema language, and generate both the
types and their generators in every language.

**Why not:** it needs a schema language and a generator for each
language, which the assertion set rejected for its own API. It also
helps only callers whose types already come from a schema.

### E. A quantified chain on the existing surfaces

`assert.ForAll[T](t).Equal(got, want, msg)`, reusing the chain the
assertion set already has.

**Why not:** a Go method cannot introduce a type parameter, so the chain
cannot infer the result type of `got`, and `Equal` on it would have to
take `func(T) any`. Package functions infer both types from the
arguments. Every language could offer the chain except the one where the
type matters most.

### F. Property forms on both surfaces

A recording `prop` beside the aborting one, as `expect` exists beside
`assert`.

**Why not:** a failed property has already run its body many times and
shrunk the result. A test that continues past it learns nothing more from
the same subject. The golden-file and benchmark assertions abort only for
the same reason.

## Drawbacks

- **The naming table grows by 37 rows**: 30 property forms through one
  rule, and `of`, `register`, `using`, `example`, `draws`, `shape-of` and
  `of-shape`. That is 222 names across six languages, before the
  relation family's members.
- **Every shape needs an inverse in every language.** Running a
  generator backwards is a second function per shape beside its decoder,
  12 per implementation, and each pair has to agree exactly.
- **Rust needs a procedural macro**, and with it a second crate to
  publish and version alongside the library.
- **TypeScript derives only from shape files.** A TypeScript suite keeps
  a shape file per type, written by another language or by hand, and
  passes each property form its generator through `using`.
- **A shape file is a second copy of a type.** In the language that
  writes it, the golden-file assertion fails a test when the file and
  the type differ. A TypeScript suite that reads a copy from another
  repository has nothing that tells it the copy is stale.
- **Java derives records and not plain classes.** A codebase of plain
  classes either annotates their field order or registers generators.
- **A validating type fails every derived property until it is
  constrained.** A record whose constructor refuses some values needs
  constraints on its shape, or a registered generator, before a derived
  property over it can pass.
- **A type without a constructor check admits values its domain does
  not.** An email typed as a string gets random text, and a property over
  it can pass on a domain wider than the caller meant.
- **`prop.MaxAllocs` is slow and serial.** It makes 101 calls per case
  in Go, and it runs one case at a time because the allocation count
  covers the whole process.
- **Field order is part of the generated values.** Reordering a struct's
  fields changes what a seed produces and what a stored case decodes to.
  The stored case still replays, as a different input.
- **A Go `int` is 32 bits on a 32-bit platform**, so the same Go test
  produces different values there. The Go overlay declares it.
- **The corpus grows by 110 cases.**

## Unresolved and future work

- Deriving a TypeScript generator from a type at compile time, through
  a transform of the compiler's output, is not proposed here.
- Property forms of the relation family's members follow that family's
  acceptance and are not proposed here.
- A shape for date and time values is not proposed here, because the
  engine has no generator for them.

## References

| What | Where |
|---|---|
| Goldstein, Cutler, Dickstein, Pierce and Head, "Property-Based Testing in Practice", ICSE 2024 | <https://doi.org/10.1145/3597503.3639581> |
| Hypothesis 6.168.3, `from_type` | <https://github.com/HypothesisWorks/hypothesis/blob/v6.168.3/hypothesis/src/hypothesis/strategies/_internal/core.py> |
| proptest-derive 1.11.0, the derived `Arbitrary` | <https://github.com/proptest-rs/proptest/tree/v1.11.0/proptest-derive> |
| Kotest 6.2.5, `checkAll` with generators inferred from type parameters | <https://github.com/kotest/kotest/blob/v6.2.5/kotest-property/src/commonMain/kotlin/io/kotest/property/propertyTest1.kt> |
| Java 21, `Class.getDeclaredFields`, which returns fields in no particular order | <https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/Class.html#getDeclaredFields()> |
