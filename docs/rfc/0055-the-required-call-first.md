---
rfc: 0055
title: The required call first and the expansion of a configuration
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-11-04
updated: 2026-11-04
discussion: https://github.com/dokimasia/assert-go/issues/92
supersedes: RFC-0004 and RFC-0051, in part
superseded-by: none
produces-adr: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# RFC-0055: The required call first and the expansion of a configuration

## Summary

The search of `linearizable` tries the candidates of a configuration in
event order. It stores a configuration in its memo when it descends into
it. Under these rules, a history of 32 calls from a simulation stops
undecided at the default budget of 10,000,000 steps, although the history
is linearizable with its read first. This proposal changes two rules of
the search:

- **The required call first.** At its first visit of a configuration, the
  search tries the required call. The required call is the call of the
  first completion entry that the search has not linearized.
- **The expansion.** After the required call, the search computes the
  configuration of every other candidate. It stores each configuration
  that the memo does not cover, and then descends into them in event order.

The search still tries every candidate of each configuration that it
visits, and the memo still skips only the configurations that it covers.
The verdict of every history is unchanged. Definition 16.0.0 adopts both
rules. Eight of the 32 vectors of `linearizable` change their steps or
their frontier.

## Motivation

The simulation of dokimi recorded a history of one key with 32 calls: 30
writes whose outcome is unknown, a read of the initial value, and two ok
writes that start before the read and complete after it. The history is
linearizable with the read first. `history.Linearizable` of assert-go
stopped undecided at the default budget after 66 seconds. The CI of dokimi
failed on the history after 574 seconds.

Each write writes a value other than the initial one, so the read must
precede every write that takes effect. In event order, the read's
invocation is the last candidate. So the search visits every configuration
of the writes that the memo does not skip before it tries the read, and
none of them leads to a pass. The memo cover skips a configuration whose
extra calls have no completion. It does not skip a configuration that has
linearized one of the two ok writes, because a cover needs the same calls
with a completion. At 12 writes of unknown outcome, the memo stores 2,648
configurations, and 2,516 of them linearize an ok write before the read.

The reference search takes these steps on histories with n writes of
unknown outcome by three clients, two ok writes that start among them, and
a read of the initial value that completes before the two ok writes
complete:

| Writes of unknown outcome | 15.0.0 | This proposal |
|---|---|---|
| 8 | 4,552 | 3 |
| 12 | 25,396 | 3 |
| 16 | 147,631 | 3 |
| 20 | 591,410 | 3 |
| 24 | 1,678,631 | 3 |

Under 15.0.0 the reference spent 664 seconds on 24 writes. Definition
13.6.0 has no memo cover, and under it the reference stopped undecided at a
budget of 2,000,000 steps at 16, 18 and 30 writes.

The search with the required call first was rejected once. That
measurement ran on the memo of definition 13.6.0. On random register
histories with crashes, the 90th percentile of the steps rose from 1,726 to
19,122, and the maximum from 4,206 to 1,332,682. On the memo of 15.0.0, the
maximum on the same histories is 254,537 steps, against 1,868 under 15.0.0.

With the required call first, the write of a crashed client is a candidate
at every later configuration until the search linearizes it, because a call
without a completion is never the required call. A configuration from which
no pass exists then visits the orders of those writes. The memo cover skips
a longer order of writes when the memo stores a shorter order that leaves
the same states. A depth-first search visits the longer orders first. The
expansion stores the configuration of each write before the search descends
into the first one. On the same histories, the maximum falls to 5,042
steps.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Required call | The call of the first completion entry whose call the search has not linearized |
| Candidate | A call that the search has not linearized and whose invocation comes before the completion of the required call |
| Expansion | Computing the configuration of each candidate other than the required call, and storing each configuration that the memo does not cover |
| Child | A configuration that the expansion stored |
| Frame | An entry of the stack: the linearized call, the states before it, and the children of its configuration that the search has not visited |

### The rules

The search keeps Wing and Gong's configurations, its memo, its cover and
its limits. The order in which it tries the candidates changes, and so does
the point at which it stores a configuration:

```text
search(partition):
  entries   = the invocation events of the partition's calls, and the
              completion events of its ok calls, in event order
  done      = {}                      calls linearized so far
  states    = [init()]
  stack     = []                      frames
  memo      = {}                      configurations stored
  steps     = 0
  children  = none                    none until the configuration expands
  loop:
    if entries contains no completion: return passed
    if children is none:
      r = the required call
      next = advance(states, r)
      if next is not empty and store(done + r, next):
        push (r, states, none)
        linearize(r, next)
        continue
      children = expand()
    if children is not empty:
      take the first (c, next) out of children
      push (c, states, children)
      linearize(c, next)
      children = none
    else:
      if stack is empty: return violated
      pop (c, previous, rest); restore c's entries
      done = done - c; states = previous
      children = rest
      if children is none: children = expand()

expand():
  children = []
  for each candidate c other than the required call, in event order:
    next = advance(states, c)
    if next is not empty and store(done + c, next):
      append (c, next) to children
  return children

advance(states, c):
  next = []
  for each state s in states, in order:
    if steps + cost(s) > budget: return undecided, limit steps
    steps = steps + cost(s)
    append the states step(s, c) returns to next, keeping the first
      of each group of equal states
  return next

store(configuration):
  if a configuration in memo covers it: return false
  if (size of memo + 1) * calls of the partition > memo-limit:
    return undecided, limit memo
  add the configuration to memo
  return true

linearize(c, next):
  done = done + c; states = next
  remove c's entries from entries
```

When the search backtracks from the required call, it expands the
configuration that the backtrack restores, because the frame of the
required call has no children yet. When it backtracks from a child, it
descends into the next child of the same frame, or backtracks again when no
child is left.

### The verdict

The search tries every candidate of each configuration that it visits. It
tries the required call first and the other candidates in the expansion.
The rules change the order of Wing and Gong's search and leave the orders
that it can build unchanged.

A configuration in the memo is finished, on the stack, or a child that a
frame on the stack has not visited yet. The search descends into each such
child before it backtracks past its frame. Every order that follows a
skipped configuration also follows the configuration that covers it. The
search has tried those orders from a finished configuration. It tries them
from a configuration on the stack or from an unvisited child before it
backtracks past that configuration or its frame.

So the skip does not remove a pass. A partition passes, is violated or uses
up a limit as the definition states.

### What changes

- **Steps.** A history can change its steps when one of the configurations
  that the search visits has more than one candidate. A history in which
  every visited configuration has one candidate keeps its steps.
- **The frontier.** The search order changes, so the frontier of a
  violated or undecided history can contain another order of its calls. The
  frontier is still the first configuration, in search order, with the
  largest set of linearized calls. Its candidates list the required call
  first when the model rejects it, and then the other rejected candidates
  in event order.
- **The outcome at a limit.** A history that used up a limit can finish
  within it, and a history that finished can use up a limit.
- **The memo limit.** The memo stores every child, and the memo limit
  counts it.

### The cost of the rules

- **The required call.** The search finds the first completion entry among
  the remaining entries. A step of another candidate leaves the required
  call unchanged, because every other completion entry comes after it. A
  step of the required call makes the call of the next completion entry the
  required call. The reference scans the entries from the start.
- **The steps of the expansion.** When the first child leads to a pass,
  the steps of the other children are spent without use, because the
  expansion computes every candidate before the search descends. On random
  register histories with crashes, the median rose from 676.5 to 1,815.5
  steps.
- **The children of a frame.** For each child that the search has not
  visited, a frame keeps the call and its list of states. A stack of depth d
  keeps at most d times the concurrency of the partition such lists.
- **The memo.** The memo stores each child. We counted the stored
  configurations on two sets, and the memo stored fewer than under 15.0.0
  on both: 8,994 against 10,907 on the random register histories with
  crashes, and 39,835 against 827,027 on the random register histories with
  a wrong read.

### Conformance

The corpus pins the rules in these new vectors:

- `linearizable/a-read-before-two-writes-that-complete-after-it-passes-within-the-budget`:
  twelve writes of unknown outcome, two ok writes and a read of the initial
  value, built as in the motivation, pass in 3 steps within a budget of
  100. The search of 15.0.0 stops undecided at the budget. The expansion
  without the required call first stops undecided at the budget as well.
- `linearizable/unknown-writes-and-a-read-of-an-absent-value-are-violated-within-the-budget`:
  sixteen writes of unknown outcome and a read of a value that no write
  wrote are violated in 273 steps within a budget of 1,000. The search of
  15.0.0 stops undecided at the budget. The required call first without the
  expansion stops undecided at the budget as well.

These vectors of the corpus render new outputs under the rules:

| Vector | Steps under 15.0.0 | Steps under 16.0.0 |
|---|---|---|
| `linearizable/one-of-two-concurrent-compare-and-sets-succeeds` | 4 | 5 |
| `linearizable/an-append-follows-a-concurrent-put` | 3 | 6 |
| `linearizable/a-contains-concurrent-with-an-add-may-miss-it` | 5 | 3 |
| `linearizable/a-dequeue-outputs-a-value-nobody-enqueued` | 6 | 6 |
| `linearizable/a-write-whose-outcome-is-unknown-takes-effect-later` | 6 | 5 |
| `linearizable/a-write-whose-outcome-is-unknown-may-never-take-effect` | 4 | 2 |
| `linearizable/a-pending-write-takes-effect-when-a-later-read-needs-it` | 2 | 3 |
| `linearizable/unknown-writes-that-no-read-needs-pass-within-the-budget` | 1,325 | 1 |

The frontier of the dequeue vector linearizes the enqueue of 2 before the
enqueue of 1, and its state becomes the queue [2, 1]. Its steps are
unchanged. The other 24 vectors render the same outputs.

### Version

A change of the search or of its candidate order is a major version of the
definition. Both rules change the steps and the frontiers that the vectors
pin, so definition 16.0.0 adopts them and every overlay extends 16.0.0. An
implementation that keeps the search of 15.0.0 fails the two new vectors
and the eight changed ones.

## Measurements

The executable reference ran four searches on five sets of histories:

- **15.0.0** tries the candidates in event order, with the memo cover.
- **Required first** adds the first rule alone.
- **Expansion** adds the second rule alone, and keeps the event order.
- **This proposal** adds both rules.

### The histories of the issue

Each history has n writes of unknown outcome by three clients, two ok
writes that start among them, and a read of the initial value that
completes before the two ok writes complete:

| Writes of unknown outcome | 15.0.0 | Required first | Expansion | This proposal |
|---|---|---|---|---|
| 8 | 4,552 | 3 | 380 | 3 |
| 12 | 25,396 | 3 | 743 | 3 |
| 16 | 147,631 | 3 | 1,259 | 3 |
| 20 | 591,410 | 3 | 1,890 | 3 |
| 24 | 1,678,631 | 3 | 2,625 | 3 |

At 30 writes, the count of the issue, the required call first and this
proposal take 3 steps, and the expansion alone takes 3,968.

### Writes of unknown outcome and a read

n writes of unknown outcome by three clients, then a read. The read returns
the initial value, the value of the last write, or a value that no write
wrote:

| Writes | Read | 15.0.0 | Required first | Expansion | This proposal |
|---|---|---|---|---|---|
| 16 | initial | 3,648 | 1 | 273 | 1 |
| 16 | last | 517 | 3 | 33 | 18 |
| 16 | absent | 3,648 | 3,648 | 273 | 273 |
| 32 | initial | 47,928 | 1 | 1,057 | 1 |
| 32 | last | 333 | 5 | 97 | 66 |
| 32 | absent | 47,928 | 47,928 | 1,057 | 1,057 |

A violated history needs every order, so the required call first does not
shorten it. With the expansion, the history with the read of an absent
value is violated after 1,057 steps at 32 writes.

### Random register histories with crashes

40 linearizable histories of 73 calls on one register, by three clients.
Half of the calls are writes, and each write crashes with a probability of
0.6. A crashed write completes as unknown, and takes effect with a
probability of 1/2 at a random point after its invocation. Every written
value is unique:

| Search | Median steps | 90th percentile | Maximum |
|---|---|---|---|
| 15.0.0 | 676.5 | 1,006 | 1,868 |
| Required first | 439 | 9,316 | 254,537 |
| Expansion | 6,639 | 9,796 | 9,957 |
| This proposal | 1,815.5 | 4,243 | 5,042 |

This proposal takes more steps than 15.0.0 on 37 of the 40 histories. Its
largest rise is from 201 to 3,599 steps.

### Random register histories with a wrong read

The set has 400 histories of 40 calls that are built as the histories with
crashes. In every second history, one read returns another written value or
a value that no write wrote. 236 of the histories are linearizable and 164
are not. Each search ran with a budget of 300,000 steps:

| Search | Histories | Median steps | 90th percentile | Largest decided | Undecided |
|---|---|---|---|---|---|
| 15.0.0 | Linearizable | 345 | 1,193 | 115,183 | 1 |
| 15.0.0 | Not linearizable | 1,307.5 | 59,046 | 219,536 | 7 |
| Required first | Linearizable | 178.5 | 1,685 | 137,257 | 0 |
| Required first | Not linearizable | 1,164 | 46,812 | 163,938 | 6 |
| Expansion | Linearizable | 1,285 | 2,174 | 3,206 | 0 |
| Expansion | Not linearizable | 456 | 1,833 | 4,433 | 0 |
| This proposal | Linearizable | 342.5 | 886 | 1,679 | 0 |
| This proposal | Not linearizable | 456 | 1,833 | 4,433 | 0 |

The median and the 90th percentile count an undecided history at the
budget. Where two searches decide a history, they give the same verdict.

### Porcupine's 108 histories

The 108 test histories of Porcupine v1.3.1, as the history seam records
them: a timed-out call completes as unknown, and a call still open at the
end is pending:

| Search | Fewer steps | More steps | Median | 90th percentile | Total steps |
|---|---|---|---|---|---|
| 15.0.0 | | | 203 | 6,990 | 12,536,121 |
| Required first | 70 | 2 | 138.5 | 590 | 12,013,995 |
| Expansion | 54 | 16 | 176.5 | 2,840 | 11,642,869 |
| This proposal | 71 | 2 | 143.5 | 353 | 11,916,944 |

Every search gives Porcupine's verdict on all 108 histories. Under this
proposal, `etcd/080` rises from 4,677 to 10,647 steps, and `kv/c50-ok`
rises from 741,945 to 1,135,594. `etcd/007` falls from 466,971 to 194
steps.

This proposal lowers the median of Porcupine's own encoding from 272.5 to
189 steps. That encoding gives every call a completion. Nine of its
histories take more steps, and the largest rise is `etcd/067`, from 270 to
20,976 steps. The steps of the reference equal the count of a step counter
in Porcupine on 80 of the 105 histories that Porcupine searches to the
end. Under 15.0.0 they are equal on all 105.

## Alternatives considered

### A. The required call first alone

The search would try the required call first and the other candidates in
event order, and store a configuration when it descends into it. This is
the order of Lowe's just-in-time search and of the jit-linearizations of
Knossos.

**Why not:** it decides the histories of the issue in 3 steps, and it
leaves the tail of the writes of crashed clients. Its maximum on the
random histories with crashes is 254,537 steps, against 1,868 under 15.0.0.
Six of the 164 histories that are not linearizable are undecided at
300,000 steps.

### B. The expansion alone

The search would expand every configuration that it visits and keep the
event order.

**Why not:** it decides each random history in fewer than 10,000 steps,
and it spends the steps of every candidate on the path of a pass. Its median on
the random histories with crashes is 6,639 steps, against 1,815.5 under
this proposal. Its median on the linearizable histories with a wrong read
is 1,285, against 342.5.

### C. Lowe's just-in-time graph search

Lowe's search linearizes a call when a completion requires it, after a
sequence of pending calls of other clients.

**Why not:** we did not measure it. Its configurations exist only at
completions, so the memo cover, the frontier and the unit of a step need
definitions of their own in each language. Alternative A measures the cost
of trying sequences of pending calls before a required call in depth-first
order.

### D. A larger budget

**Why not:** under 15.0.0 the steps of the issue's shape grow from 591,410
at 20 writes to 1,678,631 at 24. The history of the issue, with 30 writes,
needs more than 10,000,000 steps, and assert-go spent 66 seconds on those.

### E. A cover across calls with a completion

The memo would also skip a configuration that has linearized an ok write
when a configuration without that write leaves the same states.

**Why not:** that skip can remove a pass. An order that passes from the
skipped configuration has linearized the ok write already. The other
configuration must still linearize the write, so the same order does not
pass from it.

### F. Two searches

The search would try the required call first within a share of the budget,
and search again in event order when the first search does not decide.

**Why not:** a history that the first search does not decide costs both
searches. Each language would specify two searches and the split of the
budget. With the expansion, one search decides both kinds of history.

## Drawbacks

- **Histories with crashes take more steps.** 37 of the 40 random histories
  with crashes take more steps. The median rises from 676.5 to 1,815.5, and
  the maximum from 1,868 to 5,042.
- **Some of Porcupine's histories take more steps.** In the encoding of the
  seam, `etcd/080` takes 10,647 steps instead of 4,677 and `kv/c50-ok`
  1,135,594 instead of 741,945. In Porcupine's own encoding, `etcd/067`
  takes 20,976 steps instead of 270.
- **The steps no longer equal Porcupine's.** Under 15.0.0 the steps of the
  reference are equal to those of Porcupine on all 105 histories that
  Porcupine searches to the end. That equality checks the reference against
  a second implementation. Under this proposal the steps are equal on 80
  of them. The verdicts are still equal on all 108.
- **A frame keeps its children.** An implementation keeps the lists of
  states of the unvisited children of every frame, up to the concurrency of
  the partition per frame.
- **Every implementation changes its search.** The definition's major
  version changes. An implementation implements 15.0.0 until it adopts both
  rules.

## References

| What | Where |
|---|---|
| The issue | <https://github.com/dokimasia/assert-go/issues/92> |
| The linearizability checker, whose search this proposal changes | [RFC-0004](0004-the-history-checker.md) |
| The memo cover | [RFC-0051](0051-calls-without-a-completion-in-the-memo.md) |
| Wing and Gong, the search | <https://doi.org/10.1006/jpdc.1993.1015> |
| Lowe, the memo and the just-in-time search | <https://doi.org/10.1002/cpe.3928> |
| `jit-linearizations` of Knossos | <https://github.com/jepsen-io/knossos/blob/master/src/knossos/linear.clj> |
| Porcupine v1.3.1 and its test histories | <https://github.com/anishathalye/porcupine/tree/v1.3.1> |
