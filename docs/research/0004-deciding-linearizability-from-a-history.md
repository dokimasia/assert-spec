---
research: 0004
title: What decides whether a linearizability check of a recorded history finishes, reports only real violations, and explains the ones it finds?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-10-02
updated: 2026-10-02
freshest-source: 2026-10-02
supersedes: none
superseded-by: none
---

# Research-0004: What decides whether a linearizability check of a recorded history finishes, reports only real violations, and explains the ones it finds?

## The question

A linearizability check takes a history of concurrent calls and a
sequential model, and searches for an order of the calls that the model
accepts and that keeps real-time order. The standard would specify such a
check once and implement it in five languages. Three properties decide
whether the check is worth having:

- **It finishes.** The problem is NP-complete in general. A check that
  runs for hours on a test's history is not a check a suite can run.
- **It reports only real violations.** A false violation sends an
  engineer after a bug that does not exist. Its sources are the history,
  the treatment of calls that never returned, and the model's equality.
- **It explains a violation.** "Not linearizable" over a thousand calls
  leaves the engineer to find the problem by hand.

For each property, the question is which choices of algorithm, recording
and workload decide it, and whether anyone has measured them.

### What would count as an answer

- For cost: a published measurement of a search algorithm on histories of
  stated size and concurrency, or our own measurement with the method
  stated.
- For false violations: a definition that settles a case, or a reported
  false violation with its cause.
- For explanations: a checker's documented output, or a demonstration
  that a proposed explanation is unsound.

### What sources are admissible

Peer-reviewed papers and their artefacts. A tool's own source and
documentation at a named version. Issue threads in which a maintainer
reports a reproduced fault. Our own measurements, with the method.

### What would change the answer

- A measurement showing that a tree search without memoisation finishes
  as reliably as a graph search. The recommended algorithm would change.
- A recording method that is both free of false precedence and free of
  added synchronization. The trade-off in the recorder finding would go
  away.
- An explanation that shrinks the history itself and is still sound.

## The answer

A check finishes when the search memoises on the set of linearized calls
and the model state, partitions the history into independent keys, and
runs on histories with few concurrent clients and frequent reads. Lowe
bounds his just-in-time graph search on a register by a number linear in
the history's length and exponential in its concurrency. Queues are the
exception. Their generic search is exponential in the queue's length when
clients enqueue concurrently. A step budget then turns a search that
cannot finish into a reported outcome instead of a hang.

A check reports only real violations when three conditions are met. The
history orders a call before another only when the first one finished
before the second one started. A call that never returned may take effect
at any point after its start, or never. The memo treats two model states
as equal only when they are interchangeable. Each condition has a
documented failure in a published tool or paper.

A check explains a violation by reporting where its search stopped: the
longest order it built, the model state there, and why each remaining call
could not come next. Shrinking the history to a smaller violated history
is unsound, because a sub-history of a linearizable history can itself be
violated. A small counterexample comes from shrinking the test that
produced the history.

## Findings

### The general problem is NP-complete, and three special cases are polynomial

Gibbons and Korach proved that deciding linearizability of one history is
NP-complete. Lowe (2017, §1) and Fan and Golab (2018) both report from it
that a register history with a fixed number of processes, in which each
read maps to one write, is decidable in O(n log n).

Emmi and Enea (POPL 2018, Theorem 3.13) proved that linearizability is
decidable in polynomial time for unambiguous histories of collection types,
which they show to include stacks, queues, sets and maps. A history is
unambiguous when at most one operation adds each value.

Lowe (2017, §4) bounds his just-in-time graph search for a register at
(N + 1) · 2^p · (p + 1) configurations, for a history of length N over p
threads. The search is linear in N and exponential in p. For a map with K
keys the bound is (N + 1) · 2^p · K^(p+1). For a queue, p threads that
enqueue distinct values concurrently can be linearized in p factorial
orders, and after m enqueues the queue can be in at least (p factorial)^(m/p)
states.

**What we concluded:** the length of a test's history matters less than
its concurrency and its data type. A register or a map partitioned by key
checks in linear time at a fixed number of clients. A queue does not.

### Graph search with memoisation is reliable, and tree search is not

Lowe (2017, §6) ran 50 single runs of each tree search on a map, with 2^8
operations per worker and a limit of ten billion configurations. The Wing
and Gong tree search finished within 30 ms on 43 runs and did not finish on
5, each of which ran for about 25 minutes. The just-in-time tree search
did not finish on 1 run of 50, after about 14 minutes. The graph searches,
which store visited configurations, did not show this behaviour. A tree
search and a graph search run in competition were slightly faster than
either alone, and need two specifications from the user: an immutable one
and an undoable one.

On queues, every generic algorithm stopped at its iteration limit at an
enqueue probability of about 0.4, with four workers of 2^11 operations
each. Lowe's queue-specific algorithm finished those histories, and needed
backtracking about once in 9,000 runs of 800 operations.

Horn and Kroening (FORTE 2015, §5) partitioned set histories by key before
the same graph search. On about 700 histories from four threads of 70,000
operations each, the partitioned search was three times faster on average
and used an order of magnitude less memory. On Intel TBB's concurrent set
it took 6 s and 672 MiB against 101 s and 9,792 MiB. The Wing and Gong
search without Lowe's memo "times out on the majority of benchmarks".

Porcupine v1.3.1 implements Horn and Kroening's partitioned search: Wing
and Gong's search over the calls that precede the first unmatched return,
with Lowe's memo of configurations (`checker.go`, lines 256–333). Its memo
key is the set of linearized calls and the model state. It bounds a search
only by wall time, and its documentation lets a caller read a timeout as a
pass (`model.go`, lines 359–366). Lowe's just-in-time graph search is a
different candidate rule, which he measured as faster on queues and as
similar on maps, with an advantage on longer map histories.

**What we concluded:** the search to specify is a memoised graph search
over partitions. A tree search would make an outcome depend on luck.
Competition between two searches would make it depend on timing.

### Porcupine's own histories spread over five orders of magnitude at one size

We added a counter of model steps to a copy of Porcupine v1.3.1's checker
and ran its 108 test histories: 6 key-value histories and 102 etcd
histories. Each etcd history is one register with 73 to 90 reads, writes
and compare-and-set calls. Jepsen starts a new process after each timeout,
so the three histories we counted have 19 to 23 process identities and 15
to 19 calls whose outcome is unknown.

| Steps in a history's most expensive partition | Value |
|---|---|
| Median | 272.5 |
| 90th percentile | 21,128 |
| Maximum | 1,177,310, `etcd_002`, 77 operations, 69 ms |
| Histories above 100,000 steps | 6 |
| Etcd histories, minimum and maximum | 37 and 1,177,310 |
| Largest memo | 179,127 configurations |

Porcupine issue #6 reports the same spread on a bank workload. The
maintainer found that 251 lines of the history checked in 100 ms and that
252 lines did not finish within "several minutes", and attributed it to
reads that occurred rarely. Kyle Kingsbury replied in the thread that
checking "is still O(c!) with respect to concurrency" in Knossos, and
advised partitioning in time and across objects and reading often.

**What we concluded:** histories of one length differ in cost by five
orders of magnitude, so a check counts its budget in steps. One history
then gives one outcome on every machine, which a wall-clock limit cannot
give.

### Synthetic histories confirm the bounds: registers grow linearly, queues with their length

We generated linearizable histories and checked them with the same
instrumented copy of Porcupine's search. Each client runs its calls one
after another. A call takes effect 1 to 20 time units after its
invocation and returns 1 to 20 units after that. The outputs come from
applying the calls, in the order they took effect, to a sequential
register or queue. Every written value is unique. Each row is 10 seeds,
and `p` is the share of calls that write or enqueue.

Registers, where every history finished under the cap of 10,000,000 steps:

| Clients | Calls | Median steps at p = 0.3 | p = 0.5 | p = 0.7 |
|---|---|---|---|---|
| 2 | 1,024 | 1,176 | 1,231 | 1,231 |
| 4 | 2,048 | 4,711 | 6,088 | 6,058 |
| 8 | 4,096 | 159,222 | 258,469 | 319,099 |

The steps per call change little as a history grows at a fixed number of
clients. On the longest histories they are about 1.2 at two clients, 2.3
to 3 at four and 39 to 78 at eight.

Queues, with a cap of 1,000,000 steps:

| Clients | Calls | p = 0.3 | p = 0.5 | p = 0.7 |
|---|---|---|---|---|
| 2 | 16 | 17 | 18 | 24, at most 262 |
| 2 | 64 | 71 | 112 | 890, at most 238,002 |
| 2 | 256 | 290 | 1,112, at most 17,685 | All 10 above the cap |
| 2 | 1,024 | 1,153 | 27,259, and 2 of 10 above the cap | Not run |
| 4 | 128 | 181 | 1,933, at most 177,411 | All 10 above the cap |
| 4 | 512 | 795 | 4 of 10 above the cap | Not run |
| 8 | 256 | 646 | 7 of 10 above the cap | Not run |

A row is not run once at least half the histories of a shorter row of the
same shape used the whole cap. At 8 clients and p = 0.7, 8 of 10 histories
of 64 calls used the whole cap.

When dequeues outnumber enqueues, the queue is short and its check is
linear in the history's length. A queue that grows leaves concurrent enqueues
unordered until a dequeue orders them, as Lowe's analysis predicts, and
two clients are enough for the cost to pass a million steps at 256 calls.

Without a hash of the state, every state of one set of linearized calls
shares one bucket of Porcupine's memo, and each step scans the bucket. A
run of the queue table without a hash was stopped after ten minutes on one
row. With a hash, the whole table took 8.4 seconds. The step counts do not
depend on the hash, and the time does.

**What we concluded:** a generated concurrent test bounds the cost of a
queue check by bounding the calls that run concurrently. At 16 calls, two
clients needed at most 262 steps in every queue history we generated.

### A synchronizing recorder hides bugs, and a clock-based recorder invents them

Lowe (2017, §7.1) first logged calls through a shared log in which each
thread claimed a slot with a synchronization event. That synchronization
"masked the lack of synchronization in the datatype", and memory
consistency bugs went unfound. He moved to a private log per thread with
`System.nanoTime` timestamps, merged by time. With that recorder, a test of
an unsynchronized shared variable found the bug in 679 ± 26 ms. He states
that the approach requires the timestamps to be accurate and "may work less
well on other machines".

In Porcupine issue #40, the maintainer reproduced the opposite failure on
an Apple M3 Pro. A timestamp taken before an atomic load was reordered
after it, so a read appeared to start after a write it had not observed.
The anomaly did not occur on amd64 or under Rosetta 2. The maintainer
found nothing in Go's memory model that orders `time.Now()` with memory
operations, and added a note to the README in commit `b6694c6`.

**What we concluded:** no recording method is both free of false precedence
and free of added synchronization. A counter that every client increments
atomically never reports a precedence that did not happen, and it can hide
a missing barrier in the subject. Clock timestamps can expose that barrier,
and they can produce a false violation.

### The definition of linearizability settles calls that never returned

Herlihy and Wing (1990, §2) call a history linearizable when it can be
extended, by appending zero or more responses to pending invocations, to a
history H' whose complete(H') is equivalent to a legal sequential history
that keeps the real-time order of H. A pending call either takes effect at
some point after its invocation or does not take effect at all.

Knossos records each completion as `ok`, `fail` for a call that did not
take place, or `info` for a call whose outcome is unknown. A process whose
call timed out is crashed and performs no further operation. Porcupine has
no such concept. Its etcd tests append the return of an unanswered call at
the end of the history and make the model accept an `unknown` output
(`porcupine_test.go`, lines 236–255 and 367–381).

**What we concluded:** three completions cover the cases the definition
distinguishes: the call took effect, took no effect, or has an unknown
outcome. A call with an unknown outcome completes after the last event
with an absent output, and its client continues under a new identity,
which keeps each process sequential.

### A smaller violated sub-history is not an explanation

We ran three histories through Porcupine v1.3.1, with a register that
starts at 0:

| History | Verdict |
|---|---|
| `put(1)` over [0, 10], `get → 1` over [5, 15], `get → 0` over [20, 30] | `Illegal` |
| `get → 1` over [5, 15] alone | `Illegal` |
| `put(1)` over [0, 10], then `get → 1` over [20, 30] | `Ok` |
| `get → 1` over [20, 30] alone | `Illegal` |

Linearizability is not closed under sub-histories. A search for the
smallest violated sub-history of the first history returns `get → 1`
alone, which is violated because nothing wrote 1. The first history is
violated because `get → 0` follows a completed `put(1)`.

Knossos reports the frontier of its search instead: `:op`, the first
operation it could not linearize, `:previous-ok`, the last operation it
could, and `:final-paths`, the orders it tried with the model's message
for each failure. Porcupine reports, for each call, the longest
linearizable prefix that contains it, and renders them as HTML.

Two test frameworks shrink the test instead of the history. Quviq's
`eqc_par_statem` deletes commands and moves commands from a parallel branch
into the sequential prefix, so that the counterexample is "minimally
parallel" (Claessen et al., ICFP 2009, §4.3). Lincheck removes operations
from the scenario greedily until the test stops failing (Koval et al., CAV
2023, §2).

**What we concluded:** the checker states its frontier, and the property
engine shrinks the workload and the schedule that produced the history.

### One model is enough for the sequential and the parallel test

Quviq's `eqc_par_statem` takes the same state machine as `eqc_statem` and
searches the interleavings with its `next_state` and `postcondition`.
Claessen et al. (ICFP 2009, §4) report that this tests for race conditions
"with no further investment in developing a parallel specification". Their parallel test is a sequential prefix followed by two
parallel branches. They cap the parallel part at 16 commands, about 10,000
interleavings in the worst case, and require every precondition to be true
in every interleaving. Memoising the search on the remaining branches and the
model state gave a speed-up of about 20%.

OCaml's STM library (Midtgaard et al., OCaml Workshop 2022) checks a
sequential prefix and two parallel domains against a model with
`next_state`, `precond`, `postcond` and `run`. Lincheck builds a labelled
transition system from the data structure itself, or from a sequential
specification class when the user supplies one.

**What we concluded:** a model that steps purely, with a state the search
can copy and compare, serves the sequential test and the concurrent one.
A model that is code inside an action's body serves only the first.

### A model built from the subject finds real bugs and fails on hidden state

Line-Up (Burckhardt et al., PLDI 2010) checks deterministic
linearizability with no specification: it enumerates the sequential
behaviours of the component itself. On 13 classes with 90 methods of the
.NET Framework 4.0, its reports exposed seven errors that the development
team fixed. Lowe (2017, §1) reports that Line-Up took "up to hundreds of
minutes to find each bug" with three threads of three operations.

OCaml's Lin library reconciles a parallel run with sequential runs of the
same implementation. The multicoretests team abandoned Lin tests of
`Ephemeron`, because garbage collection changed the results between the
parallel observation and the sequential ones, and replaced them with STM
tests against a model (Tarides, 2024-12-23).

**What we concluded:** a model built from the subject checks atomicity only,
and only for a subject whose sequential behaviour is deterministic.

### Two clients find most concurrency bugs, and more workers help only without a controlled scheduler

Lu et al. (ASPLOS 2008) examined 105 concurrency bugs from MySQL, Apache,
Mozilla and OpenOffice. 101 involve no more than two threads. 96% manifest
when a particular order between two threads is enforced. 92% manifest when
the order among at most four memory accesses is enforced.

Lowe (2017, §8) found one five-operation hash-map bug fastest with five or
six workers on a busy machine, and with six to eight on a quiet one. Fewer
workers produced less concurrency and less erratic scheduling.

Ozkan, Majumdar and Niksic (PPoPP 2019) checked 8,673 linearizable
histories from stress tests of `java.util.concurrent`. Schedules that order
at most five operations in a chosen way witnessed 99.9% of them, and at most
two witnessed 93.3%.

**What we concluded:** the sources disagree only in appearance. Lu et al.
count the threads a bug needs. Lowe counts the threads that an
uncontrolled scheduler needs to hit that order by chance. With the schedule
taken from the test's choices, two clients cover what Lu et al. found.

## What we could not establish

- **The O(n log n) bound in the original paper.** Both statements of it are
  secondary: Lowe's and Fan and Golab's. We did not obtain Gibbons and
  Korach's paper.
- **The cost of a model step in each language.** The measurements here are
  Go. A Python step can cost an order of magnitude more, and nobody has
  measured the ratio for this algorithm.
- **Defaults of Lincheck and of OCaml's STM.** We read their documentation
  and papers, not their source, and did not find a stated number of
  operations per thread.

## What would change this answer

- A measurement on generated workloads in which two clients miss a class of
  bug that three or more find under a controlled scheduler.
- A recorder that orders events without synchronizing the clients and
  without a clock that can be reordered.
- A data type outside the collection types for which the generic search
  fails at the budget on short histories.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | Herlihy and Wing, "Linearizability: a correctness condition for concurrent objects", TOPLAS 12(3), 1990, <https://www.cs.cmu.edu/~wing/publications/HerlihyWing90.pdf> | Peer-reviewed paper, §2 | 2026-10-02 | The definition, pending invocations, complete(H) |
| 2 | Lowe, "Testing for linearizability", Concurrency and Computation: Practice and Experience, 2017, <https://www.cs.ox.ac.uk/people/gavin.lowe/LinearizabiltyTesting/paper.pdf> | Peer-reviewed paper, read in full | 2026-10-02 | Search bounds, tree and graph search measurements, queues, logging, worker counts |
| 3 | Horn and Kroening, "Faster linearizability checking via P-compositionality", FORTE 2015, <https://arxiv.org/abs/1504.00204> | Peer-reviewed paper, §1 and §5 | 2026-10-02 | Partitioning speed-up and memory, Table 1 |
| 4 | Fan and Golab, "Analyzing linearizability violations in the presence of read-modify-write operations", 2018 | Paper, §1 and §2 | 2026-10-02 | The read-mapping bound, as a summary of Gibbons and Korach |
| 5 | Emmi and Enea, "Sound, complete, and tractable linearizability monitoring for concurrent collections", POPL 2018, <https://doi.org/10.1145/3158113> | Peer-reviewed paper, abstract and §1 | 2026-10-02 | Theorem 3.13, unambiguous histories |
| 6 | Porcupine v1.3.1, commit `97cd067`, <https://github.com/anishathalye/porcupine> | Source code | 2026-10-02 | The algorithm, the memo, partitions, timeouts, the etcd model |
| 7 | Porcupine issue #6, <https://github.com/anishathalye/porcupine/issues/6> | Maintainer and Knossos author in an issue thread | 2026-10-02 | 251 against 252 lines, O(c!) |
| 8 | Comments on Porcupine issue #40, <https://api.github.com/repos/anishathalye/porcupine/issues/40/comments>. The issue page itself returns 404 on the web and through the API | Maintainer's reproduction | 2026-10-02 | Reordered timestamps on arm64 |
| 9 | Knossos README, <https://github.com/jepsen-io/knossos> | Maintainer's documentation | 2026-10-02 | `ok`, `fail`, `info`, crashed processes, the report fields |
| 10 | Our measurement: a step counter in a copy of Porcupine v1.3.1, Go 1.27, four cores | Own measurement | 2026-10-02 | The 108-history table |
| 11 | Our probe: four register histories through Porcupine v1.3.1 | Own measurement | 2026-10-02 | Sub-histories are not explanations |
| 12 | Claessen, Pałka, Smallbone, Hughes, Svensson, Arts and Wiger, "Finding race conditions in Erlang with QuickCheck and PULSE", ICFP 2009 | Peer-reviewed paper, §4 | 2026-10-02 | One model for both tests, two branches, 16 commands, minimally parallel shrinking |
| 13 | Midtgaard, Nicole and Osborne, "Multicoretests: parallel testing libraries for OCaml 5.0", OCaml Workshop 2022 | Workshop paper | 2026-10-02 | Lin and STM |
| 14 | Tarides, "Multicore property-based tests for OCaml 5: challenges and lessons learned", 2024-12-23 | Maintainers' report | 2026-10-02 | Lin and hidden state |
| 15 | Koval et al., "Lincheck: a practical framework for testing concurrent data structures on JVM", CAV 2023 | Peer-reviewed paper | 2026-10-02 | Model checking, transition systems from the subject, greedy minimization |
| 16 | Burckhardt, Dern, Musuvathi and Tan, "Line-Up: a complete and automatic linearizability checker", PLDI 2010, <https://doi.org/10.1145/1809028.1806634> | Peer-reviewed paper, abstract | 2026-10-02 | Seven errors in .NET 4.0 |
| 17 | Lu, Park, Seo and Zhou, "Learning from mistakes", ASPLOS 2008, <https://doi.org/10.1145/1346281.1346323> | Peer-reviewed paper | 2026-10-02 | Two threads, four accesses |
| 18 | Ozkan, Majumdar and Niksic, "Checking linearizability using hitting families", PPoPP 2019 | Peer-reviewed paper, §6 | 2026-10-02 | Linearizability depth |
| 19 | Our measurement: synthetic register and queue histories through the same copy, from a Go test | Own measurement | 2026-10-02 | The register and queue tables |

## What we searched

| Search | Tool | Date | Useful |
|---|---|---|---|
| Porcupine's source, tests, test data and history | Clone at v1.3.1 | 2026-10-02 | Yes |
| Porcupine issues #6 and #40 | GitHub CLI and REST API | 2026-10-02 | Yes |
| Knossos's README | Web fetch | 2026-10-02 | Yes |
| `1504.00204`, `2003.10554` | arXiv | 2026-10-02 | Yes |
| Lowe, "Testing for linearizability", evaluation | Web search, then the PDF | 2026-10-02 | Yes |
| Herlihy and Wing's definition with pending invocations | Web search | 2026-10-02 | Yes |
| Gibbons and Korach, read mapping, polynomial | Web search | 2026-10-02 | Secondary sources only |
| Emmi and Enea, tractable linearizability monitoring | Web search | 2026-10-02 | Yes |
| Line-Up, Lincheck, multicoretests Lin and STM | Web search | 2026-10-02 | Yes |
| Claessen et al., QuickCheck and PULSE | Web search | 2026-10-02 | Yes |
| Lu et al., real-world concurrency bug characteristics | Web search | 2026-10-02 | Yes |
| Ozkan et al., hitting families | Web search | 2026-10-02 | Yes |
| Lincheck default thread and operation counts | Web fetch of the Kotlin guide | 2026-10-02 | No; no numbers stated |
