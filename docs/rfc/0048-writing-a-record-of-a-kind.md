---
rfc: 0048
title: Writing a record of a kind
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-29
updated: 2026-10-29
discussion: https://github.com/dokimasia/assert-go/issues/81
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0048: Writing a record of a kind

## Summary

A tool of dokimasia writes its records into the artifact of the test
runner, beside the call records of assert. The overlay of each language
states one place for a record of every kind. Each library applies that
rule to its own call records, in code that it does not export. This
proposal adds the helper `write-record(seat, kind, record)`:

- It writes `record`, the JSON text of one record, into the artifact of
  the test of `seat`, at the place of `kind`.
- It numbers the records of each kind in each test from 1.
- It ends the call with a fault for a kind outside the pattern of a kind,
  for the kind `dokimi.assert`, and for a record that is not one JSON
  object.
- It does not write on a recorder, or on another seat that keeps its call
  records as values.

Definition 13.5.0 adds the helper.

## Motivation

dokimi's conform writes one suite record of the kind `dokimi.suite` for
each application of a suite. In Go the place of that record is an attr
event with the key `dokimi.suite.<n>`. test2json turns a line into an attr
event only when the line fits its buffer of 4,096 bytes. assert-go splits
a longer record over consecutive attr events of one key, and escapes every
rune beyond ASCII when a line has room for fewer bytes than a rune takes.
That code is unexported in `internal/record/attr.go`, and its key prefix is
fixed to `dokimi.assert.`.

Without the helper, conform copies about 40 lines of that code. The copy
has to follow each change of the overlay by hand, and a change of the rule
in assert-spec then needs a change in two modules.

The tools of the other languages meet the same gap:

| Language | The place of a record of a kind | What only assert has |
|---|---|---|
| Go | An attr event with the key `<kind>.<n>` | The split at the line buffer and the escape |
| Python | A property `<kind>.<n>` of the test's item | The item of the test of a seat |
| Rust | A line of the file beside the test binary whose suffix names the kind | The file, its lock, and its creation in each run |
| TypeScript | An element of the array under the kind in the meta object of the test's task | The task of the test of a seat |
| Java, Kotlin | A report entry `<kind>.<n>` of the test | The reporter of the test |

In each language the tool has the seat of the test. Only the internal code
of assert reaches the artifact from the seat.

## Detailed design

### The helper

```text
write-record(seat, kind, record)
```

- `record` is the JSON text of one record of `kind`, a JSON object. The
  tool fixes its fields. The definition fixes the name and the place.
- The helper writes the record into the artifact of the test of `seat`,
  at the place that the `location` of the overlay states for `kind`.
- The records of one kind in one test take the numbers 1, 2 and 3 in the
  order of the calls. In an artifact where the name of a record contains
  its number, the record takes that number.
- The helper writes whatever `DOKIMI_ASSERT_RECORD` states. That switch
  applies to the call records of assert alone.

In three cases the helper ends the call with a fault and does not write
the record:

- `kind` does not match `dokimi\.[a-z][a-z0-9-]*`.
- `kind` is `dokimi.assert`. assert numbers and writes its call records
  itself, and a second writer of the kind would break their numbering.
- `record` is not one JSON object.

The helper does not write on a seat that keeps its call records as values:
the recorder, the case of a property, and the seat that `rejects` or
`eventually` hands a body. On a seat outside a test runner it does not
write either. The helper checks the kind and the record on these seats
too, so a test of a tool on a recorder finds a wrong kind.

### The seat of each language

| Language | Seats with an artifact | The place of a record |
|---|---|---|
| Go | The first seat of the chain that is a `*testing.T`, `*testing.B` or `*testing.F`, or that embeds one. The walk stops at the first seat that keeps call records | `Attr("<kind>.<n>", value)`, split as call records are |
| Python | The `Collector` of the fixture `seat` | `(f"{kind}.{n}", record)` in `user_properties` of the test's item |
| Rust | `Collector` and `Standard` | A line of the file named after the binary with the suffix of the kind, such as `.dokimi-suite.jsonl`. A run of the binary writes the file anew |
| TypeScript | The seat of the fixture of `@dokimi/assert/vitest` | The parsed record, pushed onto `meta[kind]` of the test's task |
| Java, Kotlin | The seat of `SeatExtension` | A report entry `<kind>.<n>` through the `TestReporter` of the test |

The location rule of Rust asks every line to name its test. A call record
names it in the field `test`. A record of another kind names it in a
field that its tool fixes, because the helper does not change the JSON of
a tool.

```go
// WriteRecord writes record, the JSON text of one record of kind, into the
// artifact of the test of tb. The record is an attr event with the key
// <kind>.<n>, and n counts the records of kind in the test from 1. A record
// whose line does not fit the line buffer of test2json is split over
// consecutive attr events of the key, as a call record is. A kind outside
// the pattern of a kind, the kind dokimi.assert and a record that is not one
// JSON object end the call with a fault.
func WriteRecord(tb TB, kind, record string)
```

```python
def write_record(seat: Seat, kind: str, record: str) -> None:
    """Write record, the JSON text of one record of kind, into the artifact
    of the test of seat."""
```

```rust
/// Writes `record`, the JSON text of one record of `kind`, into the artifact
/// of the test of `seat`.
pub fn write_record(seat: &dyn Seat, kind: &str, record: &str)
```

```typescript
/** Writes record, the JSON text of one record of kind, into the artifact of the test of seat. */
export function writeRecord(seat: Seat, kind: string, record: string): void;
```

Go adds `expect.WriteRecord`, which calls `assert.WriteRecord`, as
`expect.Cleanup` calls `assert.Cleanup`. The writer of the call records of
Go calls the same split with the kind `dokimi.assert`.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `write-record` | `WriteRecord` | `write_record` | `write_record` | `writeRecord` | `Check.writeRecord` | `Check.writeRecord` |

### Conformance

A record of a kind is an output of a test, so no vector pins it. Each
language tests these behaviours in its own tests:

- The helper writes each record at the place of its kind, numbered from 1
  in each test.
- Go splits a record whose line does not fit the buffer of test2json, as
  it splits a call record.
- Each of the three faults ends the call on a seat with an artifact and on
  a recorder, and nothing is written.
- A recorder writes nothing for a valid record.

### Version

The helper adds a name and changes the meaning of no name. Definition
13.5.0 adds the row, and every overlay extends 13.5.0.

## Alternatives considered

### A. The caller numbers the records

The helper would take the number of the record, as the request in the
discussion proposes.

**Why not:** in Go two records with one number share one key, and a
reader joins their values into one record that is not JSON. Rust and
TypeScript do not number their records, so the argument would be unused
there.

### B. A writer in Go alone

assert-go would export the writer, and the definition would not name it.

**Why not:** the place of a record of every kind is part of the
definition, and the naming table lists every public item. The libraries
of Python, Rust, TypeScript, Java and Kotlin keep the way to the artifact
in internal code too, so a tool in those languages meets the same gap.

### C. A recorder keeps the records of every kind

A recorder would keep the records of each kind, and a member would return
them.

**Why not:** the recorder of every language would gain a member that no
tool has asked for. A tool tests its records as the JSON that it builds,
before it writes them.

### D. The helper follows `DOKIMI_ASSERT_RECORD`

**Why not:** a run that does not record calls would lose the suite records
of dokimi. The switch belongs to the call records of assert.

## Drawbacks

- One helper in six languages, and one row in the naming table.
- Go keeps a counter for each kind of each test for the life of the
  process, as it keeps the call records of each test.
- Rust writes one more file beside a test binary that writes a record of
  another kind.
- A record of a kind on a recorder is lost. A tool that reads its records
  back in a test runs the test on a seat of the runner.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/81> |
| The kinds of record in an artifact | RFC-0043, and `spec/overlays.md`, section Records |
| The call records | RFC-0016 and `spec/recording.md` |
| The split at the line buffer of test2json | `internal/record/attr.go` of assert-go |
