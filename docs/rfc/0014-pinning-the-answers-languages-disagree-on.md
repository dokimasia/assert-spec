---
rfc: 0014
title: Pinning the answers languages disagree on
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-02
updated: 2026-10-02
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0014: Pinning the answers languages disagree on

## Summary

Version 2.0.0 of the definition states, as corpus cases, the answers on
which the target languages' standard libraries disagree: the unit of a
text's length, the dialect of `matches`, null under `empty`, `-0`
under `equal`, coercion under `contains`, infinities under `close-to`,
NaN bounds under `in-range`, and the relaxations. It corrects 18 arity
values to the rule that the assertion table states, and it makes each
conformance check fail on the faults it let pass: a tampered vendored
copy, an undeclared skip, a wrong failure record and an unproven
validator rule.

## Motivation

A corpus case pins an answer only where somebody wrote the case. The
definition left these inputs without a case, and Go and Python 3.14's
standard libraries give different answers to each:

| Input | Go | Python 3.14 |
|---|---|---|
| The length of `"é"`, `"😀"` and `"é"` | 2, 4 and 3, in bytes | 1, 1 and 2, in code points |
| `"^abc$"` against `"abc\n"` | No match | `re.search` matches |
| `"^\d$"` against `"٣"` | No match | `re.search` matches |
| `"(a)\1"` against `"aa"` | RE2 rejects the pattern | `re.search` matches |
| `+Inf` close to `+Inf` within 1 | `abs(a - b)` is NaN | `math.isclose` is true |
| `1` in a list of `1.0` | No match | `1 in [1.0]` is true |

A suite written against those defaults passes in Go and in Python while
the two copies test different things. That is the drift the standard
exists to catch, and the corpus caught none of it.

The checks around the corpus had gaps of the same kind. A vendored
overlay was never compared with its digest. A corpus file and its digest
could be edited together. Strict mode passed when upstream could not be
read. 48 of the validator's 94 rules could be deleted without a test
failing.

## Detailed design

### The answers the corpus pins

| Assertion | Answer | Corpus cases |
|---|---|---|
| `length` | Text has the number of its Unicode scalar values. A byte string has its number of bytes. A null value has no length, and fails with `got` null | `length/text-counts-scalar-values` and 5 more |
| `empty`, `not-empty` | A null value is no container, and both fail. `empty` reports `length` null | `empty/null-is-no-container`, `not-empty/null-is-no-container` |
| `equal`, `not-equal` | Floats compare by value, so `-0` equals `+0` | `equal/negative-zero-equals-zero`, `not-equal/negative-zero-against-zero` |
| `contains` | An element or a key compares as `equal` compares, so an int does not match a float | `contains/an-int-does-not-match-a-float` |
| `matches` | The pattern is in the portable subset that `string-matching` reads. It matches anywhere in the text. `$` matches at the end of the text only, `\d`, `\w` and `\s` are their ASCII classes, and `.` matches no line terminator. A pattern outside the subset fails the assertion | `matches/dollar-matches-at-the-end-of-the-text-only` and 10 more |
| `close-to` | Two equal infinities are not close, because their difference is NaN | `close-to/equal-infinities-are-not-close` |
| `in-range` | A range with a NaN bound contains no number | `in-range/a-nan-low-bound-contains-nothing`, `in-range/a-nan-high-bound-contains-nothing` |
| `completes-within` | A subject that has not returned when the duration has passed fails then, and the assertion does not wait for it | None: a case would state a duration, and the answer would depend on the machine |

The unit of length is the Unicode scalar value because every target
language counts one without a dependency. A byte count would make the
languages whose strings are not bytes encode the text first, and a
grapheme count would need segmentation tables whose Unicode version
moves. A caller who needs the byte length of a text passes its bytes.

The subset of `matches` is the one that `string-matching` already
defines as what every target engine reads the same way. Each
implementation parses it as `string-matching` does, and states the
subset's meaning to its own engine: an anchor at the end of the text,
ASCII classes, and a `.` that excludes `\n`, `\r`, U+0085, U+2028 and
U+2029.

The subset gains two limits, because an engine refused patterns inside
it. RE2 refuses nested counts whose product passes 1,000, such as
`(a{1000}){2}`, so the counts along every chain of nested quantifiers
multiply to at most 1,000. Python's engine refuses groups nested 495
deep, and the reference parser stopped with a recursion error at 199, so
groups nest at most 100 deep. RFC-0010 states both limits with the rest
of the subset.

### Relaxations in the corpus

A case may state `options`, a list of relaxation ids that its assertion
accepts. A case whose options include a relaxation that a language
declines in its overlay does not apply to that language.

`equate-empty` compares an absent container with an empty one of the
same type, and the typed-literal encoding had no absent container of a
type. A `list` with `of` and a `value` of null now states an absent list
of that type, and a `map` with `key`, `of` and a null `value` an absent
map. A language without typed absence decodes both to its null.

The corpus states 14 cases with options or absent containers, flat and
nested: 12 under `equal`, `not-equal`, `contains` and `not-contains`,
and one each under `nil` and `not-nil`.

### The failure record

The corpus now checks the whole record of every failing case:

- The record's `assertion` is the case's assertion.
- Its contract is the caller's message, unchanged.
- It contains exactly the fields that the assertion declares, whether
  the case states their values or not.

`contains-in-order`'s cases state `haystack` as well.

### Arity

The assertion table states that arity counts the required arguments,
excluding the failure seat and including the trailing message. 18 values
counted the seat. They now follow the rule:

| Assertion | Before | After |
|---|---|---|
| `pairwise`, `err-is`, `err-is-not`, `completes-within`, `pure`, `eventually-true` | 4 | 3 |
| `err-absent`, `err-present`, `throws`, `not-throws`, `honours-cancellation`, `honours-deadline`, `nil-context-safe`, `rejects` | 3 | 2 |
| `eventually` | 5 | 4 |
| `golden-match`, `golden-match-at` | 5 | 3 |
| `golden-match-json-field` | 6 | 4 |

A type that the caller states counts as an argument, so `err-as` keeps
3. Optional arguments do not count: the relaxations, a golden
comparison's scrubbers and a property's options. Each implementation's
completeness gate compares the arity with its members as far as its
language can read them, and states which members its language spells
another way.

### The checks around the corpus

| Check | What it now refuses |
|---|---|
| `spec-check.sh` | An overlay that differs from the manifest's entry for its language. A manifest whose digest is not the digest of the files it lists. Under `--strict`, an upstream that cannot be read, with exit status 3 |
| The validator | A language that names some assertions and not all of them. A case option that is not a list, that names a relaxation its assertion does not accept, or that repeats one. A file that is no JSON object, reported where it raised before |
| A corpus runner | A subject or a call that the implementation cannot make and that no skip declares |

Every rule of the validator has a test that breaks it, and every check of
`spec-check.sh` has a test that vendors a copy it must refuse.

### Version

The definition moves to 2.0.0. A pinned answer fails an implementation
whose answer differs, and the arity corrections change a value that a
completeness gate reads, so the change is major under the versioning
rule.

## Alternatives considered

### A. Leave the answers to each language

Each language keeps its platform's answer, and the README warns about
the differences.

Rejected because a warning does not fail a build. Each row of the
motivation's table is the drift that RFC-0001 exists to catch.

### B. Count text in bytes

Rejected because Python, Java, Kotlin and TypeScript would encode a
text before they could count it, and a caller who wants bytes can pass
them.

### C. Each language's own regular expressions, with the differences declared

Rejected because the differences are in the commonest syntax: `$`,
`\d` and `.`. A declared divergence on each would leave `matches`
meaning something different in every language.

### D. `empty` passes on null

The definition keeps an absent value apart from an empty one, and
`equate-empty` is how a caller relaxes that. We rejected the option for
that reason.

## Drawbacks

- Every implementation fails cases until it changes. An implementation
  that counts a text in bytes, reads `$` before a final newline, or
  passes a regular expression to its platform unchanged fails them.
- `matches` refuses patterns that callers write today, such as
  lookarounds and backreferences.
- A runner checks more of every record, so an implementation that
  reported extra fields fails cases it passed.

## Unresolved and future work

- `empty`, `not-empty` and `length` of an absent container of a stated
  type. Go reads a nil slice as one that has no items, and a language
  without typed absence reads its null as no container. We state no
  such case until we decide which answer the standard takes.
- Cases for `completes-within`, which need a duration that no machine
  can miss.

## References

| What | Where |
|---|---|
| Unicode scalar value | The Unicode Standard 16.0, definition D76 |
| The portable subset | RFC-0010, the `string-matching` generator |
| The versioning rule | `README.md`, Versioning |
