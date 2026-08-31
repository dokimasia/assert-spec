---
rfc: 0005
title: The failure record
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-31
updated: 2026-08-31
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0005: The failure record

## Summary

A failure is a string in all five implementations, and the corpus checks
one by looking for words inside it. This replaces both: a failure becomes
a record with named values, and a corpus case states the values it
expects rather than substrings it hopes to find.

## Motivation

The current check does not work, and there is a case that proves it.

The corpus requires the `nil` failures to carry the word `nil`. Python's
`is_none` reports `expected none, got 0`, which does not contain it. The
case passes anyway, because the failure leads with the caller's message,
the caller's message is the case id, and the case id is
`nil/zero-is-not-null`. The word the corpus asks for comes from the id
being echoed back, never from the assertion. Every `nil` and `not-nil`
case in Python passes on that accident.

That is one language and one family, found by accident while writing a
sixth implementation. Nothing about the mechanism confines it to either.
A message begins with a string the caller chose, so searching that
message for a substring is a check the caller can satisfy.

The definition already gestures at something better. Each assertion
carries `message_fields`, but the entries are words rather than names:
`equal` lists `want` and `got`, and `nil` lists `nil`. The first pair
reads like field names and the third does not, because they were written
as words a message ought to contain.

There is a second reason, which is what the failure is for. A generator
emitting suites in five languages gets five string formats back and has
to parse them to do anything: aggregate a run, deduplicate the same
failure found in Go and Rust, or minimise an input. A record is the same
shape everywhere.

## Detailed design

### The record

```
Failure
  assertion   the canonical id, as the definition names it
  contract    the caller's message, unchanged
  detail      named values, keyed by the names the assertion declares
  where       the file and line the assertion was called from, when the
              language can supply one
```

`contract` stays exactly what a caller passed. `detail` is what replaces
reading values out of a sentence.

For `equal` reporting a mismatch:

```json
{
  "assertion": "equal",
  "contract": "the count is right",
  "detail": { "want": 2, "got": 1 },
  "where": { "file": "tests/store_test.go", "line": 42 }
}
```

`where` is absent where a language cannot produce it without a cost the
standard should not impose. Rust supplies it from `#[track_caller]`, Go
from the runtime, Python from the frame. It is not required.

### What an assertion declares

`message_fields` becomes `detail_fields`, and its entries become names
rather than words:

| Assertion | Today | Proposed |
|---|---|---|
| `equal` | `[want, got]` | `[want, got]` |
| `nil` | `[nil]` | `[got]` |
| `length` | `[length]` | `[want, got]` |
| `in-range` | `[range]` | `[got, low, high]` |
| `close-to` | `[within]` | `[got, want, tolerance]` |
| `throws` | `[panic]` | `[]` |

Two of them read as names already and carry over. The rest were words,
and each becomes the values the failure holds.

An assertion may declare no fields. `true` and `false` report the
contract alone, which is what the definition already says about them.

### What a corpus case states

A case expecting a failure names the detail it expects:

```json
{
  "id": "equal/differing-ints",
  "args": [ {"type": "int", "value": 1}, {"type": "int", "value": 2} ],
  "expect": "fail",
  "detail": { "want": {"type": "int", "value": 2},
              "got":  {"type": "int", "value": 1} }
}
```

The values use the typed-literal encoding the arguments already use, so
an int and a float that print the same stay different, and a case cannot
be satisfied by a value of the wrong type that happens to render alike.

A case may state some fields and not others. What it states must match;
what it omits is not checked. That keeps a case from pinning a detail it
does not care about.

### What a failure still renders to

A record renders to the sentence a person reads. Nothing about a test's
output changes:

```
the count is right: want 2, got 1
```

The rendering is per-language and unstandardised, because a Go developer
and a Python developer read different conventions and neither is served
by splitting the difference. What is standardised is the record behind
it.

### Migration

Nothing outside these repositories implements a seat or reads a failure,
so there is no compatibility to keep. The corpus states `detail`, the
implementations report a record, and `message_contains` goes at the same
time.

Reading both forms during a transition was the alternative, and it costs
a checker that understands two ways of stating the same expectation for
as long as the transition lasts. With no caller to protect, that buys
nothing.

## Alternatives considered

### A. Keep strings and require the word to come from the assertion

The corpus could require that the failure carry the word once the
caller's message is stripped. That is a small change to the checker and
no change to any implementation.

Rejected because it fixes one symptom of a design that has others. It
still cannot tell an int from a float that renders the same, still gives
a generator nothing to read, and still makes a failure's content depend
on prose that each language writes differently.

### B. Standardise the rendered sentence too

If the record is standardised, the sentence could be as well, and then
the corpus could compare messages exactly.

Rejected because the sentence is the part a person reads in their own
language's idiom. Go's `want X, got Y` and Python's `expected X, got Y`
are each right in place. Standardising the record gets the checkable
benefit; standardising the prose gets an argument.

### C. Make `where` required

A failure that cannot say where it came from is harder to act on, and
four of the five implementations can supply it.

Rejected because the fifth would have to pay for it. Requiring a stack
walk on every failure to satisfy the standard would make the standard
the reason a library is slow.

## Drawbacks

Every assertion in five implementations changes how it reports. That is
the largest single change the standard has asked for, and it touches the
one path every assertion goes through. The clock proposal changes the
same interface, so the two want doing together rather than in sequence.

Seventy corpus cases need `detail` written for them, and writing it means
deciding what each assertion's failure holds. For several the answer
differs from what the current word suggests, so this is work rather than
transcription.

The record is a second thing to keep in step with the naming table. An
assertion gaining a field is now a definition change as well as an
implementation one.

Rendering stays unstandardised, so a reader moving between languages sees
different sentences for the same failure. That was already true and this
does not fix it.

## Unresolved and future work

Whether `detail` values should be typed literals or plain JSON. Typed
literals keep an int and a float apart, at the cost of a corpus that is
more verbose to read.

Whether a failure should carry the relaxations in force. A case where
`equate-nans` changed the answer is currently indistinguishable from one
where it did not.

Whether `where` should be a list rather than one location, for an
assertion whose failure involves two call sites.

## References

- The typed-literal encoding, which `detail` reuses:
  `spec/encoding.md`
- Automatically generated oracles encoding implemented rather than
  intended behaviour, which is the reason a fixed record beats a
  scraped one: Bodicoat, Jahangirova and Terragni,
  <https://arxiv.org/abs/2601.05542>
