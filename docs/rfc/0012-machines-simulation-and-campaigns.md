---
rfc: 0012
title: Machines, simulation and campaigns
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-01
updated: 2026-10-05
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0012: Machines, simulation and campaigns

## Summary

This adds machines, deterministic simulation and campaigns to the
property engine:

- **Machines.** A model-based test runs a sequence of actions against a
  subject, records each call in a history, and checks the history against
  a pure model of the subject after every step. It checks an invariant
  after every step and liveness once the run has settled. The same
  machine runs a section of its steps from two or more clients at once,
  and checks that section's history for linearizability against the same
  model. A machine without a model leaves its checks to the invariant and
  the liveness check, such as an isolation check of the history. A trace
  of actions, from a failure report or from production, runs as a case
  and shrinks like one.
- **Simulation.** A deterministic simulation takes every decision it
  makes, which task runs, which message is lost, how far the clock moves,
  from the case. A failing run of thousands of steps then shrinks to the
  few that matter, with no code from the caller.
- **Campaigns.** A search that runs for hours keeps the cases that
  found something new and explores near them, where an ordinary run
  generates every case at random.

## Motivation

### A stateful subject fails after a sequence, not on an input

A store, a queue or a replicated log fails after a sequence of
operations. Model-based testing generates the sequence, applies each
step to the subject and to a model of it, and compares the two.

Libraries differ in what happens when an action cannot run in the
current state:

- fast-check generates its commands without the model and skips a
  command whose `check` returns false. Its shrinker then removes the
  commands that never ran.
- jqwik chooses each step from the actions whose precondition is true
  in the current state.
- proptest's state machines generate the whole sequence from the model
  before the subject runs, and filter it with preconditions. Their
  documentation warns that preconditions that are hard to satisfy can
  fail a test by exceeding the maximum number of rejections.

An engine that rejects a step and generates again spends cases on
rejections, and can fail a test because no action was enabled, whatever
the subject did.

### A concurrent subject fails under an interleaving, and the sequential model can judge it

A subject that clients use at once fails when two calls interleave
wrongly, and the sequential test passes. Lu et al. examined 105
concurrency bugs from MySQL, Apache, Mozilla and OpenOffice: 101 involve
no more than two threads, and 96% manifest when a particular order
between two threads is enforced.

Quviq's `eqc_par_statem`, OCaml's STM and Lincheck test concurrency with
the model that the sequential test already has:

- `eqc_par_statem` runs a sequential prefix and two parallel
  branches, and searches the interleavings with the `next_state` and
  `postcondition` of `eqc_statem`. Its authors report that this needs "no
  further investment in developing a parallel specification".
- STM runs a sequential prefix and two parallel domains against a model
  with `next_state`.
- Lincheck checks concurrent scenarios against a sequential specification
  class.

In each of them, the model is separate from the code that calls the
subject, so the check can run the model over any order of the recorded
calls. A model written inside an action's body, beside the call to the
subject, serves the sequential test only.

A test on real threads does not replay: the operating system schedules
them. OCaml's Lin and STM repeat each parallel instance and fail when one
repetition fails, because "CPU scheduling and garbage collection may hinder
reproducibility". A simulation takes the schedule from the case instead,
and replays.

### A simulation reproduces from a seed and does not shrink

A deterministic simulation runs a system under a scheduler, a clock and
a fault model that the test controls, so one seed reproduces a run. A
seed has no smaller version, so a failing run of 100,000 steps is
debugged at its full length. fast-check's scheduler shows the gap: it
picks the next task at random from its own copy of the run's random
generator, and it does not shrink. When every decision the simulation
takes is a choice of the property engine, the shrinker reduces the run
the way it reduces any case: it deletes the steps, faults and messages
the failure does not need.

### Random generation rarely finds deep states

Three results bear on what an engine should do about states that random
generation rarely finds. Each acts on what a case may choose rather than
on the subject:

- Swarm testing omits whole features from each test, at random. In a
  week of testing C compilers, a machine using swarm testing found 104
  distinct crashes. An identical machine using the tuned default
  configuration of the same generator found 73.
- Targeted property-based testing steers generation towards inputs that
  score higher on a value the test reports. In one case study it found a
  counterexample after about 200 tests on average, against 1,188 for
  random generation, about 3.5 times faster in wall time.
- Zest mutates the choices behind a generator and keeps the inputs that
  covered new branches. On five Java programs it covered 1.03 to 2.81
  times as many branches of their semantic analysis as AFL and
  QuickCheck did. It also found 10 new bugs, each in at most 10 minutes
  on average.

## Detailed design

### Machines

A machine is a pure model of a subject and a set of named actions over
the subject:

```text
Machine
  model -> Model              optional; the linearizability checker's model: init, step and equal
  actions() -> [Action]       in a fixed order; the order sets which action is simpler
  invariant(case, state)      optional; runs after setup, after every sequential and drain step, and last
  settle(case, state)         optional; runs once, after the drain

Action
  name
  weight -> integer           optional, 1 by default; the relative frequency among the listed actions
  enabled(state) -> bool      optional; false removes the action from a sequential or drain step's list
  drain -> bool               optional, false by default; true lets the action take the steps of the drain
  input(case, state) -> Input optional; requests the step's input from the case
  run(case, client, input)    calls the subject and records each call in the case's history

steps(case, machine, options)
  mean        the average number of sequential steps, 30 by default
  max         the largest number of sequential steps, and of drain steps, 100 by default
  swarm       whether each case may disable whole actions, on by default
  clients     the clients of the concurrent section, 1 by default; 1 runs no concurrent section
  concurrent  the largest number of steps in the concurrent section, 16 by default
  scheduler   the task scheduler whose tasks run the section's clients; without it, real threads do
  repeat      the runs a case on real threads makes before it passes, 4 by default

Case
  history() -> History        the case's history, empty when the case starts
```

`state` is the first of the model states after the calls recorded so far.
A model with one next state per call has exactly one. `enabled` must be
true in every one of the states, and the runner calls it once per state.

A machine without a model has no state, and its members receive an absent
one. The runner then checks no history after a step or after the
concurrent section, and `invariant` and `settle` state every check. A
machine over a database checks isolation this way, with `serializable` or
`snapshot-isolation` over the case's history in `settle`.

A bounded queue, as a machine:

```go
func TestQueue(t *testing.T) {
	prop.ForAll(t, "a queue behaves like a slice", func(c *prop.Case) {
		n := c.Draw(prop.Integer[int](1, 1000), "capacity")
		q := NewQueue(n)
		written := 0

		stateful.Steps(c, stateful.Machine[[]int]{
			Model: history.Model[[]int]{
				Init: func() []int { return nil },
				Step: func(s []int, op history.Op) [][]int {
					if op.Operation == "put" {
						full := len(s) == n
						if op.Known && op.Output != !full {
							return nil
						}
						if full {
							return [][]int{s}
						}
						return [][]int{append(slices.Clone(s), op.Args[0].(int))}
					}
					if len(s) == 0 {
						if op.Known && op.Output != nil {
							return nil
						}
						return [][]int{s}
					}
					if op.Known && op.Output != s[0] {
						return nil
					}
					return [][]int{s[1:]}
				},
			},
			Actions: []stateful.Action[[]int]{{
				Name:  "put",
				Input: func(*prop.Case, []int) any { written++; return written },
				Run: func(c *prop.Case, client int, v any) {
					call := c.History().Invoke(client, "put", []any{v})
					call.OK(q.Put(v.(int)))
				},
			}, {
				Name: "get",
				Run: func(c *prop.Case, client int, _ any) {
					call := c.History().Invoke(client, "get", nil)
					if v, ok := q.Get(); ok {
						call.OK(v)
					} else {
						call.OK(nil)
					}
				},
			}},
			Invariant: func(c *prop.Case, s []int) {
				assert.Equal(c, q.Size(), len(s), "the queue and the model agree on size")
			},
		}, stateful.Clients(2))
	})
}
```

`stateful.Steps` runs inside a property body, and records every decision
as a choice of the case, in six parts:

1. **Swarm.** One choice per action, as the next section states.
2. **Setup.** A machine with a model checks the history that the case has
   recorded, as after every step. The invariant runs.
3. **Sequential steps.** Before each step, the runner lists the actions
   that swarm kept and that are enabled in every state. With none, the
   sequence ends and records no choice. Otherwise a continue flag decides,
   by the engine's collection rule with minimum 0, maximum `max` and
   average `mean`. An index into the list then chooses the action.
4. **The concurrent section**, with `clients` of 2 or more.
5. **The drain.**
6. **Settling.**

A step is a span labelled with its action's name, from its continue flag
to the end of its run. The shrinker deletes whole steps, removes runs of
them with `delete-span-chunk`, and swaps adjacent steps of one action with
`sort-siblings`. Inside the span, `input` requests the step's input from
the state, and `run` then calls the subject on client 0. So every input
of a step is a choice that the case recorded before the subject ran.

A random case picks the index with probability proportional to each
action's weight. The draw is one `below` of the sum of the listed
actions' weights, and the index is the first whose running sum exceeds
it. A list of one action consumes nothing from the random source. The
index has target 0, so the edge phase takes the first listed action. A
replayed case takes the recorded index, so weights shape what a run
explores and never what a stored case means.

`run` records every call it makes to the subject through the case's
history, with an invocation before the call and `ok`, `fail` or `unknown`
after it. A call can also complete in another step, as when a simulated
network delivers its reply. The action that delivers the reply records
the completion.

After every sequential step of a machine with a model, the runner checks
the history recorded so far with `linearizable` and the model. The check
treats the whole history as one partition, whatever keys its calls
declare, because the model is one state of the whole subject. A violated
check fails the case with the checker's record. An undecided check fails
it the same way, as an undecided `linearizable` fails a test. The next
step's state is the first state after the order the check found. A run
of one client records a sequential history, and each check costs one
model step per call. An action may still assert inside `run` what the
model does not state, such as the type of an error.

The counterexample lists the steps in order, each with its action's name
and the values its input requested. A map from names to functions and
Hypothesis's rule-based machines can both be written as a machine of this kind,
and each implementation offers the spelling its language prefers.

### Swarm

With swarm on, a case first makes one choice per action, in order. 0
disables the action for the whole case, and 1 keeps it. The choice has
target 0, and the edge phase keeps every action. A random case keeps each
action with probability 1/2, the coin toss of the swarm paper,
conditioned on keeping one action or more:

- Once an earlier action is kept, one coin of 1 in 2 decides.
- While every earlier action is disabled, the choice tosses one coin for
  its action and one for each later action, again until a coin comes up.
  It keeps its action when its own coin came up.
- The last action's choice, while every earlier action is disabled, has
  the bounds [1, 1] and consumes nothing, as a collection's flag below
  its minimum does.

Each non-empty set of n actions is then kept with probability
1 / (2^n − 1). A shrink moves each choice towards 0 where the failure
allows, so the minimal case keeps only the actions the failure needs. A
failure that needs none of the actions keeps the last one.

Swarm testing works for two reasons its authors identified. Some actions
prevent the behaviour a bug needs. And actions compete for the steps of a
case, so with all enabled no single one is repeated enough to find a
deep state. Their own example is a stack that fails once it has
more than 32 items. With push and pop equally likely, few tests ever
put 32 items on it. A swarm generator that first chooses a non-empty
subset of the two operations produces tests of pushes alone a third of
the time.

### Settling

After the last step, the runner drains the machine. Only the actions
with `drain` set take the steps of the drain, whether swarm kept them or
not. A ready task, a pending message and a due timer are drain actions.
Crashes, partitions, lost messages and new requests are not. A drain
without its drain actions would leave work undone that `settle` then
reports.

Before each drain step, the runner lists the drain actions enabled in
every state, chooses one by index as it chooses a sequential step's
action, and runs it on client 0. A drain step records no continue flag.
The check and the invariant follow it, as they follow a sequential step.
The drain ends when no drain action is enabled or when `max` drain steps
have run. Its steps are choices like any other, so they shrink, and a
machine without drain actions settles at once.

`settle` then checks what must be true after the subject has recovered:
every accepted write is readable, and every request has a reply. It runs
on the state of the last check. Every part of a case that records a call
ends with a check, so the last check has read the whole history. The
final invariant runs after `settle`. An invariant checks safety after
every step. `settle` checks liveness once. A deterministic simulation
test usually stops the faults, lets the system recover and then checks
liveness. The drain does the first two of those for the caller.

### Concurrent runs

With `clients` of 2 or more, a case continues after its sequential steps
with a concurrent section:

1. The section lists every step before any of them runs. Its length
   follows the engine's collection rule with a maximum of `concurrent`,
   16 by default, so its average is 5. Each step chooses a client,
   uniform over 0 to `clients` with target 0, and then an action by index
   among the actions that swarm kept and that state no `enabled`. With no
   such action, the section records no choice.
2. The runner requests each step's input as it lists the step, on the
   thread that runs the body, from the state after the sequential steps.
   A step's span covers its flag, its client, its index and its input.
   Generation ends before execution, so a replay requests the same
   choices.
3. Client 0 is the body's own client. The body runs client 0's steps in
   order, and then starts each of clients 1 to `clients` that has a step,
   at once. Each of them runs its steps in order. On real threads, the
   concurrency driver starts each client on a thread of its own. With a
   `scheduler`, each client runs as a task of the task scheduler. The
   runner spawns the tasks in client order and runs the scheduler until
   no task is ready.
4. When every client has finished, the runner checks the whole history
   with `linearizable` and the machine's model, when it has one. It drains
   the machine from the state after the order the check found, and runs
   `settle`.

An action that a concurrent step can choose has no `enabled`, because the
model's state at a concurrent step is unknown until the check orders the
calls. `eqc_par_statem` requires instead that every precondition be true
in every interleaving, which costs a search per generated test. A total
action makes that search unnecessary: the queue's `put` in the example
returns false when the queue is full.

The client choice has target 0, so the shrinker moves each step to client
0, before the other clients start, wherever the failure allows. In a
minimal counterexample, moving any step of clients 1 to `clients` to
client 0 loses the failure. `eqc_par_statem` gets the same result from a
shrink pass of its own, which moves commands from the parallel branches
into the sequential prefix. Its authors call the result minimally
parallel.

The defaults follow the evidence:

- Lu et al. found that 101 of 105 concurrency bugs involve no more than
  two threads. Lin and STM run two parallel domains, and `eqc_par_statem`
  two parallel branches.
- `eqc_par_statem` caps its parallel part at 16 commands, about 10,000
  interleavings in the worst case.
- The checker's cost grows with the clients. On synthetic register
  histories with unique writes, the median check took about 1.2 model
  steps per call with two clients, 2.3 to 3 with four, and 39 to 78 with
  eight.
- On queue histories, the cost also grows with the queue's length. With
  two clients that enqueue in 70% of their calls, the check needed at most
  262 steps for 16 calls, at most 238,002 for 64, and more than 1,000,000
  for every one of 10 histories of 256. A cap of 16 concurrent steps
  bounds the cost, because the sequential steps before the section add one
  model step per call.
- On the reference, three clients and 32 steps found only the bugs that
  two clients and 16 steps found, and their checks cost more, as the
  measurements in this RFC show.

A written value that a read must identify comes from a counter, as
`written` does in the example. An integer generator repeats an earlier
value of its case with probability 1/4, to find bugs that need two equal
keys. With two writes of one value, a read no longer maps to the one write
it observed. Deciding linearizability is polynomial for register histories
with that mapping, and NP-complete in general.

#### Real threads repeat a case

Real threads do not replay. A case whose concurrent section runs on real
threads runs `repeat` times, 4 by default, and fails when any run fails.
The replay before shrinking repeats the same way, and so does each shrink
candidate, which costs up to `repeat` runs of the shrink budget. A case
that fails once and then passes `repeat` replays ends as `flaky`.

On a Go probe over goroutines, a `repeat` of 4 ended 2 of 200 failing
seeds as `flaky`, against 34 at 1, for a median of 34 shrink runs against
15. A race between two operations appeared on real threads only where an
operation yields between its read and its write. Without the yield, none
of 200 seeds found it at any `repeat`.

Each language declares in its overlay whether its concurrent sections can
run as tasks of the task scheduler, which replays, or only on real
threads.

### Traces

A machine's counterexample is a list of entries in request order: a step
entry names an action, and the draws of that action follow it. The
`Draws` option, which runs a body first on stated draws, accepts the
same list:

```json
[
  { "label": "capacity", "value": { "type": "int", "value": 2 } },
  { "step": "put" },
  { "label": "v", "value": { "type": "int", "value": 1 } },
  { "step": "put" },
  { "label": "v", "value": { "type": "int", "value": 2 } },
  { "step": "get" }
]
```

The body runs on the trace once, and its choices come from the entries:

- A draw takes the next entry, which must be a draw entry with the draw's
  label. It decodes the choices that the entry's value runs backwards to.
  A draw past the last entry takes its targets.
- `steps` turns each step entry back into the choices of one step. Before
  the step it lists the actions, as it always does, and takes the index
  of the entry's action as the choice.
- The swarm choices keep the actions that the trace's step entries name,
  and disable the rest.
- A request outside these takes its target.

A concurrent step entry states its client: `{ "step": "put", "client": 1 }`.
The section starts at the first step entry with a client. Every later
step entry of the section states one. A drain step entry states the drain
mark: `{ "step": "deliver", "drain": true }`. The drain takes its step
entries in order. A drain step without an entry takes the target index.

A trace that the body cannot follow fails the test before any other case
runs. The failure gives the entry and one of these reasons:

- a draw entry with another label than the draw's
- a value that the draw's generator cannot produce
- a step entry that the runner cannot take at its position: an action
  that the step's list lacks, a step past its section's maximum, a client
  outside the clients, a concurrent step of a machine with one client, or
  a drain step after the drain has ended

A production incident, written as the operations the clients sent and
the faults the network applied, becomes a case the same way. It runs as
the first case of every run and shrinks to the steps that matter. Every
draw in an action's `input` has to come from a generator that runs
backwards. Converting a production log into a trace is the caller's code,
because the log's format is the caller's.

### Simulation

The engine supplies what makes a deterministic simulation reproducible
and shrinkable. The caller writes the simulator.

| A simulation needs | What supplies it |
|---|---|
| One source for every random decision | The case's `rand()`. The workload, the fault model and the simulated network take their randomness from the case |
| Time that moves only when the test moves it | The seat's controlled clock, which the case passes on, and `duration` for every delay |
| A scheduler | `steps`. A ready task, a pending message and a due timer are each an action, and the runner chooses among the enabled ones. The task scheduler, below, for a subject that starts its own tasks |
| Calls from several clients | Actions that start a call and record its invocation, and later actions that deliver the reply and record its completion. A concurrent section whose clients run as tasks |
| Calls whose outcome a fault hides | `unknown` completions in the case's history, which the check reads as calls that took effect or did not |
| A fault mix that differs between runs | Weighted actions and swarm |
| Liveness, checked after faults stop | The `drain` flag on the actions that let the system recover, the drain after the last step, and `settle` |
| Long runs | The engine's `max-choices` and the machine's `max`, raised for the run, `delete-span-chunk`, and `shrink-time` raised for the shrink |
| More than one core | The engine's `workers`, which give the inputs and the outcome of one worker |
| An incident to reproduce | A trace, run as the first case and shrunk |
| Detection of decisions taken outside the engine | The case's `observe`, and the divergence a `flaky` outcome reports |
| Hours of search | Campaigns |

Every decision the simulation takes from the case is a choice, so a
failing run shrinks like any other case. The shrinker removes the
faults, steps and messages the failure does not need, and moves every
delay towards zero, so the minimal run is also a short one.

Decoding and generation are the same in every language, so the same
applies across languages. Two simulations of one protocol, written in
two languages with the same sequence of requests, receive the same fault
schedule from the same seed.

The standard supplies no simulation runtime: no network model and no
fault library. Each of those is built on its language's concurrency model,
and no definition can make two languages schedule threads alike. It
supplies one scheduler, for the tasks that a subject starts through an
executor the test injects, or on a runtime that runs its tasks on one
thread. A subject that reads the wall clock, iterates an unordered map, or
lets the platform schedule its threads defeats replay. The engine cannot
prevent that. It finds the first step where a replay differs and reports
it.

### The task scheduler

```text
Scheduler
  new(case, strategy) -> Scheduler
      A scheduler that releases tasks on the thread that runs the body.
  spawn(task)
      Makes task ready. A subject starts its tasks through this, and the runner its clients.
  yield()
      Ends the running task's turn. The task becomes ready again, after every ready task.
  run()
      Releases one ready task at a time, in an order the case chooses,
      until no task is ready.
```

A released task runs until it yields or ends, and may spawn other tasks
while it runs. A yield outside a task, on the thread that runs the body,
continues at once, so a step on client 0 runs to its end. A task that
calls `run` of its own scheduler fails the test.

Each strategy chooses the task to release:

- **`uniform`** chooses an index into the ready tasks, in the order they
  became ready, uniform over them, with target 0 and edge 0. A release
  with one ready task records its choice and consumes nothing. Wherever
  the failure allows, a shrunk schedule releases tasks in the order they
  became ready, which is the order of a runtime with one event loop.
- **`pct(depth)`** follows PCT. Each task receives a priority when it is
  spawned, an integer in [0, 2^64 − 1] with target 0, and keeps it when
  it yields. The ready task with the highest priority runs, the earliest
  ready among equals, and a release makes no choice. Each run starts with
  depth − 1 change points, each an `optional` count of releases with
  target absent. At a change point, the task released at that count,
  counting the run's releases from 0, falls below every other task. A
  later change point puts its task lower still. Wherever the failure
  allows, shrinking removes the change points and sets every priority to
  0, which gives the `uniform` strategy's simplest schedule.

`uniform` is the default. PCT with a depth of 3 exposed 48 of SCTBench's
49 bugs, and controlled random scheduling 43, in Thomson, Donaldson and
Betts' comparison. Deligiannis et al. needed a priority-based scheduler for
4 of 11 bugs in Microsoft's MigratingTable that a random scheduler missed.
Both comparisons scheduled threads. On tasks that yield at every
operation, `uniform` found both races of the measurements in every seed,
and PCT found the stack's race in half of the seeds. Under PCT, a task
runs through its yields until a change point, so a race between two
operations needs a change point between them.

Partial-order sampling and reads-from fuzzing found more bugs than PCT on
the same benchmark. Both need to know which events conflict, and a task
scheduler releases tasks without seeing what they touch.

Each language connects the scheduler to its runtime: an executor that the
subject takes in Go, Java and Rust, an event loop for Python's asyncio, a
wrapper around promises in TypeScript, and a test dispatcher in Kotlin.
A language whose runtime suspends a task at a point the scheduler sees,
such as an `await`, spells `yield` as that point. fast-check's scheduler
wraps promises the same way and takes its order from its own random
generator, so its schedule neither replays from a stored case nor
shrinks.

### Campaigns

A campaign is a profile of the engine for a search that runs for hours.
`DOKIMI_ASSERT_PROP_PROFILE=campaign` runs consecutive seeds until
`DOKIMI_ASSERT_PROP_BUDGET` has passed on the platform clock, shrinks
and stores every distinct failure it finds, and fails the test at the
end with all. `DOKIMI_ASSERT_PROP_BUDGET` states the budget in whole
seconds, as a decimal number above 0. The budget reads the platform clock
on purpose: it limits the job and is not part of what a property means.
A `hermetic` run ignores both variables, and a run in a mutation run's
process ignores the `campaign` profile. Each runs as an ordinary run.

The case gains one member for it:

```text
Case
  target(label, score)
      Records a score this case achieved under label. A campaign
      explores near the cases with the highest score for each label. An
      ordinary run records it and generates as if it were absent.
```

An ordinary run ignores scores, so its inputs remain a function of the
seed and the case index, which the worker rule, the `ci` seed and the
corpus vectors depend on. Steering by score needs an optimisation
algorithm, and a campaign leaves that algorithm free. Targeted
property-based testing found counterexamples about 3.5 and 9 times
faster than random generation in two of its case studies, over runs of
hundreds to thousands of tests. That is a campaign's length, not an
ordinary run's. Hypothesis 6.168.3 interleaves its own target phase into
ordinary runs.

A campaign keeps a pool of cases. A case joins it when it counts a
`classify` label no earlier case counted, records an `observe`
fingerprint no earlier case recorded, or exceeds the best `target`
score for its label. Most further cases are mutations of a pool member:
one choice generated again, a span deleted or repeated, or a span
replaced by a span with the same label from another member. The rest are
random.

Labels, fingerprints and scores are the signals because they are the
same in every language. Code coverage is what Zest followed, and code
coverage is instrumented differently in each of the six languages, by
tools the standard does not control. A caller who wants coverage
guidance runs the property under the language's fuzzer through the fuzz
bridge.

The mutation heuristics are each implementation's own, so a campaign's
seed does not reproduce its search across languages. Every failure it
finds is stored as choices, and those replay in every language.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | The six parts of `steps` and their order. How a step chooses its action: the list, the continue flag, and the index by weight. The step count rule, with a mean of 30 and a maximum of 100. The swarm choices, their order, their target, their edge, the probability 1/2 and its conditioning on keeping one action. A step's input before its run, and the step's span. For a machine with a model, the check of the whole history as one partition after setup, after every sequential and drain step, and after the concurrent section. The concurrent section: its length rule with a maximum of 16, the client choice with target 0, client 0's steps before the others start, the tasks in client order, actions without `enabled`, and inputs requested before execution. `repeat` and its default of 4. The drain: which actions it runs, its steps without a flag, and when it stops. When `settle` and the invariant run. The task scheduler: when a task becomes ready, its strategies, their choices and their targets. What a machine's counterexample lists, how a step entry turns back into a choice, and which entries a trace refuses |
| Named | The machine, the action and their members, `steps` and its options, the case's `history` and `target`, the task scheduler, its members and its strategies, the `campaign` profile and its budget variable |
| Declared | Whether a language runs a concurrent section as tasks of the scheduler, on real threads, or both, and how it spells `yield` |
| Free | How a campaign mutates its pool. A campaign is a search, and what it finds is stored as portable choices. How a language connects the task scheduler to its runtime |

### Conformance

A machine takes callables, so the corpus tests it through named
subjects, as it tests the other assertions that take a callable:

| Subject | What it does | What the case states |
|---|---|---|
| `queue-loses-on-wrap` | A queue of a drawn capacity whose put at the last slot writes its value into the first slot | The minimal steps: capacity 2, two puts of 0 and 1, one get |
| `counter-overflows` | A counter whose third increment without a reset returns 0 | The minimal steps: 3 increments, swarm keeping only `increment` |
| `store-loses-on-crash` | A store that loses unflushed writes on a crash. A drain action flushes, and `settle` reads every acknowledged write | The failure comes from `settle`, after a put and a crash |
| `correct-queue` | A queue with no fault | Passes |
| `racy-counter` | A counter whose increment reads the count, yields to the task scheduler, writes the count plus one and returns it | Two clients under the task scheduler. The minimal case runs two increments on clients 1 and 2, which both return 1 |
| `correct-counter` | A counter whose increment is atomic | Passes with two clients |

The reference computes each case's minimal steps at the vector's seed.
From other seeds, the shrink of `queue-loses-on-wrap` can end at four
steps instead: a put, a get, a put and a get, every value 0, where the
second get returns null. The shrinker is the same in every language, so
every implementation shrinks to its vector's steps from its vector's seed.

Each of the first four subjects has a passing and a failing case, 8 in
all. The racy counter and the correct one add a case each. Three more
cases run traces:

- the minimal steps of `queue-loses-on-wrap` as a trace, which fails
- a trace whose second step is not enabled, which fails before any case
  runs
- the minimal steps of `racy-counter`, whose last two step entries state
  their clients

That is 13 cases. The minimal step sequences come from the executable
reference of the engine, as the engine's own shrinking vectors do.

### Names

| Group | Rows |
|---|---|
| The machine and the action | 2 |
| The machine's members: `model`, `actions`, `invariant`, `settle` | 4 |
| The action's members: `name`, `weight`, `enabled`, `drain`, `input`, `run` | 6 |
| `steps` and its options: `mean`, `max`, `swarm`, `clients`, `concurrent`, `scheduler`, `repeat` | 8 |
| The case's `history` and `target` | 2 |
| The task scheduler, `new`, `spawn`, `yield`, `run`, `uniform` and `pct` | 7 |

That is 29 rows, 174 names across six languages. Traces use the `Draws`
option and add no name. The model's own members are named with the
linearizability checker.

Machines, `steps` with its options, and the task scheduler are named in a
package of their own, `stateful`. Hypothesis, jqwik and proptest each give
their state machines a module of their own. The options of `steps` then
share no namespace with the options of a run. The case's `history` and
`target` are named with the case, in `prop`, because any property body
can call them.

### Versioning

| Change | Version |
|---|---|
| Adding machines, the task scheduler and campaigns | Minor |
| A change to how a random case weighs actions, keeps swarm choices or draws a step count | Minor; a seed reproduces only within one version |
| A change to how `steps` decodes its choices into actions, clients and swarm decisions, or to how a strategy decodes its choices | Major; a stored case replays as other steps |
| A change to when a task becomes ready, or to where a yielding task waits | Major; a stored case replays as another schedule |
| A change to how a step entry turns back into a choice | Major; a trace replays as other steps |

### Measurements

The step defaults, a mean of 30 and a maximum of 100, are chosen, not
measured. rapid averages 30 actions, Hypothesis caps a stateful test at
50 steps, and jqwik builds chains of 32 actions at 1,000 tries, and none
of them published a measurement.

The executable reference ran every other default against its
alternatives, on the conformance subjects and three subjects of its own:

- the swarm paper's stack, whose push onto 32 items drops its value
- a racy queue, whose put reads the tail, yields, and writes its value
  there, with a get that drains every value
- a racy stack, the stack run as tasks: push and pop read the size,
  yield, and then write it

Each subject ran in 1,000 seeds per setting, each seed one run of at
most 100 valid cases without a shrink. The first 100 seeds of each row
that found the bug ran again with shrinking. The checks after each step
ran with a budget of 100,000 steps and a memo limit of 2^22 bits,
because one check of a queue history passed 4 GB of memory with the
default limits in the Python reference. A run that ended at an undecided
check counts as undecided, not as a find.

Each cell of the next two tables gives the share of seeds that found the
bug within 100 cases, then the median and the 90th percentile of the
cases a find took.

| Subject | Swarm off | Swarm at 1/2 | Swarm at 3/4 |
|---|---|---|---|
| `queue-loses-on-wrap` | 100%, 2 (8) | 100%, 11 (20) | 100%, 5 (13) |
| `counter-overflows` | 100%, 2 (5) | 100%, 2 (7) | 100%, 2 (7) |
| `store-loses-on-crash` | 100%, 2 (5) | 100%, 8 (15) | 100%, 5 (11) |
| `correct-queue` | Passed in every seed | Passed in every seed | Passed in every seed |
| The swarm paper's stack | 10%, 52 (91) | 100%, 11 (22) | 100%, 15 (46) |

- **Swarm is on, at 1/2.** Without swarm, 900 of 1,000 seeds missed the
  stack's bug.
- **3/4 found no bug in more seeds than 1/2.** Both found every bug in
  every seed. At 3/4, the two bugs that need two actions took fewer
  cases. The stack's slowest find at 3/4 took 98 of the 100 cases,
  against 44 at 1/2.
- **The minimal steps** were 3 for `counter-overflows`, 2 for
  `store-loses-on-crash` and 33 for the stack. For `queue-loses-on-wrap`
  they were 3 in 48% to 65% of the shrunk seeds and 4 in the rest.

| Subject | Strategy | Found | Median cases (90th percentile) |
|---|---|---|---|
| `racy-counter` | `uniform` | 100% | 5 (12) |
| `racy-counter` | `pct(2)` | 99.3% | 16 (58) |
| `racy-counter` | `pct(3)` | 100% | 13 (47) |
| The racy stack | `uniform` | 100% | 19 (44) |
| The racy stack | `pct(2)` | 49.4% | 46 (88) |
| The racy stack | `pct(3)` | 50.3% | 44 (87) |

`uniform` found both races in every seed and in the fewest cases, and is
the default.

The concurrent section ran under `uniform`. Checker steps count every
check of a case, and the largest check is the most steps of one check.

| Subject | Clients | Maximum | Found | Undecided | Median cases | Checker steps per case | Largest check |
|---|---|---|---|---|---|---|---|
| `racy-counter` | 2 | 16 | 100% | 0% | 5 | 380 | 117 |
| `racy-counter` | 2 | 32 | 100% | 0% | 5 | 377 | 117 |
| `racy-counter` | 3 | 16 | 100% | 0% | 5 | 392 | 118 |
| `racy-counter` | 3 | 32 | 100% | 0% | 5 | 392 | 118 |
| The racy queue | 2 | 16 | 100% | 0% | 5 | 869 | 4,967 |
| The racy queue | 2 | 32 | 100% | 0% | 5 | 947 | 25,757 |
| The racy queue | 3 | 16 | 99.3% | 0.7% | 4 | 1,055 | 31,085 |
| The racy queue | 3 | 32 | 97.3% | 2.7% | 4 | 1,243 | 100,000 |

Two clients and 16 steps found both races in every seed, at the lowest
cost. A third client left 0.7% and 2.7% of the racy queue's runs
undecided, and 32 steps found no race in more seeds than 16 did. Both
raised the checker's cost: the queue's largest check took 4,967 steps at
two clients and 16 steps, and the whole budget of 100,000 at three
clients and 32. The default maximum is 16, and this RFC recommends a
section of two clients.

On goroutines, through the concurrency driver at a `GOMAXPROCS` of 4, a
Go probe ran `racy-counter`'s concurrent section in 200 seeds per row of
the next table. Each seed ran up to 100 cases, replayed its first
failing case, and shrank a confirmed one within 2,000 runs.

| The increment | `repeat` | Seeds that found it | Counterexample | Flaky | Median shrink runs | Minimal steps |
|---|---|---|---|---|---|---|
| Yields between its read and its write | 1 | 200 | 166 | 34 | 15 | 2 to 5 |
| Yields between its read and its write | 4 | 200 | 198 | 2 | 34 | 2 to 3 |
| Yields between its read and its write | 16 | 200 | 200 | 0 | 115 | 2 |
| Does not yield | 1, 4 and 16 | 0 | 0 | 0 | none | none |

- **`repeat` is 4.** It ended 1% of the failing seeds as `flaky`, against
  17% at 1, for 2.3 times the shrink runs. 16 ended none as `flaky`, for
  3.4 times the runs of 4.
- **Real threads expose a race only where an operation yields.** Without
  the yield, no seed found the race at any `repeat`. The task scheduler
  found it in every seed.

No alternative found a bug in more seeds than its default did. Every
default keeps the value this RFC proposed.

## Alternatives considered

### A. Actions that skip themselves

An action that cannot run in the current state rejects itself, and the
engine generates another. Each action is one function, and the machine
needs no precondition per action.

**Why not:** a precondition becomes a rejected step. A machine whose
actions are disabled in most states spends its cases generating again,
and a run can fail because no action was enabled, whatever the subject
did.
Listing the enabled actions first costs one call per action per step,
and every step then runs an action.

### B. Generate the whole sequence before running it

proptest's state machines generate a complete sequence of transitions
from the model first, then run it against the subject. The sequence
exists before the subject runs, so it can be inspected and shrunk
without the subject.

**Why not:** a sequential step requests its input after the steps before
it have run, from the state they left, such as a handle to close or an id
to read. A sequence generated in advance needs symbolic references for
those values and a pass that resolves them. Interleaving generation with
execution needs neither, and the engine's shrinker already works on the
recorded choices. A concurrent section is the exception. It requests every
input before its clients start, from the state after the sequential steps,
and its actions are total for that reason.

### C. Rules with bundles

A rule-based machine passes values between rules through named bundles:
one rule adds a handle to a bundle, and later rules draw from it. It
states the data flow between actions in the definition of the machine.

**Why not:** a model already has that data, and an action's `input`
requests a value from the model's state with `sampled-from`. Bundles would
be a second place to keep the same state, and one more concept to name six
times.

### D. A simulation runtime in the standard

A scheduler, a simulated network and a fault library, specified once.
Callers would get deterministic simulation without writing a harness.

**Why not:** each is built on its language's concurrency model. Go
schedules goroutines and JavaScript runs one event loop, and no
definition makes those agree. What the standard can make agree is where
every decision comes from and how a run shrinks, which is what this
proposal specifies. The task scheduler is the one exception. It decides
only which ready task runs next, and every language can take that
decision from a choice.

### E. Guide campaigns by code coverage

Zest followed code coverage, and coverage finds structure in the subject
that a label does not name.

**Why not:** every language instruments coverage differently, through
tools the standard does not control. A coverage-guided search is
available anyway, through the fuzz bridge and the language's own fuzzer.

### F. Fix the campaign's mutations

Specify the mutations, so a campaign's seed reproduces its whole search
in every language.

**Why not:** a campaign is a search whose heuristics should improve
without a new version of the definition. What it finds is already
portable, because every failure is stored as choices.

### G. Actions that update a model they share

Each action applies its inputs to the subject and to model variables that
the actions share, and asserts the subject's output against them. A
machine is then plain code, with no model function to write.

**Why not:** a concurrent section cannot run it. The model's state at a
concurrent step depends on an order that only a search finds, and the
search must copy, compare and step states without calling the subject. The
sequential test and the concurrent test would need two models of one
subject, which is the cost `eqc_par_statem`, STM and Lincheck avoid with
one pure model.

### H. The runner records each call from the action's return value

An action returns its output, and the runner records the invocation
before the action and the completion after it. The caller writes no
recording code.

**Why not:** an action could then make one call per step. It could not
complete a call in a later step, as a simulated network does when it
delivers a reply. The action also knows whether an error means that the
call took no effect or that its outcome is unknown, and the runner does
not.

### I. An all-zero swarm keeps every action

A case whose swarm choices are all 0 keeps every action. No case is
left without an action, and no choice is forced.

**Why not:** the shrinker moves every swarm choice to 0 wherever the
failure allows, and all zeros keep every action. The minimal case of a
failure that needs one action would then keep them all. It would name
no action that matters.

### J. A forced last choice over plain coins

Each action is kept on one coin of 1 in 2. The last choice keeps its
action when every earlier choice disabled one.

**Why not:** the last action is kept more often than the others. With
two actions, half of all cases keep the last action alone, against a
third under the conditioned coins. The order of the actions, which sets
which one is simpler, would then also set what a run explores.

### K. Drain every action that is not a fault

The drain runs every enabled action except the faults, until none is
enabled or `max` steps have run.

**Why not:** the drain then keeps issuing new requests. A queue machine
puts and gets for another `max` steps, and a simulation sends requests
that `settle` then finds unanswered. Only the actions that let the system
recover belong in the drain, and the caller marks them.

### L. Check each partition of the history apart

A machine checks its history as `linearizable` does, one partition per
key.

**Why not:** a machine's model is one state of the whole subject. A
partition by key would split that state, and the next step's state could
not come from the order the check found.

## Drawbacks

- **Determinism is the caller's discipline.** The engine reports where a
  replay diverged. It cannot make a subject that reads the wall clock or
  lets the platform schedule its threads reproducible.
- **Every shrink step of a simulation reruns the simulation.** The
  engine stops a shrink after 30 seconds on the platform clock, so a
  simulation that takes a minute per run does not shrink at all by
  default. A caller raises `shrink-time` for it, and the full budget of
  2,000 runs at a minute each takes 33 hours on one worker and about 4
  hours on 8.
- **Swarm changes what a run explores.** A case keeps all three of three
  actions with probability 1/7, so fewer cases exercise every action
  together. A bug that needs all three is found less often than without
  swarm. On the reference, the two bugs that need two actions took a
  median of 8 and 11 cases with swarm, against 2 without it.
- **The drain lengthens every case of a machine with drain actions.**
  After the last step it runs up to another `max` steps, 100 by default,
  before `settle`, and a shrink reruns them for every candidate.
- **A trace needs generators that run backwards.** An action whose
  draws use `map`, `filter`, `bind` or `composite` cannot replay a trace,
  and the caller rewrites those draws to use invertible generators.
- **A campaign does not reproduce its search across languages.** Its
  findings do.
- **The caller records each call, and writes a pure model for the checks
  after every step.** A model is a second implementation of the subject's
  semantics, and each call to the subject costs an action two lines: an
  invocation and a completion.
- **A machine with a model checks the history after every step.** A run
  of one client costs one model step per call per check, so a case of
  100 sequential steps costs about 5,000 model steps.
- **The check after every step inherits the checker's worst case.** A
  queue's state differs for each order of its calls, so the checker's
  memo merges few configurations. On the reference, a racy queue with
  three clients and 32 concurrent steps left 2.7% of its runs undecided
  at a budget of 100,000 steps, and each undecided check fails its case.
- **Concurrent actions must be total.** An action with a precondition is
  not available to a concurrent section.
- **At two clients, a random section runs a third of its steps on client
  0.** The client choice is uniform over 0, 1 and 2, and client 0's steps
  run before the other clients start, so they run at once with no other
  call.
- **A concurrent section on real threads does not replay.** Each case and
  each shrink candidate runs up to `repeat` times, and a race that a run
  hits rarely still ends as `flaky`.
- **A call that hangs in a concurrent section hangs the case.** The runner
  states no time limit for a section, and the test framework's own limit
  applies.
- **The naming table grows by 29 rows**, 174 names across six languages.

## Unresolved and future work

None.

## References

| What | Where |
|---|---|
| fast-check 4.10.2, the model runner | <https://github.com/dubzzz/fast-check/blob/v4.10.2/packages/fast-check/src/check/model/ModelRunner.ts> |
| fast-check 4.10.2, the scheduler arbitrary | <https://github.com/dubzzz/fast-check/blob/v4.10.2/packages/fast-check/src/arbitrary/_internals/SchedulerArbitrary.ts> |
| jqwik 1.10.1, action chains | <https://github.com/jqwik-team/jqwik/blob/1.10.1/api/src/main/java/net/jqwik/api/state/ActionChain.java> |
| proptest-state-machine 1.11.0, the reference state machine | <https://github.com/proptest-rs/proptest/blob/v1.11.0/proptest-state-machine/src/strategy.rs> |
| Hypothesis 6.168.3, the target phase in the engine | <https://github.com/HypothesisWorks/hypothesis/blob/v6.168.3/hypothesis/src/hypothesis/internal/conjecture/engine.py> |
| Groce, Zhang, Eide, Chen and Regehr, "Swarm Testing", ISSTA 2012 | <https://agroce.github.io/issta12.pdf> |
| Löscher and Sagonas, "Targeted Property-Based Testing", ISSTA 2017 | <https://doi.org/10.1145/3092703.3092711> |
| Padhye, Lemieux, Sen, Papadakis and Le Traon, "Semantic Fuzzing with Zest", ISSTA 2019 | <https://doi.org/10.1145/3293882.3330576> |
| Lu, Park, Seo and Zhou, "Learning from mistakes", ASPLOS 2008 | <https://doi.org/10.1145/1346281.1346323> |
| Claessen et al., "Finding race conditions in Erlang with QuickCheck and PULSE", ICFP 2009 | <https://publications.lib.chalmers.se/records/fulltext/125252/local_125252.pdf> |
| Midtgaard, Nicole and Osborne, "Multicoretests: parallel testing libraries for OCaml 5.0", OCaml Workshop 2022 | <https://github.com/ocaml-multicore/multicoretests> |
| Koval et al., "Lincheck", CAV 2023 | <https://doi.org/10.1007/978-3-031-37706-8_8> |
| Burckhardt, Kothari, Musuvathi and Nagarakatte, PCT, ASPLOS 2010 | <https://doi.org/10.1145/1735970.1736040> |
| Thomson, Donaldson and Betts, "Concurrency testing using controlled schedulers", TOPC 2016 | <https://www.doc.ic.ac.uk/~afd/papers/2016/TOPC.pdf> |
| Deligiannis et al., "Uncovering bugs in distributed storage systems during testing", FAST 2016 | <https://www.usenix.org/conference/fast16/technical-sessions/presentation/deligiannis> |
| The evidence on checking histories, and the synthetic measurements | Research-0004 |
| The evidence on schedules, faults and test size | Research-0005 |
| The history seam and the concurrency driver | RFC-0003 |
| The linearizability checker and its model | RFC-0004 |
| The property engine: choices, spans, the collection rule, the shrink passes, workers and the store | RFC-0010 |
| The `Draws` option and the generators that run backwards | RFC-0011 |
| The isolation checks that a machine without a model calls in `settle` | RFC-0015 |
