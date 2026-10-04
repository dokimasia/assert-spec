---
rfc: 0004
title: The linearizability checker
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-08-30
updated: 2026-10-04
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0004: The linearizability checker

## Summary

`linearizable` decides whether a recorded history of concurrent calls is
linearizable with respect to a sequential model. It passes, or it fails as
`violated` with the point where its search stopped, or as `undecided` with
the limit that stopped it. The search, its order, its budget and its
report are part of the definition, so one history gives the same outcome
and the same report in every language.

The checker partitions a history by the keys its calls declare, follows
the definition of linearizability for calls whose outcome is unknown, and
counts its budget in calls of the model's step function. A history from a
generated concurrent test of two clients checks in linear time. A search
that uses up its budget ends as undecided instead of running without end.

Transactional isolation reads the same history, with one call per
transaction, through a different algorithm, and is specified separately.

## Motivation

### A return value cannot show that concurrent calls were atomic

A store, a queue, a lock or a cache that several callers use at once is
correct when every call appears to take effect at one instant inside its
own interval. Herlihy and Wing named this linearizability in 1990. An
assertion on one return value cannot see it. Two clients can each receive
a plausible value while together they observe an order that no sequence of
the calls could produce.

Six published tools check it, each in one language and each with its own
choices:

| Tool | Language | Its bound | Calls with an unknown outcome | What it reports |
|---|---|---|---|---|
| Knossos | Clojure | Memory. It returns `:unknown` when memory runs out | `info` completions and crashed processes | The first call it could not order, the last it could, and the orders it tried |
| Porcupine v1.3.1 | Go | A wall-clock timeout, after which it returns `Unknown`, which its documentation lets a caller read as a pass | None. The caller encodes them in the model | The longest linearizable prefix per call, as HTML |
| Lowe's framework | Scala | An iteration limit in its published experiments | None | The history, marked where linearization failed, with the return values the model allowed |
| Lincheck | JVM | A number of schedules | None | An interleaving with its switch points |
| Line-Up | .NET | Small tests: three threads of three operations in its evaluation | None | A violation of deterministic linearizability |
| `eqc_par_statem` | Erlang | A parallel part of at most 16 commands | None | A minimally parallel test case |

A Go service and its JVM client, tested with two of these, get two verdicts
with different meanings. The verdict itself is not where they differ,
because complete searches agree on whether a linearization exists. The
tools differ in when they give up, in what a crashed call means and in what
they report. This proposal fixes those three.

### The problem is hard, and a test's histories are not

Deciding linearizability of one history is NP-complete. The cost depends on
the history's concurrency and data type more than on its length. On a
register, Lowe bounds his graph search by a number of configurations linear
in the length and exponential in the number of concurrent processes. On a
map partitioned by key, each key has the same bound. On a queue, concurrent
enqueues of distinct values multiply the possible states.

Measured on Porcupine's own 108 test histories, with a step counter added
to its checker, the median history needed 272.5 calls of the model's step
and the slowest 1,177,310. Measured on synthetic histories of a register
with unique writes, two clients needed about 1.2 steps per call at every
length up to 1,024 calls. The evidence and the method are in the research
listed under References.

A generated test controls its own workload. It can use two clients, unique
written values and frequent reads, which are the conditions under which the
search is linear.

## Detailed design

### Terms

| Term | Meaning |
|---|---|
| Call | An invocation event and its completion event, if any |
| Completion | `ok` with an output, `fail`, or `unknown`; a call without a completion is pending |
| Precedence | Call a precedes call b when a's completion event comes before b's invocation event |
| Model | An initial state and a step function over states |
| Partition | A set of calls that share keys, checked on its own |
| Configuration | The set of calls linearized so far and the model states they leave |
| Step | One call of the model's step function |
| Frontier | The longest order the search built, the states it leaves, and the calls that could not follow it |

### Components

| Component | Responsibility |
|---|---|
| History | Records invocations and completions in one order, with the keys each call touches. The observation seams specify it |
| Partitioner | Joins calls that share a key into partitions, and orders the partitions |
| Search | Searches each partition for an order the model accepts, in a fixed order, with a memo of configurations |
| Budget | Counts steps per partition, and stops a search at the limit |
| Report | Builds the failure record from the first partition that did not pass |

### The assertion

```yaml
"linearizable":
  arity: 3
  package: history
  summary: >
    Every partition of a recorded history has an order of its calls that
    keeps the history's precedence and that the model accepts. A fixed
    search decides it within a budget of model steps. A search that uses
    up the budget is undecided, and an undecided history fails.
  detail_fields: [outcome, partitions, steps, partition, linearized, states, candidates, limit]
```

The arguments are the history, the model and the message. Options follow
the message. A check of a whole history is conclusive, so `linearizable`
aborts only, as `prop-for-all` and the golden-file and benchmark
assertions do.

`linearizable` has no property form. Its history comes from clients that
run at once, and a property generates such a history through a machine's
concurrent section, which takes the schedule from the case and shrinks
it.

```go
func TestRegisterIsLinearizable(t *testing.T) {
	h := history.New()
	reg := NewRegister()
	var wg sync.WaitGroup
	for client := range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range 50 {
				if i%2 == 0 {
					v := client*1000 + i
					c := h.Invoke(client, "write", []any{v}, "x")
					reg.Write(v)
					c.OK(nil)
				} else {
					c := h.Invoke(client, "read", nil, "x")
					c.OK(reg.Read())
				}
			}
		}()
	}
	wg.Wait()

	history.Linearizable(t, h, history.Model[int]{
		Init: func() int { return 0 },
		Step: func(s int, op history.Op) []int {
			if op.Operation == "write" {
				return []int{op.Args[0].(int)}
			}
			if !op.Known || op.Output == s {
				return []int{s}
			}
			return nil
		},
	}, "the register is linearizable")
}
```

### Outcomes

| `outcome` | When | What the record names |
|---|---|---|
| `passed` | Every partition has an order the model accepts | Nothing; no record is reported |
| `violated` | The search of a partition tried every order within the budget and found none the model accepts | The partition and its frontier |
| `undecided` | The search of a partition used up the budget, and no partition was violated | The partition, the limit, and the frontier when the search stopped |

`undecided` fails the test. A check that could not decide has not passed,
for the same reason a property that tested no input has not passed.

The detail of a failing check:

| Field | Value |
|---|---|
| `outcome` | `violated` or `undecided` |
| `partitions` | The number of partitions |
| `steps` | The steps spent in every partition the check searched |
| `partition` | The keys of the reported partition. An empty list means every key |
| `linearized` | The calls of the frontier's order, in that order. Each states its `process`, `operation`, `args` and `output`, in the history's JSON form, and the indices of its events |
| `states` | The model states after that order |
| `candidates` | The calls that could come next, each of which the model rejected in every one of those states |
| `limit` | For `undecided`: `steps` or `time`. Null otherwise |

### The model

```text
Model
  init() -> State
      The state before any call.
  step(state, op) -> [State]
      The states that may follow state when the call that op describes
      takes effect. For a call whose outcome is unknown, the model returns
      the states the call leaves when it takes effect. An empty list
      rejects the call in this state. step must not modify state, and must
      return the same list for the same arguments.
  equal(State, State) -> bool                optional
      Whether two states are interchangeable. The standard's equal by default.

Op
  operation    the call's operation
  args         the call's arguments
  known        whether the call completed with ok
  output       the call's output when known is true; absent otherwise
```

A step returns a list so that one signature serves a specification with
more than one legal next state. A pool whose `get` returns any free item,
or a register whose write may be lost, returns several states. A
deterministic model returns one state or none.

`equal` must be exact. The memo merges two configurations whose states are
equal, and an equality coarser than the model's meaning merges a
configuration that could still succeed with one that cannot. That turns a
linearizable history into a violated one. The standard's equality treats
-0 and +0 as equal, so a model that tells them apart states its own
`equal`. The standard's equality also treats a NaN as unequal to itself.
The memo then never matches a state that contains a NaN, and the search
repeats the work after it. A hash that agrees with `equal` is each
language's own business.

### Completions and precedence

The history seam records invocation and completion events in one order,
and guarantees that each process has at most one open call. The checker
reads it this way:

- A call with an `ok` completion takes effect between its invocation and
  its completion, with its output.
- A call with a `fail` completion took no effect, and the checker removes
  it.
- A call with an `unknown` completion, and a pending call, completes after
  the last event of the history with an absent output. Several such calls
  complete in the order of their invocations. Each takes effect at some
  point after its invocation, or never. This is the definition of
  linearizability for a history with pending invocations.
- Precedence comes from event order only. The checker reads no clock.

### Partitions

Each invocation declares the keys it touches, as typed literals. A call
that declares no key touches every key. The checker joins two calls into
one partition when they share a key, and forms partitions as the connected
components of that relation. A call that touches every key puts the whole
history into one partition.

Herlihy and Wing's locality theorem, and Horn and Kroening's
P-compositionality, make the per-partition verdicts equal the verdict for
the whole history when the declared keys are complete. Every partition
starts from the model's initial state, and the model is written over the
full state. A key-value model is a map, and each partition touches only its
own keys.

Partitions are ordered by the index of their first invocation event.

### The search

The search of one partition is fixed:

```text
search(partition):
  entries   = the partition's invocation and completion events in event order;
              the completions of unknown and pending calls go after the last
              event, in the order of their invocations
  done      = {}                      calls linearized so far
  states    = [init()]
  stack     = []                      (call, states before it)
  memo      = {}                      configurations seen
  entry     = the first entry
  loop:
    if entries is empty: return passed
    if entry is the invocation of call c:
      next = the states step returns for c from each state, in order,
             keeping the first of each group of equal states
      if next is not empty and (done + c, next) is not in memo:
        add (done + c, next) to memo
        push (c, states); done = done + c; states = next
        remove c's two entries from entries
        entry = the first entry
      else:
        entry = the entry after entry
    else:                             a completion whose call is not in done
      if stack is empty: return violated
      pop (c, previous); restore c's two entries
      done = done - c; states = previous
      entry = the entry after c's invocation
```

The candidates at each point are the calls whose invocations come before
the first completion of a call not yet linearized, tried in event order. An
accepted step restarts from the first entry. Two configurations are the
same when their sets of calls are equal and their lists of states contain
equal states.

This is Wing and Gong's search with the memo of configurations that Lowe
introduced. Lowe measured the memo's effect: his tree searches, which keep
no memo, failed to finish within ten billion configurations on up to 5 of
50 map histories, where the graph search finished.

### The budget

| Option | Default | Meaning |
|---|---|---|
| `budget(steps)` | 10,000,000 | The steps one partition's search may spend |
| `time-limit(duration)` | None | The wall time the whole check may take, on the platform clock |
| `workers(n)` | 1 | Partitions searched at once |

A step is one call of the model's step function. A configuration with three
states costs three steps.

The budget is counted, so one history gives one outcome on every machine.
The default decides all 108 of Porcupine's test histories with 8.5 times
the steps the slowest of them needed. In Go, 10,000,000 steps of the etcd
model take about 0.6 seconds, extrapolated from a measured 69 ms for
1,177,310 steps.

The time of a step depends on the implementation, and the step count does
not. A memo that keys its buckets on the set of calls alone scans every
state of that set on each lookup. On the synthetic queue histories, such a
memo ran for more than ten minutes on one row of 10 histories, and a memo
that also hashes the state checked all 28 rows in 8.4 seconds. Every
implementation hashes the state for that reason, in a way of its own.

The time limit is off by default. A time limit makes `undecided` depend on
the machine, and `undecided` fails the test. A long job sets one, and the
record states which limit stopped the search. The limit reads the platform
clock and not the seat's, as the property engine's `shrink-time` does,
because it limits the job and states nothing about the history. Under a
controlled clock that never advances by itself, a limit on the seat's
clock would never end a check.

The memo stores at most one configuration per step. A configuration
contains a set of calls, which an implementation can store in one bit per
call of the partition, and its states. A partition of 4,096 calls at the
full budget can use about 5 GB for call sets. The partition is the unit of
memory, so partitioning by key bounds it.

The checker searches the partitions in order. It stops at the first
violated partition and reports it. When no partition is violated, it
reports the first undecided partition, or passes. With n workers, it
searches up to n partitions at once and reports what one worker would.

### The frontier

The frontier of a search is its first configuration, in search order, with
the largest set of linearized calls. In a violated search, the model
rejects every call that could follow the frontier, in every one of its
states. An accepted call would have produced a larger configuration, or a
configuration of that larger size already in the memo, and either one
contradicts the frontier's size. In an undecided search, the frontier is
the largest configuration found before the search stopped, and the record
lists the candidates the search had tried there.

The record states the frontier's order of calls, its states and those
candidates. Knossos reports the same parts as `:previous-ok`, the model
state and `:final-paths`. A reader sees the order the search could build,
the state after it, and why no remaining call fits.

A smaller violated history is not reported. Linearizability is not closed
under sub-histories. A linearizable history of `put(1)` followed by
`get → 1` has the violated sub-history `get → 1`, because nothing wrote 1.
The property engine instead shrinks the test that produced the history.
The call site of `linearizable` is the failure identity, so the shrinker
reduces the workload and the schedule and checks each candidate's new
history.

### A model built from the subject

```text
model-from(factory) -> Model
    A model whose state is the sequence of calls applied so far. step builds
    a fresh subject with factory, applies the sequence, applies the call, and
    accepts it when the subject's output equals the recorded output under
    the standard's equal. A call whose outcome is unknown is accepted.
    Two states are equal when their sequences are equal.
```

A caller with a deterministic subject and no written model gets a check of
atomicity. The subject's own sequential behaviour is the specification, so
the check finds a call that is not atomic and cannot find a call whose
sequential result is wrong. A machine of the property engine checks the
latter against a written model.

The subject must give the same outputs for the same sequence of calls. A
subject with hidden state gives different outputs on replay. A cache keyed
by object identity does, and so does a structure that a garbage collector
changes. The check then reports violations that did not happen.

Each step replays the sequence. A step at depth d costs d calls of the
subject. States that differ only in the order of commuting calls are not
equal. The memo merges fewer configurations for such a model than for a
written one.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The outcomes and the detail fields. How the checker reads `ok`, `fail`, `unknown` and pending calls. Precedence from event order. Partitions from keys, and their order. The search, its candidate order, its restart rule and its memo key. A step as the unit of the budget, the default budget, and the rule that reports the first violated partition, then the first undecided one. The frontier's definition. `model-from`'s steps and equality. The outcome of a check on n workers equals the outcome on one |
| Named | `linearizable`, the model and its members, `model-from`, the options |
| Declared | `workers` in a language whose checker cannot run on more than one thread |
| Free | How a frontier renders, including an HTML timeline. How a language stores a set of calls. A hash that agrees with `equal`. Whether a model is a struct of functions, an interface or an object |

### Conformance

The corpus states a check as a history and the name of a model:

```json
{ "id": "linearizable/a-read-after-a-completed-write-misses-it",
  "model": "register",
  "history": [
    { "invoke": 0, "client": 0, "operation": "write", "args": [{ "type": "int", "value": 1 }], "keys": [{ "type": "string", "value": "x" }] },
    { "ok": 0, "output": { "type": "null" } },
    { "invoke": 1, "client": 1, "operation": "read", "args": [], "keys": [{ "type": "string", "value": "x" }] },
    { "ok": 1, "output": { "type": "int", "value": 0 } }
  ],
  "expect": "fail",
  "detail": { "outcome": "violated", "steps": 2 } }
```

The history is a script in the history seam's JSON form. An entry with
`invoke` opens a call, and an entry with `ok`, `fail` or `unknown`
completes the call it names. Each implementation records the entries
through its history seam, in order, and builds the named model natively, as
it builds a named subject. The definition states the named models in a
`models` section of `assertions.yaml`, beside the subjects.

The named models:

| Model | Operations | State | Absent output |
|---|---|---|---|
| `register` | `write(v)`, `read() → v` | One value, initially 0 | A read accepts any state |
| `cas-register` | `write(v)`, `read() → v`, `cas(from, to) → bool` | One value, initially 0 | A `cas` takes effect when `from` equals the state |
| `key-value` | `put(k, v)`, `get(k) → v`, `append(k, s)` | A map from keys to strings, each initially empty | As `register`, per key |
| `queue` | `enqueue(v)`, `dequeue() → v or empty` | A sequence | A `dequeue` removes the head when one exists |
| `set` | `add(v)`, `remove(v) → bool`, `contains(v) → bool` | A set | A `remove` removes the value when present |
| `lossy-register` | `write(v)`, `read() → v` | One value; a write leaves either the old or the new value | As `register` |

The vectors:

| Kind | Each case states | And pins | Count |
|---|---|---|---|
| Verdicts | A history and a named model | `passed` or `violated` and the steps spent | 2 per model, 12 |
| Frontiers | A violated history | The frontier's order, states and candidates | 1 per model, 6 |
| Completions | A history with `fail`, `unknown` and pending calls | The verdict | 4 |
| Partitions | A history with shared keys and a call over every key | The partitions, their order and the reported partition | 3 |
| Budget | A history and a budget below its need | `undecided`, the steps and the frontier | 2 |
| Workers | A history with three partitions, on four workers | The outcome on one worker | 1 |

That is 28 cases, in `corpus/history/linearizable.json`. People write the
inputs in `corpus/history/linearizable.yaml` beside it. `make render`
computes the outputs with an executable reference of the search in
`tools/`, as it does for `corpus/prop/`, and the gate renders every vector
again.

Before acceptance, the reference decides Porcupine's 108 test histories,
with Porcupine's verdicts as the expectation. Porcupine's etcd histories
come from a repository that states no licence, so they are measured
against and not published.

### Names

| Id | Go | Python | Rust | TypeScript | Java, Kotlin |
|---|---|---|---|---|---|
| `linearizable` | `history.Linearizable` | `history.is_linearizable` | `history::is_linearizable` | `history.isLinearizable` | `History.isLinearizable` |
| `model` | `history.Model` | `history.Model` | `history::Model` | `history.Model` | `Model` |
| `model.init` | `Model.Init` | `Model.init` | `Model::init` | `Model.init` | `Model.init` |
| `model.step` | `Model.Step` | `Model.step` | `Model::step` | `Model.step` | `Model.step` |
| `model.equal` | `Model.Equal` | `Model.equal` | `Model::equal` | `Model.equal` | `Model.equal` |
| `op` | `history.Op` | `history.Op` | `history::Op` | `history.Op` | `Op` |
| `history.model-from` | `history.ModelFrom` | `history.model_from` | `history::model_from` | `history.modelFrom` | `History.modelFrom` |
| `history.budget` | `history.Budget` | `history.budget` | `history::budget` | `history.budget` | `History.budget` |
| `history.time-limit` | `history.TimeLimit` | `history.time_limit` | `history::time_limit` | `history.timeLimit` | `History.timeLimit` |
| `history.workers` | `history.Workers` | `history.workers` | `history::workers` | `history.workers` | `History.workers` |

That is 10 rows, 60 names. `linearizable` takes the naming table's
spelling for an adjective. In the table, `pure` is `Pure` in Go and
`is_pure` in Python. A type's id is bare, as in the table's types. A
member's id joins the type's id and the member's name. The fields of an op
are named with its type. The history itself is named with its seam.

### Versioning

| Change | Version |
|---|---|
| Adding `linearizable`, its model, its options and its named models | Minor |
| A new named model or option | Minor |
| A change to the frontier's definition | Minor; the verdict does not change |
| A change to the search, its candidate order, the step unit or the default budget | Major; a history can move between `passed` and `undecided` |
| A change to how the checker reads a completion | Major |
| A change to a named model's semantics | Major |

### Measurements

| Workload | Steps | Source |
|---|---|---|
| Porcupine's 108 test histories, the most expensive partition | Median 272.5, 90th percentile 21,128, maximum 1,177,310 | Step counter in Porcupine v1.3.1 |
| Register with unique writes, 2 clients, 1,024 calls, 10 seeds | Median 1,176 to 1,231 across write shares of 0.3 to 0.7 | Synthetic linearizable histories |
| Register, 4 clients, 2,048 calls | Median 4,711 to 6,088 | The same |
| Register, 8 clients, 4,096 calls | Median 159,222 to 319,099 | The same |
| Queue, 2 clients, 16 calls, enqueue share 0.7 | Median 24, at most 262 | The same |
| Queue, 2 clients, 64 calls, enqueue share 0.7 | Median 890, at most 238,002 | The same |
| Queue, 2 clients, 256 calls, enqueue share 0.7 | Every one of 10 histories above 1,000,000 | The same |
| Queue, 2 clients, 1,024 calls, enqueue share 0.3 | Median 1,153 | The same |

The register rows show the search linear in the length at a fixed number
of clients, and the cost per call rising with the clients, as Lowe's bound
predicts. The queue rows show the cost rising with the queue's length: a
queue that dequeues more often than it enqueues checks in linear time, and
one that grows passes a million steps at 256 calls with two clients. A
concurrent section of 16 calls checks in a few hundred steps at most.

## Alternatives considered

### A. Leave the relation undeclared

The standard could record linearizability as absent and point callers at
the tools above. A checker is a research artefact, and those tools are
mature.

**Why not:** the tools disagree on when to give up, on what a crashed call
means and on what to report. A Go project and a JVM project that test one
protocol would get verdicts with different meanings. The checker is also
small. Porcupine's checker and model types are 905 lines of Go.

This is the strongest alternative for transactional isolation, which needs
a different workload and a different algorithm, and is specified
separately for that reason.

### B. Drive an existing checker in each language

**Why not:** wrapping five tools wraps their five choices on those three
questions. Porcupine's `Unknown` is a wall-clock timeout that its
documentation lets a caller read as a pass. Knossos's `:unknown` is memory
exhaustion. Neither is reproducible on another machine.

### C. Report only passed and violated

A search that uses up its budget could report `passed`, since it found no
violation.

**Why not:** that claims something unproven, at the moment the history is
most complex. Porcupine's documentation offers this reading, and the
standard does not.

### D. Search without partitioning

**Why not:** Horn and Kroening measured partitioning by key at three times
faster on average, and an order of magnitude less memory, over about 700
histories of four threads with 70,000 operations each. On Intel TBB's
concurrent set it took 6 s and 672 MiB against 101 s and 9,792 MiB.

### E. A partition function from the caller

Porcupine takes a partition function and lets the model be written per
partition.

**Why not:** a caller then writes two models, one over the full state and
one per partition, and nothing checks that they agree. Keys declared on
each call partition the history and keep one model.

### F. A tree search, or a tree search and a graph search in competition

Lowe's tree searches were faster than the graph searches on most runs, and
a competition of the two was slightly faster than either.

**Why not:** a tree search failed to finish on 1 to 5 of 50 runs where the
graph search finished, and a competition makes the outcome depend on which
search finishes first on a given machine. A competition also needs two
specifications of the model, an immutable one and an undoable one.

### G. Lowe's just-in-time candidate rule

Lowe's just-in-time graph search linearizes calls only when a return
forces them, and he measured it as faster than Wing and Gong's graph search
on queues and on long map histories.

**Why not:** its candidate rule enumerates sequences of pending calls of
other processes, which is more to specify exactly in five languages. Its
advantage was measured on histories of 2^11 operations per worker. A
generated concurrent test of two clients is far shorter, and the measured
cost there is about one step per call. If a generated workload uses up the
budget under Wing and Gong's rule and finishes under Lowe's, this
alternative becomes the design.

### H. An algorithm for one data type

Lowe's queue algorithm decides queue histories on which every generic
search stops at its limit. Emmi and Enea give polynomial algorithms for
stacks, queues, sets and maps over histories in which no value is added
twice.

**Why not:** each is a second path to the same verdict, implemented five
times, with its own budget and frontier. The generic search reports such a
history as undecided instead of running without end. A generated test caps
its concurrent section at 16 steps, which bounds a queue partition's
concurrent enqueues. A generated workload of a collection type that uses
up the default budget at two clients reverses this.

### I. Shrink the history to a smaller violated history

**Why not:** linearizability is not closed under sub-histories, as the
frontier section shows. A minimal violated sub-history can blame calls that
had nothing to do with the violation.

### J. Weaker conditions: sequential consistency, quiescent consistency, quasi-linearizability

Lincheck checks quiescent consistency, quantitative relaxation and
quasi-linearizability beside linearizability.

**Why not:** no shape in the catalogue of relations this standard serves
states any of them. Sequential consistency drops real-time precedence and
keeps per-process order, and the search above handles it with that one
change to the candidate rule. A relation that states one of these
conditions reverses this.

## Drawbacks

- **Five implementations of a search.** Porcupine's checker and model types
  are 905 lines of Go, and Horn and Kroening's checker with its tests is
  about 4,000 lines of C++. Each implementation adds the search, the
  partitioner, the record and `model-from`, plus the executable reference
  in Python.
- **The caller writes a model.** A model is a second implementation of the
  subject's semantics, and a wrong model reports violations that did not
  happen. `model-from` removes that cost for a deterministic subject and
  checks atomicity only.
- **`equal` must be exact, and nothing checks it.** A coarse equality turns
  a linearizable history into a violated one.
- **Queues are exponential under concurrent enqueues.** The generic search
  reports a long, enqueue-heavy queue history as undecided.
- **`undecided` is a third failure.** A runner that knows pass and fail
  meets a failure that states no violation.
- **Memory follows the budget.** A partition of 4,096 calls can use about
  5 GB for call sets at the full budget.
- **The naming table grows by 10 rows**, 60 names.
- **The corpus grows by 28 cases**, and this repository gains an executable
  reference of the search.

## Unresolved and future work

None. The measurements before acceptance are the Go and Python step costs
at the default budget, and the reference's verdicts on Porcupine's test
histories.

## References

| What | Where |
|---|---|
| Herlihy and Wing, linearizability, the locality theorem and pending invocations | <https://doi.org/10.1145/78969.78972> |
| Wing and Gong, the search | <https://doi.org/10.1006/jpdc.1993.1015> |
| Gibbons and Korach, NP-completeness | <https://doi.org/10.1137/s0097539794279614> |
| Lowe, the memo, the just-in-time search, tree and graph measurements, the queue algorithm | <https://doi.org/10.1002/cpe.3928> |
| Horn and Kroening, P-compositionality | <https://arxiv.org/abs/1504.00204> |
| Emmi and Enea, collection types | <https://doi.org/10.1145/3158113> |
| Knossos | <https://github.com/jepsen-io/knossos> |
| Porcupine v1.3.1 | <https://github.com/anishathalye/porcupine/tree/v1.3.1> |
| Lincheck | <https://doi.org/10.1007/978-3-031-37706-8_8> |
| Line-Up | <https://doi.org/10.1145/1809028.1806634> |
| Claessen et al., `eqc_par_statem` and PULSE, ICFP 2009 | <https://publications.lib.chalmers.se/records/fulltext/125252/local_125252.pdf> |
| The evidence and measurements behind this design | Research-0004 |
| The history seam | RFC-0003 |
| Named subjects in the corpus | RFC-0007 |
| The property engine, its shrinker and `shrink-time` | RFC-0010 |
| Property forms, which this assertion does not have | RFC-0011 |
| Machines and concurrent runs | RFC-0012 |
| Transactional isolation | RFC-0015 |
