---
research: 0007
title: Can mutation testing run as a library that the test runner drives, and from one build for all mutants, in Go, Java, Kotlin, Python, TypeScript and Rust?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-10-02
updated: 2026-10-02
freshest-source: 2026-10-02
supersedes: none
superseded-by: none
---

# Research-0007: Can mutation testing run as a library that the test runner drives, and from one build for all mutants, in Go, Java, Kotlin, Python, TypeScript and Rust?

## The question

gremlins, the mutation tester that the Go repositories gate on, is a binary
installed beside the toolchain. For each mutant it writes the mutated file
into a copy of the module and runs `go test`, which compiles and links a
test binary. The question has two parts for each language that the standard
supports:

- Can mutation testing run as a library that the language's own test
  runner drives, with nothing installed beside it?
- Can every mutant run from one build, and what does one build save over a
  build per mutant?

### What would count as an answer

- A tool in the language that has the property, read in its source or its
  documentation.
- A measurement of a build per mutant against one build, on the same
  mutants.
- A construct of the language that one build cannot express, with the
  reason.

### What sources are admissible

Peer-reviewed papers, the tools' source code and documentation,
maintainers' statements, and measurements of our own.

### What would change the answer

- A language whose build or module loading forces a build per mutant.
- A measurement in which a build per mutant costs less than one build that
  contains every mutant.

## The answer

Both properties are possible in all five languages. The table lists the
tools that have each property today:

| Language | A library that the test runner drives | Every mutant from one build | Both in one tool |
|---|---|---|---|
| Go | ooze, called from a test. It builds once per mutant | mutest and kanly, both separate binaries | None published. Our prototype has both |
| Java | None beyond two projects with 1 and 2 stars | PIT rewrites bytecode and compiles nothing per mutant. Major compiles every mutant once inside javac | None |
| Kotlin | mutflow, a compiler plugin with a JUnit extension | mutflow, and PIT on Kotlin's bytecode | mutflow, 35 stars |
| Python | pytest-gremlins, a pytest plugin | Python compiles nothing. mutmut 3 and pytest-gremlins load every mutant once and switch between them | pytest-gremlins, released as alpha |
| TypeScript | None found | StrykerJS transpiles once and switches the active mutant inside a running test runner | None |
| Rust | mutagen, an attribute macro in the dev-dependencies, run by `MUTATION_ID=n cargo test` | mutagen, and mutest-rs, a replacement compiler driver | mutagen, nightly only, last changed in May 2023 |

The technique behind one build is mutant schemata. The program is compiled
once with every mutant behind a runtime switch, and each run selects one
mutant. Untch, Offutt and Harrold proposed it in 1993. Papadakis et al.'s
2019 survey calls it the most commonly used technique against the cost of
compiling each mutant. The JVM offers a second technique, which PIT uses:
rewrite the loaded bytecode in memory.

What one build saves depends on the time a test run takes against the time
a build takes. On three Go packages, with the same mutants in both modes,
one build was 48 times faster when the suite ran in milliseconds, 5.2 times
faster when it ran in a fifth of a second, and 1.1 times faster when it
ran in four seconds. A build per mutant added 1.3 to 2.4 MB to the build
cache per mutant. mutest-rs, with one build, finished in a median of 22.9
seconds on eight Rust crates, where cargo-mutants, with a build per mutant,
took 1.6 hours. That comparison also includes test selection.

A library that the test runner drives must keep the build it starts free
of the test that started it. ooze and our prototype use a build tag, and
mutflow compiles twice. One build has costs of its own. It cannot mutate
constants or code that runs while the program loads, and type context needs
the instrumenter's help. A run that executes no switch passes for every
mutant, unless a run that forces every switch to fail catches it.

## Findings

### Mutant schemata compile every mutant once, and the literature measures the saving

Untch, Offutt and Harrold (ISSTA 1993) encode every mutant of a program in
one metaprogram, which the program's own compiler compiles once. They
report preliminary speedups of over 300% against the interpretive mutation
systems of the time. They expect schemata to run somewhat slower than
mutation built into a compiler, because each mutated operation becomes a
call.

Papadakis et al.'s survey (Advances in Computers 112, 2019, §5.2) states
that a separate source file per mutant "requires approximately 3 seconds
(on average) to compile a single mutant of a large project", citing the
trivial compiler equivalence study. The survey names meta-mutation, or
mutant schemata, the most commonly used technique against that cost. It
names bytecode manipulation as the alternative: PIT for Java, and tools for
.NET's intermediate language and for LLVM bitcode.

Pizzoleto et al.'s systematic review (JSS 157, 2019) classifies 153 studies
of cost reduction into 21 techniques. Metamutants, its name for mutant
schemata, are one of them.

Just, Kapfhammer and Schweiggert (AST 2011) generate every mutant inside
javac, as conditional expressions and statements. For aspectj's 406,382
mutants, generating and compiling them took 33% longer than an ordinary
compile. Running the test suites with every condition in place took 15%
longer on average, with every condition evaluated. The tool paper on Major
(ASE 2011) reports that the overhead ranged from 1% for Apache Ant to 29%
for Java PathFinder.

Wang et al. (ISSTA 2017) fork one process for each group of mutants that
leave the same state after a mutated statement. On top of split-stream
execution, which forks at the first mutated statement, this was 2.56 times
faster on average.

**What we concluded:** compiling a program once with every mutant is an
established technique with measured savings. What differs between
languages is the tooling.

### Go: one tool is a library, two build once, and no published tool is both

- **gremlins** v0.6.0 applies each mutant to a worker's copy of the module
  and runs `go test -failfast` on the package
  (`internal/engine/executor.go`, lines 160 to 242). Every mutant compiles
  and links a test binary.
- **ooze** is a library. A test file behind `//go:build mutation` calls
  `ooze.Release(t)`, and `go test -tags=mutation` runs it. For each mutant,
  ooze copies the repository to a temporary directory, writes the mutated
  file and runs `go test -count=1 ./...` there
  (`internal/laboratory/laboratory.go`). It builds once per mutant.
- **mutest**, by fchimpan, and **kanly** are separate binaries that compile
  each package once. Each replaces a mutated operator with a call to a
  generated generic function, which reads the active mutant from an
  environment variable. mutest hands the rewritten files to the compiler
  through `go build`'s `-overlay` flag and leaves the source tree untouched.
  Neither publishes a measurement against a build per mutant. mutest's
  README names the MIT licence, and its repository contains no licence
  file.
- **gomutants** applies each mutant as an overlay and builds once per
  mutant. It runs only the tests whose coverage includes the mutated line.

We wrote a prototype that has both properties, in
`~/.cache/assert-spec-mutation/gomut`. It finds the mutants that gremlins
enables by default: arithmetic operators, boundaries and negations of
comparisons, and increments. It rewrites the package into schemata with
generic helper functions, passes the result to the compiler through
`-overlay`, and builds one test binary. `gomut.Check(t, ".")` runs the whole
check from a test behind a build tag, so `go test -tags mutation` drives
it. The same harness can instead build once per mutant, from an overlay
that changes one operator, which is how gremlins and ooze work.

We ran both modes on three packages, one mutant at a time, each mode with a
fresh build cache warmed by one ordinary test run (Go 1.27.1,
`GOMAXPROCS=4`, 4 cores):

| Package | Mutants | Suite | Verdicts | One build | A build per mutant | Ratio |
|---|---|---|---|---|---|---|
| go-humanize v1.1.0 | 193 | 0.006 s | 162 killed, 31 survived, the same in both modes | 0.7 s, median 3 ms per mutant | 31.4 s, median 163 ms | 48× |
| google/btree v1.1.3 | 124 | 0.2 s | 106 killed, 18 survived, the same in both modes | 5.6 s, median 5 ms | 29.2 s, median 197 ms | 5.2× |
| shopspring/decimal v1.4.0, every 10th of 574 mutants | 58 | 4 s | 39 killed, 19 survived, the same in both modes | 139.2 s, median 3,986 ms | 151.4 s, median 4,175 ms | 1.1× |

The one build took 0.23 to 0.37 seconds. A build per mutant added 160 to
190 milliseconds to every mutant. The go-humanize times leave out one
mutant that loops until the 32-second timeout in both modes. With it, the
totals are 32.3 and 63.2 seconds. With a suite this fast, the timeout costs
as much as all the builds together.

A build per mutant also grew the build cache: by 252.6 MB on go-humanize,
232.0 MB on btree and 141.0 MB on the decimal sample, which is 1.3, 1.9 and
2.4 MB per mutant. One build grew it by 3.9, 5.0 and 8.0 MB.

Run as a test, `go test -tags mutation -run TestMutation` on a copy of
go-humanize built once, ran all 193 mutants and reported each of the 31
survivors as a failure of the test, at the mutant's file, line and column.
It took 61 seconds, of which the looping mutant's fixed timeout of one
minute took 60. Adding the prototype as a dependency raised the copy's go
line from 1.21 to 1.27, the version that the prototype and
`golang.org/x/tools` declare.

With no mutant active, the schemata binary ran decimal's suite in a median
of 4.058 seconds against 4.016 for the ordinary binary, 1.1% slower, over
five alternating rounds. btree's suite, repeated 20 times in each run, took
4.201 seconds against 3.969, 5.9% slower, with a spread of about 5% between
rounds.

Building the prototype found these limits of schemata in Go:

- A constant expression cannot contain a runtime switch, so constant
  declarations and array lengths keep their operators. kanly states the
  same limit for constant declarations and struct tags.
- An untyped constant in a non-constant shift takes its type from the
  surrounding expression. Passed to a generic helper, the constant in
  `(1 << k) + 1`, inside a `uint` declaration in decimal, became an `int`,
  and the build failed. The call needs its type argument written out, and
  the prototype skips a site whose type it cannot name. kanly restricts its
  literal mutations to plain `int` for the same reason.
- Generic helpers need language version 1.18. decimal's `go.mod` declares
  `go 1.10`, and the build failed with "type parameter requires go1.18 or
  later". A `//go:build go1.18` line raises the language version of one
  file. Every rewritten file needs it too, because a call that infers a
  generic function's type arguments fails in an older file with "implicit
  function instantiation requires go1.18 or later". A module at go 1.22 or
  above must not get the line, because it would lower the language version
  and change the semantics of loop variables.
- The go command matches an overlay against the paths it computes from its
  working directory. Through the symbolic link from `/home` to `/var/home`,
  the overlay matched no file, the original package ran for every mutant,
  and all 193 mutants of go-humanize survived. The prototype now resolves
  links first, and it runs the binary once with a value that makes every
  switch panic. That run must fail, and the prototype stops when it passes.
  mutmut runs the same check before its mutants.
- An operand whose type is a type parameter, and a comparison of an
  interface value with a concrete value, do not give the helper a single
  type argument. The prototype skips both.

**What we concluded:** Go can have both properties in one library. The
library needs the go command when the tests run, which is present wherever
`go test` runs, and `-overlay` keeps the source tree untouched. One build
cut the time 5 to 48 times on packages whose suites run in under a second,
and saved little on a package whose suite takes four seconds. On every
package it cut the build cache's growth, by 18 to 65 times.

### Java: bytecode rewriting avoids the build, and no mature tool runs from the test runner

PIT generates the mutated bytecode in a child JVM and inserts it into the
running JVM through the Java instrumentation API (Coles et al., ISSTA
2016). It keeps one mutant in memory at a time. By default it starts one
JVM for the mutants of each class, and it can start one per mutant at the
cost of speed. It runs from the command line, Ant and Maven, and a separate
plugin adds Gradle. PIT's FAQ notes that "code in static initializer blocks
is not re-run so the mutants have no effect".

Major replaces javac. With `-XMutator`, it compiles every mutant into the
classes as conditional expressions, and its analysis back-end extends Ant's
JUnit task (Major documentation). Javalanche (ESEC/FSE 2009) combines both
techniques. It rewrites bytecode to avoid recompilation and guards every
mutation with a runtime flag, and it records that µJava also uses mutant
schemata.

MutKt and JAllele run from the test runner. MutKt, with 1 star, offers a
JUnit extension and a Gradle plugin and mutates compiled bytecode. JAllele, with
2 stars, attaches an agent to its own JVM. We read only their READMEs.

**What we concluded:** on the JVM, compiling nothing per mutant needs no
schemata, because rewriting loaded bytecode is cheaper than any build. A
JUnit extension could drive the same mechanism, and no mature tool does.

### Kotlin: one young tool has both properties

mutflow is a compiler plugin for Kotlin's K2 compiler and a JUnit
extension. The plugin compiles every variant of a mutation point into the
class, as `when` branches that ask a runtime registry which variant is
active. The extension, `@MutFlowTest`, runs a test class once per mutation.
mutflow compiles twice, so the production JAR contains no mutation code. It
mutates only classes annotated `@MutationTarget` or matched by a pattern in
the Gradle plugin, and it finds mutation points while a baseline run
executes `MutFlow.underTest { }` blocks. It has 35 stars, and its last push
was on 2026-09-27.

PIT also mutates Kotlin's bytecode. The open-source plugin that filters the
junk mutations of compiler-generated code is no longer maintained, and
Arcmutate's replacement needs a commercial licence key.

**What we concluded:** a library for this standard on the JVM would combine
a compiler plugin with a JUnit extension, the two parts that give mutflow
both properties for Kotlin today. Java code that javac compiles would need
a plugin of its own, or bytecode rewriting.

### Python: nothing is compiled, and the cost per mutant is the import

mutmut 3 copies each mutated function into one version per mutant and
replaces the function with a trampoline. The trampoline calls the version that the
environment variable `MUTANT_UNDER_TEST` names
(`src/mutmut/mutation/trampoline.py`). mutmut imports pytest once and forks
one process per mutant (`src/mutmut/workers/isolation.py`), so it needs
`fork` and runs on POSIX systems only. It mutates code inside functions
only. Its 3.0.0 release, on 2024-10-20, "switched to mutation schemata,
which enabled parallel execution". It runs as a separate command,
`mutmut run`.

pytest-gremlins is a pytest plugin, and `pytest --gremlins` runs it. It
instruments the code once through import hooks, switches between mutants
with an environment variable, and runs only the tests whose coverage
includes a mutant. Its design document puts the requirement as "Not a
wrapper. Not a separate CLI. A proper pytest plugin". Version 1.9.0 is
marked alpha. Its first release was on 2026-01-27.

**What we concluded:** in Python, the cost that corresponds to a build per
mutant is importing the code and starting a process. Switching between
mutants in one loaded process removes both. pytest-gremlins gives Python
both properties, at alpha quality.

### TypeScript: one transpile exists, and the test runner does not drive it

StrykerJS 4.0 (October 2020) switched to mutation switching, its name for
mutant schemata. Its authors expected "somewhere between 20% to 70% speed
increase", and the code is transpiled or bundled once instead of once per
mutant. Its instrumenter relies on `// @ts-nocheck`, so the code type-checks
with every mutant in place. A separate TypeScript checker removes the
mutants that would not compile on their own.

StrykerJS 6.0 (May 2022) added hot reload: a worker loads the code once and
switches the active mutant between test runs. On Stryker's own core that
was "a whopping 70% performance improvement". A static mutant, which code
executes once while it loads, needs a fresh worker. Ignoring the static
mutants, 6% of the mutants, saved another 50% on the same code.

Stryker's runner for vitest creates one Vitest instance and reruns the
tests in it for each mutant, with the active mutant passed in before each
run (`packages/vitest-runner/src/vitest-test-runner.ts`, version 10.0.0).
So the runner depends on Vitest's internals. Issue #5928 reports that an API
change between Vitest 4.0 and 4.1 broke per-test coverage and produced
false survivors.

mutineer writes each mutant to a temporary file and swaps it in through a
Vite plugin, so it loads a module per mutant. Vitest has offered plugins a
`configureVitest` hook since version 3.1, beside Vite's `transform` hook.
We found no tool that uses them to run mutation testing from inside vitest.

**What we concluded:** TypeScript has one transpile and hot reload, from a
separate command. Whether a vitest plugin can switch mutants between runs
without reloading modules is not established.

### Rust: one build is measured at two orders of magnitude, and the library form needs nightly

cargo-mutants copies the tree to a scratch directory, reused so that
builds are incremental. For each mutant it patches the file, checks that
`cargo test --no-run` compiles, runs `cargo test` and reverts the patch. Its
maintainer argues that "for most trees ... the test time will be longer
than incremental builds", and its documentation states that building each
mutant lets it try mutants that might not compile.

mutagen is an attribute macro, `#[mutate]`, added as a dev-dependency. It
compiles every mutation into the code and selects one at runtime through
`MUTATION_ID`. `cargo test` writes the list of mutations, so
`MUTATION_ID=1 cargo test` runs a mutant without mutagen's runner. A
procedural macro sees no type information, so every mutation must compile
without it, and constants, statics, patterns and unsafe code are not
mutated. mutagen needs nightly Rust, and its last push was on 2023-05-29.

mutest-rs replaces rustc with a driver that uses the compiler's type
analysis to generate only valid mutations. It compiles one meta-mutant per
crate, with `match` expressions on a global handle, and it needs a second
meta-mutant for each integration-test crate (Lévai, Shin and McMinn, ICST
2026). Its repository pins one nightly toolchain, nightly-2026-07-18. On
eight crates, its default configuration took a median of 22.9 seconds
where cargo-mutants took 1.6 hours. Across crates and its three
configurations, it was 8 to 2,252 times faster.

The sources disagree on how much the build costs. cargo-mutants' maintainer
expects tests to outweigh incremental builds. mutest-rs measured two
orders of magnitude at the median, and attributes the speedup both to the single
compilation and to its call graph, which drops unreachable mutations and
irrelevant tests. Our Go measurements reproduce both positions: the build
dominates when the suite is short, and the tests dominate when it is long.

**What we concluded:** Rust has both properties in mutagen, which needs
nightly and is unmaintained, and one build at scale in mutest-rs, which
needs a pinned nightly compiler.

### What one build cannot mutate

- **Constants.** Stryker.NET states that mutant schemata cannot mutate
  constant values. mutagen leaves `const` and `static` expressions alone,
  and kanly and our prototype leave constant declarations alone.
- **Code that runs while the program loads.** StrykerJS needs a fresh
  worker for each static mutant, and PIT's mutants in static initializer
  blocks have no effect.
- **A mutant that does not compile.** One such mutant breaks the build of
  all. Stryker.NET removes the mutations that the compiler rejects
  and compiles again, usually one to three times. mutest-rs generates only
  valid mutations. cargo-mutants avoids the problem by building each mutant.
- **Type context.** Go's untyped constants and TypeScript's type checker
  both need the instrumenter's help, as the Go and TypeScript sections
  describe.
- **Every run executes the switches.** Major measured 15% on average. Our
  Go prototype measured 1.1% and 5.9%.
- **Mutants share a process.** PIT starts a JVM per class to limit leaked
  state. mutmut forks per mutant, and offers a fork server for test setups
  that are not safe to fork. mutest-rs runs tests on threads by default,
  and in separate processes for mutations that affect unsafe code.
- **A switch that no test executes.** Every mutant then survives, as all
  193 did when our overlay matched no file. A run that forces every switch
  to fail detects it.

### A library that the test runner drives must leave itself out of the build it starts

- ooze and our prototype put the calling test behind a build tag that the
  nested `go test` does not set.
- mutflow compiles the code twice. Only the test compilation contains
  mutations.
- mutagen's documentation tells the caller to write
  `#[cfg_attr(test, mutate)]`, so only test builds contain mutations.

A library also becomes a dependency of the module under test, with its own
minimum language version. Adding our prototype raised go-humanize's go line
from 1.21 to 1.27.

**What we concluded:** the guard is one build condition in each language.
A library form makes its own version floor the floor of every module that
uses it.

## What we could not establish

- **A Java library that the test runner drives, of any maturity.** We read
  MutKt and JAllele only through their READMEs.
- **A tool that vitest drives.** Whether a vitest plugin can switch mutants
  without reloading modules needs a prototype.
- **Schemata for Go's generic code.** Our prototype skips operands whose
  type is a type parameter. We did not check how mutest and kanly handle
  them.
- **Go at the scale of a large module.** We measured three single-package
  modules whose builds took 0.2 to 0.4 seconds. A package with a longer
  build or many dependents moves the ratio towards one build.
- **pytest-gremlins' speed.** Its design document sets speed goals and
  reports no measurement.

## What would change this answer

- A Go release that changes how `-overlay` matches paths, or removes it.
- A measurement in which the switches slow a suite by more than the builds
  they save.
- A tool that JUnit or vitest drives and that builds once, which would fill
  the two empty cells of the table.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | Untch, Offutt and Harrold, "Mutation analysis using mutant schemata", ISSTA 1993, <https://doi.org/10.1145/154183.154265>, PDF at <https://www.albany.edu/faculty/offutt/research/papers/schema.pdf> | Peer-reviewed paper, abstract and §3 | 2026-10-02 | The technique, over 300% against interpretive systems, call overhead |
| 2 | Papadakis, Kintis, Zhang, Jia, Le Traon and Harman, "Mutation Testing Advances: An Analysis and Survey", Advances in Computers 112, 2019, <https://doi.org/10.1016/bs.adcom.2018.03.015>, preprint at <https://mutationtesting.uni.lu/survey.pdf> | Survey, §5.2 read | 2026-10-02 | About 3 s to compile a mutant of a large project, schemata the most common technique, bytecode manipulation |
| 3 | Pizzoleto, Ferrari, Offutt, Fernandes and Ribeiro, "A systematic literature review of techniques and metrics to reduce the cost of mutation testing", JSS 157, 2019, <https://doi.org/10.1016/j.jss.2019.07.100> | Systematic review, abstract and §5 | 2026-10-02 | 153 studies, 21 techniques, metamutants among them |
| 4 | Just, Kapfhammer and Schweiggert, "Using conditional mutation to increase the efficiency of mutation analysis", AST 2011, <https://www.gregorykapfhammer.com/download/research/papers/key/Just2011a-paper.pdf> | Peer-reviewed paper | 2026-10-02 | 406,382 mutants for 33% more compile time, 15% more test time |
| 5 | Just, Schweiggert and Kapfhammer, "MAJOR: An efficient and extensible tool for mutation analysis in a Java compiler", ASE 2011, <https://homes.cs.washington.edu/~rjust/publ/major_compiler_ase_2011.pdf>, and the Major manual, <https://mutation-testing.org/doc/major.pdf> | Tool paper and manual | 2026-10-02 | Overhead from 1% to 29%, `-XMutator`, the Ant back-end |
| 6 | Schuler and Zeller, "Javalanche: efficient mutation testing for Java", ESEC/FSE 2009, <https://doi.org/10.1145/1595696.1595750> | Tool paper | 2026-10-02 | Bytecode rewriting with mutant schemata, µJava's schemata |
| 7 | Coles, Laurent, Henard, Papadakis and Ventresque, "PIT: a practical mutation testing tool for Java", ISSTA 2016, <https://doi.org/10.1145/2931037.2948707> | Tool paper | 2026-10-02 | Mutants inserted through the instrumentation API, a JVM per class |
| 8 | PIT FAQ, <https://pitest.org/faq/> | Maintainer's documentation | 2026-10-02 | Static initializer blocks are not re-run |
| 9 | Wang, Xiong, Shi, Zhang and Hao, "Faster mutation analysis via equivalence modulo states", ISSTA 2017, <https://arxiv.org/abs/1702.06689> | Peer-reviewed paper, abstract | 2026-10-02 | 2.56 times over split-stream execution |
| 10 | Lévai, Shin and McMinn, "mutest-rs: Flexible, efficient mutation analysis tool for Rust programs, using extensive static analysis", ICST 2026, pp. 216–220, <https://philmcminn.com/publications/levai2026b.pdf> | Peer-reviewed tool paper, read in full | 2026-10-02 | One meta-mutant per crate, Table II, the pinned nightly |
| 11 | mutest-rs repository, `rust-toolchain.toml`, <https://github.com/zalanlevai/mutest-rs> | Source code | 2026-10-02 | nightly-2026-07-18 |
| 12 | cargo-mutants documentation, <https://mutants.rs/how-it-works.html> and <https://mutants.rs/goals.html>, and discussion #209, <https://github.com/sourcefrog/cargo-mutants/discussions/209> | Maintainer's documentation and statement | 2026-10-02 | A build per mutant, tests outweigh incremental builds |
| 13 | mutagen README, <https://github.com/llogiq/mutagen> | Maintainer's documentation | 2026-10-02 | `#[mutate]`, `MUTATION_ID`, nightly, its limits, last push 2023-05-29 |
| 14 | gremlins v0.6.0, `internal/engine/executor.go`, <https://github.com/go-gremlins/gremlins> | Source code | 2026-10-02 | A `go test` per mutant |
| 15 | ooze, README and `internal/laboratory/laboratory.go`, <https://github.com/gtramontina/ooze> | Source code | 2026-10-02 | A library run by `go test`, a repository copy and a build per mutant |
| 16 | mutest README, <https://github.com/fchimpan/mutest> | Author's documentation | 2026-10-02 | One build per package, generic helpers, `-overlay` |
| 17 | kanly README, <https://github.com/devenjarvis/kanly> | Author's documentation | 2026-10-02 | Mutant schema generation, the limits on constants and literals |
| 18 | gomutants README, <https://github.com/gomutants/gomutants> | Author's documentation | 2026-10-02 | Overlay patches per mutant, per-test coverage routing |
| 19 | mutmut, `src/mutmut/mutation/trampoline.py`, `src/mutmut/workers/isolation.py`, `HISTORY.rst` and the documentation at <https://mutmut.readthedocs.io/en/latest/> | Source code and documentation | 2026-10-02 | Trampolines, `MUTANT_UNDER_TEST`, a fork per mutant, schemata since 3.0.0 |
| 20 | pytest-gremlins documentation, <https://pytest-gremlins.readthedocs.io/en/latest/>, and PyPI metadata, <https://pypi.org/project/pytest-gremlins/> | Author's documentation and registry metadata | 2026-10-02 | A pytest plugin with mutation switching, version 1.9.0, alpha |
| 21 | StrykerJS announcements of 4.0, <https://stryker-mutator.io/blog/announcing-stryker-4-mutation-switching/>, and 6.0, <https://stryker-mutator.io/blog/stryker-js-v6-expeditious-superior-mutations/>, and the page on static mutants, <https://stryker-mutator.io/docs/mutation-testing-elements/static-mutants/> | Maintainers' documentation | 2026-10-02 | 20% to 70%, 70% from hot reload, static mutants |
| 22 | `@stryker-mutator/vitest-runner` 10.0.0, `src/vitest-test-runner.ts`, and StrykerJS issue #5928, <https://github.com/stryker-mutator/stryker-js/issues/5928> | Source code and issue thread | 2026-10-02 | One Vitest instance, coupling to Vitest's API |
| 23 | Stryker.NET, "Mutant schemata", <https://stryker-mutator.io/docs/stryker-net/technical-reference/mutant-schemata/> | Maintainers' documentation | 2026-10-02 | Compile errors rolled back, constants not mutated |
| 24 | mutflow README and `DESIGN.md`, <https://github.com/anschnapp/mutflow> | Author's documentation | 2026-10-02 | A K2 plugin, a JUnit extension, two compilations |
| 25 | Arcmutate Kotlin support, <https://docs.arcmutate.com/docs/kotlin.html>, and pitest-kotlin, <https://github.com/pitest/pitest-kotlin> | Vendor documentation and maintainer's note | 2026-10-02 | Junk-mutation filtering, a commercial licence, the open plugin unmaintained |
| 26 | MutKt README, <https://github.com/rodrigotimoteo/mutkt>, and JAllele README, <https://github.com/gliptak/jallele> | Authors' documentation | 2026-10-02 | JVM tools that run from the test runner |
| 27 | mutineer README, <https://github.com/mutineerjs/mutineer>, and Vitest's plugin API, <https://vitest.dev/api/advanced/plugin> | Author's and maintainers' documentation | 2026-10-02 | A file swap per mutant, `configureVitest` since 3.1 |
| 28 | `go help build`, Go 1.27.1 | Toolchain documentation | 2026-10-02 | The `-overlay` flag |
| 29 | Our measurement: `~/.cache/assert-spec-mutation/gomut`, run with `run-mode.sh`, compared with `compare.py`, logs `final-*.log` and `humanize-single.log` | Own measurement | 2026-10-02 | The Go table and the build-cache growth |
| 30 | Our run of the library form: `gomut.Check` from `TestMutation` in `~/.cache/assert-spec-mutation/targets/humanize-library`, log `library-demo.log` | Own measurement | 2026-10-02 | Both properties from `go test`, the raised go line |
| 31 | Our measurement: `overhead.sh`, logs `overhead-decimal.log` and `overhead-btree.log` | Own measurement | 2026-10-02 | 1.1% and 5.9% with no mutant active |
| 32 | Our probe: a `go 1.10` module with a `//go:build go1.18` file, `~/.cache/assert-spec-mutation/langprobe` | Own measurement | 2026-10-02 | A build line raises one file's language version |
| 33 | GitHub repository metadata for the tools above | Registry metadata | 2026-10-02 | Stars and last push dates |

## What we searched

| Search | Tool | Date | Useful |
|---|---|---|---|
| Go mutation testing as a library run from `go test` | Web search | 2026-10-02 | Yes: ooze, mutest, gooze, mutate4go |
| Mutant schemata in Go, compile once and switch by environment variable | Web search | 2026-10-02 | Yes: mutest, kanly, gomutants |
| StrykerJS mutation switching and hot reload | Web search | 2026-10-02 | Yes |
| mutmut 3 trampolines and its fork per mutant | Web search, then the source | 2026-10-02 | Yes |
| Rust meta-mutants, mutest-rs and cargo-mutants' design | Web search, then the paper and the documentation | 2026-10-02 | Yes |
| `mutant schemata`, `meta-mutant`, `mutation switching`, `split-stream` | arXiv | 2026-10-02 | AccMut and Mull only |
| Conditional mutation, Major, Javalanche, PIT | Web search, then the papers | 2026-10-02 | Yes |
| A pytest plugin with mutation switching | Web search | 2026-10-02 | Yes: pytest-gremlins |
| A mutation runner that vitest drives | Web search | 2026-10-02 | No: Stryker's runner and mutineer only |
| A Kotlin compiler plugin with mutant schemata | Web search | 2026-10-02 | Yes: mutflow |
| A JUnit extension that runs mutants inside the test JVM | Web search | 2026-10-02 | Only MutKt and JAllele |
| Mull and LLVM-level schemata | Web search | 2026-10-02 | Yes: one binary with every mutant behind a flag, for C and C++ |
| The survey's "3 seconds" per compile, and its reference | The survey's PDF, converted to text | 2026-10-02 | Yes: the trivial compiler equivalence study |
