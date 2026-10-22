<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# assert-spec

One set of test assertions, defined as data, so the same test means the
same thing in every language that implements it.

This repository holds the definition. It ships no library. Each
implementation reads these files and runs this corpus in its own CI, so
a library that omits an assertion, names one wrongly, or disagrees about
what an assertion means fails its own build.

## The problem

Write the same test twice, once in Go and once in Python, and the two
should pass or fail together. Today they do not.

Go's `cmp` package, configured the way most test helpers configure it,
says a nil slice equals an empty slice. Python says `None` does not
equal `[]`. Port a suite from one to the other and both builds go green
while testing two different things. The difference surfaces months later
as a bug that reproduces in one service and not its rewrite.

Six libraries written from a prose specification drift the same way, and
the drift stays invisible because each library's own tests pass. Each
team tests what it believes the specification says. Nothing tests
whether the beliefs agree. Only a shared artifact, read by all of them,
can catch that, and it has to be data because prose does not fail a
build.

## What is here

```
spec/assertions.yaml   what each assertion means          edited by people
spec/naming.yaml       what each language calls it        edited by people
spec/assertions.json   the same, rendered                 read by libraries
spec/naming.json       the same, rendered                 read by libraries
spec/conformance.md    what converges and what does not
spec/manifest.json     a digest of everything an implementation vendors
spec/zones.json        the zone list and its offset changes, from tzdata
spec/encoding.md       how a corpus case states a value
spec/failure.md        the record that a failing assertion reports
spec/overlays.md       how a language declares it cannot comply
spec/recording.md      what a recorded run writes for each call
corpus/*.json          the cases, one file per assertion they cover
corpus/prop/*.yaml     the property engine's vector inputs  edited by people
corpus/prop/*.json     the vectors with their outputs       read by libraries
corpus/history/*.yaml  the history's vector inputs          edited by people
corpus/history/*.json  the vectors with their outputs       read by libraries
corpus/stateful/*.yaml the machines' vector inputs          edited by people
corpus/stateful/*.json the vectors with their outputs       read by libraries
corpus/files/*.yaml    the file assertions' vector inputs   edited by people
corpus/files/*.json    the vectors with their outputs       read by libraries
overlays/*.json        one per language, declaring divergences
tools/render.py        YAML to JSON, and the vectors' outputs
tools/validate.py      the rules, checked
tools/prop/            the property engine's executable reference
tools/history/         the history's and the checkers' executable reference
tools/stateful/        the machines' and the scheduler's executable reference
tools/files/           the trees' and the file assertions' executable reference
.spec.yaml             the files an implementation vendors with spec
VERSION                9.0.0
```

People edit the YAML. `make render` produces the JSON, which is
committed and is what implementations read: every target language parses
JSON from its standard library, and several would otherwise take a
dependency just to read the definition. CI re-renders and fails if the
result differs from what is committed.

## Assertions have ids, names come from a table

An assertion has a canonical id that no user types. Each language maps
that id to a name its users recognise.

```yaml
# spec/assertions.yaml — what it means
"throws":
  arity: 3
  summary: >
    A callable raises. Yields what was raised.
  detail_fields: []
```

```yaml
# spec/naming.yaml — what a user types
"throws":
  go: "Panics"
  python: "raises"
```

A single shared vocabulary would read as a translation in most of the
six languages. Splitting the id from the name lets a Python developer
write `raises` and a Go developer write `Panics` while both answer to
one definition.

## The set

71 assertions: 50 in the root namespace, 4 for golden files and golden
trees, 9 for trees of files and single paths, 4 for benchmark ceilings,
1 property check and 3 checks of a recorded history. They cover equality,
truth, nullity, length, containment, text, numbers, ordering, errors,
raising, cancellation and deadlines, retrying, goroutine and task leaks,
allocations, relations between runs of a subject, recorded output, files
and directories, performance ceilings, properties over generated inputs,
the linearizability of concurrent calls, and the isolation of
transactions.

39 of them also have a property form, which runs the assertion on every
input that a property generates. Rendering adds the forms to the `prop`
package by one rule, so the assertion table states 110 entries.

An assertion earns its place by answering two questions. Does it state
something that must be true, and fail when it is not? Does it mean the
same thing in every target language? Anything that fails the second is a
helper, and helpers live in the libraries.

## Three mechanisms, because one is not enough

Conformance is checked three ways, and they catch different things.

**The corpus** checks meaning. Each case states arguments as typed
literals and says whether the assertion passes or fails, and sometimes
what the failure must mention:

```json
{
  "id": "equal/null-against-empty-list",
  "args": [
    { "type": "list", "of": "int", "value": [] },
    { "type": "null" }
  ],
  "expect": "fail",
  "detail": {
    "want": { "type": "null" },
    "got": { "type": "list", "of": "int", "value": [] }
  }
}
```

Typed literals cross a language boundary only as data, so the corpus
covers 39 of the 71 assertions. Eighteen of those state their
arguments. The other 21 name a behaviour instead, because what they
take is a callable and no encoding states one. The ten assertions that
read files take a directory or a path, which a case states as a tree
that the runner writes before the call, so their cases are vectors. The
remaining 22 take an error value, a predicate, a callable that no subject
describes, a golden file, a benchmark measurement, a property's body, a
spec or a recorded history, and none of those is a typed literal
either. The property engine
itself is data in and data out, so 430 vectors under `corpus/prop/` pin
its decoding, generation, shrinking, coverage test, fuzz bridge, replay
token, run detail and store. They also pin the values each shape
generates, the choices that produce a value, the shape each fixture type
reads as, a passing and a failing run of every property form but
`prop-max-allocs`, the runs of a form's examples, and the call records of
a property's runs. The history
and the checkers are data in and data out too. 80 vectors under
`corpus/history/` pin the events that calls record, the entries that the
history refuses, the verdict, steps and record of a check against each
named spec, and the verdict and record of each isolation check. So are
the steps of a machine. 14 vectors under `corpus/stateful/` pin the run of
each machine subject, the minimal steps of each fault, the traces that a
run follows or refuses, and the step at which a replay of a subject whose
refusals change its actions diverges. 57 vectors under `corpus/files/`
pin the verdict and the record of the ten assertions that read files:
the comparison of two trees, its bound of 64 paths and its digest of a
large file, a golden tree and its update, and the kind, the target, the
content and the mode at one path.

**The completeness gate** checks membership. Every assertion must be
present under the name the naming table gives it, with the arity the
definition states as far as the language can read it. The gate covers
the 22 assertions that the corpus cannot state, and `prop-max-allocs` and
`prop-max-allocs-with-setup`, whose allocation counts no vector can
state. The standard checks a
library's meaning where meaning can be stated, and its membership
everywhere else.

**An overlay** is where a language declares it cannot comply, with the
reason. A divergence nobody wrote down is a bug; one written down is a
decision someone can argue with.

Which of these a given difference belongs to, and which differences need
no recording at all, is stated in `spec/conformance.md`.

## Recording every call

A run with `DOKIMI_ASSERT_RECORD=1` writes a call record for every
assertion call, pass or fail, into the artifact that the language's test
runner already writes for a run. In Go, that artifact is the event
stream of `go test -json`. A call record states the assertion, the
contract, the verdict and the detail of a failure. The calls in a
property's cases appear under the property's own call, with the phase
of each case. `spec/recording.md` fixes the record, and each overlay
names its language's artifact.

## Keeping the implementations in step

Each implementation vendors a copy of the definition with
[spec](https://github.com/stealth-scale/spec), so its build runs without
the network. `.spec.yaml` lists the files that an implementation vendors
and the overlay of each language.

- `spec manifest` writes `spec/manifest.json`. The manifest states the
  version, the digest of each vendored file, the files of each language
  and the digest of the whole set. `make render` runs it after the JSON,
  and CI fails when the committed manifest differs.
- `spec sync` writes the files of an implementation's languages into its
  copy. The `manifest.json` of the copy records the commit of this
  repository that the copy comes from.
- `spec check` fails when a copy differs from its manifest. `spec check
  --remote` also fails when the commit of the copy is not on `main`.
- Each implementation runs the workflow `propose.yml` of spec on
  weekdays. The workflow opens a pull request with the new copy when
  `main` has moved, and closes it when the copy matches again.

To try a change here before you push it, run `spec try`. It writes the
working tree into the checkout of each implementation beside this
repository, such as `../assert-go`, and runs the tests of that
implementation. `spec try --restore` restores the copies.

## Checking this repository

`make check` runs the gate that CI runs. It lints the tools and runs
their tests. It renders the definition and fails when the committed JSON
or manifest differs, and it checks the definition against its rules. The
Python targets run through [uv](https://docs.astral.sh/uv/), which
fetches its own Python. `make render` and `make manifest` also need
spec, which `go install go.stealthscale.io/spec/cmd/spec@latest`
installs.

```sh
make check      # the full pre-merge gate
make render     # rebuild the JSON from the YAML, and the manifest
make validate   # hold the definition and corpus to their rules
make forms      # check that GitHub renders the issue forms
make test       # run the tests of the tools
make fmt        # format the tools
```

`make validate` reads the rendered JSON, not the YAML, because that is
what implementations read. It checks that the version files agree, that
every assertion is described, that every language that names one
assertion names all of them, that a qualified name names a member of the
package its assertion declares, that every corpus case names a defined
assertion with a unique id, decodable literals and options its assertion
accepts, and that an overlay extends this version and diverges only from
assertions that exist. It also checks that each overlay states where its
language writes the call records and how it runs the concurrent section of
a machine, that each history vector names a defined spec, that the
vectors of each isolation level report every kind the level forbids, that
each machine subject runs in a vector named for it, that the workspace and
the golden tree of each files vector follow the rules of a tree, and that
each language whose threads run on more than one core limits the
history's recorder. It reports everything it finds in one run.

`make test` breaks each rule of the validator in a scratch copy and
requires the validator to report it. A validator only ever run on a
clean tree would pass just as readily with every rule deleted.

## Versioning

`VERSION` carries the version of the definition. An overlay names the
version it extends, so an overlay left behind by a change to the
standard fails validation rather than passing quietly.

Adding an assertion is a minor version. Changing what an existing
assertion means, or renaming one, is a major version, because it changes
whether an existing test still states what its author meant. Renaming a
member of the surface table is a major version for the same reason, and
so is a corpus case that pins an answer the implementations gave
differently.

## Implementations

| Language | Repository | Assertions |
|---|---|---|
| Go | [assert-go](https://github.com/dokimasia/assert-go) | 110 of 110 |
| Java | [assert-java](https://github.com/dokimasia/assert-java) | 105 of 110 |
| Kotlin | [assert-java](https://github.com/dokimasia/assert-java) | 105 of 110 |
| Python | [assert-python](https://github.com/dokimasia/assert-python) | 105 of 110 |
| Rust | [assert-rust](https://github.com/dokimasia/assert-rust) | 110 of 110 |
| TypeScript | [assert-typescript](https://github.com/dokimasia/assert-typescript) | 104 of 110 |

Each count is what the language's overlay declares against version
9.0.0. An implementation whose copy is behind has an open pull request
from spec with the new copy.

Java and Kotlin ship from one repository and are named identically, so
a test reads the same in both. Neither states a ceiling on allocation
count in a test, a property or a benchmark. The JVM reports bytes
allocated per thread and no count of allocations. Python states none of
the three, because CPython reports the memory alive at one moment and no
running count. For the same reason its ceiling on bytes bounds the peak
of an iteration and not the bytes it allocates, which its overlay
declares as a limit. TypeScript states none of the four
allocation ceilings, because V8 reports allocation only as a heap-usage
delta that moves with whether the collector ran. Each gap is in that
language's overlay with the measurement behind it.

Go and Rust state all 110 and declare nothing absent. Go checks no
allocation ceiling in a build with the race detector, msan or asan, in
one whose `-gcflags` turn off optimisation or inlining, or in a test
binary that a mutation run instrumented, because those builds allocate
differently from the one that ships. Go also reads an
`int` at the platform's width, which is 32 bits on a 32-bit platform. A
property over an `int` generates other values there. In Rust seven are
partial: the six
allocation ceilings need a counting allocator installed as the test
binary's global allocator, and no-task-leaks sees tasks on a runtime but
not a thread, because nothing in Rust's standard library enumerates
threads. Rust also declines the three relaxations. Its types keep an
absent container and an empty one apart, and its own equality already
treats NaN as unequal to itself. Its assertions compare through
`PartialEq`, which has no identity to compare by.

Go, Java, Kotlin and Rust declare a limit on the history's recorder
because their threads run on more than one core. The recorder's counter
synchronizes the clients that record into it. That synchronization can
supply a memory barrier that the subject lacks. TypeScript searches the
partitions of a history one at a time for any number of workers.

The TypeScript compiler erases every type, so the TypeScript library reads
no type into a shape. It skips the 34 fixture vectors. A property derives
its inputs from shape files alone. The library runs the concurrent section
of a machine only as tasks and declines `repeat`. Its overlay also limits
`prop.fuzz`, because vitest does not run a fuzzer.

PHP is declared as a target language and the naming table carries no
names for it yet, so adding it starts by filling that column.

The argument behind the design is in
[docs/rfc/0001-the-standardized-assertion-set.md](docs/rfc/0001-the-standardized-assertion-set.md).

## Licence

MIT. See [LICENSE](LICENSE).
