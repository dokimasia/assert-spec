---
rfc: 0027
title: The values in the records of empty, not-empty and matches
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-07
updated: 2026-10-07
discussion: https://github.com/dokimasia/assert-go/issues/25, https://github.com/dokimasia/assert-go/issues/26
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0027: The values in the records of empty, not-empty and matches

## Summary

A failure of `empty` states the length of the value and not the value. A
failure of `not-empty` states nothing, and a failure of `matches` states no
reason when the portable subset refuses the pattern. This adds `got` to the
records of `empty` and `not-empty`, and `reason` to the record of
`matches`. `reason` is the text with which the language's parser of the
subset refuses the pattern, and null for a pattern inside the subset.
Definition 7.1.0 makes the change.

## Motivation

### A failure of empty hides the items

`empty` of a list of two strings fails with the detail `{"length": 2}`. A
reader learns that two items are there, and not which two. A test that
collects the items that break a contract, such as the files that a load
dropped, states the contract with `empty`, and its failure should name
those items.

In the test suites that we read, the test kits wrote `equal(dropped, null)`
instead, because the record of `equal` states both values. The comparison
with null hides the contract behind another one. It also fails for an
empty list, which the contract allows.

`length` already states `got` and `want`, and `equal` states both values.
`not-empty` states nothing. A reader of its record cannot tell a null value
from an empty container, or from a value that has no length.

### A refused pattern reads as a wrong value

A pattern outside the subset fails `matches`, and the record states the
text and the pattern alone. RE2 reads `\t` inside a class as a tab. The
subset escapes fewer characters and refuses it. `matches` of `text` and
`^[^\t]*$` fails with `got` and `pattern`, and a reader takes the text for
the fault.

The parser of the subset states the reason when it refuses a pattern: the
position in the pattern and the construct that the subset leaves out
there. The assertion drops it. In one suite that we read, a fuzz target
asserted that a key contained no punctuation of a grammar, with a class
that escaped a tab. Every seed failed with the record of a wrong value,
and the cause was found only by reading the parser.

### Why the definition

The values that a failure states are fixed: every language states the same
fields, and the corpus requires that each failing case's record contains
exactly the fields that its assertion declares. A language cannot add a
field to a record on its own.

## Detailed design

### empty and not-empty

```yaml
"empty":
  arity: 2
  summary: >
    The container has no items. A null value is no container, and
    fails. got is the value, and length its number of items, or null
    for a value that has no length.
  detail_fields: [got, length]

"not-empty":
  arity: 2
  summary: >
    The container has at least one item. A null value is no container,
    and fails. got is the value.
  detail_fields: [got]
```

- `got` states the value as the assertion received it: a container, a
  value that has no length, or null.
- `length` keeps its meaning. A null value and a value that has no length
  state `length` null.
- A record states a large container as it states any large value of a
  record, by the bounds of the typed literal of each language.

### matches

```yaml
"matches":
  arity: 3
  summary: >
    A pattern of the portable subset that string-matching reads matches
    anywhere in the text. $ matches at the end of the text only, \d, \w
    and \s are their ASCII classes, and . matches no line terminator. A
    pattern outside the subset is a failure, not an error, and reason is
    the text with which the language's parser of the subset refuses it.
    reason is null for a pattern inside the subset.
  detail_fields: [got, pattern, reason]
```

- `reason` depends on the pattern alone. A value that is no text and a
  pattern outside the subset state both `got` and `reason`.
- The text of `reason` is the language's own, as the sentence of a failure
  is. Each parser states the position in the pattern and the construct that
  the subset refuses there.

### The corpus

| Cases | Change |
|---|---|
| `empty/populated-list-fails`, `empty/null-is-no-container` | State `got` beside `length` |
| `not-empty/empty-list-fails`, `not-empty/empty-string-fails`, `not-empty/null-is-no-container` | State `got` |
| The five failing cases of `matches` whose pattern is inside the subset | State `reason` null |

The six failing cases of `matches` whose pattern is outside the subset
state no `reason`, because its text is the language's own. A case that
omits a field does not check it.

### The executable reference

The forms `prop-empty`, `prop-not-empty` and `prop-matches` state the
record of a failing case. The reference's judge of each states the new
fields. `make render` then writes the vectors of the three forms again.
The reference's judge of `matches` reads plain patterns alone. Each of them
is inside the subset, so its `reason` is null.

### Version

A field of a record does not change a verdict, so a test still states what
its author meant. Adding a field is a minor version change, as adding an
assertion is. Definition 7.1.0 adds the three fields. Every overlay extends
7.1.0.

## Alternatives considered

### A. A test that reads the items itself

A test would compare the value with null through `equal`. The record of
`equal` states both values.

**Why not:** the comparison states another contract. A null value and an
empty one differ under `equal`. A check that a value has no items accepts
both. The record of a failure then names `equal`, and a reader looks for
two values that should be equal.

### B. A fault for a pattern outside the subset

`matches` would end the call with a fault for a pattern outside the
subset, as it does for a misuse. The fault would state the parser's reason.

**Why not:** a fault changes what the assertion means, which is a major
version change. The definition makes such a pattern a failure because a
test with it establishes nothing. A failure with a reason reports the same
cause without that change.

### C. A refusal code in place of text

`reason` would be one of a closed list of codes, such as `escape`, `flag`,
`lookaround`, `backreference`, `count` and `depth`. The corpus could then
pin it in every case.

**Why not:** each parser would map each refusal onto the list, and the list
would change with every rule of the subset. A reader needs the position and
the construct, which the parser's text states. The corpus pins `reason`
null for every pattern inside the subset, which is the half of the field
that a wrong implementation would most likely get wrong.

## Drawbacks

- Three assertions change their records in six languages.
- A record of `empty` contains the whole container, so a failure over a
  large container writes a large record, up to the bounds of the language's
  typed literal.
- The corpus cannot check the text of `reason`. A language that states any
  text there passes, as long as it states null for a pattern inside the
  subset.
- Ten corpus cases and the vectors of three property forms change.
