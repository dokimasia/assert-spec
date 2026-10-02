---
research: 0005
title: Which scheduling and fault-injection strategies have measured results for finding concurrency and distribution bugs, and how large must a test be?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-10-02
updated: 2026-10-02
freshest-source: 2024-12-23
supersedes: none
superseded-by: none
---

# Research-0005: Which scheduling and fault-injection strategies have measured results for finding concurrency and distribution bugs, and how large must a test be?

## The question

A deterministic simulation takes every decision from the test case: which
task runs next, which message is lost, which node crashes, and how far the
clock moves. The property engine then shrinks a failing run like any other
case. The definition leaves these choices open:

- How the scheduler chooses the next task. Uniform random choice, a
  priority scheme or a partial-order-aware scheme each find a different
  share of bugs per run.
- How large a run needs to be: how many concurrent clients, nodes, faults
  and input events a bug needs.
- How faults are chosen, and whether random faults find bugs at all.

The question is which of these choices has measured evidence, and what the
measurements show.

### What would count as an answer

- A comparison of scheduling strategies on a named benchmark, with the
  number of bugs each found or the rate at which it found them.
- A study of real bugs that counts the threads, nodes, faults or events
  each needed.
- An industrial report of bugs found by simulation or systematic testing,
  with the method stated.

### What sources are admissible

Peer-reviewed papers and the industrial reports published at peer-reviewed
venues. A system's own documentation about its testing. Maintainers'
reports for a test framework.

### What would change the answer

- A benchmark on which uniform random scheduling finds more bugs than the
  priority schemes.
- A bug study showing that most distribution bugs need more than three
  nodes or more than three faults.

## The answer

Uniform random scheduling is a sound baseline and not the best strategy.
On SCTBench's 49 buggy programs, PCT with three priority change points
found 48 bugs and controlled random scheduling 43. A partial-order-aware
sampler found bugs 2.6 times as often as PCT and 4.7 times as often as a
random walk, by geometric mean. A reads-from-guided fuzzer found more again.
Both of these schemes need to observe which events conflict, which the
standard's scheduler does not observe.

Small runs suffice. Of 105 concurrency bugs in one study, 101 involve two
threads or fewer. Of 198 distributed-system failures in another, 98%
manifest on three nodes or fewer, and 90% need three input events or
fewer. Of 103 crash recovery bugs in a third, 99% need three crashes or
fewer. Random network partitions with k of 2 or 3 cover the partition
patterns of every Jepsen bug in one study.

Industrial systems that adopted deterministic simulation or systematic
testing report bugs that stress testing missed for months, found in small
configurations with full traces.

## Findings

### Priority schemes find more bugs than a random walk, and partial-order schemes more again

Burckhardt, Kothari, Musuvathi and Nagarakatte (ASPLOS 2010) define PCT. It
assigns random priorities to threads, runs the highest-priority runnable
thread, and changes priorities at d − 1 random steps. For a program with n
threads and k steps, one run finds a bug of depth d with probability at
least 1/(n·k^(d−1)).

Thomson, Donaldson and Betts (TOPC 2016) applied five controlled
schedulers to the 49 programs of SCTBench with a limit of 100,000
schedules:

| Strategy | Bugs found of 49 |
|---|---|
| PCT, d = 3 | 48 |
| Iterative delay bounding | 45 |
| Controlled random scheduling | 43 |
| Iterative preemption bounding | 38 |
| Depth-first search | 33 |

They expected random scheduling to be ineffective, and found it
comparable to delay bounding. They advise that future work compare against
it.

Yuan, Yang and Gu (CAV 2018) define partial-order sampling, POS, which
reassigns a random priority to every event that races with the event just
executed. On SCTBench, its geometric-mean bug hit ratio was about 2.6 times
PCT's and 4.7 times a random walk's. It was best on 20 of 32 non-trivial
bugs, PCT variants on 10 and the random walk on 3. POS hit every bug, every
PCT variant missed one, and the random walk missed three.

Wolff et al. (ASPLOS 2024) guide a random scheduler by the reads-from
relation. Over 20 trials on 49 programs from SCTBench and ConVul, it found
bugs in 46.1 programs on average, PERIOD in 44.6 and PCT in about 37.

Deligiannis et al. (FAST 2016) tested Microsoft's MigratingTable with P#.
The random scheduler found 7 of its 11 bugs. The remaining 4 needed the
priority-based scheduler, together with test cases written for them.

**What we concluded:** a scheduler should offer a priority scheme beside
uniform choice. POS and the reads-from scheme need a conflict relation
between events. A simulation step of the standard is an action chosen from
a list, and no conflict relation between actions is declared.

### Real bugs need few threads, nodes, inputs and faults

Lu et al. (ASPLOS 2008) examined 105 concurrency bugs. 101 involve no more
than two threads, and 92% manifest when the order among at most four
memory accesses is enforced.

Yuan et al. (OSDI 2014) examined 198 user-reported failures of Cassandra,
HBase, HDFS, Hadoop MapReduce and Redis:

- 98% manifest on no more than three nodes, and 84% on no more than two.
- 77% need more than one input event, and 90% need no more than three.
- The order of the events matters in 88% of the failures that need more
  than one.
- 26% are not deterministic given the right inputs.
- 92% of the catastrophic failures come from incorrect handling of a
  non-fatal error that the software signalled.

Gao et al. (ESEC/FSE 2018) examined 103 crash recovery bugs of ZooKeeper,
Hadoop MapReduce, Cassandra and HBase. 97% involve four nodes or fewer, and
85% three or fewer. 99% are triggered by no more than three crashes, and
87% by no more than three crashes and one reboot. 92% need no more than
three client requests. The timing of a crash or a reboot matters.

**What we concluded:** a simulation of two or three clients and three
nodes, with up to three crashes, covers the bugs these studies counted.

### Random partitions are effective, and the reason is combinatorial

Majumdar and Niksic (POPL 2018) define coverage notions for network
partitions, such as splitting every k processes into different blocks. For
the Jepsen bugs they studied, k of 2 and 3 sufficed for splitting
coverage, and k and l up to 3 for separating coverage. They prove a lower
bound, independent of the number of processes, on the probability that a
random partition covers a goal. A small set of random tests then covers
every goal with high probability.

**What we concluded:** random fault choices, taken from the test case, are
a defensible default for partitions.

### Deterministic simulation and systematic testing find bugs that stress testing misses

FoundationDB's paper (SIGMOD 2021, §4) describes a deterministic
discrete-event simulation of the real database code. Network, disk, time
and the random number generator are abstracted. The simulator injects
machine, rack and data-centre failures, partitions and disk corruption,
and the code injects unusual but legal behaviour at chosen points. Swarm
testing varies the cluster, the workloads, the faults and the enabled
injection points per run. Checks include invariants in the workload's data
and recovery after the simulated environment returns to a recoverable
state. FoundationDB's documentation estimates about one trillion CPU-hours
of simulation.

Bornholt et al. (SOSP 2021) report on ShardStore, an Amazon S3 storage
node of over 40,000 lines of Rust. Executable reference models made up 1%
of the code, and the checks and harnesses 12%. Property-based testing
checked functional correctness and crash consistency, and stateless model
checking checked linearizability against the reference model. The checks
found 16 issues before they went into production. Automated test-case
minimization aided the diagnosis.

Deligiannis et al. (FAST 2016) report a liveness bug in Azure Storage vNext
that "only intermittently manifested during stress testing for months
without being fixed". P# found it in a small setting with a full trace.

**What we concluded:** the industrial reports agree on three mechanisms: a
reference model, every source of nondeterminism under the test's control,
and a small configuration that a minimizer reduces further.

### Real-thread tests repeat a run because they cannot replay it

OCaml's Lin and STM libraries run each parallel test instance repeatedly
and fail when one repetition fails, because "CPU scheduling and garbage
collection may hinder reproducibility" (multicoretests README). The
maintainers report hidden state, such as garbage collection, making Lin's
reconciliation of one parallel run with sequential runs give false alarms
(Tarides, 2024-12-23). Lowe (2017, §8) found one bug faster on a busy
machine than on a quiet one.

**What we concluded:** a test on real threads needs a repetition rule for
its failing case and its shrink candidates. No source measures the number
of repetitions.

## What we could not establish

- **Whether PCT finds more bugs than uniform choice when the schedulable units are
  actions instead of memory accesses.** Every comparison above schedules
  threads at shared-memory accesses or synchronization points.
- **A measured number of repetitions for a real-thread test.** The OCaml
  libraries offer a repetition combinator and a retry setting without
  publishing the effect of either.
- **TaxDC's counts.** We read its abstract only: 104 distributed concurrency
  bugs from Cassandra, Hadoop MapReduce, HBase and ZooKeeper, with 2,083
  classification labels.

## What would change this answer

- A comparison of PCT and uniform choice over simulated actions, run with
  the conformance subjects of the machine proposal.
- A bug study of distributed systems in which most bugs need four or more
  nodes.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | Burckhardt, Kothari, Musuvathi and Nagarakatte, "A randomized scheduler with probabilistic guarantees of finding bugs", ASPLOS 2010, <https://doi.org/10.1145/1735970.1736040> | Peer-reviewed paper, §1–§2 | 2026-10-02 | PCT and its bound |
| 2 | Thomson, Donaldson and Betts, "Concurrency testing using controlled schedulers: an empirical study", TOPC 2016, <https://www.doc.ic.ac.uk/~afd/papers/2016/TOPC.pdf> | Peer-reviewed paper | 2026-10-02 | The SCTBench comparison |
| 3 | Yuan, Yang and Gu, "Partial order aware concurrency sampling", CAV 2018, <https://www.cs.columbia.edu/~junfeng/papers/pos-cav18.pdf> | Peer-reviewed paper, §6 | 2026-10-02 | POS against PCT and random walk |
| 4 | Wolff, Shi, Duck, Mathur and Roychoudhury, "Greybox fuzzing for concurrency testing", ASPLOS 2024, <https://doi.org/10.1145/3620665.3640389> | Peer-reviewed paper, §5 | 2026-10-02 | Reads-from fuzzing against PERIOD and PCT |
| 5 | Deligiannis et al., "Uncovering bugs in distributed storage systems during testing (not in production!)", FAST 2016, <https://www.usenix.org/conference/fast16/technical-sessions/presentation/deligiannis> | Peer-reviewed industrial paper | 2026-10-02 | Random and priority schedulers on MigratingTable; the vNext liveness bug |
| 6 | Lu, Park, Seo and Zhou, "Learning from mistakes", ASPLOS 2008, <https://doi.org/10.1145/1346281.1346323> | Peer-reviewed bug study | 2026-10-02 | Threads and accesses per bug |
| 7 | Yuan et al., "Simple testing can prevent most critical failures", OSDI 2014, <https://www.usenix.org/system/files/conference/osdi14/osdi14-paper-yuan.pdf> | Peer-reviewed failure study | 2026-10-02 | Nodes, input events, order, error handling |
| 8 | Gao et al., "An empirical study on crash recovery bugs in large-scale distributed systems", ESEC/FSE 2018, <https://doi.org/10.1145/3236024.3236030> | Peer-reviewed bug study | 2026-10-02 | Nodes, crashes, reboots and requests per bug |
| 9 | Majumdar and Niksic, "Why is random testing effective for partition tolerance bugs?", POPL 2018, <https://doi.org/10.1145/3158134> | Peer-reviewed paper | 2026-10-02 | Partition coverage and its probability bound |
| 10 | Zhou et al., "FoundationDB: a distributed unbundled transactional key value store", SIGMOD 2021, <https://www.foundationdb.org/files/fdb-paper.pdf>, and "Simulation and testing", FoundationDB 7.4.7 documentation | Peer-reviewed industrial paper and the project's documentation | 2026-10-02 | The simulator, its faults, swarm testing, the CPU-hour estimate |
| 11 | Bornholt et al., "Using lightweight formal methods to validate a key-value storage node in Amazon S3", SOSP 2021, <https://doi.org/10.1145/3477132.3483540> | Peer-reviewed industrial paper | 2026-10-02 | Reference models, 16 issues, minimization |
| 12 | OCaml multicoretests README, <https://github.com/ocaml-multicore/multicoretests>, and Tarides, "Multicore property-based tests for OCaml 5: challenges and lessons learned", 2024-12-23 | Maintainers' documentation and report | 2026-10-02 | Repetition, hidden state |
| 13 | Lowe, "Testing for linearizability", Concurrency and Computation: Practice and Experience, 2017 | Peer-reviewed paper, §8 | 2026-10-02 | A busy machine finds a bug faster |
| 14 | Leesatapornwongsa, Lukman, Lu and Gunawi, "TaxDC", ASPLOS 2016, <https://doi.org/10.1145/2872362.2872374> | Peer-reviewed bug study, abstract | 2026-10-02 | The study's scope |

## What we searched

| Search | Tool | Date | Useful |
|---|---|---|---|
| PCT, probabilistic guarantees, bug depth | Web search | 2026-10-02 | Yes |
| Controlled schedulers, empirical study, SCTBench | Web search | 2026-10-02 | Yes |
| Partial order aware concurrency sampling | Web search | 2026-10-02 | Yes |
| Greybox fuzzing for concurrency testing, reads-from | Web search | 2026-10-02 | Yes |
| P#, Azure storage, testing not in production | Web search | 2026-10-02 | Yes |
| Real-world concurrency bug characteristics | Web search | 2026-10-02 | Yes |
| Simple testing can prevent most critical failures | Web search | 2026-10-02 | Yes |
| Crash recovery bugs in distributed systems | Web search | 2026-10-02 | Yes |
| TaxDC, distributed concurrency bugs | Web search | 2026-10-02 | Abstract only |
| Random testing, partition tolerance bugs | Web search | 2026-10-02 | Yes |
| FoundationDB simulation testing | Web search | 2026-10-02 | Yes |
| ShardStore, lightweight formal methods | Web search | 2026-10-02 | Yes |
| multicoretests lessons learned, repetition | Web fetch | 2026-10-02 | Yes, without numbers |
