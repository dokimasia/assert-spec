---
rfc: 0016
title: Recording every assertion call
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-03
updated: 2026-10-03
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0016: Recording every assertion call

## Summary

Only a failing assertion reports a record: its failure record. This RFC
adds a call record for every assertion call, pass or fail: the call's
number in its test, the assertion, the contract, the verdict, the
surface, the call site, and the detail of a failure. A property records
the calls of each of its cases, and `eventually` and `rejects` record
the calls of their bodies, each under the call that ran the body.

Recording is off by default, and `DOKIMI_ASSERT_RECORD=1` turns it on
for a run. The definition fixes the information that a recorded run
states and the encoding of a call record. Each language writes its call
records into the artifact that its test runner already writes for a
run, and its overlay names that artifact. In Go, the artifact is the
event stream of `go test -json`.

## Motivation

### A run's artifact states tests, not assertions

Each test runner reports every test of a run with its status. Go writes
the events of `go test -json`, and pytest and JUnit write their
reports. Each report states tests and their statuses, and not the
assertions that a test made. A consumer of a run's artifact cannot
answer these questions:

- Which checks did a passing test make? A test without assertions and a
  test with forty report the same status.
- Which assertion failed, and how often across runs? Following one
  assertion across runs needs its identity in every run, including the
  runs in which it passed.
- What did a passing property test? A failing property reports its run
  in its failure record. A passing property does not report, so its
  number of cases and its seed are lost.

### The failure record covers failures alone

RFC-0005 made a failure a record, the same in every language. A pass
has no record. A call record for every call gives a consumer the same
information from every language, and applies the failure record's
commitment to the calls that pass.

### Each runner already writes an artifact

The runner computes a test's status, and it writes the artifact that
states it. A call record belongs beside its test in that artifact. A
file of the library's own would repeat the runner's tracking of tests
and statuses, and a consumer would join the two by the test's name.

Go, pytest and JUnit accept data of a test's own into their artifacts:

| Runner | Channel | What the artifact contains |
|---|---|---|
| Go 1.27.1 | `Attr(key, value)`, a member of `testing.TB` | `go test -json` writes an `attr` event with the test, the key and the value |
| pytest | The `record_property` fixture | The property is part of the test's report, and reporters such as the JUnit XML report receive it |
| JUnit Jupiter 6.1.3 | `TestReporter.publishEntry(key, value)` | A report entry of the current test, which every `TestExecutionListener` receives |

Hypothesis's observability output is the prior art for a property. When
an environment variable is set, Hypothesis writes one JSON line per
test case, with the case's status and the phase that generated it. It
is off by default.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Call | One call of an assertion |
| Call record | What a recorded run writes for one call |
| Test | What the runner reports a status for: a Go test or subtest, a pytest item, a JUnit test method |
| Body | A function that an assertion runs against a seat it creates: the body of a property or of `eventually`, and the check that `rejects` runs |
| Run | One call of a body. A run of a property's body is a case |
| Artifact | The file or stream that a language's runner writes for a run |

### Tests, statuses and call records

The artifact of a recorded run states, for every test that ran:

- The test, as the runner identifies it.
- Whether the test passed, failed or was skipped.
- The call record of every call that the test's seat received, in
  order.

Every runner states the test and its status already. This RFC adds the
call records.

### The call record

| Field | Value | Present |
|---|---|---|
| `definition` | The definition version that the library implements, as `MAJOR.MINOR.PATCH` | Always |
| `seq` | The call's number in its test, from 1 | Always |
| `parent` | The `seq` of the call whose body this call ran in | For a call in a body |
| `run` | The run of that body, from 1 | For a call in a body |
| `phase` | The kind of the property's case | For a call in a property's case |
| `assertion` | The canonical id, as `assertions.json` names it | Always |
| `contract` | The caller's message, unchanged | Always |
| `verdict` | `pass`, `fail` or `error` | Always |
| `aborting` | `true` for the aborting surface, `false` for the recording one | Always |
| `where` | The call site, as `file`, the base name of the file, and `line` | When the language supplies it, as for the failure record |
| `detail` | The detail fields, as the detail section states them | On `fail`. A property states it on `pass` too |
| `error` | The text of the fault that ended the call | On `error` |
| `test` | The test, as the runner identifies it | When the artifact does not state the test beside the call record |

`where.file` is the base name, as in the store's identity, so a call
record is the same on every machine that checks the test out.

A passing `equal`:

```json
{
  "definition": "2.3.0",
  "seq": 1,
  "assertion": "equal",
  "contract": "the count is right",
  "verdict": "pass",
  "aborting": true,
  "where": { "file": "store_test.go", "line": 42 }
}
```

A failing `equal` on the recording surface:

```json
{
  "definition": "2.3.0",
  "seq": 2,
  "assertion": "equal",
  "contract": "the name is kept",
  "verdict": "fail",
  "aborting": false,
  "where": { "file": "store_test.go", "line": 43 },
  "detail": { "want": { "type": "string", "value": "Ada" },
              "got":  { "type": "string", "value": "ada" } }
}
```

### Verdicts

| `verdict` | The call |
|---|---|
| `pass` | The assertion found what the contract requires |
| `fail` | The assertion did not, and the call reported its failure record |
| `error` | The call ended without a verdict, because the library refused an argument or its environment, and the test failed |

A malformed `DOKIMI_ASSERT_PROP_SEED`, a replay token in a form that no
encoder writes, and a damaged file in a property's store each end a
call with `error`.

### The detail

- A failing call's record states the detail of its failure record:
  every field that the assertion declares, each value a typed literal.
- A passing call's record states no detail. A passing value is the
  test's data, it can be large, and no output of the test contains it.
  Some fields, such as the `index` of `pairwise`, have no value on a
  pass.
- `prop-for-all` and every property form state their detail on a pass
  too, because the detail of a run describes the run on every outcome.
  On a pass, `outcome` is `passed`, `cases`, `rejected` and `seed`
  state the run, and every other field is null, as the behaviour vectors
  state a passing run. A passing property still does not report a
  failure record.
- A property's detail is the detail of its run, written as the form
  vectors write it. The run fixes the type of each field, so a field is
  a plain JSON value. A value that the body drew is a typed literal,
  because its type is the generator's.
- The `failure` field of a property's detail is the failure record of
  the minimal case: its `assertion`, `contract`, `detail` and `where`.

A passing property and the first call of its body:

```json
{
  "definition": "2.3.0",
  "seq": 3,
  "assertion": "prop-for-all",
  "contract": "decoding undoes encoding",
  "verdict": "pass",
  "aborting": true,
  "where": { "file": "codec_test.go", "line": 18 },
  "detail": { "outcome": "passed", "cases": 100, "rejected": 0, "seed": "7",
              "counterexample": null, "failure": null, "choices": null,
              "others": null, "divergence": null, "coverage": null }
}
```

```json
{
  "definition": "2.3.0",
  "seq": 4,
  "parent": 3,
  "run": 1,
  "phase": "simplest",
  "assertion": "equal",
  "contract": "decoding returns the encoded values",
  "verdict": "pass",
  "aborting": true,
  "where": { "file": "codec_test.go", "line": 22 }
}
```

### Values that no typed literal states

A detail can contain a value of any type, and the typed literals state
data alone. A call record states every other value as an opaque
literal:

```json
{ "type": "opaque", "text": "func(int) bool" }
```

`text` is the language's own rendering of the value, as its failure
sentence prints it. A function, a channel, a cancellation handle and an
error value are opaque. A value whose literal would nest more than 61
levels is opaque too: the store bounds an entry at 64 levels, which
leaves 61 to the value of a draw. A reader shows an opaque value and
does not compare it. A corpus case never states one.

### Calls in a body

`prop-for-all` and its forms, `eventually` and `rejects` each create a
seat and run a body against it. Every call in the body is recorded:

| Assertion | A run of its body |
|---|---|
| `prop-for-all` and every property form | A case |
| `eventually` | An attempt |
| `rejects` | The check, run once |

The call record of a call in a body states the call that ran the body
in `parent`, and the run in `run`. A call takes its number when it
reports its verdict, except a call that runs a body, which takes its
number before the calls of its body. `parent` is then always lower than
the `seq` of the calls under it.

A property records the calls of its cases that a run on one worker
makes, in the order it makes them. On one worker, a case that repeats a
tested case ends at the choice that repeats it, and a body that
diverges ends at the choice that diverges. The body does not call an
assertion after that choice. A run on n workers records the same calls
in the same order: it numbers the calls of a case when it takes the
case's result, and it records only the calls that a run on one worker
makes.

A call in a property's case states the kind of its case in `phase`:

| `phase` | The case |
|---|---|
| `example` | A case whose values the caller states, through `prop.draws` or `prop.example` |
| `stored` | A case that the store keeps |
| `simplest` | The case whose every choice is its target |
| `random` | A random case |
| `prefix` | A prefix case |
| `edge` | An edge case |
| `coverage` | A random case of the coverage phase |
| `replay` | The replay of the failing case before shrinking |
| `shrink` | A candidate that the shrinker runs |
| `explain` | A filling or a boundary step of the explain phase |
| `token` | The case of a replay token |
| `fuzz` | The case that the fuzz bridge decodes from a fuzzer's input |

A failing property records the calls of every run of its shrink, up to
the budget of 2,000 runs, and of up to five runs per draw of the explain
phase. The property's own call record states its verdict. The call
records of its cases state the verdict of each call in each case.

### The test of a call record

A call record belongs to the test whose seat received the call. A call
in a body belongs to the test of the call that ran the body. Only a
test's seat writes call records into an artifact.

A test creates a recorder seat to read the outcome of a call. The
recorder keeps the call records of the calls it receives whatever the
switch states, and its member `records` returns them, one encoded call
record each. They do not enter the artifact, because the test treats
such a call as its subject. The test's own verdict on the outcome is a
call of its own.

### Facts that a call record omits

- The values of a passing call, for the reasons that the detail states.
- The values that a case decoded. A property's record states the
  counterexample of the minimal case. RFC-0010 leaves an output per case,
  for tools that chart what a run generated, to a proposal of its own.
- A test's failure outside every call, such as a panic. The test's
  status states it.
- The time of a call. The runner states the time of each test.

### The switch

| `DOKIMI_ASSERT_RECORD` | Effect |
|---|---|
| Unset, empty or `0` | A test's seat writes no call record. This is the default |
| `1` | A test's seat writes the call record of every call it receives |
| Any other value | Every call ends with a fault that names the variable, and its test fails |

A library reads the variable once per process, so a change during the
run has no effect. With recording off, a call on a test's seat reads the
switch and does not build a call record. The allocation ceilings of the
assertions apply to such a call.

A recorder seat keeps the call records of its calls whatever the switch
states, because a test reads them as the outcome of its subject. The
calls in a body are recorded when the call that ran the body is
recorded. A corpus runner then reads the call records through its
recorder seat in the process that runs the corpus.

Recording is off by default, because a recorded run costs output and
time:

- `go test -v` prints one `=== ATTR` line per call record, and a
  property records the calls of every case.
- `go test -json` writes every call record twice: as the `attr` event,
  and as an `output` event that repeats the line.
- A recorded call builds and encodes its call record, and a failing call
  encodes its values.

We measured the first two in Go 1.27.1.

The switch is an environment variable, as `DOKIMI_ASSERT_PROP_SEED`,
`DOKIMI_ASSERT_PROP_REPLAY` and `DOKIMI_ASSERT_PROP_PROFILE` are, and not
a command-line flag. A Go test flag fails `go test ./...` in every
package whose test binary does not define it. In a module of two
packages, one of which defined `-record`, the other package's test
binary exited with `flag provided but not defined: -record`, and the run
failed.

### The artifact

The definition fixes what a recorded run states and how a call record
is encoded. Each language chooses the artifact that contains its call
records, and its overlay states the artifact under a new key,
`records`:

| Key | Meaning |
|---|---|
| `artifact` | What the runner writes for a run, and the command that writes it |
| `location` | Where each call record is in the artifact, and how the artifact names its test |
| `status` | Where the artifact states each test's status |

A language whose runner does not accept data of a test's own writes its
call records to a file of its own, one call record per line, each with
its `test`, and states the file in `artifact`.

The entry for Go:

```json
"records": {
  "artifact": "The event stream that go test -json writes for a run. go test writes the call records under -json and -v alone.",
  "location": "One attr event per call record. Its Package and Test name the test, its Key is dokimi.assert.<seq>, and its Value is the call record's JSON. A call record whose line does not fit test2json's 4,096-byte line buffer is split over consecutive attr events of the same Key, whose Values join into the call record.",
  "status": "The pass, fail and skip events of each test."
}
```

The split follows from test2json. In Go 1.27.1, test2json reads the test
binary's output through a 4,096-byte buffer, and it turns an `=== ATTR`
line into an `attr` event only when the whole line fits. A value of
4,006 bytes became an `attr` event. Values of 4,106 and 9,006 bytes
became `output` events alone.

### Encoding

- A call record is one JSON object in UTF-8, written on one line.
- Its keys are the fields of the call record. A field that is not
  present is absent, never null.
- `detail` is a JSON object keyed by the assertion's detail fields, as
  in the failure record.
- Every value in the detail of an assertion other than a property is a
  typed literal of `spec/encoding.md`, or an opaque literal. A
  property's detail is the detail of its run, as the detail section
  states.

### What changes in the definition

| File | Change |
|---|---|
| `spec/recording.md` | New. The call record, the verdicts, the phases, the calls in a body, the switch and the artifact |
| `spec/encoding.md` | The opaque literal, for call records alone |
| `spec/overlays.md` | The `records` key |
| `spec/conformance.md` | The call record in the Fixed tier, and the artifact in the Declared tier |
| `naming.yaml` | `recorder-seat.records` |
| `corpus/prop/recording.yaml` | New vectors: the call records of a property's runs |
| The validator | Requires `records` in an overlay that extends 2.3.0 or later, and a recorded call of every phase but `fuzz` in the recording vectors |

### Conformance

- Each corpus runner runs every case through its recorder seat, which
  keeps the case's one call record, and checks that record: `seq` 1
  without a `parent`, the case's assertion, the contract unchanged, the
  verdict that the case's `expect` states, `aborting` for the surface it
  ran, and the detail as it checks a failure record. A passing case's
  record states no detail.
- Each recording vector states a body that asserts once per run with
  `true`, a seed and settings. It pins the `run`, the `phase` and the
  verdict of every call record that the run writes, in order. The six
  vectors are a passing run, a failing run with its replay, shrink and
  explain runs, a run with a coverage requirement, a replay token, an
  example and stored cases, and a failing run on four workers.
- `eventually` and `rejects` take bodies that no corpus case can state.
  Each implementation tests the call records of their bodies itself, as
  it tests the two assertions.
- The validator refuses an overlay that extends 2.3.0 or later without
  `records`, a `records` entry with a missing or empty key, and
  recording vectors that leave a phase other than `fuzz` without a
  recorded call. Each rule has a test that breaks it.

| Tier | What it covers here |
|---|---|
| Fixed | The fields of a call record and their encoding, the verdicts, the phases, the opaque literal, the numbering, the switch and its values, which calls a run records, and the order of a property's call records |
| Named | `recorder-seat.records` |
| Declared | The artifact, in the overlay's `records` entry |
| Free | How a library writes a call record into the artifact |

### Version

The definition moves to 2.3.0. Recording adds a capability and changes
no assertion's meaning, which the versioning rule makes a minor version.
An overlay that extends 2.2.0 needs no `records` entry, so each
implementation records calls from the release in which it moves to
2.3.0.

## Alternatives considered

### A. The library writes a file of its own in every language

Each library writes one JSON-lines file per process, with every call
record and its test.

Rejected because the runner computes a test's status after the test's
function returns. A panic, a call of the seat's `fail` member by the
test's own code, and a failing cleanup each fail a test whose calls all
passed. The file would state call records without statuses, and a
consumer would join it with the runner's artifact by the test's name.
`go test ./...` also runs one process per package. A language whose
runner does not accept data of a test's own writes its own file, as the
design allows.

### B. A passing call states its detail

Every call record states the assertion's detail, so a consumer sees what
each passing call compared.

Rejected:

- A passing value is the test's data, and no output of a test contains
  it. A recorded run would copy every compared value into an artifact
  that CI keeps and that a dashboard reads.
- A property records the calls of every case. A passing `equal` over a
  large structure in 100 cases would encode the structure 100 times.
- Some fields have no value on a pass, such as the `index` of
  `pairwise`.

A consumer that needs a measured value on a pass, such as an allocation
count, would reverse this decision for the assertions that measure.

### C. Recording on by default

Rejected because of the volume measured in Go: one `=== ATTR` line per
call under `-v`, and every call record twice under `-json`. An
unrecorded run also writes exactly what it writes without this RFC.

### D. One record per test

A test states the number of its calls that passed and failed.

Rejected because a count identifies no assertion. A consumer could not
tell which assertion failed, or follow one assertion across runs.

### E. A tracing or logging framework

Each call is a span of OpenTelemetry, or an event of the language's
logger.

Rejected because spans, levels and attribute groups model nothing that a
call record states, and none of them encodes typed literals. Hypothesis
calls its own observability output "deliberately a much lighter-weight
and task-specific system than e.g. OpenTelemetry".

## Drawbacks

- Every assertion in every implementation reports a pass as well as a
  failure, through one function per implementation.
- A failing property records every run of its shrink and of its explain
  phase: up to 2,000 runs, and up to five per draw, each with the calls
  of its body.
- A consumer reads one kind of artifact per language. The call records
  in each are the same, and each overlay states its artifact.
- Go writes every call record twice under `-json`, and it splits a call
  record whose line does not fit test2json's buffer.
- An assertion inside a callable that another assertion measures, or
  inside a benchmark's loop, records on every call. The call record's
  allocations count in the measurement, so an allocation ceiling over
  such a callable can fail in a recorded run.
- An opaque value states the language's text, so two languages can state
  one value differently.
- A test that asserts from more than one thread numbers its calls in the
  order in which the threads report them, and that order can differ
  between runs.

## Unresolved and future work

None.

## References

| What | Where |
|---|---|
| Go 1.27.1, `testing.TB.Attr` and its contract | `src/testing/testing.go`, lines 975 and 1747 to 1770 |
| Go 1.27.1, test2json's `attr` action and its 4,096-byte input buffer | `src/cmd/internal/test2json/test2json.go`, lines 96, 133 and 355 |
| pytest, `record_property` | <https://pytest.readthedocs.org/en/latest/builtin.html> |
| JUnit 6.1.3, `TestReporter` | <https://docs.junit.org/6.1.3/api/org.junit.jupiter.api/org/junit/jupiter/api/TestReporter.html> |
| Hypothesis, observability | <https://hypothesis.readthedocs.io/en/latest/reference/integrations.html> |
| The failure record | RFC-0005 and `spec/failure.md` |
| The detail of a run, the phases, and the store's identity and depth bound | RFC-0010 |
| The typed-literal encoding | `spec/encoding.md` |
| The versioning rule | `README.md`, Versioning |
