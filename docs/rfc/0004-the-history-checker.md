---
rfc: 0004
title: The linearizability checker
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
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
counts its work: the calls of the model's step function, and the size of
the memo of its search. A register or a key-value history from a
generated concurrent test of two clients checks in linear time. A queue's
cost grows with the queue's length, which the 16 steps of a concurrent
section bound. A search that uses up a limit ends as undecided instead of
running without end or running out of memory.

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

Searched by this design's executable reference, Porcupine's own 108 test
histories needed a median of 272.5 calls of the model's step function in
their most expensive partition, and every decided partition needed at most
1,177,310. Four partitions of one history of 50 clients, each with 195 to
230 calls and a concurrency of 10 to 12, were not decided within
10,000,000 steps. Measured on synthetic histories of a register with
unique writes, two clients needed about 1.2 steps per call at every length
up to 1,024 calls. The evidence and the method are in the research listed
under References and in Measurements.

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
| Partitioner | Removes the calls that failed, joins calls that share a key into partitions, and orders the partitions |
| Search | Searches each partition for an order the model accepts, in a fixed order, with a memo of configurations |
| Limits | Count the steps and the memo's size per partition, and stop a search at either limit |
| Report | Builds the failure record from the first partition that did not pass |

### The assertion

```yaml
"linearizable":
  arity: 3
  package: history
  summary: >
    Every partition of a recorded history has an order of its calls that
    keeps the history's precedence and that the model accepts. A fixed
    search decides it within a budget of model steps and a limit on the
    size of its memo. A search that uses up either is undecided, and an
    undecided history fails.
  detail_fields: [outcome, partitions, steps, partition, calls, concurrency, linearized, states, candidates, limit]
```

The arguments are the history, the model and the message. Options follow
the message. A check of a whole history is conclusive, so `linearizable`
aborts only, as `prop-for-all` and the golden-file and benchmark
assertions do.

`linearizable` has no property form. Its history comes from clients that
run at once, and a property generates such a history through a machine's
concurrent section. On real threads, the machine repeats the case,
because the operating system's schedule does not replay. In a
simulation, the case's choices schedule the clients. The property engine
shrinks the steps in both.

```go
func TestRegisterIsLinearizable(t *testing.T) {
	h := history.New()
	reg := NewRegister()
	outcomes := history.Concurrently(2, time.Minute, func(client int) (any, error) {
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
		return nil, nil
	})
	for _, o := range outcomes {
		assert.True(t, o.Finished, "every client finishes within a minute")
	}

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
| `violated` | The search of a partition tried every order within its limits and found none the model accepts | The partition and its frontier |
| `undecided` | The search of a partition used up a limit, and no partition was violated | The partition, the limit, and the frontier when the search stopped |

`undecided` fails the test. A check that could not decide has not passed,
for the same reason a property that tested no input has not passed.

The detail of a failing check:

| Field | Value |
|---|---|
| `outcome` | `violated` or `undecided` |
| `partitions` | The number of partitions |
| `steps` | The steps spent in the partitions up to and including the reported one, as one worker searches them |
| `partition` | The keys of the reported partition, in the order the history first declares them. An empty list means every key |
| `calls` | The number of calls in the reported partition |
| `concurrency` | The largest number of the reported partition's calls that are open at one event. An unknown or pending call is open to the end of the history |
| `linearized` | The calls of the frontier's order, in that order. Each states `call` and `completion`, the indices of its events, and its `process`, `operation`, `args` and `output` in the history's JSON form. A pending call states no `completion`, and a call whose outcome is unknown states no `output` |
| `states` | The model states after that order |
| `candidates` | The calls that could come next, in the form of `linearized`. The model rejected each of them in every one of those states |
| `limit` | For `undecided`: `steps`, `memo` or `time`. Null otherwise |

`calls` and `concurrency` state the two quantities that the search's cost
grows with: Lowe's bound is linear in a partition's calls and exponential
in its concurrency. A reader of an undecided check sees which one to
reduce.

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
  it. A call that the subject refused, such as a compare-and-set whose
  expected value differed, is an `ok` call with its output, as the
  observation seams state, so the model checks the refusal.
- A call with an `unknown` completion, and a pending call, has an absent
  output. It takes effect at some point after its invocation, or never.
  This is the definition of linearizability for a history with pending
  invocations. Such a call precedes no other call, and the search passes
  without it once every `ok` call is linearized, so a model may reject it
  in a state where it cannot take effect.
- Precedence comes from event order only. The checker reads no clock.

### Partitions

Each invocation declares the keys it touches, as typed literals. A call
that declares no key touches every key. The checker first removes the
calls that failed. It joins two of the remaining calls into one partition
when they share a key, and forms partitions as the connected components of
that relation. A call that touches every key puts the whole history into
one partition.

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
  entries   = the invocation events of the partition's calls, and the
              completion events of its ok calls, in event order
  done      = {}                      calls linearized so far
  states    = [init()]
  stack     = []                      (call, states before it)
  memo      = {}                      configurations seen
  steps     = 0
  entry     = the first entry
  loop:
    if entries contains no completion: return passed
    if entry is the invocation of call c:
      next = []
      for each state s in states, in order:
        if steps + cost(s) > budget: return undecided, limit steps
        steps = steps + cost(s)
        append the states step(s, c) returns to next, keeping the first
          of each group of equal states
      if next is not empty and (done + c, next) is not in memo:
        if (size of memo + 1) * calls of the partition > memo-limit:
          return undecided, limit memo
        add (done + c, next) to memo
        push (c, states); done = done + c; states = next
        remove c's entries from entries
        entry = the first entry
      else:
        entry = the entry after entry
    else:                             a completion whose call is not in done
      if stack is empty: return violated
      pop (c, previous); restore c's entries
      done = done - c; states = previous
      entry = the entry after c's invocation
```

`cost(s)` is 1 for a written model. For a model that `model-from` builds,
it is d + 1, where d is the number of calls in s.

The candidates at each point are the calls whose invocations come before
the first completion of a call not yet linearized, tried in event order. An
accepted step restarts from the first entry.

Two configurations are the same when their sets of calls are equal and
their lists of states contain the same states: each state of one list
equals a state of the other, and the two lists have one length. Each list
contains no two equal states, so the comparison ignores the order in
which a path produced them.

This is Wing and Gong's search with the memo of configurations that Lowe
introduced. Lowe measured the memo's effect: his tree searches, which keep
no memo, failed to finish within ten billion configurations on up to 5 of
50 map histories, where the graph search finished.

### The limits

| Option | Default | Meaning |
|---|---|---|
| `budget(steps)` | 10,000,000 | The steps one partition's search may spend |
| `memo-limit(bits)` | 2^33, which is 1 GiB | The bits one partition's memo may count for its sets of calls: one bit per call of the partition, for each configuration |
| `time-limit(duration)` | None | The wall time the whole check may take, on the platform clock |
| `workers(n)` | 1 | Partitions searched at once |

A step is one call of the model's step function. A configuration with three
states costs three steps. The search checks the budget before each step
and takes no step that would pass it. A search with a written model that
stops at the budget has spent exactly the budget.

Both limits are counted, so one history gives one outcome on every
machine. At the default budget, the reference gives Porcupine's verdict on
all 108 of Porcupine's test histories. Every partition but four needed at
most 1,177,310 steps, under an eighth of the budget. Those four partitions
are in one violated history of 50 clients, and the check reports that
history through a later partition that is violated. The full budget takes
0.6 to 1.8 seconds in Go and 18 to 23 seconds in Python, on the two
histories in Measurements.

The time of a step depends on the implementation, and the step count does
not. A memo that keys its buckets on the set of calls alone scans every
state of that set on each lookup. On the synthetic queue histories, such a
memo ran for more than ten minutes on one row of 10 histories, and a memo
that also hashes the state checked all 28 rows in 8.4 seconds. Every
implementation hashes the state for that reason, in a way of its own.

The memo stores at most one configuration per step. A configuration
contains a set of calls, which an implementation can store in one bit per
call of the partition, and its states. Without a limit, a partition of
4,096 calls at the full budget would use about 5 GB for call sets, and a
smaller machine would end the check by running out of memory. The memo
limit counts the call sets in bits, whatever an implementation stores, and
stops such a partition after 2,097,152 configurations with 1 GiB of call
sets. A machine case with RFC-0012's defaults records at most 116 calls
when each step makes one call, and a partition of that size uses up the
step budget first. The limit does not count the states, whose size
depends on the model.

The time limit is off by default. A time limit makes `undecided` depend on
the machine, and `undecided` fails the test. A long job sets one, and the
record states which limit stopped the search. The limit reads the platform
clock and not the seat's, as the property engine's `shrink-time` does,
because it limits the job and states nothing about the history. Under a
controlled clock that never advances by itself, a limit on the seat's
clock would never end a check.

The checker searches the partitions in order. It stops at the first
violated partition and reports it. When no partition is violated, it
reports the first undecided partition, or passes. With n workers, it
searches up to n partitions at once and reports what one worker would:
the same partition, and the steps of the partitions up to and including
it. The steps of a partition that one worker would not have searched do
not count.

### The frontier

The frontier of a search is its first configuration, in search order, with
the largest set of linearized calls. In a violated search, the model
rejects every call that could follow the frontier, in every one of its
states. An accepted call would have produced a larger configuration, or a
configuration of that larger size already in the memo, and either one
contradicts the frontier's size. In an undecided search, the frontier is
the largest configuration found before the search stopped, and the record
lists the candidates that the model had rejected there when the search
stopped.

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
    A model whose state is the sequence of the operations and arguments of
    the calls applied so far. step builds a fresh subject with factory,
    applies the sequence, applies the call, and accepts it when the
    subject's output equals the recorded output under the standard's equal.
    A call whose outcome is unknown is accepted. Two states are equal when
    they list equal operations, with arguments equal under the standard's
    equal, in the same order.
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

Each step replays the sequence. A step at depth d makes d + 1 calls of the
subject, and counts as d + 1 steps of the budget, so the budget bounds the
subject's calls as it bounds a written model's steps. The state leaves out
outputs, because a fresh subject replays only operations and arguments.
States that differ only in the order of commuting calls are not equal. The
memo merges fewer configurations for such a model than for a written one.

### Failure handling

| Condition | Behaviour |
|---|---|
| A partition's search uses up the step budget | `undecided`, with `limit` `steps` |
| A partition's memo would pass the memo limit | `undecided`, with `limit` `memo` |
| The whole check passes the time limit | `undecided`, with `limit` `time` |
| A panic or an exception in `init`, `step` or `equal`, or in a subject that `model-from` replays | The call ends with a fault that names the operation and the call, and its call record states the verdict `error` |
| A history without calls, or whose calls all failed | `passed` |

A model is the test's own code, so a panic in it is a bug in the test, and
not a verdict on the subject. The fault ends the check instead of ending
the test run without a record.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The outcomes and the detail fields, `calls` and `concurrency` included, and the form of a call in the record. How the checker reads `ok`, `fail`, `unknown` and pending calls. Precedence from event order. The removal of failed calls, partitions from keys, their order and the order of their keys. The search, its candidate order, its restart rule, its memo key, and the equality of two configurations' states as sets. A step as the unit of the budget, the check before each step, the default budget, and `model-from`'s d + 1 steps. The memo limit's count, one bit per call of the partition for each configuration, and its default. The rule that reports the first violated partition, then the first undecided one, and the steps of the partitions up to the reported one. The frontier's definition. `model-from`'s equality. The named models, their states and the order of the states a step returns. A fault for a panic in a model. The outcome of a check on n workers equals the outcome on one |
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
    { "ok": 1, "output": { "type": "null" } }
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
| `register` | `write(v)`, `read() → v` | One value, initially null | A read accepts any state |
| `cas-register` | `write(v)`, `read() → v`, `cas(from, to) → bool` | One value, initially null | A `cas` takes effect when `from` equals the state, and leaves the state otherwise |
| `key-value` | `put(k, v)`, `get(k) → v`, `append(k, s)` | A map from keys to strings that stores no empty string, so a key it does not store reads as empty | As `register`, per key |
| `queue` | `enqueue(v)`, `dequeue() → v`, which outputs `null` when the queue is empty | A sequence | A `dequeue` removes the head when one exists |
| `set` | `add(v)`, `remove(v) → bool`, `contains(v) → bool` | A set, listed in the order its values were added | A `remove` removes the value when present |
| `lossy-register` | `write(v)`, `read() → v` | One value, initially null. A write leaves the new value or the old one, in that order | As `register` |

The output of a write, a put, an append, an enqueue or an add is not
checked. Every named model accepts a call whose outcome is unknown in
every state.

The vectors:

| Kind | Each case states | And pins | Count |
|---|---|---|---|
| Verdicts | A history and a named model | `passed` or `violated` and the steps spent | 2 per model, 12 |
| Frontiers | A violated history | The frontier's order, states and candidates | 1 per model, 6 |
| Completions | A history with `fail`, `unknown` and pending calls, and a refused `cas` recorded as `ok` with the output false while the state equals `from` | The verdict | 5 |
| Partitions | A history with shared keys and a call over every key | The partitions, their order and the reported partition | 3 |
| Limits | A history and a budget or a memo limit below its need | `undecided`, the limit, the steps, `calls`, `concurrency` and the frontier | 3 |
| Workers | A history with three partitions, on four workers | The outcome and the steps on one worker | 1 |

That is 30 cases, in `corpus/history/linearizable.json`. People write the
inputs in `corpus/history/linearizable.yaml` beside it. `make render`
computes the outputs with the executable reference of the search in
`tools/history/`, as it does for `corpus/prop/`, and the gate renders every
vector again. A panic in a model is no data that a vector can state, so
each implementation tests the fault in its own suite.

The reference gives Porcupine's verdict on all 108 of Porcupine's test
histories, in two encodings:

- In Porcupine's encoding, every return of Porcupine's parser is an `ok`
  completion at its position, and the models are Porcupine's. The
  reference's steps equal those of a step counter added to Porcupine on
  each of the 105 histories that Porcupine searches to the end: the 102
  etcd histories and the three linearizable key-value histories.
- In the seam's encoding, a timed-out call completes as `unknown`, a call
  still open at the end of the log is pending, a refused compare-and-set is
  `ok` with the output false, and the models are the named `cas-register`
  and `key-value`.

Porcupine's etcd histories come from a repository that states no licence,
so they are measured against and not published.

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
| `history.memo-limit` | `history.MemoLimit` | `history.memo_limit` | `history::memo_limit` | `history.memoLimit` | `History.memoLimit` |
| `history.time-limit` | `history.TimeLimit` | `history.time_limit` | `history::time_limit` | `history.timeLimit` | `History.timeLimit` |
| `history.workers` | `history.Workers` | `history.workers` | `history::workers` | `history.workers` | `History.workers` |

That is 11 rows, 66 names. `linearizable` takes the naming table's
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
| A change to the search, its candidate order, the step unit, the default budget, or the memo limit's count or default | Major; a history can move between `passed` and `undecided` |
| A change to how the checker reads a completion | Major |
| A change to a named model's semantics | Major |

### Measurements

| Workload | Steps | Source |
|---|---|---|
| Porcupine's 108 test histories, the most expensive partition that the check searches | Median 272.5, 90th percentile 21,128, maximum 1,177,310 for 107 of the 108 | The reference, in Porcupine's encoding |
| Porcupine's `kv/c50-bad`, 50 clients, its 10 partitions | 4 undecided at 10,000,000, each with 195 to 230 calls and a concurrency of 10 to 12. The other 6 violated within 741,965 | The same |
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

The time of the full budget, 10,000,000 steps, on two histories that need
more, in five runs in Go and three in Python:

| History | Go | Python | Configurations in the memo |
|---|---|---|---|
| 18 concurrent writes of distinct values, then a read of a value no write wrote, etcd model | 0.60 to 0.70 s | 17.8 to 18.7 s | 1,261,695 |
| The partition of key `0` of `kv/c50-bad`, Porcupine's key-value model | 1.64 to 1.80 s | 18.0 to 22.8 s | 4,938,837 |

Go is Porcupine v1.3.1 with a step counter that stops it at the budget, and
Python is the reference. Porcupine's memo stores the same configurations.
On the second history it stores one fewer, because its counter stops it
after the last step and before that step's configuration is stored. A step
costs 60 to 180 ns in Go and about 2 µs in Python. The model's own cost
adds to that. The reference's named `key-value` model keeps its state as a
map of typed values, and takes 48 to 56 seconds on the same partition for
the same 4,938,837 configurations.

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

**Why not:** no relation of Research-0002's classification states any of
them. Sequential consistency drops real-time precedence and keeps
per-process order, and the search above handles it with that one change to
the candidate rule. A relation that states one of these conditions
reverses this.

### K. The cost of a passing check in its call record

The call record of a passing check states its steps and partitions, so a
reader of the records sees a check approach its budget before it fails as
undecided.

**Why not:** the call record of a pass states a detail for a property
alone, and a check's steps are reported when they matter, on the failure
that a budget causes. A consumer of call records that tracks budgets
reverses this.

### L. The shortest violated prefix

Linearizability is closed under prefixes, so the first completion after
which the history's prefix is violated is a sound place to point a reader
at.

**Why not:** finding it costs a search of each prefix in a binary search,
up to log2 of the events more searches, each within the budget. The
frontier already names its candidates with the indices of their events. A
reader who cannot find the violation from the frontier of a long history
reverses this.

### M. The process of a call in an op

`Op` states the process that made the call, so a model of a lock or a
lease can check that the process that releases is the one that acquired.

**Why not:** no named model needs it, and a caller whose model does can
pass the client in the call's arguments. Adding a member later is a minor version.
A named model whose operations depend on their caller reverses this.

### N. Check a history while it is recorded

The checker reads events as clients record them, and discards the part of
the search that no later event can change, so a long soak test checks in
bounded memory.

**Why not:** a test records its calls before it checks them, and the memo
limit bounds a check's memory. A soak test that records more calls than a
partition's limits allow reverses this.

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
- **Histories of many clients can use up the budget.** Four partitions of
  one of Porcupine's histories of 50 clients, each with a concurrency of
  10 to 12, are undecided at the default budget.
- **The full budget is slow in Python.** It takes about 20 seconds there,
  against under 2 seconds in Go.
- **`undecided` is a third failure.** A runner that knows pass and fail
  meets a failure that states no violation.
- **The memo limit counts call sets, not states.** A model with large
  states can still use more memory than the limit states.
- **`model-from` spends its budget fast.** A step at depth d costs d + 1
  steps, so a deep history uses up the budget sooner than with a written
  model.
- **The naming table grows by 11 rows**, 66 names.
- **The corpus grows by 30 cases**, and this repository gains an executable
  reference of the search.

## Unresolved and future work

None.

## References

| What | Where |
|---|---|
| Herlihy and Wing, linearizability, the locality theorem and pending invocations | <https://doi.org/10.1145/78969.78972> |
| Wing and Gong, the search | <https://doi.org/10.1006/jpdc.1993.1015> |
| Gibbons and Korach, NP-completeness | <https://doi.org/10.1137/s0097539794279614> |
| Lowe, the memo, the just-in-time search, tree and graph measurements, the queue algorithm, the bound in calls and concurrency | <https://doi.org/10.1002/cpe.3928> |
| Horn and Kroening, P-compositionality | <https://arxiv.org/abs/1504.00204> |
| Emmi and Enea, collection types | <https://doi.org/10.1145/3158113> |
| Knossos | <https://github.com/jepsen-io/knossos> |
| Porcupine v1.3.1 | <https://github.com/anishathalye/porcupine/tree/v1.3.1> |
| Lincheck | <https://doi.org/10.1007/978-3-031-37706-8_8> |
| Line-Up | <https://doi.org/10.1145/1809028.1806634> |
| Claessen et al., `eqc_par_statem` and PULSE, ICFP 2009 | <https://publications.lib.chalmers.se/records/fulltext/125252/local_125252.pdf> |
| The evidence and measurements behind this design | Research-0004 |
| The relations that the standard classifies | Research-0002 |
| The history seam and the concurrency driver | RFC-0003 |
| Named subjects in the corpus | RFC-0007 |
| The property engine, its shrinker and `shrink-time` | RFC-0010 |
| Property forms, which this assertion does not have | RFC-0011 |
| Machines and concurrent runs | RFC-0012 |
| Transactional isolation | RFC-0015 |
