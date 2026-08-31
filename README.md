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
spec/encoding.md       how a corpus case states a value
spec/overlays.md       how a language declares it cannot comply
corpus/*.json          70 cases in 17 files
overlays/*.json        one per language, declaring divergences
tools/render.py        YAML to JSON
tools/validate.py      the rules, checked
VERSION                1.0.0
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

41 assertions: 34 in the root namespace, 3 for golden files, 4 for
benchmark ceilings. They cover equality, truth, nullity, length,
containment, text, numbers, ordering, errors, raising, cancellation and
deadlines, retrying, goroutine and task leaks, recorded output, and
performance ceilings.

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

Typed literals only cross a language boundary as data, so the corpus
reaches 25 of the 41 assertions. Seventeen of those state their
arguments; the other eight name a behaviour instead, because what they
take is a callable and no encoding carries one. The remaining 16 take a
golden file or a benchmark measurement, and neither is data either.

**The completeness gate** checks membership. Every assertion must be
present under the name the naming table gives it. That covers the 16 the
corpus cannot reach: a library is held to the standard on meaning where
meaning can be stated, and on membership everywhere else.

**An overlay** is where a language declares it cannot comply, with the
reason. A divergence nobody wrote down is a bug; one written down is a
decision someone can argue with.

Which of these a given difference belongs to, and which differences need
no recording at all, is stated in `spec/conformance.md`.

## Keeping the implementations in step

An implementation vendors a copy of the definition, so its build fails on
its own without reaching the network. What a copy cannot tell you is
whether it is current, and the version does not answer that: adding the
relaxations changed the definition without changing the version, and by
the rule below it should not have.

`spec/manifest.json` carries a digest of every file an implementation
vendors, so there is something to compare against that tracks the bytes
rather than the meaning. Each implementation runs `spec-check` in its own
CI. A copy that does not match the manifest beside it fails, always. A
copy that differs from this repository fails only when that change is
the one that touched it: falling behind is allowed and is tracked by an
issue, and committing a copy nobody else has is not.

`spec-sync` fetches a pinned ref rather than reading a sibling
directory, so it answers the same way on a laptop and on a runner. Set
`SPEC_LOCAL` to try a change before pushing it; it says loudly that the
copy it leaves behind is reproducible nowhere else.

The two scripts are themselves vendored from `tools/` here and carried
in the manifest, and `spec-sync` refreshes them along with the
definition. Five copies of a script drift exactly the way five copies
of the definition did, and running one from the network instead would
make an offline check depend on being online.

A change here opens an issue on each of the five, so a definition change
becomes five pieces of visible work rather than five silent
divergences.

## Checking this repository

Everything runs through [uv](https://docs.astral.sh/uv/), which fetches
its own Python. Clone and run the gate; there is nothing else to
install.

```sh
make install    # create the environment
make check      # the full pre-merge gate
make render     # rebuild the JSON from the YAML
make validate   # hold the definition and corpus to their rules
make test       # check the validator catches what it claims to
make fmt        # format the tools
```

`make lint-md` needs `markdownlint`, and falls back to `npx` when it is
not on the path. Every other target needs only uv.

`make validate` reads the rendered JSON, not the YAML, because that is
what implementations read. It checks that the version files agree, that
every assertion is described, that the naming table covers every
assertion in a declared language, that a qualified name sits in the
package its assertion declares, that every corpus case names a defined
assertion with a unique id and a decodable literal, and that an overlay
extends this version and diverges only from assertions that exist. It
reports everything it finds in one run.

`make test` runs 39 cases that each break one rule in a scratch copy and
require the validator to catch it. A validator only ever run on a clean
tree would pass just as readily with every rule deleted.

## Versioning

`VERSION` carries the version of the definition. An overlay names the
version it extends, so an overlay left behind by a change to the
standard fails validation rather than passing quietly.

Adding an assertion is a minor version. Changing what an existing
assertion means, or renaming one, is a major version, because it changes
whether an existing test still states what its author meant.

## Implementations

| Language | Repository | Assertions |
|---|---|---|
| Go | [assert-go](https://github.com/dokimasia/assert-go) | 41 of 41 |
| Java | [assert-java](https://github.com/dokimasia/assert-java) | 40 of 41 |
| Kotlin | [assert-java](https://github.com/dokimasia/assert-java) | 40 of 41 |
| Python | [assert-python](https://github.com/dokimasia/assert-python) | 41 of 41 |
| Rust | [assert-rust](https://github.com/dokimasia/assert-rust) | 41 of 41 |
| TypeScript | [assert-typescript](https://github.com/dokimasia/assert-typescript) | 39 of 41 |

Java and Kotlin ship from one repository and are named identically, so
a test reads the same in both. Neither states a ceiling on allocation
count, because the JVM reports bytes allocated per thread and no count
of allocations. TypeScript states neither allocation ceiling, because
V8 answers only as a heap-usage delta that moves with whether the
collector ran. Each gap is in that language's overlay with the
measurement behind it.

Rust states all forty-one and declares nothing absent, which no other
implementation manages. Three are partial: the two allocation ceilings
need a counting allocator installed as the test binary's global
allocator, and no-task-leaks sees tasks on a runtime but not a thread,
because nothing in Rust's standard library enumerates threads. It also
declines both relaxations, since its types keep an absent container and
an empty one apart and its own equality already says NaN is unequal to
itself.

PHP is declared as a target language and the naming table carries no
names for it yet, so adding it starts by filling that column.

The argument behind the design is in
[docs/rfc/0001-the-standardized-assertion-set.md](docs/rfc/0001-the-standardized-assertion-set.md).

## Licence

MIT. See [LICENSE](LICENSE).
