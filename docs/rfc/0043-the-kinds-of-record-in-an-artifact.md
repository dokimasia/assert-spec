---
rfc: 0043
title: The kinds of record in an artifact
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-28
updated: 2026-10-28
discussion: https://github.com/dokimasia/assert-spec/issues/25
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0043: The kinds of record in an artifact

## Summary

The entry `records` of an overlay states where a language writes its call
records in the artifact of its test runner. It states nothing about a record
of another tool in the same artifact. This proposal lets one artifact
contain the records of more than one tool:

- The prefix `dokimi.` of a record's name is reserved for the tools of
  dokimasia. The call records of assert are the kind `dokimi.assert`.
- The entry `records` gains the key `kinds`, the kinds of record that the
  artifact can contain.
- The rule of `location` applies to every kind: a record of another kind is
  found and split as a call record is, under the name of its own kind.
- `overlays.md` lists each kind and the specification that fixes its
  records.

Definition 13.1.0 adds the key and the rule.

## Motivation

### dokimi writes its suite records into the artifact of assert

dokimi writes a suite record for each application of a suite. It writes the
record into the artifact that the test runner writes, beside the call
records of assert, so one upload and one parser cover both. In Go a suite
record is an attr event with the key `dokimi.suite.<seq>`, next to the attr
events of `dokimi.assert.<seq>`.

The definition does not state that key:

- A later name of assert-spec could collide with `dokimi.suite`.
- The overlay does not list the names that a reader of the artifact finds
  there.
- The validator checks `artifact`, `location` and `status`. None of them
  states the records that a tool may add.

### The place of a record's name in each artifact

| Language | Where the name of a record is |
|---|---|
| Go | The `Key` of an attr event: `dokimi.assert.<seq>` |
| Python | The `name` of a property element of the JUnit XML: `dokimi.assert.<seq>` |
| Java, Kotlin | The `name` of a property element of the JUnit XML: `dokimi.assert.<seq>` |
| TypeScript | A key of the meta object of a test: `dokimi.assert`, with an array of records |
| Rust | The suffix of a file of the library's own: `.dokimi-assert.jsonl` |

In each of the six overlays, the name of a call record starts with
`dokimi.assert`. Only the rule for a second name is missing.

## Detailed design

### The reserved prefix

A name of a record in an artifact that starts with `dokimi.` belongs to a
tool of dokimasia. A kind is the part of the name before the number of the
record: `dokimi.assert` in `dokimi.assert.3`. A kind matches
`dokimi\.[a-z][a-z0-9-]*`.

### The entry

```json
"records": {
  "artifact": "The event stream that go test -json writes for a run.",
  "location": "One attr event per record. Its Package and Test name the test, its Key is the kind of the record followed by the record's number in its test, such as dokimi.assert.3 or dokimi.suite.1, and its Value is the record's JSON. A record whose line does not fit test2json's 4,096-byte line buffer is split over consecutive attr events of the same Key.",
  "status": "The pass, fail and skip events of each test.",
  "kinds": ["dokimi.assert", "dokimi.suite"]
}
```

| Key | States |
|---|---|
| `artifact` | What the runner writes for a run, and the command that writes it |
| `location` | Where each record is in the artifact, under the name of its kind, and how the artifact names its test |
| `status` | Where the artifact states each test's status |
| `kinds` | The kinds of record that the artifact can contain |

`location` states one rule for every kind. Each language rewrites its
`location` so that the kind takes the place of `dokimi.assert`:

| Language | The record of a kind |
|---|---|
| Go | An attr event whose `Key` is the kind followed by the number |
| Python, Java, Kotlin | A property element whose `name` is the kind followed by the number |
| TypeScript | An element of the array under the key of the kind in the meta object |
| Rust | A line of the file whose suffix is the kind with each `.` replaced by `-`, followed by `.jsonl`, such as `.dokimi-suite.jsonl` |

### The kinds

`overlays.md` lists each kind with the specification that fixes its
records:

| Kind | Records | Specification |
|---|---|---|
| `dokimi.assert` | The call records of assert | `recording.md` of this definition |
| `dokimi.suite` | The suite records of dokimi, one for each application of a suite | dokimi |

A kind joins the table through an RFC of this repository. assert-spec does
not fix the fields of a kind that another tool writes. It fixes the name and
the place.

### The validator

The validator refuses an entry `records` in these cases:

- `kinds` is missing, is not a list or is empty.
- A value occurs twice, or does not match the pattern of a kind.
- A kind is not in the table of `overlays.md`.
- `dokimi.assert` is not among the kinds.

### Version

The key `kinds` and the reserved prefix add a rule. They do not change the
meaning of an existing record. Definition 13.1.0 adds them. Every overlay states
`kinds` and extends 13.1.0.

## Alternatives considered

### A. A convention outside the definition

dokimi would keep writing `dokimi.suite` without a rule, as it does today.

**Why not:** a later name of assert-spec could take the key. The names would
then be stated in dokimi's code alone, and not in the overlay.

### B. An object for every other property, as CTRF's `extra`

The records of other tools would go into one object that the definition does
not describe.

**Why not:** the artifacts are the runners' own formats: an event stream,
JUnit XML, a JSON report and a file of lines. None of them has an object
that this definition can add. The name of a record is the one place that
every artifact offers.

### C. One artifact for each tool

dokimi would write its suite records into a file of its own.

**Why not:** a run would need two uploads and two parsers, and the test
runner of Go, Python, Java and Kotlin writes one artifact per run. A
reader would have to join the two by the name of the test.

### D. A field `kind` in each record

Every record would state its kind in a field.

**Why not:** the call record would gain a field, a major change of its
encoding. The name of the record already states its kind in every artifact
but Rust's, and Rust's file name does.

## Drawbacks

- Every overlay gains a key, and every implementation's copy of the
  definition changes.
- The table of kinds names a tool outside this repository.
- Rust's artifact becomes one file per kind beside each test binary.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/25> |
| The entry `records` | `spec/overlays.md`, section Records |
| The call records | RFC-0016 and `spec/recording.md` |
| CTRF's `extra` | <https://github.com/ctrf-io/ctrf/blob/main/spec/ctrf.md> |
