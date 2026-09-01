---
rfc: 0004
title: The history checker
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-30
updated: 2026-09-01
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0004: The history checker

## Summary

A recorded history answers whether one client's reads went backwards by
scanning it. It cannot answer whether a run was linearizable or
serializable by scanning anything, because those ask whether some
ordering exists, and finding one is a search.

This states the checker that does the search: what it decides, how it
stays tractable, and what it answers when it cannot decide at all.

## Motivation

Two relations in the shape catalogue state correctness conditions over a
whole run rather than over a pair of operations. Serializability asks
whether concurrent transactions are equivalent to some serial order.
Snapshot isolation asks whether each transaction saw one consistent
snapshot. Both are decided by the dependency graph below.

Linearizability is a third condition of the same kind, and the catalogue
does not name it. It asks whether every call appears to take effect
instantaneously somewhere inside its own interval. Deciding it needs a
search rather than a graph, so it is the most expensive part of what
follows and the part no catalogue relation requires.

All three are what people want from a store, and all three are what a
test suite usually leaves unchecked. A suite that asserts a value came
back does not notice that two clients observed an order no serial
execution could produce.

The reason they are usually skipped is that they are hard, and the
hardness is proven rather than anecdotal. Papadimitriou showed in 1979
that deciding whether a history is serializable is NP-complete. Gibbons
and Korach showed in 1997 that the corresponding decision for sequential
consistency and for linearizability is NP-complete too.

That is a reason to design carefully. It is not a reason to leave the
question unasked, because the histories a test produces are small and
structured in ways the general case is not.

## Detailed design

### Three answers, not two

```
Verdict
  Holds
  Violated(witness)
  Undecided(reason, budget-spent)
```

An assertion that cannot decide must say so. Reporting `Holds` when the
search ran out of budget claims something unproven, and reporting
`Violated` claims something false. The third answer is what makes the
checker honest, and everything below exists to make it rare.

`Undecided` fails the test by default, because a check that could not run
is not a check that passed. A caller may ask for it to be reported and
tolerated, which is the right setting for a nightly run that widens the
budget rather than a pull request that must not block on a search.

### The witness

A violation reports the operations that cannot be ordered, not just the
fact of it:

```
Witness
  operations   the calls involved, with their intervals
  explanation  what ordering was required and what forbade it
  partition    the key the violation was found under, where partitioned
```

A history checker that answers "not linearizable" and stops leaves the
reader to find the problem in a thousand operations. The witness is the
deliverable.

### Deciding linearizability

The search asks whether the calls can be arranged in a total order that
respects real time and that a sequential model would have produced. The
caller supplies the model:

```
Model
  initial() -> State
  step(State, operation, arguments) -> (accepted, State)
```

`step` says whether the model could have produced that return from that
state, and what state it moves to. Nothing else about the subject is
needed.

Three things keep the search tractable, and without them it is not.

**Partition first.** A history over independent keys decomposes: a run is
linearizable if and only if the sub-history for each key is. Checking
twenty keys of fifty operations is twenty small searches rather than one
search over a thousand. This is the difference between a checker that
finishes and one that does not, and it applies to almost every store-like
subject.

**Memoise on state, not on path.** Two different orderings that linearize
the same set of calls and reach the same model state are
interchangeable, so the search need explore only one. Without this the
search re-walks the same futures exponentially.

**Bound the budget.** The search takes a ceiling in candidate orderings
explored. Reaching it answers `Undecided` with the count, which tells a
caller to partition better, shorten the history, or widen the budget.

The algorithm is Wing and Gong's, with the improvements Lowe measured.
Nothing here is novel and it should not be: this is a solved problem
whose solutions are published, and the work is implementing them five
times rather than inventing a sixth.

### Deciding serializability, and why it is a different shape

The same search does not transfer. A transaction is not one call with an
interval; it is several, and what matters is which transaction read what
another wrote.

So the checker builds a dependency graph instead. Each transaction is a
node, and an edge records that one transaction must precede another:
because it wrote what the other read, because it read what the other
overwrote, or because both wrote the same item. A cycle in that graph is
a run no serial order could have produced.

This is Adya, Liskov and O'Neil's formulation, and its virtue is that
cycle detection is a graph walk rather than a search. Finding a cycle is
polynomial in the size of the history.

That does not contradict the NP-completeness result. Deciding
serializability in full generality remains hard. What the graph decides
is whether a named anomaly is present, and each anomaly is a shape of
cycle: a cycle of write-write edges, a cycle with one read-write edge,
a cycle with several. A history with no such cycle has no anomaly the
formalism names, which is a weaker statement than "is serializable" and
is the statement worth making.

Snapshot isolation is the same graph read differently. It forbids the
cycles that involve a dirty write, a dirty read or a read skew, and
permits the one that is write skew. That is why it sits beside
serializability rather than below it, and why one checker answers both by
asking which cycles are allowed.

### What the caller supplies

For linearizability, a model and a partition key. For the transactional
checks, the read and write sets of each transaction, which the history
already records if the operations name the items they touch.

Neither needs the subject to cooperate. Both are read off a history the
concurrency driver produced.

## Alternatives considered

### A. Do not build it; leave these relations undeclared

The standard could record them as absent, which is what the overlay
mechanism is for, and point users at the tools that do this well.

This is the strongest alternative and it has a real argument behind it. A
checker is a research-grade artifact, the published tools implement it
well, and building one five times is a different project from an
assertion library. Everything else in the standard is a comparison or a
scan.

Rejected because the tools are per-language and do not agree. A Go
project reaches for one checker, a JVM project for another, and a project
with both gets two verdicts with different meanings. The whole argument
for a standard is that a relation means the same thing in every language,
and these are the relations where a disagreement costs the most.

### B. Drive an existing checker in each language

Mature implementations exist, and a first attempt is not their equal.

Rejected on the same ground the rest of the runtime avoids dependencies,
and for a reason specific to this case: a checker's verdict is only
comparable across languages if the checkers agree on what they decided
and on what they do when they give up. Wrapping five different tools
means wrapping five different answers to the third question, and the
third answer is the one that matters.

### C. Answer only Holds and Violated

Two answers is a simpler contract, and a search that exhausts its budget
could report `Holds` on the grounds that no violation was found.

Rejected because that is a false claim, and a quiet one. A budget
exhausted on a large history would report success exactly when the run
was most complex, which is when a violation is most likely.

### D. Search without partitioning

The general algorithm is correct without it, and partitioning needs the
caller to name a key.

Rejected on tractability. Without partitioning the search is over the
whole history, and on any realistic run it exhausts the budget. A checker
that answers `Undecided` in the common case has not been built.

## Drawbacks

This is the largest thing in the standard by a wide margin. A search with
memoisation and backtracking, a dependency graph with cycle detection,
and a witness good enough to read, five times over. Every other member is
a comparison or a scan.

The linearizability check needs a model from the caller, which is a
second implementation of the subject's semantics. Writing one is real
work and getting it wrong reports violations that are not there.

`Undecided` is a third outcome every consumer has to handle. A runner
that understands pass and fail now has a case that is neither.

The transactional checks decide less than their names suggest. Answering
that no named anomaly is present is not answering that the history is
serializable, and a reader who takes the assertion's name at face value
believes the stronger thing. The documentation can say so; the name still
says serializable.

Partitioning is only sound where the keys are independent. An operation
spanning two keys breaks the decomposition, and nothing in the seam
notices that the caller partitioned something that does not decompose.

## Unresolved and future work

Whether the budget is stated in candidate orderings, in wall time, or in
both. Orderings are reproducible and comparable across machines. Time is
what a caller wants to bound.

Whether a model is required for the transactional checks or whether the
read and write sets are enough. The graph needs only the sets, but a
model would catch a return value no serial order could have produced.

What the checker does with operations that failed rather than returned. A
call that errored occupied an interval and may or may not have taken
effect, and the treatment differs between the two checks.

Whether the standard should state a corpus for the checker itself. A
checker is a program that can be wrong, and the histories it should
accept and reject are exactly the kind of thing this project already
expresses as data.

## References

- Linearizability, and why a call is placed inside its own interval:
  Herlihy and Wing, <https://doi.org/10.1145/78969.78972>
- The search itself: Wing and Gong,
  <https://doi.org/10.1006/jpdc.1993.1015>
- Deciding serializability is NP-complete: Papadimitriou,
  <https://doi.org/10.1145/322154.322158>
- Deciding sequential consistency and linearizability is NP-complete:
  Gibbons and Korach, <https://doi.org/10.1137/s0097539794279614>
- The search and the improvements that make it practical: Lowe,
  <https://doi.org/10.1002/cpe.3928>
- Isolation levels as cycles in a dependency graph: Adya, Liskov and
  O'Neil, <https://doi.org/10.1109/icde.2000.839388>
- Snapshot isolation, and why write skew is permitted: Berenson,
  Bernstein, Gray, Melton and O'Neil,
  <https://doi.org/10.1145/568271.223785>
