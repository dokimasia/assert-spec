---
research: 0006
title: Which transactional isolation levels can a checker decide from client-observed histories, at what cost, and what must the workload guarantee?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-10-02
updated: 2026-10-02
freshest-source: 2023-05-09
supersedes: none
superseded-by: none
---

# Research-0006: Which transactional isolation levels can a checker decide from client-observed histories, at what cost, and what must the workload guarantee?

## The question

Isolation levels are defined over a database's internal history: which
transaction installed which version, and in what order. A test observes
only what clients sent and received. A checker in the standard would
derive anomalies from those observations, in five languages, without a
native dependency. The question has three parts:

- Which levels can be decided from client observations, and in what time?
- What must the workload guarantee for a derived anomaly to be real?
- What do checkers that drop that guarantee cost?

### What would count as an answer

- A definition of each level in terms of observable anomalies.
- A complexity result for checking a level.
- A checker's soundness theorem with the conditions it needs, and a
  measurement of its running time.

### What sources are admissible

Peer-reviewed papers, theses, and the artefacts they describe.

### What would change the answer

- A polynomial algorithm for serializability or snapshot isolation over
  histories with blind writes.
- A demonstration that an anomaly derived from a version-revealing
  workload was not present in the database.

## The answer

Read committed, read atomic and causal consistency check in polynomial
time. Serializability, prefix consistency and snapshot isolation are
NP-complete in general, and polynomial when the number of sessions is
fixed.

A workload in which every write appends a unique element to a list, and in
which reads return the whole list, reveals the version order of every
object a read observed. Over such histories, Elle derives write, read and
anti-dependencies between transactions and finds, in linear time, the
dependency cycles that Adya's definitions forbid. It is sound: every
anomaly it reports is present in every database history consistent with
the observations.

Checkers for workloads with blind writes exist for serializability and
for snapshot isolation. They encode the search for SMT solvers. They are
sound and complete, take time that grows faster than linearly, and have
no guarantee of termination.

## Findings

### Adya defines each level by the dependency cycles it forbids

Adya, Liskov and O'Neil (ICDE 2000) build a direct serialization graph over
committed transactions, with write-dependency, read-dependency and
anti-dependency edges, and define:

| Level | Proscribes |
|---|---|
| PL-1 | G0, a cycle of write-dependency edges |
| PL-2 | G1: G1a, an aborted read; G1b, an intermediate read; and G1c, a cycle of write- and read-dependency edges |
| PL-2.99, repeatable read | G1 and G2-item, a cycle with one or more item anti-dependency edges |
| PL-3, serializable | G1 and G2, a cycle with one or more anti-dependency edges, predicate edges included |

Adya's thesis (MIT-LCS-TR-786, 1999, §4) adds PL-2+, which proscribes G1 and
G-single, a cycle with exactly one anti-dependency edge. It defines snapshot
isolation, PL-SI, as proscribing G1 and G-SI, using start-dependency edges
between transactions: "Since G-SIb is strictly stronger than G-single,
PL-SI is strictly stronger than PL-2+." Berenson et al. (SIGMOD 1995) show
that snapshot isolation permits write skew.

**What we concluded:** a client who cannot observe start times can detect
G-single. A G-single cycle proves that snapshot isolation was violated.
Its absence does not prove that the history satisfies snapshot isolation.

### Serializability and snapshot isolation are NP-complete to check, and three weaker levels are polynomial

Papadimitriou (JACM 1979) proved that deciding whether a history is
serializable is NP-complete. Biswas and Enea (OOPSLA 2019) show that read
committed, read atomic and causal consistency are checkable in polynomial
time, and that prefix consistency and snapshot isolation are NP-complete in
general. Their algorithms for the NP-complete levels are polynomial when
the number of sessions is fixed.

### A version-revealing workload makes the check sound and linear

Kingsbury and Alvaro (VLDB 2020) define two properties of a workload:

- **Recoverability.** Every value written to an object is unique, so each
  observed version maps to the one write that produced it.
- **Traceability.** Each version contains the versions before it, as a list
  with appended elements does, so a read of `[1, 2, 3]` shows that the
  object contained `[]`, `[1]`, `[1, 2]` and `[1, 2, 3]` in that order.

Blind writes to a register "destroy history": two writes of 1 and 2 leave
no evidence of their order. Over a traceable and recoverable observation,
Elle derives write-write, write-read and read-write dependencies for every
version some read observed. Theorem 1 of the paper states that a reported
cycle anomaly is present in every clean interpretation of the observation,
and that a reported aborted read, dirty update or intermediate read is
present in every interpretation. Writes that no read observed, near the end
of a history, leave part of a version order unknown. Frequent reads keep
that part small.

Elle searches for cycles with Tarjan's algorithm and a breadth-first search
within each strongly connected component, and reports the shortest cycle
it finds with an explanation of each edge. It detects G0, G1a, G1b, G1c,
G-single and G2 cycles, dirty updates, garbage reads, duplicated writes and
internal inconsistency, and cycles that include per-process and real-time
edges. It does not handle predicates.

Elle checked histories of hundreds of thousands of transactions in tens of
seconds. On the same histories, Knossos "often timed out or ran out of
memory after a few hundred transactions". A constraint-solver
serializability checker became intractable beyond "a hundred-odd
transactions". Elle found anomalies in every database the authors tested,
among them TiDB, YugaByte DB, FaunaDB and Dgraph.

**What we concluded:** the workload determines which checker fits. A test
that generates its own transactions can make them traceable and
recoverable, and then does not need a search.

### Solver-based checkers accept blind writes, at a higher cost

Tan et al. (OSDI 2020) check serializability with Cobra, which encodes the
search for the MonoSAT solver and prunes it on a GPU. It checked 10,000
transactions in 14 seconds, against at most 1,000 for the baselines in the
same time, and its authors state that there is no guarantee that it
terminates in reasonable time.

Huang et al. (VLDB 2023) check snapshot isolation with PolySI, through
generalized polygraphs and an SMT solver. PolySI reproduced all 2,477 known
snapshot isolation anomalies in its benchmark and found new violations in
three production cloud databases.

Zhang et al. (EuroSys 2023) check snapshot isolation with Viper, through
BC-polygraphs and MonoSAT. Viper checked 400 transactions in 0.04 seconds,
where the next-best checker took 115.98 seconds, and 10,000 transactions in
439.7 seconds. Its authors attribute the super-linear growth to the problem
being NP-complete. They note that Elle "requires atomic update operations
that reveal write order".

**What we concluded:** a solver-based checker would add an SMT solver to
the test dependencies of five languages and would make a check's running
time unpredictable. A generated workload does not need it.

## What we could not establish

- **Whether Elle's derivation finds every anomaly that a complete checker
  finds on the same traceable history.** Elle's paper proves soundness. It
  does not claim completeness, and we did not find a measurement of the
  gap.
- **The cost of Elle's approach in each target language.** All the
  measurements are of the Clojure implementation.

## What would change this answer

- A polynomial checker for snapshot isolation or serializability over
  histories with blind writes.
- A measured case in which Elle's derivation misses an anomaly that a
  complete checker reports on the same traceable history.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | Adya, Liskov and O'Neil, "Generalized isolation level definitions", ICDE 2000, <https://www.cs.cmu.edu/~15721-f24/papers/Generalized_Isolation_Levels_Definitions.pdf> | Peer-reviewed paper, §4–§5 | 2026-10-02 | G0, G1a, G1b, G1c, G2-item, G2 and the PL levels |
| 2 | Adya, "Weak consistency: a generalized theory and optimistic implementations for distributed transactions", MIT-LCS-TR-786, 1999, <https://publications.csail.mit.edu/lcs/pubs/pdf/MIT-LCS-TR-786.pdf> | Doctoral thesis, §4 | 2026-10-02 | G-single, PL-2+, PL-SI, G-SIa, G-SIb |
| 3 | Berenson, Bernstein, Gray, Melton, O'Neil and O'Neil, "A critique of ANSI SQL isolation levels", SIGMOD 1995, <https://doi.org/10.1145/568271.223785> | Peer-reviewed paper, as Research-0002 read it | 2026-08-30 | Write skew under snapshot isolation |
| 4 | Papadimitriou, "The serializability of concurrent database updates", JACM 1979, <https://doi.org/10.1145/322154.322158> | Peer-reviewed paper, as Research-0002 read it | 2026-08-30 | Serializability is NP-complete |
| 5 | Biswas and Enea, "On the complexity of checking transactional consistency", OOPSLA 2019, <https://arxiv.org/abs/1908.04509> | Peer-reviewed paper, abstract | 2026-10-02 | Which levels are polynomial |
| 6 | Kingsbury and Alvaro, "Elle: inferring isolation anomalies from experimental observations", VLDB 2020, <https://arxiv.org/abs/2003.10554> | Peer-reviewed paper, §2–§7 | 2026-10-02 | Recoverability, traceability, Theorem 1, the cycle search, performance, case studies |
| 7 | Tan, Zhao, Mu and Walfish, "Cobra: making transactional key-value stores verifiably serializable", OSDI 2020, <https://www.usenix.org/system/files/osdi20-tan.pdf> | Peer-reviewed paper, §1 | 2026-10-02 | Solver-based serializability, 10,000 transactions in 14 s |
| 8 | Huang et al., "Efficient black-box checking of snapshot isolation in databases", VLDB 2023, <https://arxiv.org/abs/2301.07313> | Peer-reviewed paper, abstract | 2026-10-02 | PolySI's results |
| 9 | Zhang, Ji, Mu and Tan, "Viper: a fast snapshot isolation checker", EuroSys 2023, <https://doi.org/10.1145/3552326.3567492> | Peer-reviewed paper, §1, §2.3, §7 | 2026-10-02 | Viper's results, the comparison with Elle |

## What we searched

| Search | Tool | Date | Useful |
|---|---|---|---|
| `2003.10554`, Elle, for Knossos, recoverability, G-single and indeterminate | arXiv and its text search | 2026-10-02 | Yes |
| `1908.04509`, `2301.07313` | arXiv | 2026-10-02 | Yes, abstracts |
| Adya, generalized isolation level definitions, PL levels | Web search, then the PDF | 2026-10-02 | Yes |
| Adya's thesis, PL-SI, G-single | Web search, then the PDF | 2026-10-02 | Yes |
| Cobra, verifiably serializable | Web search | 2026-10-02 | Yes |
| Viper, fast snapshot isolation checker | Web search | 2026-10-02 | Yes |
