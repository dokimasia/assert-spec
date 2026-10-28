<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# Overlays

Every assertion in the set is required. No assertion is marked
optional, because marking one optional makes a language that cannot
supply it look identical to a language whose author ran out of time.

An overlay is where a language says which of those two it is.

```json
{
  "extends": "spec://assertions@1.1.0",
  "language": "php",
  "diverge": [
    {
      "id": "bench-max-allocs",
      "stance": "blocked",
      "why": "PHP exposes no per-iteration allocation counter",
      "remedy": "none known"
    }
  ]
}
```

One file per language, named for the language, in `overlays/`. A
language with nothing to declare still carries a file with an empty
`diverge`, so full compliance is something someone stated rather than
something nobody checked.

| Key | Meaning |
|---|---|
| `extends` | `spec://assertions@<version>`, the version this overlay was written against |
| `language` | The language, matching both the filename and a column in the naming table |
| `diverge` | Every assertion this language does not supply |
| `records` | Where this language writes the call records of a recorded run |
| `sections` | How this language runs the concurrent section of a machine |

A divergence carries `id`, `stance` and `why`. `remedy` is optional and
says what would close the gap.

## Limits

A divergence says an assertion is absent. A limit says it is there and
there is a case it cannot see, which is a different thing and worth
telling apart.

```json
"limits": [
  {
    "id": "no-task-leaks",
    "what": "Sees platform threads. A leaked virtual thread is not reported.",
    "why": "Virtual threads appear in no standard enumeration on any JVM version."
  }
]
```

`what` is written for someone deciding whether to rely on the check:
say what it does see, then what it does not. An assertion cannot be
both diverged from and limited, because a divergence has to be absent
and a limit has to be present.

`why` is the whole point. A gap nobody could close and a gap nobody got
to look the same from outside, and only the reason tells them apart.
Write it for someone deciding whether to depend on the library.

The validator requires a limit on `history` in the overlays of Go, Java,
Kotlin and Rust. Their threads run on more than one core. The counter
that orders a history's events synchronizes the clients, and that
synchronization can supply a memory barrier that the subject lacks.

## What the gate does with one

An assertion missing with no matching entry fails the build. An entry
naming an assertion the library does implement fails the build too, so a
library cannot claim a gap it does not have.

`extends` pins the version. An overlay left behind by a change to the
standard fails validation rather than passing quietly.

The stance vocabulary is not closed. `blocked` is the one in use.

## Relaxations

A relaxation changes what counts as equal for one call. The definition
states three. `equate-empty` and `equate-nans` widen equality, and
fourteen assertions accept them. `by-identity` narrows it for references,
and six of those fourteen accept it.

A language may have nothing to relax. Rust's types keep an absent
container and an empty one apart, and its `==` already says NaN is
unequal to itself, so both relaxations would widen nothing. Rust's
assertions compare through `PartialEq`, which states no identity, so
Rust declines `by-identity` as well. An overlay records each the same way
it records anything else absent:

```json
{
  "relaxations": [
    {
      "id": "equate-empty",
      "why": "An absent container and an empty one are different types."
    }
  ]
}
```

Only `id` and `why` are needed. There is no `what`, because nothing is
partly there: the relaxation is either offered or it is not.

An assertion that should accept a relaxation and does not is a different
thing, and it is a limit rather than an absence. The assertion is there
and a case it should cover is missing.

## Records

`recording.md` fixes what a recorded run states. Each language writes
its call records into the artifact that its test runner writes for a
run. Its overlay states that artifact, and the kinds of record in it:

```json
"records": {
  "artifact": "The event stream that go test -json writes for a run. go test writes the call records under -json and -v alone.",
  "location": "One attr event per record. Its Package and Test name the test, its Key is the kind of the record followed by the record's number in its test, such as dokimi.assert.3 or dokimi.suite.1, and its Value is the record's JSON. A record whose line does not fit test2json's 4,096-byte line buffer is split over consecutive attr events of the same Key, whose Values join into the record.",
  "status": "The pass, fail and skip events of each test.",
  "kinds": ["dokimi.assert", "dokimi.suite"]
}
```

| Key | States |
|---|---|
| `artifact` | What the runner writes for a run, and the command that writes it |
| `location` | Where each record of each kind is in the artifact, and how the artifact names its test |
| `status` | Where the artifact states each test's status |
| `kinds` | The kinds of record that the artifact can contain |

The artifact can contain the records of more than one tool. Every name of
a record that starts with `dokimi.` belongs to a tool of dokimasia. A kind
is the part of the name before the number of the record, such as
`dokimi.assert` in `dokimi.assert.3`, and matches `dokimi\.[a-z][a-z0-9-]*`.
`location` states one rule for every kind: a record of any kind is found
and split as a call record is, under the name of its own kind.

| Kind | Records | Specification |
|---|---|---|
| `dokimi.assert` | The call records of assert | `recording.md` |
| `dokimi.suite` | The suite records of dokimi, one for each application of a suite | dokimi |

A kind joins this table through an RFC of this repository. The definition
fixes the name and the place of a record of another tool, and that tool
fixes its fields.

The validator refuses an overlay without the entry, and an entry whose
key is missing or empty. It refuses an entry whose `kinds` is not a
non-empty list, lists a kind twice, lists a value that is no kind or a kind
outside this table, or does not list `dokimi.assert`.

## Sections

A machine with two clients or more runs a concurrent section. A language
runs it as tasks of the task scheduler, which takes every release from the
case and replays, or on real threads, which the platform schedules. Its
overlay lists the ways it offers:

```json
"sections": ["tasks", "threads"]
```

| Value | States |
|---|---|
| `tasks` | A section can run as tasks of the task scheduler |
| `threads` | A section can run on real threads, and repeats each case |

The validator refuses an overlay without the entry, an empty list, a value
outside the two, and a value listed twice.
