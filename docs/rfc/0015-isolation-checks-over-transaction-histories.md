---
rfc: 0015
title: Isolation checks over transaction histories
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-10-02
updated: 2026-10-02
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0015: Isolation checks over transaction histories

## Summary

Two assertions, `serializable` and `snapshot-isolation`, decide whether a
recorded history of transactions exhibits an anomaly that the isolation
level forbids. The workload makes the history decidable. Every write
appends a value that no other write appends, to a list that reads return
whole. Over such a history, the checker derives every dependency between
transactions that a read reveals, searches the dependency graph for the
cycles the level forbids, and reports the shortest cycle with the evidence
for each edge.

The check is linear in the size of the history, needs no budget, and never
reports an anomaly that did not happen. It can miss an anomaly among
writes that no read observed. It decides snapshot isolation only through
the anomalies a client can observe.

## Motivation

### Databases do not provide the isolation they claim

Kingsbury and Alvaro's checker found anomalies in every database they
tested with it, among them TiDB, YugaByte DB, FaunaDB and Dgraph. PolySI
found snapshot isolation violations in three production cloud databases.
An assertion on one return value cannot see such an anomaly. It is a
property of what several transactions observed together.

The shape catalogue states two relations of this kind, `serializable` and
`snapshotisolation`. A test that claims either has no assertion to state
it with.

### The general problem is hard, and a test chooses its workload

Deciding whether a history is serializable is NP-complete. Biswas and Enea
showed the same for snapshot isolation, and that read committed, read
atomic and causal consistency are polynomial. Checkers that accept any
workload, with blind writes to registers, encode the search for an SMT
solver: Cobra for serializability, PolySI and Viper for snapshot isolation.
They are sound and complete, their time grows faster than linearly, and
Cobra's authors state that it has no guarantee of termination.

A blind write to a register leaves no evidence of the version it replaced.
A write that appends a unique value to a list does: a read of `[1, 2, 3]`
shows that the list contained `[]`, `[1]`, `[1, 2]` and `[1, 2, 3]` in that
order, and which transaction appended each value. Kingsbury and Alvaro
call these properties traceability and recoverability. Over a history
that has both, they derive the dependency graph directly and find its
cycles in linear time. They prove that every anomaly they report is
present in every database history consistent with the observations.

A test generates its own transactions. It can always choose list appends
with unique values, and then needs no solver.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Transaction | One call of the history, whose arguments are a list of micro-operations |
| Micro-operation | `["append", key, value]` or `["read", key, list]` |
| Version order | The order in which a key's list received its values, as the longest read of the key shows |
| Dependency | A write-write (ww), write-read (wr) or read-write (rw) edge between two committed transactions |
| Anomaly | An observation that the isolation level forbids, such as a cycle of dependencies |

### The workload

A transaction is one call recorded through the history seam:

- Its operation is `"txn"`, and its arguments are its micro-operations in
  the order the transaction ran them. A read states its key and no list.
- Its keys are every key its micro-operations touch.
- An `ok` completion means the transaction committed. Its value repeats
  the micro-operations with each read's list filled in.
- A `fail` completion means the transaction aborted and took no effect.
- An `unknown` completion, or none, means the outcome is unknown.

**Guarantees.**

1. Every appended value is unique within its key.
2. A read returns the whole list.
3. Reads are frequent, because a value that no read observed has no known
   place in its key's version order.

A SQL database meets the contract with a text column and `CONCAT`, or an
array column. A key-value store meets it with a list type or with a read
and a write of one value inside a transaction.

```go
c := h.Invoke(client, "txn", []any{
	[]any{"append", "x", 7},
	[]any{"read", "y", nil},
}, "x", "y")
y, err := store.AppendThenRead("x", 7, "y")
switch {
case errors.Is(err, ErrAborted):
	c.Fail(err)
case err != nil:
	c.Unknown(err)
default:
	c.OK([]any{
		[]any{"append", "x", 7},
		[]any{"read", "y", y},
	})
}
```

### The assertions

```yaml
"serializable":
  arity: 2
  package: history
  summary: >
    A history of list-append transactions exhibits no anomaly that
    serializability forbids, among the dependencies its reads reveal: no
    inconsistent observation, no aborted or intermediate read, and no cycle
    of write, read and anti-dependencies.
  detail_fields: [anomaly, kinds, transactions, cycle, explanation]

"snapshot-isolation":
  arity: 2
  package: history
  summary: >
    A history of list-append transactions exhibits no anomaly that a
    client can observe and snapshot isolation forbids: no inconsistent
    observation, no aborted or intermediate read, no cycle of write and
    read dependencies, and no cycle with exactly one anti-dependency.
  detail_fields: [anomaly, kinds, transactions, cycle, explanation]
```

The arguments are the history and the message. Both assertions abort only,
because a check of a whole history is conclusive. Each passes or fails.
The derivation and the cycle search are linear and need no budget.
Neither has a property form, for the reason `linearizable` has none: a
property generates a history of concurrent transactions through a
machine.

### In a machine

A machine of the property engine tests isolation without a model. Its
actions record one `txn` call per transaction, with values from a counter
so that every append is unique. Its concurrent section runs the
transactions from several clients, and its `settle` calls `serializable`
or `snapshot-isolation` over the case's history. The shrinker then reduces
the workload and the schedule to the transactions the anomaly needs.

A machine whose model is a map of lists checks strict serializability
instead, through the linearizability check after every step. That check
searches orders, and its cost grows with the concurrency.

### The anomalies

| Kind | What the history shows | `serializable` | `snapshot-isolation` |
|---|---|---|---|
| `garbage-read` | A read returned a value that no transaction appended | Forbids | Forbids |
| `duplicate-append` | A read returned one value twice | Forbids | Forbids |
| `internal-inconsistency` | A read did not reflect the transaction's own earlier appends to the key | Forbids | Forbids |
| `incompatible-order` | Two committed reads of one key are not prefixes of one list | Forbids | Forbids |
| `aborted-read` | A committed transaction read a value that an aborted transaction appended. Adya's G1a | Forbids | Forbids |
| `intermediate-read` | A committed transaction read a list ending in a value that its appender followed with another append to the same key. Adya's G1b | Forbids | Forbids |
| `G0` | A cycle of ww edges | Forbids | Forbids |
| `G1c` | A cycle of ww and wr edges | Forbids | Forbids |
| `G-single` | A cycle with exactly one rw edge | Forbids | Forbids |
| `G2` | A cycle with one or more rw edges | Forbids | Permits |

`snapshot-isolation` permits `G2` cycles with two or more rw edges. Write
skew is such a cycle. Adya defines snapshot isolation as forbidding G1 and
two phenomena over start-dependency edges. A client cannot observe those
edges without the database's snapshot times. A `G-single` cycle proves that
snapshot isolation was violated. Its absence does not prove that the
history satisfies snapshot isolation.

### Derivation

The checker numbers transactions in the order of their invocation events,
and works on each key on its own:

1. **Committed transactions.** A transaction is committed when its
   completion is `ok`, or when its completion is `unknown` or missing and a
   committed read observed one of its appended values. A transaction with
   a `fail` completion is aborted.
2. **Version order.** The longest list among the committed reads of the key
   is its version order. When several are longest, they must be equal.
   Every committed read of the key must be a prefix of the version order.
   A read that is not is an `incompatible-order` anomaly.
3. **Appenders.** Each value in the version order maps to the one
   transaction that appended it to the key.
4. **Edges.**
   - **ww**: for consecutive values a and b of the version order, the
     appender of a → the appender of b, when the two differ.
   - **wr**: when a committed transaction T read a list ending in a, the
     appender of a → T, when the two differ.
   - **rw**: when a committed transaction T read a list that the value b
     follows in the version order, T → the appender of b, when the two
     differ. The first value follows the empty list.

Edges from one transaction to itself are dropped. An edge between two
transactions records each of its kinds with the key and the values that
produced it.

The checker finds the first six kinds of the table from the
micro-operations directly, in the table's order.

### Cycle search

For each cycle kind, in the table's order, the checker restricts the
dependency graph to the edges the kind allows and finds its strongly
connected components with Tarjan's algorithm. It visits transactions in
number order and each transaction's edges in the order of their targets'
numbers. The first component, in the order of its lowest-numbered
transaction, that contains a cycle of the kind gives the reported cycle:

- **`G0`, `G1c` and `G2`.** The shortest cycle through the component's
  lowest-numbered transaction, found by a breadth-first search that visits
  edges in the order of their targets' numbers. For `G2`, the cycle must
  contain an rw edge.
- **`G-single`.** For each rw edge of the component, in the order of its
  source's and then its target's number, a breadth-first search from the
  edge's target back to its source over ww and wr edges only. The first
  edge that closes a cycle gives it.

The search is linear in the transactions and edges for each kind. One
history gives the same cycle in every language.

### The record

| Field | Value |
|---|---|
| `anomaly` | The first kind, in the table's order, that the level forbids and the history exhibits |
| `kinds` | Every kind the level forbids that the history exhibits |
| `transactions` | The transactions the anomaly involves, each with its process, micro-operations, completion and event indices |
| `cycle` | For a cycle kind, the transactions in cycle order with each edge's kinds. Null otherwise |
| `explanation` | For each edge, the key and the values that prove it, and for any other kind, the reads and appends that show it |

An explanation names its evidence in the history's own terms: "T3 read
`[1, 4]` from key 5 and did not observe 6, which T7 appended after 4". How
a language renders it, as text or as a graph, is its own business.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The workload's contract and its encoding as calls. Which transactions count as committed. The derivation rules. The kinds, their order and which kinds each assertion forbids. The cycle search, its visiting order and the reported cycle. The record's fields |
| Named | `serializable`, `snapshot-isolation` |
| Free | How an explanation renders. How a language stores the graph |

### Conformance

A transaction history is data, so the corpus states it as a list of
events, as the linearizability checker's cases do:

| Kind | Each case states | And pins | Count |
|---|---|---|---|
| Each anomaly kind | A history that exhibits it | The record of each assertion that forbids it | 10 |
| Write skew | A `G2` cycle with two rw edges | `snapshot-isolation` passes, `serializable` fails | 1 |
| Passing histories | A serial history, and a concurrent one without anomalies | Both assertions pass | 2 |
| Unknown outcomes | An `unknown` transaction whose append a read observed, and one whose append no read observed | The first joins the graph, the second adds no edge | 2 |
| Search order | A history with two cycles of one kind | The reported cycle | 2 |

That is 17 cases, in `corpus/history/serializable.json` and
`corpus/history/snapshot-isolation.json`. People write the inputs in a
YAML file beside each, and `make render` computes the outputs with an
executable reference of the derivation and the search in `tools/`.

Before acceptance, the reference checks histories of 10,000 and 100,000
generated list-append transactions, to confirm that its time grows
linearly, and its verdicts are compared with Elle's on the same histories.

### Names

| Id | Go | Python | Rust | TypeScript | Java, Kotlin |
|---|---|---|---|---|---|
| `serializable` | `history.Serializable` | `history.is_serializable` | `history::is_serializable` | `history.isSerializable` | `History.isSerializable` |
| `snapshot-isolation` | `history.HasSnapshotIsolation` | `history.has_snapshot_isolation` | `history::has_snapshot_isolation` | `history.hasSnapshotIsolation` | `History.hasSnapshotIsolation` |

That is 2 rows, 12 names. `serializable` takes the spelling the naming
table gives an adjective, as `pure` is `Pure` in Go and `is_pure` in
Python. `snapshot-isolation` names a property the history has, so it takes
`has`, as `err-present` is `HasError` in Go and `has_error` in Python.

### Versioning

| Change | Version |
|---|---|
| Adding `serializable` and `snapshot-isolation` | Minor |
| A new assertion over the same derivation, such as read committed | Minor |
| A change to the derivation, the kinds or which kinds an assertion forbids | Major |
| A change to the cycle search's order | Minor; the verdict does not change |

## Alternatives considered

### A. A solver-based checker for any workload

Cobra, PolySI and Viper accept transactions with blind writes, and are
sound and complete.

**Why not:** each needs an SMT solver, which would become a test
dependency of five languages, through a native library in most of them.
Their time grows faster than linearly: Viper checked 400 transactions in
0.04 seconds and 10,000 in 439.7 seconds. Cobra has no guarantee of
termination. A test that chooses its workload gets the same verdicts on
revealed dependencies in linear time.

### B. The linearizability checker over a map

Strict serializability is linearizability with transactions as operations
and the database as one map. The linearizability checker could decide it.

**Why not:** the search is exponential in the concurrency. Kingsbury and
Alvaro report that Knossos "often timed out or ran out of memory after a
few hundred transactions" on histories that their checker finished in
seconds.

### C. Registers with unique writes

Unique writes to registers make each read's version recoverable. They need
no list type.

**Why not:** a register's writes leave no version order. Without it, ww
edges and most rw edges cannot be derived, and fewer anomalies are
detectable from the same number of transactions.

### D. One assertion with a level parameter

`isolation(history, level, msg)` would cover every level with one name.

**Why not:** a named relation is what makes a test readable, and the shape
catalogue names the two relations separately. A level parameter is a
string that no compiler checks.

### E. Leave isolation to existing tools

Kingsbury and Alvaro's checker is published, sound and fast, and the
earlier research for this standard recommended leaving checkers to
existing tools.

**Why not:** it runs on the JVM, in Clojure, so a Go, Python or Rust suite
calls it through another runtime. This is the strongest alternative, and a
caller who already runs it gains little from these assertions.

### F. More levels: read committed, repeatable read, strict serializability, causal consistency

The same derivation supports each with a different set of forbidden kinds,
and strict serializability with real-time edges added.

**Why not:** no shape in the catalogue states any of them. A relation that
states one reverses this, at the cost of one assertion and its corpus
cases.

## Drawbacks

- **The workload must reveal its versions.** A subject without a list type
  or a read-modify-write transaction cannot be checked this way.
- **Unobserved writes have no known order.** An anomaly among appends that no
  read observed is missed, so a workload must read often.
- **No predicates.** A phantom, Adya's predicate anomalies, is not
  detectable.
- **`snapshot-isolation` is one-sided.** It detects the G1 and `G-single`
  anomalies that snapshot isolation forbids, and not the anomalies that
  need the database's snapshot times.
- **Five implementations** of the derivation, the six direct checks and the
  cycle search, and an executable reference in Python.
- **The naming table grows by 2 rows**, 12 names, and the corpus by 17
  cases.

## Unresolved and future work

None. The measurements before acceptance are the reference's time on
generated histories and its agreement with Elle.

## References

| What | Where |
|---|---|
| Adya, Liskov and O'Neil, generalized isolation levels | <https://doi.org/10.1109/icde.2000.839388> |
| Adya, weak consistency, PL-2+ and PL-SI | MIT-LCS-TR-786, 1999 |
| Berenson et al., snapshot isolation and write skew | <https://doi.org/10.1145/568271.223785> |
| Papadimitriou, serializability is NP-complete | <https://doi.org/10.1145/322154.322158> |
| Biswas and Enea, the complexity of checking transactional consistency | <https://arxiv.org/abs/1908.04509> |
| Kingsbury and Alvaro, inferring isolation anomalies | <https://arxiv.org/abs/2003.10554> |
| Tan et al., Cobra | <https://www.usenix.org/system/files/osdi20-tan.pdf> |
| Huang et al., PolySI | <https://arxiv.org/abs/2301.07313> |
| Zhang et al., Viper | <https://doi.org/10.1145/3552326.3567492> |
| The evidence behind this design | Research-0006 |
| The shape catalogue's relations | Research-0002 |
| The history seam | RFC-0003 |
| The linearizability checker and its corpus format | RFC-0004 |
| Machines, which run the workload and call these checks in `settle` | RFC-0012 |
