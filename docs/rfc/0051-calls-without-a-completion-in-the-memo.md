---
rfc: 0051
title: Calls without a completion in the memo of the linearizability search
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-11-02
updated: 2026-11-02
discussion: https://github.com/dokimasia/assert-go/issues/89
supersedes: RFC-0004, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0051: Calls without a completion in the memo of the linearizability search

## Summary

The search of `linearizable` takes time exponential in the number of calls
without a completion, also where no such call needs to take effect. This
proposal changes one rule of its memo. The search skips a configuration
that a configuration in the memo covers:

- the states of the two are the same,
- their calls with a completion are the same,
- and the calls without a completion of the one in the memo are among the
  calls of the new one.

A call whose outcome is unknown, and a pending call, need not take effect.
Every order that can follow the new configuration can follow the covered
one, so the skip keeps every verdict. The order of the search is unchanged.

Definition 14.0.0 adopts the rule. A history whose calls all complete keeps
its steps and its record in every language.

## Motivation

A simulation records a call as unknown when its process crashes or its
client stops waiting, as Jepsen records a crashed operation. Such a call is
open to the end of the history and is a candidate at every point of the
search. In event order, every unknown write comes before the read that
needs none of them. The memo keys a configuration on its set of calls, and
each set of the writes is a configuration of its own.

A history of n writes of unknown outcome to one register, followed by one
read of the initial value, is linearizable with no write taking effect. The
reference search needs these steps:

| Unknown writes | Steps of the read of the initial value |
|---|---|
| 8 | 3,049 |
| 12 | 79,117 |
| 16 | 1,710,097 |
| 20 | Undecided at the budget of 10,000,000 |

assert-go v0.14.1 takes 0.2 ms, 4.3 ms and 123 ms for the first three rows,
and stops undecided at the fourth. One case of 73 calls of a simulated
register with a primary and a backup made 22 unknown writes to one key, and
its check stopped undecided at the budget after 53 cases.

The alternative of the just-in-time rule in the linearizability checker
made the condition explicit: a generated workload that uses up the budget
under Wing and Gong's rule and finishes under another. This workload uses
up the budget. The measurements under Measurements show that a change of
the order fixes it and costs elsewhere, and that the memo rule fixes it
without that cost.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Call with a completion | A call whose completion is ok, so the search has a completion entry for it |
| Call without a completion | A call whose outcome is unknown, or a pending call |
| Configuration | The set of linearized calls and the list of states they leave |
| Cover | A configuration in the memo covers a configuration when their states are the same, their calls with a completion are the same, and its calls without a completion are among the other's |

### The rule

The search of RFC-0004 stores each new configuration in its memo and skips
a configuration that the memo contains. This proposal replaces the second
half of that rule:

```text
      if next is not empty and no configuration in memo covers (done + c, next):
        if (size of memo + 1) * calls of the partition > memo-limit:
          return undecided, limit memo
        add (done + c, next) to memo
```

A configuration covers itself, so a configuration that the memo contains is
skipped as before. The comparison of states is unchanged: each state of one
list equals a state of the other, and the two lists have one length.

### The verdict of a covered configuration

Let A be a configuration in the memo that covers B. The calls that B adds
to A have no completion. The search may leave such a call out of an order,
because a call without a completion takes effect after its invocation or
never. A call without a completion does not add a completion entry, so it
does not limit a candidate. Every order of the calls that B has not
linearized also follows A, from the same states.

- If the search has finished A, A led to no pass, so B leads to none.
- If A is on the search's stack, the search tries every order that follows
  A before it backtracks past A, and the orders that follow B are among
  them.

The skip does not remove a pass. The search is still complete, so a
partition passes, is violated or uses up a limit as the definition states.

### What changes

- **Steps.** A partition with calls without a completion skips the
  configurations that the memo covers, so it can take fewer steps or more.
  It takes more where a skipped configuration led to the order that passes,
  and the search finds an equivalent order later. Measurements states both.
- **The record.** A skipped configuration is not visited, so it is no
  frontier. A violated or undecided record states the frontier among the
  configurations that the search visited.
- **The outcome at a limit.** A history that used up a limit can now finish
  within it, and the reverse can happen for a history that takes more
  steps.
- **Nothing else.** A partition whose calls all complete has no call
  without a completion, so a configuration covers only itself. Its steps and
  its record are unchanged.

### The cost of the rule

The memo groups the configurations by their calls with a completion and
the keys of their states. A lookup compares the calls without a completion
of each configuration in the group with those of the new one, one word for
each 64 calls. The configurations in a group are those that differ in their
calls without a completion alone, and the memo adds a configuration only
when no configuration of its group covers it. The memo limit still counts
one bit per call of the partition for each stored configuration.

### Conformance

The corpus pins the rule in these vectors:

- `linearizable/unknown-writes-that-no-read-needs-pass-within-the-budget`:
  twelve unknown writes and a read of the initial value pass in 1,325 steps
  within a budget of 10,000. Without the rule the search stops undecided at
  the budget.
- `linearizable/a-covered-configuration-is-no-frontier`: two unknown writes
  of 1 and a read of 7 are violated in 7 steps, and the frontier is the
  first write alone.

The other 616 vectors of the corpus render the same outputs under the
rule.

### Version

The rule changes the steps and the record of a history with calls without
a completion, and the two vectors pin the new ones. Definition 14.0.0 adopts
it, and every overlay extends 14.0.0. Each implementation of `linearizable`
changes its memo, and an implementation that keeps the old memo fails the
two vectors.

## Measurements

The executable reference ran each search on three sets of histories. Each
set compares the search of definition 13.6.0, the rule of this proposal,
and two changes of the order:

- **Required first** tries first the call whose completion is the first
  completion entry, then the other candidates in event order. This is the
  order of Lowe's just-in-time search and of the jit-linearizations of
  Knossos.
- **Unknown last** tries the candidates with a completion in event order,
  then the candidates without one in event order.

### The histories of the issue

n writes of unknown outcome by three clients, then a read. The read returns
the initial value, the value of the last write, or a value that no write
wrote:

| Writes | Read | 13.6.0 | This rule | Required first |
|---|---|---|---|---|
| 8 | initial | 3,049 | 328 | 1 |
| 8 | absent | 3,049 | 328 | 3,049 |
| 16 | initial | 1,710,097 | 3,648 | 1 |
| 16 | last | 17 | 517 | 3 |
| 16 | absent | 1,710,097 | 3,648 | 1,710,097 |
| 20 | initial | Undecided | 8,240 | 1 |
| 20 | absent | Undecided | 8,240 | Undecided |
| 32 | initial | Undecided | 47,928 | 1 |
| 32 | absent | Undecided | 47,928 | Undecided |

A changed order passes the read of the initial value at once. It cannot
decide a violated history, because a violation needs every order. The memo
rule decides both in polynomial steps on this history.

### Random register histories with crashes

40 linearizable histories of 73 calls on one register, by three clients.
Half of the calls are writes, and each write crashes with a probability of
0.6. A crashed write completes as unknown, and takes effect with a
probability of 1/2 at a random point after its invocation. Every written
value is unique:

| Search | Median steps | 90th percentile | Maximum |
|---|---|---|---|
| 13.6.0 | 876.5 | 1,726 | 4,206 |
| This rule | 676.5 | 1,006 | 1,868 |
| Required first | 664.5 | 19,122 | 1,332,682 |
| Unknown last | 871.5 | 94,900 | 1,790,171 |

A write that crashed and took effect is a candidate that a later read
needs. A changed order tries it after the other candidates, and the search
then tries many orders of those before it.

### Porcupine's 108 histories

The 108 test histories of Porcupine v1.3.1, as the history seam records them: a
timed-out call completes as unknown, and a call still open at the end is
pending. An etcd history has up to 25 calls without a completion:

| Search | Fewer steps | More steps | Median | 90th percentile | Total steps |
|---|---|---|---|---|---|
| 13.6.0 | | | 272 | 21,128 | 14,786,987 |
| This rule | 68 | 14 | 203 | 6,990 | 12,536,121 |
| Required first | 19 | 6 | 185 | 20,909 | 14,147,789 |
| Unknown last | 18 | 5 | 212 | 21,128 | 13,923,837 |

Every search gives Porcupine's verdict on all 108 histories. Under the
rule, the largest rise is `etcd/056`, from 1,174 to 6,990 steps, and the
largest fall is `etcd/080`, from 67,880 to 4,677 steps. Under required
first, `etcd/067` rises from 269 to 20,909 steps. The kv histories have no
call without a completion, and the rule leaves their steps unchanged.

The reference compares a list of states with each configuration of a
group, so its time on these histories rose by a fifth while its steps fell
by 15%.

## Alternatives considered

### A. Lowe's just-in-time order

The search would try first the call whose completion is the first
completion entry, then the other candidates in event order. Lowe's
just-in-time search and Knossos linearize a call when a return needs it.

**Why not:** it passes the issue's history at once, and it does not decide
a violated history with the same writes. On random histories with crashed
writes that took effect, its 90th percentile rose from 1,726 to 19,122
steps and its maximum from 4,206 to 1,332,682. It also changes the steps of
every history whose calls all complete, so every vector of the corpus
would change.

### B. Calls without a completion last

The search would try every candidate with a completion before any
candidate without one.

**Why not:** a crashed write that took effect waits behind every order of
the other candidates. Its maximum on the random histories was 1,790,171
steps, against 4,206 under 13.6.0.

### C. A search without the calls without a completion first

The search would first search the partition without its calls without a
completion. A pass there is a pass, because those calls need not take
effect. Otherwise the search of every call follows.

**Why not:** one needed unknown call sends the check to the full search,
whose cost the first search then adds to. The register of the simulation
needs some of its 22 unknown writes, so its check would still stop at the
budget.

### D. A larger budget

**Why not:** the steps grow by a factor of about 2.2 with each write, from
3,049 at 8 writes to 1,710,097 at 16. 20 writes need more than the budget
of 10,000,000 steps.

## Drawbacks

- **Some histories take more steps.** 14 of Porcupine's 108 histories
  take more steps, up to six times as many, and the largest of them took
  6,990 steps.
- **A lookup of the memo compares more configurations.** A group contains
  each configuration that differs from another in its calls without a
  completion alone. The reference spent a fifth more time on Porcupine's
  histories.
- **Every implementation changes its memo.** The definition's major version
  changes, so an implementation stays on 13.6.0 until it adopts the rule.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/89> |
| The linearizability checker, whose search this rule changes | [RFC-0004](0004-the-history-checker.md) |
| Lowe, "Testing for linearizability", Concurrency and Computation: Practice and Experience, 2017 | <https://www.cs.ox.ac.uk/people/gavin.lowe/LinearizabiltyTesting/paper.pdf> |
| `jit-linearizations` of Knossos | <https://github.com/jepsen-io/knossos/blob/master/src/knossos/linear.clj> |
| Porcupine v1.3.1 and its test histories | <https://github.com/anishathalye/porcupine/tree/v1.3.1> |
| Herlihy and Wing, "Linearizability: a correctness condition for concurrent objects", 1990 | <https://doi.org/10.1145/78969.78972> |
