---
rfc: 0013
title: TypeScript names that vitest's expect does not define
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-10-01
updated: 2026-10-01
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0013: TypeScript names that vitest's expect does not define

## Summary

This proposal lets the TypeScript library register the standard's
assertions on vitest's own `expect` with `expect.extend`, so that a
vitest suite calls them the way it calls every other assertion. Seven of
the TypeScript names in the naming table are already members of
vitest's `expect`, with other behaviour: `equal`, `contains`, `length`,
`matches`, `closeTo`, `throws` and `rejects`. This proposal renames them
in the TypeScript column to `isEqualTo`, `doesContain`, `hasLength`,
`doesMatch`, `isCloseTo`, `doesThrow` and `doesReject`. It also renames
`notEqual` and `notContains` to `isNotEqualTo` and `doesNotContain`, so
that each negative reads as its positive does. It names vitest's
`expect` and `Assertion` as TypeScript's chain, and adds a rule that no
TypeScript assertion name is a member of vitest's `expect`. The other 26
assertions in the root namespace keep their TypeScript names. A rename
is a major version, so the definition moves to 2.0.0.

## Motivation

### TypeScript tests assert through vitest's expect

A TypeScript project's tests run under vitest more often than under any
other runner. In the 30 days to 2026-09-29, npm counted 430,007,027
downloads of vitest, 193,177,827 of jest and 59,533,671 of mocha.

A vitest test asserts by calling a matcher on `expect`, as in
`expect(got).toEqual(want)`. A library that adds assertions registers
them with `expect.extend`, and a test calls them the same way. jest-dom
7.0.1 registers its 49 matchers like this, and every one of their names
starts with `to`.

`expect.extend` installs each matcher on chai's `Assertion` prototype,
which every `expect` in a test worker shares. A matcher registered this
way behaves as vitest's own matchers do. We registered three of the
standard's assertions and measured them on vitest 4.1.11 and 5.0.3:

- `expect.soft` recorded each failure as a separate error and let the
  test continue.
- The matchers counted toward `expect.assertions`.
- They worked on the global `expect`, under `globals: true`, and on a
  concurrent test's own `context.expect`.
- `await expect(promise).resolves` applied a matcher to the resolved
  value, because vitest's `resolves` wraps every method of the assertion.
- vitest's reporter showed a code frame at the test's line, and an
  Expected and Received diff for an equality failure.
- A custom reporter received the standard's failure record, with the
  assertion's id, the contract and the detail fields, through the
  matcher's `meta`.

### Seven names are taken

Vitest's `expect` combines chai's assertion methods with its own, and
seven of the TypeScript names in the naming table are among them. We read
the members from the running engine at 4.1.11 and 5.0.3. We then called
each colliding member on an input chosen to separate its meaning from the
standard's, and found no such input for `closeTo`:

| Assertion | Vitest's member | Input | Vitest | The standard |
|---|---|---|---|---|
| `equal` | chai's `equal`, which compares with `===` | `[1]` against `[1]` | fails | passes |
| `contains` | chai's `contains`, which compares an array's elements with SameValueZero | `[{a: 1}]` against `{a: 1}` | fails | passes |
| `length` | chai's `length`, which requires a `length` or a `size` | `{a: 1, b: 2}` against 2 | fails | passes |
| `matches` | chai's `matches`, which takes a RegExp | `"abc"` against the pattern `"a.c"` | throws a TypeError | passes |
| `close-to` | chai's `closeTo`, whose bound is inclusive | 1.5 within 0.5 of 1 | passes | passes |
| `throws` | chai's `throws`, which reads a string as text the error message must contain | a callable that throws, with `"the parser refuses"` as the argument | fails | passes |
| `rejects` | vitest's `rejects`, a property that applies the next matcher to a rejected promise | not callable as an assertion | none | none |

`closeTo` also agreed on NaN, which fails under both.

A matcher of the same name replaces chai's method for the rest of the
worker. `expect([1]).to.equal([1])` failed, `expect.extend` then
registered a structural `equal`, and the same call passed. In the next
test, `expect([1]).equal([1])` passed as well. A matcher named `rejects`
cannot be registered at all, because `expect.extend` throws
`TypeError: Cannot set property rejects of #<_Assertion> which has only a getter`.

The standard's assertions can take those seven names on vitest's
`expect` only by changing the verdicts of tests that use chai's methods.
Left as they are, the seven are unavailable on `expect`, and `equal`, the
assertion a test calls most, is one of them.

### The definition changes, not only the library

The naming table lists every public item a caller types, and a language
spells a name differently only where its conventions give a reason. A
library that registered the seven under names of its own would publish
items the table does not list. The reason here comes from the TypeScript
ecosystem: its test framework already defines those names on the object
every test calls.

## Detailed design

### The new names

| Assertion | TypeScript name today | TypeScript name |
|---|---|---|
| `equal` | `equal` | `isEqualTo` |
| `not-equal` | `notEqual` | `isNotEqualTo` |
| `contains` | `contains` | `doesContain` |
| `not-contains` | `notContains` | `doesNotContain` |
| `length` | `length` | `hasLength` |
| `matches` | `matches` | `doesMatch` |
| `close-to` | `closeTo` | `isCloseTo` |
| `throws` | `throws` | `doesThrow` |
| `rejects` | `rejects` | `doesReject` |

`not-equal` and `not-contains` are not members of vitest's `expect`.
They move with their positives so that each pair reads alike:
`isEqualTo` and `isNotEqualTo` as `isNil` and `isNotNil` do, and
`doesContain` and `doesNotContain` as `doesThrow` and `doesNotThrow` do.
A rename after this one would cost another major version.

Each name takes the auxiliary its word takes in an English sentence, as
the TypeScript column already does:

- `is` before an adjective, as in `isNil` and `isEmpty`: `isEqualTo`,
  `isNotEqualTo` and `isCloseTo`.
- `has` before a noun, as in `hasPrefix` and `hasError`: `hasLength`.
- `does` before a verb, as in `doesNotThrow`: `doesContain`,
  `doesNotContain`, `doesMatch`, `doesThrow` and `doesReject`.

Google's Truth uses `isEqualTo`, `isNotEqualTo`, `hasLength`,
`doesNotContain` and `doesNotMatch`. AssertJ uses `isEqualTo` and
`isCloseTo`. Neither vitest's `expect` assertion nor `expect` itself
defines any of the nine names, at 4.1.11 or at 5.0.3.

One name serves both call styles:

```ts
check.isEqualTo(seat, reply.status, 200, "the request succeeds");
expect(reply.status).isEqualTo(200, "the request succeeds");
```

The change to `naming.yaml` sets the `typescript` key of nine rows:

```yaml
names:
  "equal":
    typescript: "isEqualTo"
  "not-equal":
    typescript: "isNotEqualTo"
  "contains":
    typescript: "doesContain"
  "not-contains":
    typescript: "doesNotContain"
  "length":
    typescript: "hasLength"
  "matches":
    typescript: "doesMatch"
  "close-to":
    typescript: "isCloseTo"
  "throws":
    typescript: "doesThrow"
  "rejects":
    typescript: "doesReject"
```

### No TypeScript assertion name is taken on vitest's expect

The definition gains a rule for the TypeScript column. No TypeScript name
of an assertion is a member of vitest's `expect` assertion, or an own
property of `expect`, in a vitest major the TypeScript library supports.
The assertion's prototype chain had 182 names at 4.1.11 and 185 at 5.0.3.
`expect` had 25 own properties at 4.1.11 and 27 at 5.0.3.

For each vitest major it supports, the TypeScript library's completeness
gate reads both lists from the running engine and fails on an assertion
name in either list. The definition's validator cannot check the rule,
because the lists change between vitest releases and a copy in the
definition would go out of date.

### The chain in TypeScript

The definition states every assertion as a function and as a method on a
chain. TypeScript's chain is vitest's `expect`:

```yaml
surface:
  types:
    "assertion":
      typescript: "Assertion"
  helpers:
    "that":
      typescript: "expect"
```

Both rows name items the test framework supplies, as Go names
`testing.T` for its seats. The gate checks that the chain's methods exist
under the names given, not that the library defines `expect`.
`expect(got)` takes no seat. Vitest supplies the running test as the
seat, as Go's `*testing.T` is the seat in `assert.Equal(t, got, want,
msg)`. `expect.soft(got)` is the recording chain. The TypeScript
overlay's `surface` entries for `assertion` and `that` are removed.

On `expect`, the value an assertion is about becomes the argument to
`expect`. The other arguments follow in the order of the function form.
For most assertions that value is the first argument after the seat. Six
assertions take it in another position:

| Assertion | Function form | On `expect` |
|---|---|---|
| `completes-within` | `completesWithin(seat, within, fn, msg)` | `await expect(fn).completesWithin(within, msg)` |
| `eventually` | `eventually(seat, timeout, interval, body, msg)` | `await expect(body).eventually(timeout, interval, msg)` |
| `eventually-true` | `eventuallyTrue(seat, timeout, predicate, msg)` | `await expect(predicate).eventuallyTrue(timeout, msg)` |
| `pure` | `isPure(seat, observe, fn, msg)` | `await expect(fn).isPure(observe, msg)` |
| `no-task-leaks` | `noTaskLeaks(seat, msg)`, which returns the callable that ends the scope | `await expect(scope).noTaskLeaks(msg)`, where `scope` is a callable that runs the work |
| `rejects` | `doesReject(seat, msg, body)` | `expect(body).doesReject(msg)` |

In the function form, `err-as` returns the matching error, `throws`
returns what the callable threw, and `rejects` returns the failure
message. A matcher returns no value. To read one of those values, a
test calls the function form.

`honours-cancellation`, `honours-deadline`, `completes-within`,
`nil-context-safe`, `pure`, `eventually` and `eventually-true` return a
promise. On `expect`, a test awaits each of them. Vitest 5.0 fails a test
that leaves `resolves`, `rejects` or a polled assertion unawaited. It
does not track custom matchers. In our measurement, a test that left a
failing custom matcher unawaited passed. Its failure appeared as an
unhandled rejection attributed to a later test. The TypeScript library
reports an unawaited matcher itself for that reason.

The standard states its own negatives, such as `not-equal`,
`not-contains` and `not-throws`, so `.not` has no meaning in it. A
registered matcher called with `.not` fails. Its message gives the
negative assertion to use, or states that the assertion has none.

### Invariants

- No TypeScript assertion name is a member of vitest's `expect` assertion
  or an own property of `expect`, in any vitest major the library
  supports.
- Registering the library's matchers replaces no method that vitest or
  chai defines. This follows from the first invariant.
- An assertion has one TypeScript name, and both call styles use it.

### What fails, and where

| Event | Effect | Response |
|---|---|---|
| A vitest release adds a member whose name is a TypeScript assertion name | The TypeScript gate fails against that release | The definition renames the assertion in its next major version |
| A test file loads a chai plugin that defines a TypeScript assertion name as a property | Loaded before the library, the property makes the library's registration throw a TypeError, as vitest's `rejects` does. Loaded after it, the property replaces the matcher for the whole worker | None in the definition. chai-as-promised 8.0.2 defines `eventually` as a property |
| A test calls a registered matcher with `.not` | The matcher fails | The failure gives the standard's negative to use |

### Version

Renaming an assertion is a major version, so the definition moves from
1.1.0 to 2.0.0. `VERSION`, the `version` key of both tables, the rendered
JSON and the manifest change, and every overlay extends 2.0.0. Each
implementation moves to 2.0.0 when it syncs. Only the TypeScript
implementation changes code. It renames 18 exported functions: nine on
`check`, eight on `soft`, which has no `rejects`, and the `rejects` that
its root module exports.

## Alternatives considered

### A. Keep the seven names and leave them off expect

The TypeScript library registers the other 27 assertions on `expect`, and
a test calls the seven through the function form.

**Why not:** `equal` is one of the seven, and a test calls it more than
any other assertion. A suite would write `expect(x).hasPrefix(…)` beside
`check.equal(seat, x, …)`. One test would then use two styles, and a
reader could not tell why.

### B. Register under the standard's names

Replace chai's six methods with the standard's assertions, and accept
that `expect(x).equal(y)` follows the standard.

**Why not:** the replacement applies to every test in the worker. A test
written against chai changes its verdict without any change to its file.
`expect([1]).to.equal([1])` failed before the registration and passed
after it. `rejects` cannot be registered at all.

### C. One namespace on expect

Register each assertion with `expect.extend` under a hidden name, and
add one property, such as `std`, whose methods are those registered
matchers under the standard's current names:
`expect(x).std.equal(y, msg)`. The TypeScript names and the
definition's major version do not change.

We built it on 4.1.11 and 5.0.3. Each `std` call runs a registered
matcher. `expect.soft` recorded its failures, the calls counted toward
`expect.assertions`, and the reporter showed a code frame at the test's
line.

**Why not:**

- Under `resolves`, the namespace runs chai's methods. Vitest's
  `resolves` returns its own proxy in place of any chai `Assertion` that
  a property returns, so the namespace object is lost. In our
  measurement, `expect(Promise.resolve({a: 1})).resolves.std.equal({a: 1}, msg)`
  ran chai's `equal` and failed with "expected { a: 1 } to equal
  { a: 1 }".
- The namespace depends on chai's internals. chai's registered methods
  throw "Invalid Chai property" when `bind` reads their `length`, so the
  property returns an object that inherits from the assertion. That
  object works only because chai stores an assertion's flags in its
  `__flags` property.
- Each call is one word longer than a vitest matcher call.

### D. A second TypeScript name for the chain

Keep `equal` in the function form, give the chain method another name,
and add a second TypeScript column for the chain.

**Why not:** the definition gives an assertion one name per language,
under both call styles. A second column doubles what a TypeScript reader
learns. A check moved from one style to the other would also change its
name.

### E. Reserved names in the definition

List vitest's member names in the definition, and let its validator
reject a TypeScript name on the list.

**Why not:** the list changes between vitest releases, from 182 names at
4.1.11 to 185 at 5.0.3, and a copy in the definition goes out of date.
The TypeScript gate reads the running engine instead.

### F. Java's name for throws

Java and Kotlin name `throws` as `throwsException`. In Java, `throws` is
a reserved word.

**Why not:** TypeScript names `not-throws` as `doesNotThrow`, and
`doesThrow` pairs with it. A JavaScript callable can also throw a value
that is not an Error, which `throwsException` misdescribes.

### G. Rename only the seven

Rename the seven names that vitest defines. Keep `notEqual` and
`notContains`.

**Why not:** the pairs would read unevenly. `isEqualTo` would pair with
`notEqual`, and `doesContain` with `notContains`. The other negatives
with a `not` follow their positives, as `isNotNil` follows `isNil`. A
separate rename of the two would cost every overlay and implementation
another major version.

## Drawbacks

- Nine TypeScript names differ from the other languages' spelling. A
  test ported between Go and TypeScript changes nine names as well as
  its call style.
- The version is major. Six overlays change their `extends`, and five
  implementations sync to a version whose renames all fall in the
  TypeScript column.
- The TypeScript library renames 18 exported functions, and a TypeScript
  caller of the nine assertions edits every such call.
- The rule covers vitest's own `expect`. A chai plugin that a project
  loads can still define one of the names, as chai-as-promised defines
  `eventually`.
- `expect` means two things across the languages. In Go and Python,
  `expect` is the namespace that records a failure and continues. In
  TypeScript, vitest's `expect` stops at a failure, and `expect.soft`
  records.

## Open questions

- Should the rule also cover jest's `expect`, so that the TypeScript
  library can register the same matchers under jest? jest defines
  `rejects` as a modifier as well.
- Should a matcher called with `.not` fail, or apply the standard's
  negative where one exists?

## Unresolved and future work

- Which assertions each language's chain offers. The definition states
  every assertion on the chain, and Go's chain offers the 15 value
  assertions and the four error assertions `err-is`, `err-is-not`,
  `err-absent` and `err-present`. This proposal settles only
  TypeScript's.
- A TypeScript chain outside vitest.

## References

| What | Where |
|---|---|
| npm downloads from 2026-08-31 to 2026-09-29: vitest 430,007,027, jest 193,177,827, mocha 59,533,671 | <https://api.npmjs.org/downloads/point/last-month/vitest>, and the same path for `jest` and `mocha` |
| Vitest's guide to `expect.extend` and the `Matchers` interface | <https://vitest.dev/guide/extending-matchers> |
| `expect.extend` installs each matcher on chai's `Assertion` prototype | vitest 4.1.11: `@vitest/expect/dist/index.js`, lines 1867-1903; vitest 5.0.3: `dist/chunks/index.C4tKZ0yW.js`, lines 2566-2592 |
| Vitest's soft handling, in the wrapper around each registered method | vitest 4.1.11: `@vitest/expect/dist/index.js`, lines 1139-1175 |
| Vitest's `rejects` property | vitest 4.1.11: `@vitest/expect/dist/index.js`, line 1746 |
| Vitest's `resolves` wraps each method of the assertion, and returns its own proxy in place of a chai `Assertion` that a property returns | vitest 4.1.11: `@vitest/expect/dist/index.js`, lines 1709-1745; vitest 5.0.3: `dist/chunks/index.C4tKZ0yW.js`, lines 2433-2443 |
| chai's guard on `length` for each registered method, and the flags it keeps in `__flags` | chai 6.2.2: `index.js`, lines 1594 and 112-113; chai 6.3.0: `index.js`, lines 1631 and 115-116 |
| chai's `include`, `equal`, `length`, `match`, `throw` and `closeTo` | chai 6.2.2: `index.js`, lines 2025-2112, 2244-2266, 2655-2690, 2787-2908 and 2939-2971 |
| jest-dom registers 49 matchers through `expect.extend` | `@testing-library/jest-dom` 7.0.1: `vitest.js` and `dist/matchers.js` |
| chai-as-promised defines `eventually` as a property | chai-as-promised 8.0.2: `lib/chai-as-promised.js`, line 268 |
| chai's `addProperty` defines a configurable property, and `addMethod` assigns | chai 6.2.2: `index.js`, lines 1562 and 1695 |
| jest's `.rejects` modifier | <https://github.com/jestjs/jest/blob/main/docs/ExpectAPI.md> |
| Truth's `isEqualTo`, `isNotEqualTo`, `hasLength`, `doesNotContain` and `doesNotMatch` | <https://truth.dev/api/latest/com/google/common/truth/StringSubject.html> |
| AssertJ's `isEqualTo` and `isCloseTo` | <https://www.javadoc.io/static/org.assertj/assertj-core/3.26.3/org/assertj/core/api/AbstractDoubleAssert.html> |
| Our measurements on vitest 4.1.11 and 5.0.3, Node 26.10.0, 2026-10-01: the member and property lists read from the running engine; one discriminating input per colliding name; registrations of `equal` and `rejects`; three registered assertions under `expect.soft`, `expect.assertions`, `context.expect`, `globals: true`, `resolves`, the default reporter and a custom reporter; an unawaited failing matcher; alternative C, a namespace property over matchers registered under hidden names, under `expect.soft`, `expect.assertions`, `context.expect`, `resolves` and the default reporter | Scratch projects, one per vitest version |
