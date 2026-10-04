# Recording

A recorded run writes a call record for every assertion call, pass or
fail. The record states the call's number in its test, the assertion,
the contract, the verdict, the surface, the call site, and the detail of
a failure. The calls in the body of a property, of `eventually` and of
`rejects` are recorded under the call that ran the body. Recording is
off by default.

## The switch

| `DOKIMI_ASSERT_RECORD` | Effect |
|---|---|
| Unset, empty or `0` | A test's seat writes no call record. This is the default |
| `1` | A test's seat writes the call record of every call it receives |
| Any other value | Every call ends with a fault that names the variable, and its test fails |

A library reads the variable once per process, so a change during a run
has no effect. With recording off, a call on a test's seat reads the
switch and builds no call record. The allocation ceilings of the
assertions apply to such a call.

A recorder seat keeps the call records of its calls whatever the switch
states, because a test reads them as the outcome of its subject. The
calls in a body are recorded when the call that ran the body is
recorded.

## The call record

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
  "definition": "3.0.0",
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
  "definition": "3.0.0",
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

## Verdicts

| `verdict` | The call |
|---|---|
| `pass` | The assertion found what the contract requires |
| `fail` | The assertion did not, and the call reported its failure record |
| `error` | The call ended without a verdict, because the library refused an argument or its environment, and the test failed |

A malformed `DOKIMI_ASSERT_PROP_SEED`, a replay token in a form that no
encoder writes, and a damaged file in a property's store each end a call
with `error`.

## The detail

- A failing call's record states the detail of its failure record: every
  field that the assertion declares, each value a typed literal.
- A passing call's record states no detail. A passing value is the
  test's data, it can be large, and no output of the test contains it.
  Some fields, such as the `index` of `pairwise`, have no value on a
  pass.
- `prop-for-all` and every property form state their detail on a pass
  too, because the detail of a run describes the run on every outcome.
  On a pass, `outcome` is `passed`, `cases`, `rejected` and `seed` state
  the run, and every other field is null, as the behaviour vectors state
  a passing run. A passing property does not report a failure record.
- A property's detail is the detail of its run, written as the form
  vectors write it. The run fixes the type of each field, so a field is
  a plain JSON value. A value that the body drew is a typed literal,
  because its type is the generator's.
- The `failure` field of a property's detail is the failure record of the
  minimal case: its `assertion`, `contract`, `detail` and `where`.

A passing property and the first call of its body:

```json
{
  "definition": "3.0.0",
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
  "definition": "3.0.0",
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

A call record states a function, a channel and every other value
outside the typed literals as an opaque literal, as `encoding.md`
states.

## Calls in a body

`prop-for-all` and its forms, `eventually` and `rejects` each create a
seat and run a body against it. Every call in the body is recorded:

| Assertion | A run of its body |
|---|---|
| `prop-for-all` and every property form | A case |
| `eventually` | An attempt |
| `rejects` | The check, run once |

A call in a body states the call that ran the body in `parent`, and the
run in `run`. A call takes its `seq` when it reports its verdict. A call
that runs a body takes its `seq` before the calls of its body, so
`parent` is lower than the `seq` of every call under it.

### The cases of a property

A property records the calls of its cases that a run on one worker
makes, in the order it makes them:

- A case that repeats a tested case ends at the choice that repeats it.
  A body that diverges ends at the choice that diverges. The body makes
  no call after that choice.
- A run on more workers records the same calls in the same order. It
  numbers the calls of a case when it takes the case's result, and it
  records only the calls that a run on one worker makes.

`run` numbers every call of the body, also a call that ends before the
body calls an assertion.

A call in a property's case states the kind of its case in `phase`:

| `phase` | The case |
|---|---|
| `example` | A case whose values the caller states, through `prop.draws` or `prop.example` |
| `stored` | A case that the store keeps |
| `simplest` | The case whose every choice is its target |
| `random` | A random case before the first coverage check |
| `prefix` | A prefix case |
| `edge` | An edge case |
| `coverage` | A random case after the first coverage check |
| `replay` | The replay of the failing case before shrinking |
| `shrink` | A candidate that the shrinker runs |
| `explain` | A filling or a boundary step of the explain phase |
| `token` | The case of a replay token |
| `fuzz` | The case that the fuzz bridge decodes from a fuzzer's input |

A failing property records the calls of every run of its shrink, up to
the budget of 2,000 runs, and of up to five runs per draw of the explain
phase. The property's own call record states its verdict. The call
records of its cases state the verdict of each call in each case.

## The test of a call record

A call record belongs to the test whose seat received the call. A call
in a body belongs to the test of the call that ran the body. Only a
test's seat writes call records into the artifact.

A test that creates a recorder seat reads the outcome of the calls it
makes on that seat. The recorder keeps the call records of the calls it
receives, and its member `records` returns them, one encoded call record
each. They do not enter the artifact, because the test treats such a
call as its subject. The test's own verdict on the outcome is a call of
its own.

## Omitted facts

- The values of a passing call, for the reasons that the detail states.
- The values that a case decoded. A property's call record states the
  counterexample of the minimal case.
- A failure of a test outside every call, such as a panic. The test's
  status states it.
- The time of a call. The runner states the time of each test.

## The artifact

The artifact of a recorded run states, for every test that ran:

- The test, as the runner identifies it.
- Whether the test passed, failed or was skipped.
- The call record of every call that the test's seat received.

Each language writes its call records into the artifact that its test
runner writes for a run, beside the status of each test. The `records`
entry of its overlay states the artifact, as `overlays.md` states. A
language whose runner does not accept data of a test's own writes its
call records to a file of its own, one call record per line, each with
its `test`, and the entry states the file.

## Encoding

- A call record is one JSON object in UTF-8, written on one line.
- Its keys are the fields of the call record. A field that is not
  present is absent, never null.
- `detail` is a JSON object keyed by the assertion's detail fields, as in
  the failure record.
- Every value in the detail of an assertion other than a property is a
  typed literal of `encoding.md`, or an opaque literal. A property's
  detail is the detail of its run, as the detail section states.

## Conformance

Each corpus runner runs every case through its recorder seat, which
keeps the case's one call record, and checks that record:

- `seq` 1, without a `parent`.
- The case's assertion, and the contract unchanged.
- The verdict that the case's `expect` states.
- `aborting` for the surface that the case ran on.
- The detail, as the runner checks a failure record. A passing case's
  call record states no detail.

`corpus/prop/recording.json` pins the call records of a property's runs.
Each vector states a behaviour body and the settings of a run. The body
calls `true` once at its end, and the call fails when the predicate of a
`fails` entry is true. The outputs are the property's verdict and, in order,
the `run`, the `phase` and the `verdict` of each call of `true`. The
property's call is `seq` 1, and the call at position k of the outputs,
from 1, is `seq` k + 1 with `parent` 1.

`eventually` and `rejects` take bodies that no case can state. Each
implementation tests the call records of their bodies itself.
