---
adr: 0002
title: A lost update fails both isolation levels
status: Accepted
date: 2026-11-04
supersedes: RFC-0015 and RFC-0046, in part
superseded-by: none
rfc: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# ADR-0002: A lost update fails both isolation levels

## Status

Accepted

## Context

In a lost update, two committed transactions read one version of a key and both write the key. Whichever write the database installs second overwrites a version that its transaction never read. Both isolation levels forbid the history:

- A serializable store orders the two transactions, so the later one reads the write of the earlier one.
- A store with snapshot isolation commits only the first of two concurrent transactions that write one key, and aborts the second.

The checks find a lost update only as a cycle. That cycle needs the version order of the two writes:

- In a register history the two transactions read v and write their own values. The derivation gives two rw edges between them and no ww edge, so `serializable` fails the history as `G2` and `snapshot-isolation` passes it. RFC-0046 records this under "The anomalies that registers hide", and its corpus pins the pass.
- A list-append history gives the same two edges when no read observed the two appends.

A test can plant a fault that commits each write of a transaction in a transaction of its own. Over registers that fault produces lost updates and no other anomaly, so `snapshot-isolation` passes the faulty store. The issue is [dokimasia/assert-spec#32](https://github.com/dokimasia/assert-spec/issues/32).

## Decision

We add the kind `lost-update`. The checker finds it from the micro-operations directly:

- Two ok transactions show it when each has an external read of one key, both reads returned the same list or value, and each appends or writes to the key after its read. Only an ok transaction states what its reads returned.
- In the table of anomalies of RFC-0015 it follows `intermediate-read` and precedes `G0`. The checker finds the first seven kinds of the table from the micro-operations directly.
- `serializable` and `snapshot-isolation` forbid it in list-append and in register histories.
- The checker takes the ok transactions in the order of their invocations. The first transaction whose read matches the read of an earlier one ends the search, and the case contains the two. `transactions` lists the earlier one first.

The explanation has one entry:

| Field | Value |
|---|---|
| `calls` | The two transactions, the earlier one first |
| `key` | The key that both transactions read and write |
| `read` | The list or value that both reads returned, and null for the initial value of a register |

Elle's `lost-update-cases` detects the same anomaly in one scan of the committed transactions.

This decision supersedes these parts of RFC-0015:

- the table of anomalies, which gains the row of `lost-update`
- the sentence on the first six kinds that the checker finds directly
- the table of explanation entries, which gains the entry above

It also supersedes these parts of RFC-0046:

- the table of anomalies, which gains the row of `lost-update`
- the bullet "A lost update passes `snapshot-isolation`" under "The anomalies that registers hide"
- the row of the lost update in the table of its conformance vectors

A new kind is a major version under the versioning table of RFC-0015, so definition 15.0.0 adopts it. The corpus gains a list-append lost update at each level. The register lost update fails at both levels.

## Alternatives Considered

### Report the lost update as G-single

Either order of the two writes would close a `G-single` cycle of one ww edge and one rw edge. It lost because the record proves each edge with values of the history. No value of the history states the direction of that ww edge.

### List every transaction that read the version

Elle lists each transaction that read the value and wrote the key. It lost because two transactions are the smallest evidence. The record of every other direct kind also states its first instance alone.

### Keep the gap

RFC-0046 kept the lost update as a gap of register histories. It lost because a store whose commit loses writes then passes the level that forbids the anomaly.

## Consequences

**Positive:**

- A store that commits two concurrent writes of one key fails `snapshot-isolation` over registers, and over list-append histories whose appends no read observed.
- The check reads each micro-operation once.

**Negative:**

- Definition 15.0.0 is a major version. An implementation that syncs the copy before it adds the kind fails the four vectors of a lost update.
- `serializable` reports `lost-update` before `G2` for the register lost update, so the record of that vector changes at both levels.
