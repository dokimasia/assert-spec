---
rfc: 0002
title: The relation family
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-08-30
updated: 2026-10-02
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0002: The relation family

## Summary

The standard states 43 assertions, and all but a few compare a value
against another value. This adds a second kind: an assertion that states a
relation a subject must satisfy, which a test can check without knowing
the subject's correct output. The family has thirteen members. Six call
one callable with the inputs to run it with. The other seven call two,
such as a forward conversion and the inverse that has to undo it.

The analysis behind the family also adds one value assertion,
`permutation`: a sequence equal to another in any order.

## Motivation

A test needs something to compare against. Where that something is hard
to produce, the test either does not get written or gets written against
whatever the code currently returns, which pins the behaviour instead of
checking it. The field calls this the oracle problem and has surveyed it
for thirty years.

Metamorphic testing runs the subject twice and relates the two runs to
each other, so a test does not need the correct output. `f(f(x))`
equalling `f(x)` is checkable without knowing what `f(x)` is.

`pure` is the one relation among the 43 assertions. It states that
observed state does not change across a call, and the order in which the
assertions were written is the only reason it has no siblings.

A catalogue of 107 relations, derived from real interfaces, contains 7
that the standard can express and 36 that need nothing but new assertions
of the form the standard already uses (Research-0002). Of those 36:

| Disposition | Count | Where |
|---|---|---|
| A member of this family | 13 | The members |
| A value assertion, `permutation` | 1 | The value assertion |
| A merge that converges, which composes from three members | 1 | Scope |
| A store protocol that pairs an operation with the sibling confirming it | 15 | Unresolved and future work |
| Rejected | 6 | Alternatives considered |

## Detailed design

### What makes a member

A member states a property of a subject that a test can check without the
subject's correct output. It calls the subject through at least one
callable, and it does not take an expected output. A member establishes
that the subject is consistent in a stated way, and not that the subject
is correct.

### The members

Each member is given with the arguments it takes beyond the seat and the
message. The arity counts by the definition's rule: the seat is not
counted, and the message is.

**Repetition.** How a subject behaves when it runs more than once.

| Member | Arguments | Law | Arity | Detail fields |
|---|---|---|---|---|
| `idempotent` | `call`, `input`, `observe` | After `call(input)`, `observe` reads `first`. After a second `call(input)`, it reads `second`. The two are equal | 4 | `first`, `second` |
| `accumulates` | `call`, `input`, `observe` | `observe` reads an integer before the first `call(input)`, after it and after a second one. The first call changes the integer, and the second changes it by the same amount. `first` and `second` are the two changes | 4 | `first`, `second` |
| `deterministic` | `call`, `input` | 32 calls of `call(input)` return equal results. `first` is the first result, and `second` the first result that differs | 3 | `first`, `second` |

`idempotent` and `accumulates` are two positions on one axis, and a
subject may satisfy neither. A subject whose call leaves the observed
state unchanged satisfies `idempotent` and fails `accumulates`, because
its first call leaves the integer as it was.

**Algebra.** How results combine.

| Member | Arguments | Law | Arity | Detail fields |
|---|---|---|---|---|
| `commutative` | `combine`, `a`, `b` | `combine(a, b)`, the `first`, equals `combine(b, a)`, the `second` | 4 | `first`, `second` |
| `associative` | `combine`, `a`, `b`, `c` | `combine(combine(a, b), c)`, the `first`, equals `combine(a, combine(b, c))`, the `second` | 5 | `first`, `second` |
| `round-trip` | `forward`, `inverse`, `input` | `inverse(forward(input))`, the `got`, equals `input`, the `want` | 4 | `want`, `got` |

`round-trip` is the relation of a codec: a serializer, a parser, a
compressor and an encryptor all state it.

**Sequence.** Properties of what a subject yields, or of what it reads
over successive steps.

| Member | Arguments | Law | Arity | Detail fields |
|---|---|---|---|---|
| `stable-order` | `iterate` | 32 iterations yield equal sequences. `first` is the first sequence, and `second` the first sequence that differs | 2 | `first`, `second` |
| `no-duplicates` | `iterate` | One iteration yields each element at most once. `got` is the first element equal to an earlier one, and `index` its position | 2 | `got`, `index` |
| `monotonic` | `observe`, `advance`, `steps` | `observe` reads a number, then `advance` runs and `observe` reads again, `steps` times. No reading is below the reading before it, and none is NaN. `index` is the step of the first reading that is below or NaN, `first` the reading before it, and `second` that reading | 4 | `index`, `first`, `second` |

`stable-order` and `no-duplicates` are independent. A sequence may repeat
without changing its order, and may change its order without repeating.

**Totality and state.**

| Member | Arguments | Law | Arity | Detail fields |
|---|---|---|---|---|
| `total` | `call`, `domain` | `call` succeeds for each element of `domain`, in order. `index` is the position of the first element for which it fails, and `got` the failure | 3 | `index`, `got` |
| `not-pure` | `observe`, `call` | `observe` reads before and after `call`, and the two readings differ. `got` is the reading that did not change | 3 | `got` |

`not-pure` is the negation of `pure`, and takes the same arguments.

**Lifecycle.** What a subject does around its own boundaries.

| Member | Arguments | Law | Arity | Detail fields |
|---|---|---|---|---|
| `after-close` | `close`, `call`, `sentinel` | After `close`, `call` fails with `sentinel`, found through the chain of wrapped causes as `err-is` finds it. `want` is the sentinel and `got` what `call` returned | 4 | `want`, `got` |
| `poisoned` | `induce`, `observe` | After `induce`, 32 readings of `observe` each fail. `index` is the position of the first reading that does not fail, and `got` what it returned | 3 | `index`, `got` |

### Callables that fail

A callable that fails or panics fails the member, except where the law
requires a failure. The failure or the panic value takes the place of the
value that the callable did not return, in `first`, `second` or `got`.
Every other field of the record is null.

`after-close` requires `call` to fail with the sentinel, and `poisoned`
requires every reading to fail. In those two, the failure is the value
that the law examines. A panic fails them as it fails every member.

### Comparison and relaxations

`idempotent`, `deterministic`, `commutative`, `associative`,
`round-trip`, `stable-order`, `no-duplicates` and `not-pure` compare two
values as `equal` compares them, and accept `equate-empty` and
`equate-nans`. Under `equate-empty`, a codec that decodes an absent list
as an empty one passes `round-trip`.

`accumulates` and `monotonic` compare numbers. `total` and `poisoned`
examine failures, and `after-close` compares a failure with its sentinel.
These five do not accept a relaxation.

### Repetitions

`deterministic`, `stable-order` and `poisoned` run their callable 32
times. A subject whose result or order varies can agree with itself by
chance, and the count bounds that chance. We measured it on Go's map,
whose iteration order varies by design, with go1.27.1 and 20,000 trials
for each cell:

| Entries | All 10 iterations agree | All 16 agree | All 32 agree |
|---|---|---|---|
| 2 | 27% | 12% | 1.5% |
| 3 | 5.6% | 1.1% | 0.01% |
| 4 | 0.9% | 0.04% | none |
| 5 or more | under 0.1% | none | none |

At 32 iterations, `stable-order` passes a Go map of two entries in 1.5% of
runs, and it has not passed one of four or more.

### Order of the callables

A member that takes two callables takes them in the order its law reads.
`after-close` takes `close` before `call`, because the law is "close,
then call fails". RFC-0003 states the same rule for the relations that
pass their parts as roles.

### The value assertion

`permutation(got, want)` passes when `got` and `want` contain the same
elements, each as often, in any order. It compares elements as `equal`
compares them and accepts `equate-empty` and `equate-nans`. Its arity is
3, and a failure reports `want` and `got`.

`permutation` takes an expected output. It is a value assertion for that
reason, and not a member of the family.

### Corpus cases

A member takes callables. A corpus case of a member states a subject, as
the cases of `pure` do. The subject supplies every callable and every
input of the member, and the case states nothing else. Each member has
one passing case and one failing case:

| Member | Passing subject | Failing subject |
|---|---|---|
| `idempotent` | `sets-value` | `accumulates` |
| `accumulates` | `accumulates` | `sets-value` |
| `deterministic` | `returns-ok` | `counts-calls` |
| `commutative` | `adds` | `subtracts` |
| `associative` | `adds` | `subtracts` |
| `round-trip` | `renders-decimal` | `drops-the-sign` |
| `stable-order` | `yields-in-order` | `rotates` |
| `no-duplicates` | `yields-in-order` | `repeats-an-element` |
| `monotonic` | `accumulates` | `wraps-around` |
| `total` | `returns-ok` | `fails-otherwise` |
| `not-pure` | `accumulates` | `leaves-state-alone` |
| `after-close` | `refuses-after-close` | `serves-after-close` |
| `poisoned` | `never-settles` | `settles-after` |

Six of these subject kinds exist already, and the definition gains
twelve:

| Subject | Behaviour |
|---|---|
| `sets-value` | Sets the observed state to its input, 7 |
| `counts-calls` | Returns the number of times it has been called |
| `adds` | Combines two integers by adding them, over the inputs 2, 3 and 5 |
| `subtracts` | Combines two integers by subtracting the second from the first, over the inputs 2, 3 and 5 |
| `renders-decimal` | Renders an integer as decimal text and parses the text back, over the input -42 |
| `drops-the-sign` | Renders the absolute value of an integer as decimal text and parses the text back, over the input -42 |
| `yields-in-order` | Yields the integers 1 to 5 in order, on every iteration |
| `rotates` | Yields the integers 1 to 5, rotated one place further on each iteration |
| `repeats-an-element` | Yields 1, 2, 2 and 3 |
| `wraps-around` | Counts up by one per advance and returns to 0 after 3, over 5 steps |
| `refuses-after-close` | After it closes, fails every call with its closed sentinel |
| `serves-after-close` | After it closes, still succeeds on every call |

The subject `accumulates` observes an integer count that rises by one per
call. It passes `accumulates`, `monotonic` over 5 steps and `not-pure`,
and it fails `idempotent`. `permutation` takes values, so its cases state
typed literals.

### Property forms

A property form of a member generates inputs and runs the member on each
generated case:

| Member | What the form generates |
|---|---|
| `idempotent`, `accumulates`, `deterministic`, `round-trip` | `input` |
| `commutative` | `a` and `b` |
| `associative` | `a`, `b` and `c` |
| `not-pure` | The input that `call` takes, as for `pure` |

`total` has no property form. Generating its domain gives a call that
succeeds for every generated input, which is the property form of
`err-absent`. The other five members take no input to generate. RFC-0011
states the property forms.

### Scope

Each member runs its callables a fixed number of times on one thread and
compares what it reads, so it is cheap to implement and cheap to conform
to. The family leaves out every relation that needs a clock, a history or
concurrent callers.

A merge that converges under concurrent writes is commutative,
associative and idempotent, so it composes from three members and is not
a member of its own.

### Versioning

Adding the thirteen members, `permutation`, their subjects and their
cases is a minor version.

## Alternatives considered

### A. Leave these to property-based testing

Every relation here is expressible as a property, and the property-based
testing libraries are mature and widely used. fast-check, hypothesis and
proptest all have more users than this standard is likely to gain.

Rejected, because a property needs a generator, a shrinking strategy and
a separate test style. An assertion states the relation about a call that
the author already has, in the test that they were already writing. The
two compose. One named relation can be asserted about one input, and its
property form runs it over generated inputs.

### B. Add a general relation combinator instead of named members

One assertion taking a relation as an argument would cover every member
and any relation nobody has thought of. It is less to specify and less to
implement.

Rejected, because a named relation makes a suite readable and makes its
coverage countable. A test that calls `idempotent` states what it checks,
and a lambda passed to a combinator states only that something was
checked. A name is also what lets an overlay record that a language
cannot supply a member.

### C. Take values instead of callables

A member could take the two values that the caller produced, such as the
results of `combine(a, b)` and `combine(b, a)`. That would match the
existing signatures more closely.

Rejected, because the caller producing both runs is the mistake that the
member exists to prevent. A caller who runs the subject twice and
compares has written the relation by hand. The usual error is running it
twice in a way that does not test the property.

### D. `conserves`, a member for a quantity that moves but is not made or destroyed

`pure(observe, call)`, with `observe` returning the total, such as the
sum of every balance, passes exactly when the call conserves the total.
Rejected for that reason. A conserved quantity that needs a tolerance,
such as a total of floats, would need a member that compares with
`close-to`.

### E. The safety members: `escapes`, `treats-as-data` and `tamper-evident`

Each hands the subject hostile input and requires that the input does not
become syntax. Rejected, because the caller supplies the payload, so a
weak payload passes a weak subject, and the member cannot fail on the
property that it names. A versioned corpus of payloads for each context,
in the definition, would change this.

### F. `default-on-error`, a zero value beside a failure

Only Go returns a value beside a failure. Python, Java, Kotlin and
TypeScript raise. Rust returns a result that is a value or a failure.
Rejected, because an assertion that means something different in each
language is a helper, and a helper belongs in the library of its
language.

### G. `retry-succeeds`, a failing call that converges within a number of attempts

On a controlled clock, `eventually` runs a fixed number of attempts and
reports how many it ran. Rejected, because `eventually` states the same
law.

### H. Fewer repetitions

Ten repetitions pass a Go map of two entries in 27% of runs and one of
three entries in 5.6%. Rejected for that reason. 32 repetitions cost 32
calls of the callable, which is cheap for a function and noticeable for a
call over a network.

## Drawbacks

- Fourteen assertions are a 33% increase on a set of 43. Each one is
  implemented in every language, named in the naming table and given
  corpus cases, and the definition gains twelve subject kinds.
- `stable-order` passes a Go map of two entries in 1.5% of runs, and a
  map of three entries in 0.01%. A test that needs the property states a
  map of four entries or more.
- A member checks consistency and not correctness. A subject that is
  wrong in the same way on every run passes `deterministic` and
  `stable-order`.
- `deterministic` and `stable-order` call their subject 32 times, which a
  slow subject makes slow.

## Unresolved and future work

- The fifteen store protocols, such as a delete and the read that
  confirms it, an acquire and its release, and an insert and the update
  that replaces it. Each takes its callables in the order its law reads.
  A later RFC proposes them after the observation seams of RFC-0003.
- The relations that need a recorded history, a controlled clock or
  concurrent callers. The standard's clock is the controlled clock they
  need. The history and the concurrency driver are proposed as the
  observation seams.
- The property forms of the members, which RFC-0011 states.

## References

- The oracle problem: Barr, Harman, McMinn, Shahbaz and Yoo, IEEE
  Transactions on Software Engineering, <https://doi.org/10.1109/tse.2014.2372785>
- Metamorphic relations: Li, Liu, Poon, Towey, Sun, Zheng, Zhou and Chen,
  <https://arxiv.org/abs/2406.05397>
- Metamorphic testing as a kind of property-based testing: Alzahrani,
  Spichkova and Harland, <https://arxiv.org/abs/2211.12003>
- Conflict-free replicated data types, for why a converging merge is
  commutative, associative and idempotent: Shapiro, Preguiça, Baquero and
  Zawirski, <https://doi.org/10.1007/978-3-642-24550-3_29>
- The catalogue of relations and its classification: Research-0002
