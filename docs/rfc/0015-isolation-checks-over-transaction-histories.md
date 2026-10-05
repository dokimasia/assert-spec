---
rfc: 0015
title: Isolation checks over transaction histories
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-02
updated: 2026-10-05
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
cycles the level forbids, and reports the shortest cycle it finds with the
evidence for each edge.

The check never reports an anomaly that did not happen. It can miss an
anomaly among writes that no read observed. `serializable` forbids every
cycle of the dependency graph. `snapshot-isolation` forbids every cycle in
which no two read-write dependencies are adjacent. Cerone and Gotsman prove
that snapshot isolation allows exactly the dependency graphs without such a
cycle. The derivation and three of the five cycle searches are linear in
the size of the history. The searches for `G-single` and `G-nonadjacent`
try one edge after another, and are quadratic in the worst case.

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
that has both, they derive the dependency graph directly. They prove that
every anomaly they report is present in every database history consistent
with the observations.

A test generates its own transactions. It can always choose list appends
with unique values, and then needs no solver.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Transaction | One call of the history, whose arguments are a list of micro-operations |
| Micro-operation | `["append", key, value]` or `["read", key, list]` |
| Committed | A transaction that completed `ok`, or whose outcome is unknown and one of whose appends a committed read observed |
| Version order | A key's longest committed read |
| Unobserved append | A committed append whose value is in no committed read of its key |
| Dependency | A write-write (ww), write-read (wr) or read-write (rw) edge between two committed transactions |
| Anomaly | An observation that the isolation level forbids, such as a cycle of dependencies |

### The workload

A transaction is one call recorded through the history seam:

- Its operation is `"txn"`, and its arguments are its micro-operations in
  the order the transaction ran them. A read states its key and no list.
- Its keys are every key its micro-operations touch.
- An `ok` completion means the transaction committed. Its value repeats
  the micro-operations with each read's list filled in. A read that
  returned null returned the empty list.
- A `fail` completion means the transaction aborted and took no effect.
- An `unknown` completion, or none, means the outcome is unknown.

**Guarantees.**

1. Every appended value is unique within its key.
2. A read returns the whole list.
3. Reads are frequent, because a value that no read observed has no known
   place among the other values that no read observed.

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

A history that breaks the contract is a fault of the test, and the check
ends with it before it derives anything:

- a call whose operation is not `"txn"`, or an argument that is no
  micro-operation
- a read that states a list before it ran
- an `ok` value that does not repeat the invocation's micro-operations and
  appended values, or a read whose list is no list
- a value appended twice to one key

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
    A history of list-append transactions exhibits no anomaly that
    snapshot isolation forbids, among the dependencies its reads reveal: no
    inconsistent observation, no aborted or intermediate read, and no cycle
    in which no two anti-dependencies are adjacent.
  detail_fields: [anomaly, kinds, transactions, cycle, explanation]
```

The arguments are the history and the message. Both assertions abort only,
because a check of a whole history is conclusive. Each passes or fails.
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
| `garbage-read` | A committed read returned a value that no transaction appended | Forbids | Forbids |
| `duplicate-append` | A committed read returned one value twice | Forbids | Forbids |
| `internal-inconsistency` | A committed read contradicts its own transaction: it does not end with the transaction's earlier appends to the key, it differs from the transaction's earlier read of the key followed by its appends since, or it contains a value the transaction appends to the key later | Forbids | Forbids |
| `incompatible-order` | Two committed reads of one key are not prefixes of one list | Forbids | Forbids |
| `aborted-read` | A committed transaction read a value that an aborted transaction appended. Adya's G1a | Forbids | Forbids |
| `intermediate-read` | A committed transaction read a list ending in a value that another transaction followed with its own append to the same key. Adya's G1b | Forbids | Forbids |
| `G0` | A cycle of ww edges | Forbids | Forbids |
| `G1c` | A cycle of ww and wr edges with at least one wr edge | Forbids | Forbids |
| `G-single` | A cycle with exactly one rw edge | Forbids | Forbids |
| `G-nonadjacent` | A cycle with two or more rw edges, no two of them adjacent | Forbids | Forbids |
| `G2` | A cycle with one or more rw edges | Forbids | Permits |

Cerone and Gotsman characterise snapshot isolation by dependency graphs:
a history is allowed when its graph has no cycle in which no two rw edges
are adjacent (Theorem 9, with each transaction in a session of its own).
`G0`, `G1c`, `G-single` and `G-nonadjacent` are those cycles with no rw
edge, one, and two or more. A `G2` cycle that has two adjacent rw edges,
such as write skew, is permitted. A long fork, in which two reads see two
independent appends in opposite orders, is `G-nonadjacent` and forbidden.
Elle's snapshot isolation forbids `G-nonadjacent` for the same reason.

### Derivation

The checker numbers transactions by their invocation events, and works on
each key on its own:

1. **Committed transactions.** A transaction is committed when its
   completion is `ok`, or when its completion is `unknown` or missing and a
   committed read observed one of its appended values. A transaction with
   a `fail` completion is aborted. Only committed transactions join the
   graph.
2. **Version order.** The longest list among the committed reads of the
   key is its version order. The distinct reads, shortest first, must each
   be a prefix of the next. A key whose reads are not is an
   `incompatible-order` anomaly, and gives no edge.
3. **Appenders.** Each value maps to the one transaction that appended it
   to the key.
4. **Unobserved appends.** Every committed read is a prefix of the key's
   final list, so an unobserved append follows the last value of the
   version order. Its place among the other unobserved appends is
   unknown.
5. **Edges.**
   - **ww**: for consecutive values a and b of the version order, the
     appender of a → the appender of b. The appender of the last value →
     the appender of each unobserved append.
   - **wr**: when a committed transaction T read a list ending in a, the
     appender of a → T.
   - **rw**: when a committed transaction T read a list that the value b
     follows in the version order, T → the appender of b. The first value
     follows the empty list. When T read the whole version order, T → the
     appender of each unobserved append.

An edge joins two committed transactions that differ, and records each
of its kinds with the key and the values that produced it. An edge to an
unobserved append summarises a path through the appends between them: one
edge of the same kind, then ww edges. A cycle through such an edge is a
cycle of the same kind in the database's history, with ww edges inserted.

The checker finds the first six kinds of the table from the
micro-operations directly, in the table's order.

### Cycle search

For each cycle kind, in the table's order, the checker takes the strongly
connected components of the dependency graph over the kind's relations,
with Tarjan's algorithm, in the order of each component's lowest-numbered
transaction. In each component it tries the edges of the kind's closing
relation, in the order of their sources' and then their targets' numbers.
An edge from a to b closes a cycle when a path leads back from b to a:

| Kind | Component over | Closing edge | Path back |
|---|---|---|---|
| `G0` | ww | ww | The shortest path over ww |
| `G1c` | ww, wr | wr | The shortest path over ww and wr |
| `G-single` | ww, wr, rw | rw | The shortest path over ww and wr |
| `G-nonadjacent` | ww, wr, rw | rw | The shortest walk on which no rw edge follows another, that takes at least one more rw edge, and whose last edge is no rw edge |
| `G2` | ww, wr, rw | rw | The shortest path over ww, wr and rw |

Within a component, the first closing edge of `G0` and `G2` always closes
a cycle, and so does the first closing edge of `G1c` when the component
has one. A breadth-first search visits each transaction's edges in the
order of their targets' numbers, and an edge's relations in the order ww,
wr, rw. The reported cycle starts with the closing edge.

The walk of `G-nonadjacent` may pass a transaction twice. The checker
reduces it to a simple cycle. While a transaction occurs twice, it splits
the walk at the first repeat into the part between the two occurrences and
the rest, and keeps the part between them when no two of its rw edges are
adjacent, and the rest otherwise. One of the two always qualifies. When
the simple cycle has two or more rw edges, it is the reported cycle,
starting at its first rw edge. Otherwise the next closing edge is tried.

The derivation, the six direct checks, the components and the searches for
`G0`, `G1c` and `G2` are linear in the transactions and edges. The searches
for `G-single` and `G-nonadjacent` run one breadth-first search per rw edge
of a component until one closes, which is O(R·(V+E)) per component when
none closes. One history gives the same cycle in every language.

### The record

| Field | Value |
|---|---|
| `anomaly` | The first kind, in the table's order, that the level forbids and the history exhibits |
| `kinds` | Every kind the level forbids for which the derivation or the search finds an instance |
| `transactions` | The transactions the anomaly involves, each with its process, micro-operations, completion and event indices |
| `cycle` | For a cycle kind, the transactions in cycle order, each with the relations of the edge to the next that the search followed. Null otherwise |
| `explanation` | For a cycle, one entry per edge with the key and the values that prove it. For any other kind, one entry with the reads and appends that show it |

A transaction states `call`, the index of its invocation, `completion` and
`kind`, which a pending transaction omits, `process`, `args`, its
micro-operations as typed literals, and `output` when it committed. The
explanation entries:

| Anomaly | Entry |
|---|---|
| A cycle's ww edge | `from`, `to`, `relation`, `key`, `value` of `from`, and `next`, a value of `to` after it in the order |
| A cycle's wr edge | `from`, `to`, `relation`, `key`, and `value`, the last value of the list `to` read |
| A cycle's rw edge | `from`, `to`, `relation`, `key`, `value`, the last value of the list `from` read or null for the empty list, and `next`, the value of `to` after it |
| `garbage-read`, `duplicate-append` | `call`, `key`, `read` and the `value` at fault |
| `internal-inconsistency` | `call`, `key`, `read`, `expected`, what the transaction knew of the list, `whole`, whether it knew the whole list or only its end, and `future`, the transaction's later append that the read contains, or null |
| `incompatible-order` | `calls`, `key`, and the two `reads` |
| `aborted-read` | `call`, `key`, `value`, and its `appender` |
| `intermediate-read` | `call`, `key`, `value`, its `appender`, and the appender's `next` value |

An explanation names its evidence in the history's own terms: "T3 read
`[1, 4]` from key 5 and did not observe 6, which T7 appended after 4". How
a language renders it, as text or as a graph, is its own business.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The workload's contract, its encoding as calls, and its faults. Which transactions count as committed. The derivation rules, unobserved appends included. The kinds, their order and which kinds each assertion forbids. The cycle search, its visiting order, the reduction of a walk and the reported cycle. The record's fields and entries |
| Named | `serializable`, `snapshot-isolation` |
| Free | How an explanation renders. How a language stores the graph |

### Conformance

A transaction history is data, so the corpus states it as a script of
events, as the linearizability checker's vectors do. Each history is
checked by both assertions, so each case is a vector in
`corpus/history/serializable.json` and in
`corpus/history/snapshot-isolation.json`:

| Case | The history | Count |
|---|---|---|
| Each anomaly kind | A history that exhibits it, and pins the record where the level forbids it. Internal inconsistency has two: a read that lacks an earlier append, and a read of a later one. The `G2` history is a write skew, which `snapshot-isolation` passes | 12 |
| Passing histories | A serial history, and a concurrent one without anomalies | 2 |
| Unknown outcomes | An `unknown` transaction whose append a read observed, and one whose append no read observed | 2 |
| An unobserved append | An append that no read observed follows the last observed value, and closes a cycle | 1 |
| Search order | Two components with a cycle of one kind, and a closing edge with two paths back | 2 |

That is 19 histories and 38 vectors. People write the inputs in a YAML
file beside each, and `make render` computes the outputs with the
executable reference in `tools/history/isolation.py`.

### Measurements

The reference was measured on histories that three simulated stores
generated. The serializable store runs each transaction whole at its
commit. The snapshot store reads from the state at a transaction's start,
and aborts a transaction when another committed an append to one of its
keys after that start. The read-committed store reads the committed state
at each read. Each run had 8 clients over 16 active keys, which retire
after 32 appends, and up to 4 micro-operations per transaction. The median
of three checks on one processor:

| Store | Level | 10,000 transactions | 100,000 transactions |
|---|---|---|---|
| Serializable | `serializable` | 0.54 s | 7.96 s |
| Serializable | `snapshot-isolation` | 0.59 s | 7.45 s |
| Snapshot | `serializable`, which finds `G2` | 0.31 s | 4.50 s |
| Snapshot | `snapshot-isolation` | 0.29 s | 5.33 s |
| Read committed | `serializable`, which finds `G-single`, `G-nonadjacent` and `G2` | 0.52 s | 7.28 s |

Ten times the transactions takes 13 to 19 times as long, from 29 to 80 µs
per transaction. The snapshot store's histories contain write skews
throughout and no `G-single`, so their `G-single` search tries every rw
edge of every component.

The quadratic bound shows on a constructed history:

- The transactions of each of two chains append to one key, one after
  another.
- Each transaction of the first chain reads two keys, each of which one
  transaction of the second chain appends to, and reads them empty.
- The last transaction of the second chain reads a key that the first
  transaction of the first chain appends to, and reads it empty.

Every cycle then has two or more rw edges, and the `G-single` search walks
the second chain from each of them. It takes 0.11 s at 2,501 transactions,
0.43 s at 5,001 and 1.74 s at 10,001.

The verdicts were compared with Elle's, through elle-cli 0.1.11, on 2,600
histories of 10 to 400 transactions from the three stores, with aborts and
unknown outcomes. Both checkers gave the same verdict on every history at
both levels, but one: a history with no dependency edge, on which Elle
reports `unknown`.

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
revealed dependencies in polynomial time.

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

### G. A budget on the cycle search

The `G-single` and `G-nonadjacent` searches stop after a number of steps,
and a check that spends them ends undecided, as `linearizable` does. Elle
bounds the same searches by time, 1,000 ms per component.

**Why not:** the searches are polynomial and always end. Their quadratic
case needs a component in which no cycle closes the search, and the
histories of three simulated stores, 100,000 transactions with write
skews throughout included, never came near it. A budget would add an
undecided outcome and an option to assertions that otherwise always
decide.

### H. Snapshot isolation as forbidding `G-single` alone

Adya defines snapshot isolation over start-dependency edges, which a client
cannot observe. `G-single` proves a violation, and the check stops there.

**Why not:** it passes a long fork and every other cycle with two
non-adjacent rw edges, which snapshot isolation forbids. Cerone and
Gotsman's characterisation needs only the dependency graph that the
derivation builds.

## Drawbacks

- **The workload must reveal its versions.** A subject without a list type
  or a read-modify-write transaction cannot be checked this way.
- **Unobserved appends have no order among themselves.** An anomaly among
  appends that no read observed is missed, so a workload must read often.
- **No predicates.** A phantom, Adya's predicate anomalies, is not
  detectable.
- **No session order.** `snapshot-isolation` checks snapshot isolation with
  each transaction in a session of its own. A guarantee across one
  client's transactions needs process edges, which the derivation does not
  add.
- **The `G-single` and `G-nonadjacent` searches are quadratic in the worst
  case.** On the constructed history, the `G-single` search takes 1.74 s at
  10,001 transactions in the reference.
- **Unobserved appends multiply edges.** Each read of a key's whole order
  gains an rw edge to each unobserved append of the key, so a workload
  that rarely reads a hot key grows many edges.
- **`kinds` lists what the search finds.** A `G-nonadjacent` cycle can go
  unlisted when the walks of its edges reduce to `G-single` cycles. The
  verdict does not change, because both kinds fail both levels.
- **Five implementations** of the derivation, the six direct checks and the
  cycle search, and an executable reference in Python.
- **The naming table grows by 2 rows**, 12 names, and the corpus by 38
  vectors.

## Unresolved and future work

None.

## References

| What | Where |
|---|---|
| Adya, Liskov and O'Neil, generalized isolation levels | <https://doi.org/10.1109/icde.2000.839388> |
| Adya, weak consistency, PL-2+ and PL-SI | MIT-LCS-TR-786, 1999 |
| Berenson et al., snapshot isolation and write skew | <https://doi.org/10.1145/568271.223785> |
| Cerone and Gotsman, "Analysing Snapshot Isolation", PODC 2016, Theorem 9 | <https://doi.org/10.1145/2933057.2933096> |
| Papadimitriou, serializability is NP-complete | <https://doi.org/10.1145/322154.322158> |
| Biswas and Enea, the complexity of checking transactional consistency | <https://arxiv.org/abs/1908.04509> |
| Kingsbury and Alvaro, inferring isolation anomalies | <https://arxiv.org/abs/2003.10554> |
| Elle, the order of an unobserved append, `previously-appended-element` | <https://github.com/jepsen-io/elle/blob/main/src/elle/list_append.clj> |
| Elle, the cycle search and `cycle-search-timeout` | <https://github.com/jepsen-io/elle/blob/main/src/elle/txn.clj> |
| Elle, the anomalies each consistency model forbids | <https://github.com/jepsen-io/elle/blob/main/src/elle/consistency_model.clj> |
| elle-cli 0.1.11, the comparison's command-line front end to Elle | <https://github.com/ligurio/elle-cli/releases/tag/0.1.11> |
| Tan et al., Cobra | <https://www.usenix.org/system/files/osdi20-tan.pdf> |
| Huang et al., PolySI | <https://arxiv.org/abs/2301.07313> |
| Zhang et al., Viper | <https://doi.org/10.1145/3552326.3567492> |
| The evidence behind this design | Research-0006 |
| The shape catalogue's relations | Research-0002 |
| The history seam | RFC-0003 |
| The linearizability checker and its corpus format | RFC-0004 |
| Machines, which run the workload and call these checks in `settle` | RFC-0012 |
