---
rfc: 0046
title: Isolation checks over register histories
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-28
updated: 2026-10-28
discussion: https://github.com/dokimasia/assert-spec/issues/27
supersedes: none
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0046: Isolation checks over register histories

## Summary

`serializable` and `snapshot-isolation` check histories of list-append
transactions alone. A key-value store, a register of leases or a table of
rows reads a value and overwrites it, and has no list to append to. This
proposal lets the two assertions check histories of read-write register
transactions too:

- A transaction states `["write", key, value]` and `["read", key, null]`.
  Every value is written to its key once.
- A history whose micro-operations write is a register history. Any other
  history is a list-append history, as before.
- The checker infers a partial version order for each key from the initial
  state and from the writes that follow reads within one transaction. It
  derives the dependencies from that order, and searches the same cycles.
- A register history reveals fewer dependencies than a list-append history.
  The proposal states which anomalies it can miss.

The two ids, their detail fields and their record keep their shape.
Definition 13.3.0 adds the workload.

## Motivation

### A system without lists cannot be checked

A test of isolation today must give its subject a list-append workload.
Every write appends a unique value to a list that a read returns whole.
A key-value store, a register of leases or a table of rows has no
append. Its transactions read a value and replace it. A test of such a
system must add a list type to the system, or it checks nothing.

dokimi's simulation of sans-IO machines and its runner for a real cluster
record the transactions of such systems. Neither can check them.

### Registers reveal less, and still reveal most cycles

A blind write to a register leaves no evidence of the version it
replaced. A write that follows a read in its own transaction does: the
transaction read v and wrote w, so v precedes w in the key's version
order. Every key also starts at its initial state, which precedes every
written value. Kingsbury and Alvaro's Elle infers a register's version
order from exactly these facts, among others, and derives the same
dependency graph as for lists from the partial order. Its README calls
the register workload weaker than the list-append workload and applicable
to basically all systems.

A test that reads before it writes, as a read-modify-write does, gives
the checker the version order of every key that it touches.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Micro-operation | `["write", key, value]` or `["read", key, value]` in a register history |
| Initial value | The value of a key that no transaction has written. A read that returned null returned it |
| External read | A transaction's first read of a key, when the transaction has not written the key before it |
| External write | A transaction's last write of a key |
| Installed value | The value of a committed transaction's external write |
| Version pair | Two values of one key, the first of which precedes the second in every version order that the history allows |

### The workload

A register transaction is one call recorded through the history seam, as a
list-append transaction is:

- Its operation is `"txn"`, and its arguments are its micro-operations in
  the order the transaction ran them. A read states its key and null.
- An `ok` completion means the transaction committed. Its value repeats
  the micro-operations with each read's value filled in. A read that
  returned null returned the initial value.
- A `fail` completion means the transaction aborted. An `unknown`
  completion, or none, means the outcome is unknown.

**Guarantees.**

1. Every written value is unique within its key, and no write writes null.
2. A read returns the value of the key, or null for the initial value.
3. A transaction that reads a key before it writes the key reads the
   version that its write replaces. The checker relies on it for the
   version order.

```go
c := h.Invoke(client, "txn", []any{
	[]any{"read", "lease", nil},
	[]any{"write", "lease", 8},
}, "lease")
held, err := store.Swap("lease", 8)
switch {
case errors.Is(err, ErrAborted):
	c.Fail(err)
case err != nil:
	c.Unknown(err)
default:
	c.OK([]any{
		[]any{"read", "lease", held},
		[]any{"write", "lease", 8},
	})
}
```

### Which workload a history is

A history whose micro-operations contain a write is a register history.
Every other history is a list-append history, so every history that
definition 13.2.0 accepts gets the verdict that it gets today.

A read-only history is checked as list-append. Each of its reads must
return a list or null. A register read that returned a value in such a
history ends the check with a fault, where the register derivation would
report a garbage read.

The faults of the list-append workload apply, and these join them:

- a history whose micro-operations both append and write
- a write of null
- a value written twice to one key

### Derivation

The checker numbers transactions by their invocation events, and works on
each key on its own:

1. **Committed transactions.** A transaction is committed when its
   completion is `ok`, or when its outcome is unknown and a committed read
   observed one of its writes. Only committed transactions join the graph.
2. **Version pairs.** The initial value precedes each installed value. A
   committed transaction whose external read of a key returned r, and
   whose external write of the key installed w, gives the pair (r, w).
3. **Edges.**
   - **ww**: for each pair (v, w) whose v is no initial value, the
     transaction that installed v → the transaction that installed w.
   - **wr**: for each committed external read that returned a value v
     other than the initial value, the transaction that installed v → the
     reading transaction.
   - **rw**: for each committed external read that returned v, and each
     pair (v, w), the reading transaction → the transaction that installed
     w.

A pair need not be adjacent in the version order. Its edge then
summarises a path through the versions between: one edge of the same
kind, then ww edges. A cycle through such an edge is a cycle of the same
kind in the database's history, as an edge to an unobserved append is in
a list-append history.

Elle takes the same three steps: `initial-state-version-graphs`,
`wfr-version-graphs` and `version-graphs->transaction-graph`.

### The anomalies

| Kind | In a register history |
|---|---|
| `garbage-read` | A committed read returned a value that no transaction wrote to the key |
| `duplicate-append` | Does not occur. A value written twice is a fault of the history |
| `internal-inconsistency` | A committed read differs from the value that its transaction last wrote or read on the key, or returned a value that its transaction writes to the key later |
| `incompatible-order` | Does not occur. A register has no list for two reads to disagree on |
| `aborted-read` | A committed read returned a value that an aborted transaction wrote. Adya's G1a |
| `intermediate-read` | A committed read returned a value that its writer replaced with a later write of the same key. Adya's G1b |
| `G0`, `G1c`, `G-single`, `G-nonadjacent`, `G2` | The cycles of the list-append checks, found by the same search over the edges above |

Each level forbids the kinds that it forbids for a list-append history.

### The anomalies that registers hide

A check over registers never reports an anomaly that did not happen. It
reports fewer than a check over lists, because blind writes leave no
version order:

- **Two blind writes have no order.** Two transactions that write a key
  without reading it give no ww edge between them. A `G0` cycle among
  blind writes is missed.
- **A lost update passes `snapshot-isolation`.** Two transactions that
  read v and write their own values give two rw edges between them, and
  no ww edge. The cycle has two adjacent rw edges, so `serializable` fails
  it as `G2` and `snapshot-isolation` permits it. Snapshot isolation
  forbids a lost update by its ww order, which the history does not
  reveal.
- **A read of an overwritten value reveals nothing after it.** A read of
  v gives rw edges only to the writes that read v first. A transaction
  that read v while a blind write had already replaced it shows no
  anomaly.

A workload that reads every key before it writes it avoids the first two
gaps for its own writes.

### The record

The detail fields, the transactions and the cycle keep their shape. The
explanation entries keep their fields, with the register's values:

| Entry | Fields |
|---|---|
| A ww edge | `from`, `to`, `relation`, `key`, `value`, the value that `from` installed, and `next`, the value that `to` installed |
| A wr edge | `from`, `to`, `relation`, `key`, and `value`, the value that `to` read |
| An rw edge | `from`, `to`, `relation`, `key`, `value`, the value that `from` read or null for the initial value, and `next`, the value that `to` installed |
| `garbage-read` | `call`, `key`, `read` and `value`, both the value that the read returned |
| `internal-inconsistency` | `call`, `key`, `read`, `expected`, the value the transaction knew or null, `whole`, whether it knew one, and `future`, its later write that the read returned, or null |
| `aborted-read` | `call`, `key`, `value`, and `appender`, the transaction that wrote it |
| `intermediate-read` | `call`, `key`, `value`, `appender`, and `next`, the writer's later value |

The field `appender` names the writer of a register value. The record has
one shape for both workloads, so a reader of records needs no second
schema.

The derivation adds the edges of each key in the order that the keys
first appear: its ww edges in the order of the installing transactions,
then the wr and rw edges of each read in the order of the reading
transactions. Within one read, the rw edges follow the installing
transactions. An explanation states the first evidence of an edge in
that order, so one history gives the same record in every language.

### Conformance

Each register history is a vector in `corpus/history/serializable.json`
and in `corpus/history/snapshot-isolation.json`:

| Case | The history | Count |
|---|---|---|
| Each direct kind | A garbage read, an internal inconsistency of each form, an aborted read and an intermediate read | 6 |
| Each cycle kind | `G0`, `G1c`, `G-single`, `G-nonadjacent`, and a write skew as `G2` | 5 |
| A lost update | Two read-modify-writes of one value, which `serializable` fails and `snapshot-isolation` passes | 1 |
| Passing histories | A serial history of read-modify-writes | 1 |
| An unknown outcome | An `unknown` write that a read observed, which closes a cycle | 1 |

That is 14 histories and 28 vectors. The executable reference in
`tools/history/isolation.py` computes their outputs.

### Version

Accepting a history that definition 13.2.0 refused with a fault is a minor
change. Every history that 13.2.0 accepts gets the same verdict and the
same record. Definition 13.3.0 adds the workload.

## Alternatives considered

### A. Two more assertions

`serializable-registers` and `snapshot-isolation-registers` would name the
workload, as Elle's namespaces `elle.list-append` and `elle.rw-register`
do.

**Why not:** the level is what a test states, and the workload is how
the history encodes it. The micro-operations name the workload already,
so a second pair of names adds twelve names to the naming table and
nothing a test reads. The cost is the rule for a read-only history.

### B. Process and real-time orders

Elle can infer more version pairs from the order of one client's
transactions, or from real time when each key is linearizable.

**Why not:** both assume more than the levels state. Serializability
orders no two transactions by their client or by real time, so a pair
from either order can report a cycle that a serializable database
produces. A test that wants those guarantees states strict
serializability through `linearizable`.

### C. A solver for the version order

Cobra, PolySI and Viper search every version order that the history
allows, and are complete over blind writes.

**Why not:** each needs an SMT solver as a test dependency of five
languages, and their time grows faster than linearly: Viper checked 400
transactions in 0.04 s and 10,000 in 439.7 s. The list-append checks
rejected them for the same reasons.

### D. A cyclic version order as an anomaly of its own

Elle reports `cyclic-versions` when its version pairs form a cycle.

**Why not:** a cycle of version pairs is a cycle of wr edges between the
transactions that read and write them, and of ww edges between their
writers. The cycle search reports it as `G0` with the evidence of each
edge. A kind of its own would report the same history twice.

## Drawbacks

- **The checks are weaker than over lists.** The anomalies under "The
  anomalies that registers hide" pass. A test that can append should.
- **A read of the initial value multiplies edges.** Each such read gains
  an rw edge to each installed value of its key, so a hot key read empty
  by many transactions gives the product of the readers and the writers.
- **The rule for a read-only history** sends a register history without
  writes through the list-append checks, where a read of a value is a
  fault.
- **The field `appender`** names the writer of a register value.
- **Five implementations** of the register derivation and its direct
  checks, and the reference in Python. The corpus grows by 28 vectors.

## Unresolved and future work

- Process and real-time version orders, for levels that state session or
  real-time guarantees, are not proposed here.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-spec/issues/27> |
| Kingsbury and Alvaro, Elle, the section on registers | <https://arxiv.org/abs/2003.10554> |
| Elle, `initial-state-version-graphs`, `wfr-version-graphs` and `version-graphs->transaction-graph` | <https://github.com/jepsen-io/elle/blob/main/src/elle/rw_register.clj> |
| Adya, generalized isolation levels, G1a and G1b | <https://doi.org/10.1109/icde.2000.839388> |
| Cerone and Gotsman, the dependency graphs of snapshot isolation | <https://doi.org/10.1145/2933057.2933096> |
| Zhang et al., Viper, its times | <https://doi.org/10.1145/3552326.3567492> |
| The list-append checks, their search and their record | RFC-0015 |
