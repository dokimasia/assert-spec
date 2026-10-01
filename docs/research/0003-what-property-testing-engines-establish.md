---
research: 0003
title: Which property-testing engine capabilities have evidence behind them, and does any engine give the same inputs in more than one language?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-10-01
updated: 2026-10-01
freshest-source: 2026-09-29
supersedes: none
superseded-by: none
---

# Research-0003: Which property-testing engine capabilities have evidence behind them, and does any engine give the same inputs in more than one language?

## The question

A property check in this standard would be designed from the
capabilities of the established property-testing engines. Two things
decide which capabilities it adopts, and whether the standard should
define an engine at all.

For each capability an engine might have, such as typed choices, a
simplest-first phase, shrinking that keeps separate failures, a stop on
an exhausted domain, coverage requirements, targeted search, swarm
configurations, model-based testing and a fuzzer bridge, the first
question is whether an established engine offers it, and whether anyone
has measured what it buys.

A property check whose generators and shrinker are part of a
cross-language definition would let one seed produce the same inputs in
six languages. The second question is whether an engine already does
that. If one does, the standard should adopt it rather than define its
own.

### What would count as an answer

- For a capability: the engine's own documentation or source stating the
  behaviour, at a named version. Where it exists, a peer-reviewed or
  preprinted measurement of the effect.
- For cross-language reproduction: an engine whose documentation states
  that one seed or one stored case produces the same values in more than
  one language.

### What sources are admissible

An engine's own documentation, source, changelog or registry metadata. A
paper, peer-reviewed or preprinted. A maintainer's own announcement. A
blog post describing an engine from outside is not the engine.

### What would change the answer

- An engine that already reproduces inputs across languages. The standard
  would adopt its definition rather than write one.
- A measurement showing that integrated or type-directed shrinking finds
  smaller counterexamples than reduction of a recorded choice sequence.
  The shrinker in the proposal would change.
- A report that coverage requirements make runs flaky in practice. They
  would move out of the first version.

## The answer

No engine documents that one seed gives the same inputs in more than one
language. The closest is Hegel, released in 2026 by Hypothesis's
maintainers: one Rust engine runs under libraries for Rust, Go, C++,
TypeScript, Java and OCaml. Each of those libraries composes its own
generators from the engine's draws, and Hegel states no agreement between
the values two of them produce. It is in beta and publishes native
builds for five platforms. It has no Python or PHP library.

At least one established engine offers each capability the proposal
adopts, at a named version. Measured effects exist for three
of them: targeted search, swarm configurations and coverage-guided
mutation of choices. None was found for a simplest-first phase, an
edge-case phase, failure identity, duplicate avoidance or a statistical
coverage test. Reduction of the choice sequence is established as a way
to shrink without code per type, and a 2026 comparison found it neither
consistently better nor consistently worse at finding the smallest
counterexample.

## Findings

### No engine documents the same inputs across languages

Hegel splits a property-based testing library in two. libhegel, written
in Rust, "implements the core of property-based testing, including data
generation, shrinking, the example database, and so on". A library per
language "implements the user-facing syntax of properties and generators
for a particular language" and asks libhegel for each value while the
test runs (Hegel, "How Hegel works", website commit of 2026-09-29).
libhegel's C header exports one draw per primitive kind: booleans,
integers, floats, bytes, strings, dates, times and UUIDs, together with
collections, recursion, pools and state machines.

The libraries are published for Rust, Go, C++, TypeScript, Java and OCaml
under the MIT licence, and all six were updated on 2026-09-28 or
2026-09-29 (GitHub organisation `hegeldev`). libhegel is released
prebuilt for Linux on amd64 and arm64, macOS on arm64, and Windows on
amd64 and arm64, plus a WebAssembly module (hegel-c README at `ebfd9d5`).
Hegel for Go embeds the library in the test binary with `go:embed` and
loads it at run time (hegel-go README at `7986fbb`). Hegel for TypeScript
loads it through the Koffi FFI library under Node, Bun and Deno, and as
WebAssembly in a browser (hegel-typescript README at `f9f7950`). The
compatibility page states that Hegel is in beta and that a minor release
`0.N.0` may break compatibility. It does not state whether a seed, a
reproduction blob or a database entry is still valid after an upgrade,
or about values across libraries.

We added Hegel for Go 0.9.11 to a scratch module with one property. The
module's `go.mod` gained three requirements: hegel, `golang.org/x/sys`,
and `github.com/ebitengine/purego` at the unreleased pseudo-version
`v0.11.0-alpha.6.0.20260707033313-5f49e7c49322`. hegel-go's own `go.mod`
lists 24 requirements, and the consumer inherited 2 of them. The module
download was 17 MB, with libhegel for five platforms at 2.7 to 3.6 MB
each, and the test binary was 9.6 MB. The test passed, after Hegel wrote
the Linux library to `~/.cache/hegel-go`.

The first public release was announced on 2026-03-24, for Rust only, as
"more or less a 'developer preview'" that ran Hypothesis itself and
needed Python installed (Antithesis blog, David MacIver). That design is
deprecated: the `hegel-core` README states that it "is an old
implementation that is no longer used" and points to the FFI engine.

Hypothesis tried one engine with bindings once before. conjecture-rust,
a Rust core under hypothesis-ruby, last changed on 2021-08-18, and both
were removed from the Hypothesis repository on 2026-01-06 (commit
`a78f28de90`).

**What we concluded:** sharing an engine removes the differences that
come from the engine, and leaves the differences that come from how each
library builds a generator. Two Hegel libraries produce the same values
from one seed only if both compose that generator from the same draws in
the same order, and nothing in Hegel states or tests that. The standard's
requirement, the same inputs checked by a corpus, is not part of any
engine's contract.

### The libraries disagree on their defaults for inputs, shrinking and storage

| | Hypothesis 6.168.3 | fast-check 4.10.2 | proptest 1.11.0 | jqwik 1.10.1 | Kotest 6.2.5 | QuickCheck 2.19 | rapid 1.3.0 |
|---|---|---|---|---|---|---|---|
| Inputs per run | 100 | 100 | 256 | 1,000 | 1,000 | 100 | 100 |
| First inputs | Stored failures, then the simplest input | Examples, then values biased to small and extreme, more often early | Persisted seeds, then random | Edge cases mixed in; exhaustive when the domain has at most 1,000 values | 2% of samples replaced by edge cases | Random, with a size that grows from 0 with each passing test | Fail files, then random |
| Shrinking | Reduces the choice sequence | Shrinks a value through its generator's context | Value trees of each strategy | Shrinkables from each generator | A tree of shrinks per sample | A `shrink` function per type | Reduces the recorded data |
| Reproduction | A blob tied to the release | Seed and shrink path | Seed | Seed, try index and shrink steps | Seed | Seed and size | Fail file, or seed |
| Storage | `.hypothesis/examples` | None | `proptest-regressions`, meant to be committed | `.jqwik-database`, rewritten each run | A seed file per test, deleted on success | None | `testdata/rapid` |
| Licence | MPL-2.0 | MIT | MIT or Apache-2.0 | EPL-2.0 | Apache-2.0 | BSD-3-Clause | MPL-2.0 |

Each cell is from the library's own source at the version in the column
heading: Hypothesis's
`_settings.py` and `engine.py`, fast-check's `QualifiedParameters.ts`,
proptest's `config.rs` and `file.rs`, jqwik's `JqwikProperties.java` and
`CheckedProperty.java`, Kotest's `config.kt`, QuickCheck's `Test.hs` and
`Arbitrary.hs`, and rapid's `engine.go` and `persist.go`. Each licence
is from the library's licence file or package manifest.

Hypothesis activates a built-in `ci` profile when the `CI` environment
variable is set. That profile turns the database off, sets
`derandomize`, and derives the seed from a SHA-384 digest of the test
function's source (`core.py`, `reflection.py`).

**What we concluded:** a property ported between any two of these
libraries tests different inputs by default, shrinks by a different
rule, and keeps its failures in a different format, or nowhere.

### Typed choices replaced the byte stream in the strongest engine, and broke its stored data

Hypothesis moved its shrinker to "our new internal representation,
called the IR layer" in 6.103.0 on 2024-05-29, reporting that on its own
test suite "shrinking is a median of 1.38x faster". The example database
moved in 6.124.0 on 2025-01-16: "This new format is not compatible with
the previous format, so stored entries will not carry over." The
changelog adds that the database "is best thought of as a cache that may
be invalidated at times". `@reproduce_failure` "will error if used on a
different Hypothesis version than it was created for".

In 6.168.3 a choice is one of five types: integer, string, boolean,
float and bytes (`choice.py`). A test case may use `BUFFER_SIZE`, 8 × 1024
units, whose "unit ... does not have any defined semantics". The shrinker
stops after 500 successful shrinks or 300 seconds (`engine.py`).
Hypothesis's first release was 0.0.1 on 2013-03-10.

**What we concluded:** typed choices are the established design, and
Hypothesis has no stable format for what it stores or replays. A
definition that five implementations follow needs one, versioned.

### Reducing the choice sequence shrinks without code per type, and is not measured to shrink smaller

MacIver and Donaldson describe internal test-case reduction, which
reduces "the sequence of random choices made during generation", so that
"any reduced test case is one that could in principle have been
generated". Their evaluation compares it with C-Reduce and delta
debugging (ECOOP 2020).

Keles, Miao and Lampropoulos compared QuickCheck, Hedgehog and Falsify
on four ETNA workloads, measuring the tree edit distance to a minimum
found by exhaustive search. "QuickCheck's structural shrinking is usually
faster and remains competitive on final counterexample quality;
integrated shrinking does not by itself guarantee a performance or
effectiveness advantage." On correct-by-construction generators for
binary search trees and red-black trees, QuickCheck came closer to the
minimum. On the lambda-calculus workload, Falsify did. "These results do
not support a blanket claim that either structural or integrated
shrinking is always more effective" (arXiv 2608.09935, 2026).

The shrinking challenge collects 11 problems for comparing shrinkers and
reports from ten libraries, Hypothesis, jqwik, fast-check and rapid among
them. Some of its problems come from the artefact of the ECOOP 2020
paper.

**What we concluded:** the reason to reduce choices is that it needs no
shrinker per type in each language and works through `map`, `filter` and
`bind`. It is not a claim of smaller counterexamples, and the proposal
should measure its own shrinker on the shrinking challenge.

### Two engines stop on an exhausted domain, and one avoids repeats

Hypothesis records every test case in a tree whose node "is exhausted if
every possible sequence of draws below it has been explored", and its
generator produces "a short random string that (after rewriting) is not a
prefix of any choice sequence previously added to the tree"
(`datatree.py`). When the tree is exhausted and nothing failed, the run
ends with the reason "nothing left to do" (`engine.py`).

jqwik's default generation mode switches to exhaustive generation when
every parameter supports it and the number of combinations is at most
`tries`, 1,000 by default (`CheckedProperty.java`). Kotest iterates the
full product when every generator of a property is `Exhaustive`, and
ignores the iteration count.

**What we concluded:** duplicate avoidance and an early stop are
established. Hypothesis steers generation with its tree, which makes each
test case depend on the ones before it. The proposal keeps the tree and
does not steer, so that a run on more than one worker equals a run on
one.

### Only QuickCheck decides coverage statistically

QuickCheck's `checkCoverage` "uses a statistical test to account for the
role of luck in coverage failures. It will run as many tests as needed
until it is sure about whether the coverage requirements are met"
(`Property.hs`). The defaults are a certainty of 10^9 and a tolerance of
0.9. A requirement is sufficiently covered when the lower end of the
Wilson score interval is at least the tolerance times the required share,
and insufficiently covered when the upper end is below the share. It
checks at `maxSuccess` tests and again at 100 × 2^k tests (`Test.hs`).
The certainty is documented as "a false positive at most one in n runs of
QuickCheck" (`State.hs`).

jqwik applies a caller's predicate to the observed count or percentage,
and applies no statistical test of its own. Kotest's coverage functions
compare the observed share with a threshold, and are marked
experimental. fast-check's `statistics` logs shares and never fails.

We computed what the proposal's rule does. It applies QuickCheck's test
at 100, 200, 400 and 800 cases and lets the observed share decide at 800.
For a 10% requirement, the probability that a run fails is:

| Real share of the label | Probability the run fails |
|---|---|
| 8% | 0.865 |
| 9% | 0.531 |
| 10% | 0.189 |
| 12% | 0.0041, about one run in 240 |
| 15% | 2.8 × 10^-7 |
| 20% | 1.4 × 10^-17 |

The method was an exact computation over the binomial distribution of
the counted cases between checks, in Python 3.14 with
`Z = 6.109410191663286`, the standard normal quantile at 1 − 5 × 10^-10
from `statistics.NormalDist`. The Wilson bound used was the one in the
proposal, and it agreed with QuickCheck's formula to within 10^-15 on
every count tried.

**What we concluded:** with a cap on the run, a requirement near the
label's real share fails on some seeds, as a threshold does. The
statistical test decides early only when the share is far from the
requirement: a 10% requirement is met at the first check only with 27 or
more of 100 cases.

### Failure identity and separate failures are established

Hypothesis keys each failure by its `interesting_origin` and reports
every distinct one by default, `report_multiple_bugs=True`. It shrinks
the failures one at a time, the one with the smallest case first, under
one deadline of 300 seconds and one count of 500 successful shrinks for
all of them (`engine.py`, `shrink_interesting_test_cases`). jqwik's
shrinker treats a candidate whose error is not equivalent to the
original error as invalid (`PropertyShrinker.java`, through the
fast-check, jqwik and Kotest notes).

### Derived generators fail on a refusing constructor, register globally, and bound recursion by leaves

In Hypothesis 6.168.3, `builds` calls the target and lets its exception
propagate, after replacing some `TypeError` cases with clearer errors, so
a constructor that refuses a generated value fails the test (`core.py`).
`register_type_strategy` adds "an entry to the global type-to-strategy
lookup". `recursive` takes `max_leaves=100`, "the maximum number of
elements to be drawn from base on a given run". Each strategy can be
inverted from a value to choices through an internal `_invert`, which
raises `CannotInvert` for a value or strategy it cannot invert.

### Simplest-first and edge-case phases have no published measurement

Hypothesis runs a case of the simplest choices before generating
(`engine.py`). jqwik offers three edge-case modes, mixed in by default.
Kotest replaces 2% of samples with edge cases. fast-check biases one
value in `2 + floor(log10(runId + 1))` towards small and extreme values.
No measurement of any of them was found.

### Targeted search, swarm and coverage-guided mutation have measured effects

- Targeted property-based testing steers generation with a search
  strategy towards inputs that score higher. In a sensor-network case
  study, random generation needed on average 1,188 tests and 7 h 46 min
  to find a counterexample, and Target needed about 200 tests and
  2 h 12 min, "about 3.5 times faster". In a noninterference case study,
  the geometric mean time to failure fell from 102.44 ms to 11.25 ms with
  the same generation strategy under Target (Löscher and Sagonas, ISSTA
  2017). Hypothesis 6.168.3 runs its target phase "mixed in with the
  generate phase" in ordinary runs.
- Swarm testing omits features at random per test. "During one week of
  testing, the swarm machine found 104 distinct ways to crash compilers
  in the test suite whereas the other machine ... found only 73." In the
  paper's stack example, a capacity bug needs more than 32 items, and a
  swarm generator that first picks a non-empty subset of push and pop
  makes one test in three pushes only. The paper's configurations omit
  each feature by a coin toss, "50% probability per feature of omission"
  (Groce et al., ISSTA 2012).
- Zest mutates the parameters behind a generator, guided by coverage and
  validity. On Maven, Ant, BCEL, Closure and Rhino it "covers 1.03×–2.81×
  as many branches within the benchmarks' semantic analysis stages as
  baseline techniques", and found 10 new bugs, "requiring at most 10
  minutes on average to find each bug" (Padhye et al., ISSTA 2019).

### Model-based testing differs in where preconditions go

fast-check generates commands without the model, runs a command only
when its `check` returns true, and its shrinker filters out the commands
that never ran. jqwik draws each step from the actions whose precondition
is true. proptest's state machines generate the whole sequence from a
reference model before the subject runs, and their documentation warns
that hard preconditions "might slow down the test or even fail by
exceeding the maximum rejection count". Hypothesis's default is 50 steps
per stateful test. fast-check's scheduler picks the next task at random
and does not shrink.

### Practitioners prefer derived generators and want visibility

Goldstein et al. interviewed 31 developers in 30 interviews at one
company. Differential properties appeared in 17 interviews, round-trip
properties in 11, and properties that provoke crashes in 7. Handwritten
generators appeared in 19 and derived generators in 19, and participants
called writing generators "tedious" (6) or "high-effort" (7). The authors'
observation OB5 is that "developers see writing generators as a
distraction, preferring to use derived generators". Eleven participants
said they did not think as hard as they should about whether their
generators tested enough (ICSE 2024).

### A random source that every language computes exactly exists

Bob Jenkins's small noncryptographic generator has a 64-bit three-rotate
variant with the rotations 7, 13 and 37, initialised with `0xf1ea5eed` and
20 discarded rounds. It uses only addition, subtraction, exclusive or and
rotation, and its author writes "I place it in the public domain".

ECMAScript defines `Math.sqrt` to return the exactly rounded square root,
and `Math.exp` to return "an implementation-approximated Number value".

**What we concluded:** a definition can fix generation exactly in every
language if every draw uses integer arithmetic, and the coverage test may
use a square root but no other transcendental function.

## What we could not establish

- **Whether two Hegel libraries produce the same values from one seed in
  practice.** Settling it means running the same generator in two of
  Hegel's libraries with a fixed seed and comparing the values. This
  research read Hegel's documentation and code and ran nothing.
- **What exact 64-bit generation costs in JavaScript and PHP.** Settling
  it needs a benchmark of the random source in each.
- **Whether a simplest-first or edge-case phase finds bugs sooner.** No
  measurement was found. The proposal's acceptance measurements on ETNA
  would provide one.
- **Rust's fuzzing bridges.** `arbitrary`, `cargo fuzz` and Bolero were
  cloned and not studied. A research agent assigned to them was stopped
  before it wrote anything down.

## What would change this answer

- Hegel stating and testing that its libraries produce the same values
  from the same seed, with a stable release whose seeds and blobs survive
  upgrades. One engine with bindings would then be the better design.
- A Hegel library for Python or PHP.
- A measurement showing that reduction of the choice sequence loses to
  per-type shrinking by a wide margin across workloads.
- A report that statistically decided coverage requirements make runs
  flaky in practice.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | Hegel, "How Hegel works", <https://hegel.dev/explanation/how-hegel-works>, website commit `3f30c2a` of 2026-09-29 | Maintainers' documentation | 2026-10-01 | libhegel does generation, shrinking and the database; libraries build generators |
| 2 | Hegel, "Compatibility", <https://hegel.dev/compatibility> | Maintainers' documentation | 2026-10-01 | Beta; breaking minor releases; prebuilt platforms; nothing on reproduction across versions or libraries |
| 3 | Hegel, "Why Hegel?" and "Getting started", website sources at `3f30c2a` | Maintainers' documentation | 2026-10-01 | One core, thin libraries; the protocol; the six libraries |
| 4 | D. MacIver, "Hypothesis, Antithesis, synthesis", <https://antithesis.com/blog/2026/hegel/>, 2026-03-24 | Maintainer's announcement | 2026-10-01 | First release, Rust only, developer preview, Python needed |
| 5 | GitHub organisation `hegeldev`, repository list through the GitHub API | Registry metadata | 2026-10-01 | Libraries, MIT licences, activity on 2026-09-28 and 2026-09-29; `hegel-core` deprecated |
| 6 | hegel-rust at `ebfd9d5`, `hegel-c/README.md` and `hegel-c/include/hegel.h` | Source code | 2026-10-01 | Prebuilt platforms and Wasm; the C interface's draws |
| 7 | hegel-go at `7986fbb` and hegel-typescript at `f9f7950`, READMEs | Source code | 2026-10-01 | `go:embed` loading; Koffi and Wasm loading |
| 8 | Hypothesis v6.168.3: `_settings.py`, `core.py`, `reflection.py`, `internal/conjecture/engine.py`, `datatree.py`, `choice.py`, `docs/changelog.rst` | Source code and changelog | 2026-10-01 | Defaults, the `ci` profile, simplest-first, the tree, limits, choice types, IR and database history, version-locked blobs |
| 9 | Hypothesis commit `a78f28de90`, and the history of `conjecture-rust` through the GitHub API | Source history | 2026-10-01 | Removal on 2026-01-06; last change on 2021-08-18 |
| 10 | fast-check 4.10.2, jqwik 1.10.1 and Kotest 6.2.5 at their release tags, read into notes with a citation per claim | Source code | 2026-10-01 | Defaults, bias, edge cases, storage, coverage checks, model-based testing |
| 11 | proptest v1.11.0: `test_runner/config.rs`, `failure_persistence/file.rs`, `proptest-state-machine/src/strategy.rs` | Source code | 2026-10-01 | 256 cases, the regressions file, sequence-first state machines |
| 12 | rapid v1.3.0: `engine.go`, `persist.go`, `LICENSE`, and a line count of its files | Source code | 2026-10-01 | 100 checks, 30 steps, 30 s, fail files, MPL-2.0, 4,866 lines in 17 files with 4,769 test lines |
| 13 | QuickCheck 2.19: `Test.hs`, `Property.hs`, `State.hs`, `Arbitrary.hs` | Source code | 2026-10-01 | 100 tests, `checkCoverage`, the Wilson test, its constants, per-type `shrink` |
| 14 | B. Jenkins, "A small noncryptographic PRNG", <https://burtleburtle.net/bob/rand/smallprng.html> | Author's page | 2026-10-01 | The 64-bit three-rotate variant, its constants, public domain |
| 15 | ECMA-262, the current draft, `Math.sqrt` and `Math.exp`, <https://tc39.es/ecma262/> | Standard | 2026-10-01 | An exactly rounded square root; an approximated exponential |
| 16 | MacIver and Donaldson, "Test-Case Reduction via Test-Case Generation", ECOOP 2020, <https://doi.org/10.4230/LIPIcs.ECOOP.2020.13> | Peer-reviewed paper, abstract | 2026-10-01 | Internal reduction and its evaluation |
| 17 | Keles, Miao and Lampropoulos, "Evaluating Shrinking", <https://arxiv.org/abs/2608.09935> | Preprint | 2026-10-01 | No blanket advantage for either shrinking approach |
| 18 | Shi et al., "Etna", ICFP 2023, <https://doi.org/10.1145/3607860>, and Keles et al., <https://arxiv.org/abs/2603.27002> | Peer-reviewed paper and preprint, abstracts | 2026-10-01 | A platform of workloads with injected bugs, in five languages |
| 19 | The shrinking challenge, <https://github.com/jlink/shrinking-challenge>, README | Repository | 2026-10-01 | 11 problems, reports from ten libraries |
| 20 | Groce, Zhang, Eide, Chen and Regehr, "Swarm Testing", ISSTA 2012, <https://agroce.github.io/issta12.pdf> | Peer-reviewed paper | 2026-10-01 | 104 against 73 crashes; the stack example |
| 21 | Löscher and Sagonas, "Targeted Property-Based Testing", ISSTA 2017, <http://proper.softlab.ntua.gr/papers/issta2017.pdf> | Peer-reviewed paper | 2026-10-01 | 3.5 times faster in one case study; 102.44 ms against 11.25 ms in another |
| 22 | Padhye et al., "Semantic Fuzzing with Zest", ISSTA 2019, <https://arxiv.org/abs/1812.00078> | Peer-reviewed paper | 2026-10-01 | 1.03× to 2.81× branches; 10 new bugs |
| 23 | Goldstein, Cutler, Dickstein, Pierce and Head, "Property-Based Testing in Practice", ICSE 2024, <https://harrisongoldste.in/papers/icse24-pbt-in-practice.pdf> | Peer-reviewed paper | 2026-10-01 | Kinds of property and generator, and their counts |
| 24 | Our computation of coverage verdict probabilities, described above | Own measurement | 2026-10-01 | The failure probabilities in the coverage table |
| 25 | Our scratch module with Hegel for Go 0.9.11: `go get`, `go mod tidy`, `go test -c` and one run, in a capped scope | Own measurement | 2026-10-01 | Three requirements, the purego pseudo-version, 17 MB downloaded, a 9.6 MB test binary |

## What we searched

| Search | Tool | Date | Useful |
|---|---|---|---|
| `property-based testing engine for multiple languages same seed reproducible across languages Hypothesis protocol` | Web search | 2026-10-01 | No; no engine with cross-language reproduction |
| `Hegel property-based testing Hypothesis Antithesis cross-language` | Web search | 2026-10-01 | Yes; Hegel's site, announcement and organisation |
| `"property-based testing" AND ("cross-language" OR polyglot OR "language-agnostic" OR "multiple languages")` | arXiv | 2026-10-01 | No; one unrelated result |
| `"property-based testing" AND (shrinking OR "test-case reduction" OR generator OR "choice sequence")`, from 2025-01-01, by date | arXiv | 2026-10-01 | Yes; 36 results, 3 abstracts read, 1 paper read |
| `Löscher Sagonas "Targeted property-based testing" ISSTA 2017 evaluation` | Web search | 2026-10-01 | Yes; the paper |
| `Goldstein Cutler Dickstein Pierce Head "Property-Based Testing in Practice" ICSE 2024 pdf` | Web search | 2026-10-01 | Yes; the paper |
| `Etna evaluation platform property-based testing ICFP 2023 Shi Keles Goldstein Pierce Lampropoulos` | Web search | 2026-10-01 | Yes; ETNA and the shrinking evaluation |
| Hegel's website sources, for `across languages`, `every language`, `same seed`, `same values`, `between languages` and `protocol` | Text scan of 211 files | 2026-10-01 | No statement about values across libraries |
| Hypothesis, fast-check, jqwik, Kotest, proptest and rapid at their tags; QuickCheck 2.19 files; Hegel's Rust, Go, TypeScript and website repositories | Source reads | 2026-10-01 | Yes; every library fact above |

Four research agents searched on 2026-10-01 for Hypothesis's internals,
fast-check and the JVM libraries, Rust's libraries and fuzzing bridges,
and the literature. All four were stopped before they finished. Only the
fast-check, jqwik and Kotest results were written down, and they are
source 10. The others are not listed here.
