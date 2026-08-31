---
rfc: 0002
title: The relation family
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-30
updated: 2026-08-30
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0002: The relation family

## Summary

The standard states forty-one assertions, and all but a handful compare a
value against another value. This adds a second kind: an assertion that
states a relation a subject must satisfy, rather than an answer it must
give. Twenty of them, each taking a callable and the inputs to drive it
with.

Each one is a necessary property of the subject rather than a recorded
output, so a test can state it without knowing what the right answer is.

## Motivation

A test needs something to compare against. Where that something is hard
to produce, the test either does not get written or gets written against
whatever the code currently returns, which pins the behaviour instead of
checking it. The field calls this the oracle problem and has surveyed it
for thirty years.

Metamorphic testing is the established answer. Rather than asking what
the output should be, it asks what must hold between inputs and outputs:
run the subject twice and relate the two runs. `f(f(x))` equalling `f(x)`
is checkable without knowing what `f(x)` is.

The standard already has one of these. `pure` states that observed state
does not change across a call, which is a relation and not a comparison.
It sits alone among forty value assertions, and there is no reason for
that beyond the order things were written in.

The size of the gap is known rather than guessed. A catalogue of a
hundred and seven relations exists, derived from real interfaces, and
this standard can express seven of them. Thirty-six of the rest need
nothing but new members in the shape the standard already uses, and
twenty of those thirty-six take a single callable, which is what this
proposes.

## Detailed design

### What makes a member

A member of this family states a property that relates the runs of a
subject to each other, and that a test can check without knowing the
subject's correct output. That is the membership test, and it is what
keeps the family from becoming a list of everything anyone wants.

Three consequences follow. A member takes a callable rather than a
value, because it drives the subject rather than inspecting an answer. A
member needs no expected output. And a member says nothing about whether
the subject is correct, only that it is consistent in a stated way.

### The members

Each is given with the arguments it takes beyond the seat and the
message, in the order the standard's existing signatures use.

**Repetition.** How a subject behaves when run more than once.

```
idempotent(call, input, observe)      running twice leaves what running once left
accumulates(call, input, observe)     running twice leaves twice what once left
cacheable(call, input)                the same input answers the same over time
retry-succeeds(call, attempts)        a failing call converges within attempts
```

`idempotent` and `accumulates` are two positions on one axis, not a claim
and its negation. A subject carrying neither has not been asked.

**Algebra.** How results combine.

```
commutative(combine, a, b)            order does not matter
associative(combine, a, b, c)         grouping does not matter
round-trip(forward, inverse, input)   inverse(forward(x)) equals x
conserves(measure, call)              a named quantity moves but is neither made nor destroyed
```

`round-trip` is the relation a codec states, and it is the one members of
this family most often want: a serializer, a parser, a compressor and an
encryptor all state it.

Nothing here covers a merge that converges under concurrent writes,
because a merge that is commutative, associative and idempotent converges
already. The three primitives compose into it, so the composite is not a
member.

**Sequence.** Properties of what a subject yields.

```
stable-order(iterate)                 repeated iteration yields the same order
permutation(iterate, want)            every element exactly once, order unspecified
no-duplicates(iterate)                one drain yields each element at most once
monotonic(observe, advance)           successive observations never decrease
```

`permutation` and `no-duplicates` are independent. A sequence may repeat
without being disordered and may be disordered without repeating.

**Totality and defaults.** What a subject does at the edges.

```
total(call, domain)                   defined for every input in the domain
default-on-error(call, bad-input)     a failed call answers the zero value beside the error
side-effect(call, observe)            an observation does change, which is the inverse of pure
```

**Lifecycle.** What a subject does around its own boundaries.

```
after-close(close, call, sentinel)    behaves after close, reporting the sentinel
poisoned(induce, observe)             a failure state, once induced, sticks
```

**Safety.** What a subject does with input it should not trust.

```
escapes(render, unsafe, context)      untrusted input leaves escaped for the context
treats-as-data(call, unsafe, observe) untrusted input reaches an interpreter as data
tamper-evident(accept, tamper, verify) modification of accepted data is detectable
```

These three are the same shape: hand the subject something hostile and
require that it does not become syntax. They are separated because what
counts as hostile differs by context, and a caller supplies the payload.

### What a member reports

A failure names the relation, the inputs that broke it, and the two runs
that disagreed. `idempotent` failing reports what the observation was
after one call and after two, because the difference between them is the
whole finding.

### What this does not add

No member here takes a clock, records a history, or drives concurrent
callers. Each of the twenty runs a callable a fixed number of times on
one thread and compares what it sees. That is what makes them cheap to
implement and cheap to conform to.

Sixteen relations are left out for one of two reasons. A merge that
converges is commutative, associative and idempotent, so it composes from
members proposed here. The other fifteen need several named callables,
which needs a convention for naming the parts rather than a new kind of
assertion.

## Alternatives considered

### A. Leave these to property-based testing

Every relation here is expressible as a property, and the property-based
testing libraries are mature and widely used. fast-check, hypothesis and
proptest all have more adoption than this standard is likely to reach.

Rejected because they answer a different question. A property needs a
generator, a shrinking strategy and a separate test style. An assertion
states the relation about a call the author already has in front of them,
in the test they were already writing. The two compose: the same relation
can be asserted about one input or driven over generated ones, which is
the point of naming it once.

### B. Add a general relation combinator instead of named members

One assertion taking a relation as an argument would cover all
twenty-three and any relation nobody has thought of. It is less to
specify and less to implement.

Rejected because a named relation is what makes a suite readable and what
makes coverage answerable. A test that says `idempotent` says what it
checks; a test that passes a lambda to a combinator says only that
something was checked. Naming is also what lets an overlay record that a
language cannot supply one.

### C. Take a value rather than a callable

Several members could compare two values the caller produced. That would
match the existing signatures more closely.

Rejected because the caller producing both runs is the mistake the
assertion exists to prevent. A caller who runs the subject twice and
compares has written the relation by hand. The usual error is running it
twice in a way that does not test the property.

## Drawbacks

Twenty members is a forty-nine percent increase on a set of forty-one,
and every one has to be implemented five times, named in the naming
table, and given corpus cases. On the evidence of the existing set, that
is roughly one file per family per language.

The corpus reaches a member only by naming the behaviour it wants, the
way it reaches the assertions that take a callable today. Where no named
behaviour fits, a member rests on the completeness gate and on each
implementation's own tests. Sixteen of the existing forty-one are in that
position, and every member added here that wants a subject the vocabulary
does not name joins them.

Three of the safety members need a payload to be hostile with, and what
counts as hostile is language and context specific. The caller supplies
it. So the assertion cannot tell whether that payload would have broken
an unsafe subject, which means a weak payload passes a weak subject.

## Unresolved and future work

Whether `conserves` belongs here or in the sequence group. It states that
a measured quantity is unchanged across a call, which is `pure` over a
projection rather than over whole state, and the two may be one member.

Whether the safety members belong in the standard at all. They are the
only ones whose correctness depends on a corpus of attacks that ages,
and a standard that names them takes on the job of saying what the corpus
must contain.

The relations that need a recorded history, a controlled clock or
concurrent callers are not proposed here. They need machinery the
standard does not have.

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
