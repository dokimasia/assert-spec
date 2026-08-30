---
research: 0002
title: Which of the shape catalogue's 107 relations can the assertion standard carry?
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Answered
created: 2026-08-30
updated: 2026-08-30
freshest-source: 2026-08-30
supersedes: none
superseded-by: none
---

# Research-0002: Which of the shape catalogue's 107 relations can the assertion standard carry?

## The question

The shape catalogue registers 107 named relations that a generator stamps
on an interface. The assertion standard states 41. For each of the 107,
can the assertion layer express the law, and if not, what is missing?

The question can come out wrong. If most of the catalogue needs code
generation to check, the assertion layer stays a value-comparison
library and the relations belong upstream. If most of it reduces to a
relation over closures, the assertion layer is undersized by a wide
margin and the standard should grow.

### What would count as an answer

A per-shape classification, derived from each shape's own definition,
with the missing machinery named. A count is not an answer unless every
row behind it is visible and arguable.

### What sources are admissible

Each shape's own `doc.go`, which states the law it stamps. For the
consistency relations, the papers that define them, since a mixin
claiming to be snapshot isolation is checkable only against the
published definition.

### What would change the answer

A shape whose law needs the generated harness rather than the closures
a caller can pass. Every such shape moves from carryable to
generator-side, and enough of them would mean the assertion layer should
not grow at all.

## The answer

**75 of the 107 are carryable by the assertion layer. 32 are not.**

Of the 75, **43 need nothing but new assertions**: no new machinery, no
new seam, one file per family in the shape the standard already uses.
That alone would take the assertion layer from expressing 7 of the
catalogue to expressing 43 of it.

The remaining 32 need one of four seams, and they are not 32 separate
problems. Thirteen need a history recorder, ten a concurrency driver,
five a role-passing convention and four a clock.

The 32 that are not ours divide cleanly. All 23 detectors classify
signatures and nothing about them can fail. Nine mixins declare rather
than check, and three of those say so in their own documentation.

## What the evidence says

### The classification

Every row is derived from that shape's own `doc.go`, which states the law
it stamps. Class A is expressible with the 41 assertions today. Class B
needs a new assertion and nothing else. Class C needs an assertion plus
one seam. Class D is not assertion work.

| Class | Mixins | Contracts | Detectors | Total |
|---|---|---|---|---|
| **A: already expressible** | 7 | 0 | 0 | **7** |
| **B: new assertion only** | 23 | 13 | 0 | **36** |
| **C: new assertion plus a seam** | 19 | 13 | 0 | **32** |
| **D: not assertion work** | 9 | 0 | 23 | **32** |
| | 58 | 26 | 23 | **107** |

carryable (A+B+C): 75 | not ours (D): 32
seams: {'concurrency': 10, 'history': 13, 'roles': 5, 'clock': 4}

### Mixins

| Shape | Class | Seam | What the law is |
|---|---|---|---|
| `accumulates` | B | — | N calls leave N effects; needs an observe closure |
| `associative` | B | — | (a∘b)∘c == a∘(b∘c) |
| `atomic` | C | concurrency | completes fully or leaves nothing; needs an induced failure |
| `bounded` | C | concurrency | resource ceiling beyond allocation; queue depth and fanout need observation |
| `cacheable` | B | — | same input, same answer over time |
| `causal` | C | history | effects observed in causal order, ordered by a version field |
| `commutative` | B | — | a∘b == b∘a |
| `concurrent` | C | concurrency | safe under N concurrent callers |
| `concurrentreaders` | C | concurrency | safe under N concurrent readers |
| `conservative` | B | — | a named quantity is moved, never created or destroyed |
| `crdtmerge` | B | — | merge is commutative, associative and idempotent |
| `defaultonerror` | B | — | a failed read answers the zero value beside the error |
| `deleteremoves` | B | roles | delete then read reports not-found |
| `deprecated` | D | — | declaration; changes generation, checks nothing |
| `errors` | D | — | its own doc says it owes documentation, not a check |
| `eventually` | A | — | have it, though the settle/sync/observe form is richer than ours |
| `hooks` | D | — | generator wiring |
| `idempotent` | B | — | f(f(x)) == f(x) |
| `indexed` | D | — | input derivation; tells the generator an int is a position |
| `injectionsafe` | B | roles | untrusted input reaches the interpreter as data |
| `integrationonly` | D | — | test selection |
| `leakfree` | A | roles | have no-task-leaks; resources generally need an open/close pair |
| `lifecycleafterclose` | B | roles | behaves after close, typically a sentinel |
| `monotonic` | B | — | successive observations never decrease |
| `monotonicreads` | C | history | session guarantee |
| `monotonicwrites` | C | history | session guarantee |
| `nilsafe` | A | — | have none-handle-safe; generalises to any absent input |
| `notfound` | A | — | have error-is |
| `noduplicates` | B | — | one drain emits each element at most once |
| `orderafter` | C | history | effect visible only after a named sibling ran |
| `overmatch` | A | — | have contains; assert containment not equality |
| `partition` | C | roles | never serves another partition's data |
| `permutation` | B | — | every element exactly once, any order: set equality |
| `pointintime` | C | concurrency | two reads agree across an interleaved write |
| `poisonable` | B | roles | a sticky failure state, induced once |
| `pure` | A | — | have is-pure, though ours checks state and not determinism |
| `readafterwrite` | B | roles | write then read returns the written value |
| `readyourwrites` | C | history | session guarantee |
| `retrysucceeds` | B | — | converges within a bounded number of attempts |
| `sample` | D | — | generation strategy |
| `scheduled` | C | clock | a task registered for later has run once the clock passes |
| `scope` | D | — | its own doc says it owes documentation, not a check |
| `serializable` | C | history | equivalent to some serial order; needs a checker, not just a recorder |
| `sideeffect` | B | roles | the inverse of pure: an observation does change |
| `snapshotisolation` | C | history | one consistent snapshot; write skew permitted |
| `stableorder` | B | — | repeated iteration yields the same order |
| `sticky` | B | roles | one key is served by one instance |
| `streamreflectsmutations` | C | concurrency | an iterating stream observes concurrent mutation |
| `tamperevident` | B | roles | modification of accepted data is detectable |
| `timeaware` | D | — | declares the suite must control the clock |
| `timeout` | A | — | have honours-deadline and completes-within |
| `total` | B | — | defined for every input in a named domain |
| `ttl` | C | clock | unreadable once the lifetime elapses |
| `validates` | C | roles | a validator screens input before the body runs |
| `windowed` | C | clock | covers a bounded window of recent input |
| `wrappedvia` | D | — | structural delegation |
| `writesfollowreads` | C | history | session guarantee |
| `xsssafe` | B | roles | output carrying untrusted input is escaped |

### Contracts

| Shape | Class | Seam | What the law is |
|---|---|---|---|
| `appender` | B | roles | additive only: no overwrite, no delete |
| `batchwriter` | B | roles | all-or-nothing is atomicity over a batch |
| `cas` | B | roles | the write happens only on a version match |
| `chain` | C | history | append-only log, replayed and compared |
| `circuitbreaker` | C | concurrency | fails fast after repeated failures |
| `codec` | B | roles | its own doc states inverse(forward(x)) == x |
| `cursor` | C | roles | next plus close; the close is a leak check |
| `ifabsent` | B | roles | succeeds only when nothing is there |
| `ifmatch` | B | roles | succeeds only on a predicate match |
| `leaderelection` | C | concurrency | campaign, resign, is-leader |
| `lease` | B | roles | every acquire balanced by one release |
| `outbox` | C | history | at-least-once delivery downstream |
| `pagination` | C | history | every item exactly once across pages |
| `persister` | B | roles | write then read the entity back |
| `pool` | B | roles | every get balanced by one put |
| `publisher` | C | history | published events reach the subscriber |
| `ratelimit` | C | clock | a rate per unit time and a burst |
| `saga` | B | roles | the compensation reverses the step |
| `singleflight` | C | concurrency | concurrent calls share one computation |
| `transaction` | B | roles | rollback undoes the write |
| `tx` | C | roles | begin, commit, rollback |
| `updater` | B | roles | write then read confirms |
| `upserter` | B | roles | insert or update, last write wins |
| `watcher` | C | concurrency | the trigger fires what the watch observes |
| `workflow` | C | history | execution follows a declared transition graph |
| `writethroughcache` | C | roles | the cache delegates a miss to the backing store |

### The consistency relations are defined in the literature, not invented

Four mixins are exactly the four session guarantees Terry, Demers,
Petersen, Spreitzer and Theimer defined in 1994: `readyourwrites`,
`monotonicreads`, `monotonicwrites` and `writesfollowreads`
(DOI 10.1109/pdis.1994.331722, 155 citations per Crossref). The
catalogue's own docs call them "the four session guarantees", and the
set matches the paper.

**What we concluded:** they share one mechanism, a history ordered by a
version stamp, and each mixin already takes a `version` parameter naming
the field. That is one parameterised assertion over a recorded history
rather than four unrelated ones, and I have counted them as four rows
while believing they are one member.

`snapshotisolation`'s doc states that write skew is permitted "and that
is the point of the model, not an omission from it". That matches
Berenson, Bernstein, Gray, Melton and O'Neil, who defined snapshot
isolation and showed it permits write skew while preventing dirty
write, dirty read and read skew (DOI 10.1145/568271.223785, 268
citations).

`serializable`'s doc calls itself "deliberately a sibling rather than a
level" on snapshot isolation. That is consistent with the same paper:
snapshot isolation is not a point on the ANSI isolation ladder, because
it permits an anomaly the ladder does not rank and forbids ones lower
levels allow.

`crdtmerge` asks that concurrent writes merge deterministically without
conflict. Shapiro, Preguiça, Baquero and Zawirski define the conditions
that make this hold (DOI 10.1007/978-3-642-24550-3_29, 424 citations).

**What we concluded:** a merge that is commutative, associative and
idempotent converges regardless of delivery order, and the catalogue
already has all three as separate mixins. `crdtmerge` is therefore a
composite of members the standard would gain anyway, which is an
argument for adding the three primitives first and deriving the fourth.

### Two relations should be held back, and there is a proof

`serializable` and `snapshotisolation` need a history *checker*, not
just a recorder: something that decides whether an observed history is
equivalent to some serial order. That decision is not cheap.

Papadimitriou proved deciding serializability of a history is NP-complete
in 1979 (Journal of the ACM, DOI 10.1145/322154.322158, 671 citations).
Gibbons and Korach proved the corresponding result for sequential
consistency and linearizability of shared-memory histories in 1997 (SIAM
Journal on Computing, DOI 10.1137/s0097539794279614, 135 citations).
Herlihy and Wing's 1990 paper defines linearizability itself
(DOI 10.1145/78969.78972, 2188 citations).

**What we concluded:** a recorder is cheap and eleven relations need
nothing more. A checker is a research-grade artifact that existing tools
already implement well, and writing one in five languages is a different
project from an assertion library. Record the history in the standard and
leave the deciding to a checker, ours or someone else's.

### Three shapes state that they check nothing

`errors` and `scope` both say in their own documentation that the mixin
"owes documentation, not a check". `timeaware` declares that a suite must
control the clock rather than asserting anything itself. These are not
gaps in the assertion layer; they are metadata the generator reads.

**What we concluded:** this is worth stating in the standard as a category.
A relation that declares rather than checks has no assertion, no corpus
case and no completeness obligation, and the overlay format has no way to
say that today.

## What we could not establish

**Whether the four session guarantees are one member or four.** They
share a history and a version parameter. I counted four and believe one
parameterised assertion covers them, which would move the carryable total
from 75 to 72 while losing nothing.

**Whether `bounded` is already covered.** Its doc names memory, queue
depth and fanout. The benchmark contract already states allocation
ceilings, so the memory half may be class A. I classified the whole shape
as C on the queue-depth and fanout halves.

**Whether the role-passing seam is a seam at all.** Five shapes need
several named closures rather than one. That may be nothing more than a
calling convention, in which case they collapse into class B and the
"new assertion only" count rises from 43 to 48.

**What the detectors imply for the assertion layer.** I classified all 23
as signature classification on the strength of their names and directory
placement. I read the mixin and contract docs individually; I did not
read all 23 detector docs.

**Whether contracts belong in the assertion standard at all.** Each one's
law is expressible, but a contract is a protocol over several members,
and the standard currently names single assertions. Adding them may need
a second kind of entry rather than 26 more assertions.

## What would change this answer

A shape whose law turns out to need the generated harness rather than
closures the caller supplies. I judged this from each doc's description
of the law, not by attempting an implementation, and an attempt is what
would settle it.

The catalogue moving. It is versioned in code with a compile-checked
registry, so a new mixin is a new row here, and this document goes stale
the first time someone adds one.

## Sources

| # | Source | What it is | Retrieved | What it supports |
|---|---|---|---|---|
| 1 | `eidos/plugins/annotator/shape/{mixins,contracts,detectors}/*/doc.go` | The catalogue's own definitions | 2026-08-30 | Every law in the classification |
| 2 | `eidos/plugins/annotator/shape/ids/ids.go` | The registry of names | 2026-08-30 | 58 mixins, 26 contracts, 23 detectors |
| 3 | <https://doi.org/10.1109/pdis.1994.331722> | Terry, Demers, Petersen, Spreitzer, Theimer, 1994 | 2026-08-30 | The four session guarantees; 155 citations |
| 4 | <https://doi.org/10.1145/568271.223785> | Berenson, Bernstein, Gray, Melton, O'Neil, SIGMOD Record 1995 | 2026-08-30 | Snapshot isolation permits write skew; 268 citations |
| 5 | <https://doi.org/10.1145/78969.78972> | Herlihy and Wing, TOPLAS 1990 | 2026-08-30 | Linearizability; 2188 citations |
| 6 | <https://doi.org/10.1145/322154.322158> | Papadimitriou, JACM 1979 | 2026-08-30 | Deciding serializability is NP-complete; 671 citations |
| 7 | <https://doi.org/10.1137/s0097539794279614> | Gibbons and Korach, SIAM J. Comput. 1997 | 2026-08-30 | Testing sequential consistency and linearizability; 135 citations |
| 8 | <https://doi.org/10.1007/978-3-642-24550-3_29> | Shapiro, Preguiça, Baquero, Zawirski, 2011 | 2026-08-30 | Conflict-free replicated data types; 424 citations |

## What we searched

| Terms | Where | Date | Found |
|---|---|---|---|
| Every `doc.go` under `mixins/`, `contracts/` | Local source | 2026-08-30 | 84 definitions, read individually |
| `ids.go` constants, excluding Param and Role | Local source | 2026-08-30 | 107 distinct registered names |
| Session Guarantees for Weakly Consistent Replicated Data | Crossref | 2026-08-30 | Terry et al. 1994 |
| A Critique of ANSI SQL Isolation Levels | Crossref | 2026-08-30 | Berenson et al. 1995 |
| Linearizability: a correctness condition for concurrent objects | Crossref | 2026-08-30 | Herlihy and Wing 1990 |
| Testing shared memories | Crossref | 2026-08-30 | Gibbons and Korach 1997 |
| The serializability of concurrent database updates | Crossref | 2026-08-30 | Papadimitriou 1979 |
| Conflict-free replicated data types | Crossref | 2026-08-30 | First query matched a 2022 paper; re-queried by author to reach Shapiro et al. 2011 |

The classification rests on reading each shape's stated law. It does not
rest on implementing any of them, which is the check that would settle
the cases marked open above.
