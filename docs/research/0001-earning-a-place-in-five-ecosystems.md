---
research: 0001
title: Which capabilities would make each implementation worth adopting in its own ecosystem?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-08-30
updated: 2026-08-30
freshest-source: 2026-08-30
supersedes: none
superseded-by: none
---

# Research-0001: Which capabilities would make each implementation worth adopting in its own ecosystem?

## The question

For each language this standard is implemented in, which of the
capabilities we ship does the library people already reach for cover, and
which are covered by nothing?

The question can come out wrong in two directions. If the established
libraries already do what we do, there is no reason to adopt this beyond
cross-language conformance. If nothing covers the behavioural
assertions, those are the identity and the value comparisons are a side
dish.

### What would count as an answer

For each ecosystem, the libraries with the largest measured adoption,
and whether their own documentation, source or published artifact covers
each capability. A capability absent everywhere is a gap worth building
on. A capability present in five of six is not a selling point in those
five.

### What sources are admissible

A library's own documentation, published artifact or source. A package
registry's own figures. A peer-reviewed or preprinted paper. A blog post
describing a library is not the library.

### What would change the answer

Finding an established library that already asserts cancellation,
purity or resource cleanup. That would remove the main reason to adopt
any of these implementations.

## The answer

Two of the three things we present as distinctive are not. **Soft
assertions exist everywhere but Rust**, and **`eventually` exists
everywhere but Rust and Python**, including in the single most-used Go
assertion library. Worse, two established members of that family are
ones we do not have: testify's `Never` and Kotest's `continually`.

What is uncovered is narrower: **no library in any of these ecosystems
asserts that a subject honours cancellation, is pure, is idempotent, is
deterministic, cleans up what it started, or stays within an allocation
ceiling**. The one exception is Uber's goleak, which does leak detection
in Go and nothing else.

The literature explains why that gap is worth filling rather than
accidental. The oracle problem is the named bottleneck in testing, and
recent work finds that automatically generated oracles "primarily
generate regression oracles that predicate on the implemented behavior"
rather than the intended one. A fixed, named catalogue of metamorphic
relations is intended behaviour by construction. That is the thing to
build, and it is not what we currently say we are.

## What the evidence says

### Coverage, measured

Each cell is what I confirmed at the source, with the evidence below.

| Capability | Go | Java | Kotlin | Python | TypeScript | Rust |
|---|---|---|---|---|---|---|
| Soft assertions | testify `assert` | AssertJ `SoftAssertions` | Kotest `assertSoftly` | pytest-check | Vitest `expect.soft` | **none found** |
| Eventually | testify `Eventually` | Awaitility | Kotest `eventually` | not established | `@testing-library` waitFor | **none found** |
| Continually / never | testify `Never` | not found | Kotest `continually` | not found | not found | not found |
| Task or thread leaks | goleak | not found | not found | not found | diagnostic only | not found |
| Honours cancellation | **not found** | **not found** | **not found** | **not found** | **not found** | **not found** |
| Purity | **not found** | **not found** | **not found** | **not found** | **not found** | **not found** |
| Idempotence, determinism | **not found** | **not found** | **not found** | **not found** | **not found** | **not found** |
| Allocation ceiling in-test | **not found** | **not found** | **not found** | regression only | **not found** | **not found** |
| Concurrency correctness | not found | jcstress, Lincheck | Lincheck | not found | not found | loom |
| Property-based testing | rapid, gopter (small) | jqwik | Kotest | hypothesis | fast-check | proptest, quickcheck |

### Soft assertions are established everywhere but Rust

testify documents the split in one line: "Package require implements the
same assertions as the assert package but stops test execution when a
test fails" (pkg.go.dev, retrieved 2026-08-30). Go's `assert` package is
a recording surface and `require` an aborting one, which is the split
this standard states.

AssertJ ships soft assertions. The documentation site truncates, so I
read the published artifact: `assertj-core` 3.27.7 contains
`org/assertj/core/api/AbstractSoftAssertions.class`,
`AutoCloseableSoftAssertions.class` and `BDDSoftAssertions.class`
(Maven Central, retrieved 2026-08-30).

Kotest documents `assertSoftly`: "If any assertions inside the block
failed, the test will continue to run. All failures will be reported in a
single exception at the end of the block" (kotest.io, retrieved
2026-08-30).

Vitest documents `expect.soft` as continuing "instead of terminating the
test execution upon a failed assertion", with "both errors at the end of
the run" (vitest.dev, retrieved 2026-08-30).

pytest-check 2.9.1 describes itself as "A pytest plugin that allows
multiple failures per test", with 3,802,283 downloads last month (PyPI
and pypistats, retrieved 2026-08-30).

I found no Rust crate offering accumulating assertions.

**What we concluded:** the recording surface is worth keeping for
cross-language consistency, and it is a reason to adopt the library in
Rust only. Saying otherwise in the other READMEs would be a claim a
reader can disprove in one search.

### Retrying assertions are established too, and we are missing two

This is the correction that most changes the picture. testify's own
source declares `Eventually(t, condition func() bool, waitFor, tick
time.Duration, ...)`, documented as asserting "that given condition will
be met in waitFor time, periodically checking target function each
tick". Alongside it are `EventuallyWithT` and `Never`
(stretchr/testify master, `assert/assertions.go`, retrieved 2026-08-30).

Awaitility describes itself as "a small Java DSL for synchronizing
asynchronous operations", with the form
`await().atMost(Duration.ofSeconds(5)).until(customerStatusIsUpdated())`
(project README, retrieved 2026-08-30). It is at 4.3.0 on Maven Central.

Kotest documents four: `eventually`, `continually` ("ensure that a test
_continually_ passes for a period of time"), `until` and `retry`
(kotest.io, retrieved 2026-08-30).

**What we concluded:** our `eventually` and `eventually-true` are not
novel anywhere except Rust and possibly Python. And the standard is
missing the negative form that two established libraries independently
provide: testify's `Never` and Kotest's `continually` both state that a
condition holds for a duration rather than becoming true within one.
Two libraries arriving at the same member separately is the strongest
signal available that it belongs in the set.

### Nothing asserts behaviour

testify's documentation covers value assertions and does not mention
cancellation, context handling, purity, idempotence, determinism,
goroutine leaks or allocation limits (pkg.go.dev, retrieved 2026-08-30).

AssertJ states its scope as assertions for "JDK types (String, Iterable,
Stream, Path, File, Map, …)" with modules for Guava, Joda Time, Neo4J
and database types (assertj.github.io/doc, retrieved 2026-08-30).

The Vitest `expect` API documentation contains none of these concepts
(vitest.dev, retrieved 2026-08-30). Kotest's non-deterministic testing
page likewise covers only the four retrying helpers (kotest.io,
retrieved 2026-08-30).

goleak describes itself as a "Goroutine leak detector to help avoid
Goroutine leaks", used as `defer goleak.VerifyNone(t)` (README on
uber-go/goleak master, retrieved 2026-08-30). One assertion, one
language.

A web search for an assertion library covering idempotence, purity or
determinism returned nothing that does it.

### Benchmark ceilings are measured, not asserted

pytest-benchmark can fail a run, but on regression rather than on an
absolute ceiling: `--benchmark-compare-fail=min:5%` fails "if the
minimum execution time degrades by 5% or more" against a saved baseline.
Its documentation describes no memory measurement or allocation
limiting (readthedocs, retrieved 2026-08-30).

criterion has 268,755,046 total crates.io downloads and JMH is at 1.37,
both measurement tools rather than assertion ones.

**What we concluded:** a ceiling stated in the test beside the behaviour it
constrains is a different artifact from a regression threshold passed on
a command line against a stored baseline. The second needs somewhere to
keep the baseline and a policy for updating it. Ours needs neither, and
that is the claim worth making rather than "nobody does benchmarks".

### Concurrency correctness is a mature neighbour, not a competitor

Lincheck describes itself as "a practical and user-friendly framework
for writing deterministic and robust concurrent tests on JVM", verifying
"that the results of each invocation satisfy the required correctness
property (linearizability by default)" by exploring thread interleavings
(JetBrains/lincheck, retrieved 2026-08-30). loom, at 61,375,583
crates.io downloads, is "Permutation testing for concurrent code".
jcstress is at 0.16 on Maven Central.

**What we concluded:** these explore the interleaving space to find a
schedule that breaks an invariant. Our assertions check one execution
against a stated relation. They answer different questions, and a
project can want both. Nothing here overlaps, and the RFC should say so
rather than leaving a reader to wonder.

### The literature names the gap, and names why generated oracles do not fill it

The oracle problem is the field's own term for this. Barr, Harman,
McMinn, Shahbaz and Yoo surveyed it in IEEE Transactions on Software
Engineering in 2015; Crossref records 884 citations
(DOI 10.1109/tse.2014.2372785, retrieved 2026-08-30).

Metamorphic testing is the established technique for it. A 2024 survey
by eight authors including Tsong Yueh Chen, who originated the
technique, opens: "Metamorphic testing has become one mainstream
technique to address the notorious oracle problem in software testing,
thanks to its great successes in revealing real-life bugs in a wide
variety of software systems" (arXiv:2406.05397v2). Spieker and Gotlieb
define the relations as "necessary properties of a system-under-test,
called metamorphic relations, to either check its expected outputs, or
to generate new test cases" (arXiv:1910.00262v3).

Alzahrani, Spichkova and Harland place it against the nearest
alternative: "In some sense, MT can be seen as a very specific kind of
PBT" (arXiv:2211.12003v1).

The most useful recent finding is about what automation does not solve.
Bodicoat, Jahangirova and Terragni, in January 2026: "existing
techniques primarily generate regression oracles that predicate on the
implemented behavior of the class under test. They do not address the
oracle problem: the challenge of distinguishing correct from incorrect
program behavior" (arXiv:2601.05542v1).

**What we concluded:** this is the argument for a fixed catalogue. A
generated oracle learns what the code does. A named relation like
"purity" or "idempotence" states what the code should do, chosen by a
person from a list, and it cannot degrade into a snapshot of current
behaviour. That is the difference worth building on, and it is an
argument from the literature rather than from taste.

### Where the research frontier sits

Of 78 metamorphic-testing papers on arXiv cs.SE since January 2025, the
large majority apply the technique to machine-learning and
language-model systems: RAG pipelines, vision-language robots, embodied
agents, clinical prediction models, LLM-generated code. The classical
case of metamorphic relations over ordinary library APIs is comparatively
quiet.

Property-based testing research is active and adjacent. Maaz, DeVoe,
Hatfield-Dodds (a Hypothesis maintainer) and Carlini ran an LLM agent
that infers properties and synthesises property-based tests across 100
Python packages, reporting that "56% were valid bugs" and that they
"reported 5 bugs, 4 with patches, including to NumPy and cloud computing
SDKs, with 3 patches merged" (arXiv:2510.09907v1, October 2025).

**What we concluded:** the property catalogue is the part an agent still has
to guess at, and the paper above spends its effort inferring properties
before it can test anything. A standard that names the relations gives
that step a fixed vocabulary. This is speculative and belongs in the RFC
as a motivation, not as a finding.

### Property-based testing is the real competitor, and Go is the outlier

fast-check recorded 137,395,471 npm downloads last month, hypothesis
49,709,462 on PyPI, proptest 177,248,788 and quickcheck 65,857,860 total
on crates.io, and jqwik is at 1.10.1 on Maven Central (registry APIs,
retrieved 2026-08-30). Go has rapid at 871 GitHub stars and gopter at
637 (GitHub API, retrieved 2026-08-30).

**What we concluded:** a property-based test states the same relation but
needs a generator, a shrinking strategy and a different test style. An
assertion states it about a call the author already has in front of them.
They are complements. Go's small property-based testing adoption suggests
the assertion form may suit Go better, though I did not establish whether
that is a gap or a preference for native fuzzing.

## What we could not establish

**Whether anyone tried behavioural assertions and dropped them.** I
found no library offering them, which is not a decision against them.
Closing this means reading declined feature requests on testify, AssertJ,
Vitest and Kotest, which I did not do.

**Whether Python has an established `eventually`.** I checked
pytest-check, pytest-timeout, pytest-repeat and pytest-randomly and
found no retrying-assertion helper with the adoption Awaitility or
testify has. Absence of evidence here is weak: I did not search PyPI
exhaustively.

**AssertJ's soft-assertion contract.** I confirmed the classes ship;
javadoc.io returned HTTP 403 and the doc site truncates, so I did not
read what they guarantee.

**Whether Go's small property-based testing adoption is a gap or a
preference.** Go 1.18 added native fuzzing, which may be what Go
developers reach for. Not checked.

**Whether `continually`/`Never` should be one member or two.** testify
and Kotest arrived at the same idea with different names and slightly
different shapes. I did not compare their semantics closely enough to
say whether one standard member covers both.

## What would change this answer

An established assertion library shipping cancellation, purity or
cleanup assertions. testify, AssertJ, Kotest and Vitest are the ones to
watch, and AssertJ 4.0 is at 4.0.0-M1, so its scope may still move.

A Rust crate offering accumulating assertions, which would remove the
one ecosystem where the soft surface is itself a reason to adopt this.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | <https://pkg.go.dev/github.com/stretchr/testify> | Package documentation | 2026-08-30 | assert/require split; no behavioural assertions |
| 2 | <https://raw.githubusercontent.com/stretchr/testify/master/assert/assertions.go> | Library source | 2026-08-30 | `Eventually`, `EventuallyWithT`, `Never` exist, with signatures |
| 3 | <https://repo1.maven.org/maven2/org/assertj/assertj-core/> | Published artifact 3.27.7 | 2026-08-30 | AssertJ ships the soft-assertion classes |
| 4 | <https://assertj.github.io/doc/> | Project documentation | 2026-08-30 | AssertJ's stated scope is JDK and library types |
| 5 | <https://kotest.io/docs/assertions/soft-assertions.html> | Project documentation | 2026-08-30 | `assertSoftly` and its reporting contract |
| 6 | <https://kotest.io/docs/assertions/non-deterministic-testing.html> | Project documentation | 2026-08-30 | `eventually`, `continually`, `until`, `retry` |
| 7 | <https://github.com/awaitility/awaitility> | Project README | 2026-08-30 | Awaitility is a DSL for awaiting async conditions |
| 8 | <https://vitest.dev/api/expect.html> | API documentation | 2026-08-30 | `expect.soft`; no behavioural assertions |
| 9 | <https://pypi.org/pypi/pytest-check/json> | Registry metadata 2.9.1 | 2026-08-30 | "allows multiple failures per test" |
| 10 | <https://raw.githubusercontent.com/uber-go/goleak/master/README.md> | Project README | 2026-08-30 | goleak detects goroutine leaks only |
| 11 | <https://github.com/JetBrains/lincheck> | Project README | 2026-08-30 | Linearizability checking by interleaving exploration |
| 12 | <https://pytest-benchmark.readthedocs.io/en/latest/comparing.html> | Project documentation | 2026-08-30 | `--benchmark-compare-fail` is regression, not a ceiling; no allocation measurement |
| 13 | <https://doi.org/10.1109/tse.2014.2372785> | Barr, Harman, McMinn, Shahbaz, Yoo, IEEE TSE 2015 | 2026-08-30 | The oracle problem survey; 884 citations per Crossref |
| 14 | <https://arxiv.org/abs/2406.05397> | Li et al., 8 authors incl. T.Y. Chen, 2024 | 2026-08-30 | MT as mainstream answer to the oracle problem |
| 15 | <https://arxiv.org/abs/1910.00262> | Spieker and Gotlieb, 2019 | 2026-08-30 | Definition of metamorphic relations |
| 16 | <https://arxiv.org/abs/2211.12003> | Alzahrani, Spichkova, Harland, 2022 | 2026-08-30 | MT as a specific kind of PBT |
| 17 | <https://arxiv.org/abs/2601.05542> | Bodicoat, Jahangirova, Terragni, 2026-01 | 2026-08-30 | Generated oracles encode implemented, not intended, behaviour |
| 18 | <https://arxiv.org/abs/2510.09907> | Maaz, DeVoe, Hatfield-Dodds, Carlini, 2025-10 | 2026-08-30 | Agentic PBT across 100 Python packages; 56% valid bugs |
| 19 | <https://crates.io/api/v1/crates/proptest> | Registry API | 2026-08-30 | proptest 177,248,788; loom 61,375,583; criterion 268,755,046; pretty_assertions 198,248,342; insta 93,954,655 |
| 20 | <https://api.npmjs.org/downloads/point/last-month/fast-check> | Registry API | 2026-08-30 | fast-check 137,395,471/month; vitest 381,320,980; chai 446,435,556 |
| 21 | <https://pypistats.org/api/packages/hypothesis/recent> | Registry API | 2026-08-30 | hypothesis 49,709,462/month; pytest-check 3,802,283 |
| 22 | <https://api.github.com/repos/leanovate/gopter> | Repository metadata | 2026-08-30 | gopter 637 stars; rapid 871 |

## What we searched

Three angles as the method requires: the names of the things, the
problem they solve, and what a frustrated user would type.

| Terms | Where | Date | Found |
|---|---|---|---|
| `"metamorphic testing" AND ("metamorphic relations" OR "test oracle problem")`, cs.SE | arXiv | 2026-08-30 | 94 results, 3 read |
| `"metamorphic testing" OR "metamorphic relations"`, cs.SE, from 2025-01-01 | arXiv | 2026-08-30 | 78 results; overwhelmingly ML and LLM applications |
| `"property-based testing" OR "test oracle" OR "assertion generation"`, cs.SE, from 2025-06-01 | arXiv | 2026-08-30 | 96 results, 2 read in full |
| The Oracle Problem in Software Testing: A Survey | Crossref | 2026-08-30 | Barr et al. 2015, 884 citations |
| metamorphic testing oracle problem | Semantic Scholar | 2026-08-30 | HTTP 429 twice, no results |
| test assertion library assert function is idempotent deterministic pure side-effect free | Web search | 2026-08-30 | Nothing offering these assertions |
| testify packages, then `Eventually`/`Never` in its source | pkg.go.dev, GitHub raw | 2026-08-30 | Corrected an earlier claim |
| AssertJ soft assertions, then the artifact | assertj.github.io, Maven Central | 2026-08-30 | Confirmed via class listing |
| Kotest soft assertions and non-deterministic testing | kotest.io | 2026-08-30 | `assertSoftly`, `eventually`, `continually`, `until`, `retry` |
| Awaitility, Lincheck | GitHub | 2026-08-30 | Confirmed scope of each |
| awaitility, kotest, lincheck, jcstress, truth, jmh, jqwik | Maven Central metadata | 2026-08-30 | Stable versions above |
| loom, tokio-test, quickcheck, criterion, arbitrary | crates.io | 2026-08-30 | Figures above |
| pytest-benchmark, pytest-timeout, pytest-repeat, pytest-randomly | PyPI, readthedocs | 2026-08-30 | No in-test ceiling, no allocation measurement |
| leakage, why-is-node-running, @testing-library/dom, p-timeout | npm | 2026-08-30 | Node leak tooling is diagnostic, not assertion |
| rapid, gopter, go-cmp, quicktest | GitHub API | 2026-08-30 | Go property-based testing adoption is small |
| `SoftAssertions` in assertj/assertj, three query forms | GitHub code search | 2026-08-30 | Zero results; tool returned nothing |

The claim that no library covers cancellation, purity, idempotence or
determinism rests on the web search plus the documentation of testify,
AssertJ, Kotest, Vitest and goleak. It means I did not find one.

## A note on reading version metadata

Maven Central's `maven-metadata.xml` gave `<release>4.0.0-M1` for
assertj-core, which is a milestone rather than a stable release. Reading
`<release>` is not sufficient on its own; the version list has to be
filtered for pre-release markers too. The stable version is 3.27.7.
