---
rfc: 0012
title: Machines, simulation and campaigns
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Draft
created: 2026-10-01
updated: 2026-10-01
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
  subject and a model of it, checks an invariant after every step, and
  checks liveness once the run has settled. A trace of actions, from a
  failure report or from production, runs as a case and shrinks like
  one.
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

A machine is a set of named actions over a subject and a model of it:

```text
Machine
  actions() -> [Action]       in a fixed order; the order sets which action is simpler
  invariant(case)             optional; runs after setup and after every action
  settle(case)                optional; runs once after the drain that follows the last step

Action
  name
  weight -> integer           optional, 1 by default; the relative frequency among enabled actions
  enabled(case) -> bool       optional; reads the model; false removes the action from the next choice
  fault -> bool               optional, false by default; true stops the action after the last step
  run(case)                   draws its inputs, applies them to the subject and the model, asserts

steps(case, machine, options)
  mean    the average number of steps, 30 by default
  max     the largest number of steps, 100 by default
  swarm   whether each case may disable whole actions, on by default
```

A bounded queue, as a machine:

```go
func TestQueue(t *testing.T) {
	prop.ForAll(t, "a queue behaves like a slice", func(c *prop.Case) {
		n := c.Draw(prop.Integer[int](1, 1000), "capacity")
		q, model := NewQueue(n), []int(nil)

		prop.Steps(c, prop.Machine{
			Actions: []prop.Action{{
				Name:    "put",
				Enabled: func(*prop.Case) bool { return len(model) < n },
				Run: func(c *prop.Case) {
					v := c.Draw(prop.Integer[int](math.MinInt, math.MaxInt), "v")
					q.Put(v)
					model = append(model, v)
				},
			}, {
				Name:    "get",
				Enabled: func(*prop.Case) bool { return len(model) > 0 },
				Run: func(c *prop.Case) {
					assert.Equal(c, q.Get(), model[0], "get returns the oldest value")
					model = model[1:]
				},
			}},
			Invariant: func(c *prop.Case) {
				assert.Equal(c, q.Size(), len(model), "the queue and the model agree on size")
			},
		})
	})
}
```

`prop.Steps` runs inside a property body. Before each step it lists the
enabled actions and chooses one by index into that list, so a
precondition removes an action rather than rejecting a step. A random
case picks the index with probability proportional to each action's
weight. A replayed case takes the recorded index, so weights shape what
a run explores and never what a stored case means. The number of steps
follows the engine's collection rule with the stated mean and maximum. A
step is a span labelled with its action's name, so the shrinker deletes
whole steps, removes runs of them with its chunk pass, and reorders
adjacent ones. When no action is enabled, the sequence ends.

The counterexample lists the steps in order, each with its action's name
and the values it drew. A map from names to functions and Hypothesis's
rule-based machines can both be written as such a machine, and each
implementation offers the spelling its language prefers.

### Swarm

With swarm on, a case first makes one choice per action, in order. 0
disables the action for the whole case, and 1 keeps it. A random case
keeps each action with probability 1/2, the coin toss of the swarm
paper, and keeps every action when the choices would disable all. The
target of each choice is 0, so a shrink disables every action the
failure does not need, and the minimal case names the actions that
matter by keeping only them.

Swarm testing works for two reasons its authors identified. Some actions
prevent the behaviour a bug needs. And actions compete for the steps of a
case, so with all enabled no single one is repeated enough to find a
deep state. Their own example is a stack that fails once it has
more than 32 items. With push and pop equally likely, few tests ever
put 32 items on it. A swarm generator that first chooses a non-empty
subset of the two operations produces tests of pushes alone a third of
the time.

### Settling

After the last step, the runner drains the machine. It disables every
action whose `fault` is set and keeps choosing among the other enabled
actions until none is enabled or another `max` steps have run. A ready
task, a pending message and a due timer run, while crashes, partitions
and lost messages do not. The drain steps are choices like any other, so
they shrink.

Once the drain ends, `settle` checks what must be true after the subject
has recovered: every accepted write is readable, and every request has a
reply. The final invariant runs after it. An invariant checks safety
after every step. `settle` checks liveness once. A deterministic
simulation test usually stops the faults, lets the system recover and
then checks liveness. The drain does the first two of those for the
caller.

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

`steps` turns each step entry back into a choice. Before the step it
lists the enabled actions, as it always does, and takes the index of the
named action as the choice. The swarm choices keep the actions the trace
names and disable the rest. A step whose action is not enabled at that
point fails the test before any other case runs, and the failure names
the step.

A production incident, written as the operations the clients sent and
the faults the network applied, becomes a case the same way. It runs as
the first case of every run and shrinks to the steps that matter. Every
draw an action makes has to come from a generator that runs backwards.

### Simulation

The engine supplies what makes a deterministic simulation reproducible
and shrinkable. The caller writes the simulator.

| A simulation needs | What supplies it |
|---|---|
| One source for every random decision | The case's `rand()`. The workload, the fault model and the simulated network take their randomness from the case |
| Time that moves only when the test moves it | The seat's controlled clock, which the case passes on, and `duration` for every delay |
| A scheduler | `steps`. A ready task, a pending message and a due timer are each an action, and the runner chooses among the enabled ones |
| A fault mix that differs between runs | Weighted actions and swarm |
| Liveness, checked after faults stop | The `fault` flag, the drain after the last step, and `settle` |
| Long runs | The engine's `max-choices` and the machine's `max`, raised for the run, the chunk pass, and `shrink-time` raised for the shrink |
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

The standard supplies no simulation runtime: no scheduler for threads or
tasks, no network model and no fault library. Each of those is built on
its language's concurrency model, and no definition can make two
languages schedule threads alike. A subject that reads the wall clock,
iterates an unordered map, or lets the platform schedule its threads
defeats replay. The engine cannot prevent that. It finds the first step
where a replay differs and reports it.

### Campaigns

A campaign is a profile of the engine for a search that runs for hours.
`DOKIMI_ASSERT_PROP_PROFILE=campaign` runs consecutive seeds until
`DOKIMI_ASSERT_PROP_BUDGET` has passed on the platform clock, shrinks
and stores every distinct failure it finds, and fails the test at the
end with all. The budget reads the platform clock on purpose: it
limits the job and is not part of what a property means.

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

### The model and linearizability

The model in a machine is the model a linearizability check needs: an
initial state, and a step that decides whether an operation's result
could have come from a state and which state follows. Running a
machine's steps from more than one thread and checking the recorded
history against the model is not proposed here. It depends on the
history and the checker, which are separate proposals.

### What is fixed and what is free

| Tier | What it covers here |
|---|---|
| Fixed | How `steps` chooses an action, by index into the enabled list. The step count rule, with a mean of 30 and a maximum of 100. The swarm choices, their order, their target and the probability 1/2. The drain after the last step, which actions it runs and when it stops. When `settle` and the invariant run. What a machine's counterexample lists, and how a step entry turns back into a choice |
| Named | The machine, the action and their members, `steps` and its options, `target`, the `campaign` profile and its budget variable |
| Free | How a campaign mutates its pool. A campaign is a search, and what it finds is stored as portable choices |

### Conformance

A machine takes callables, so the corpus tests it through named
subjects, as it tests the other assertions that take a callable:

| Subject | What it does | What the case states |
|---|---|---|
| `queue-loses-on-wrap` | A bounded queue that drops a value when its index wraps | The minimal steps: `capacity` puts, one get |
| `counter-overflows` | A counter that fails after 3 increments without a reset | The minimal steps: 3 increments, swarm keeping only `increment` |
| `store-loses-on-crash` | A store that loses unflushed writes on a crash and checks them in `settle` | The failure comes from `settle`, after a crash step |
| `correct-queue` | A queue with no fault | Passes |

Each subject has a passing and a failing case, 8 in all. Two more cases
run traces: the minimal steps of `queue-loses-on-wrap` as a trace, which
fails, and a trace whose second step is not enabled, which fails before
any case runs. The minimal step sequences come from the executable
reference of the engine, as the engine's own shrinking vectors do.

### Names

The machine and the action, their 8 members, `steps` with its 3 options,
and `target`. That is 15 rows, 90 names across six languages. Traces use
the `Draws` option and add no name.

### Measurements before acceptance

The step defaults, a mean of 30 and a maximum of 100, are chosen, not
measured. rapid averages 30 actions, Hypothesis caps a stateful test at
50 steps, and jqwik builds chains of 32 actions at 1,000 tries, and none
of them published a measurement. Swarm's 1/2 is the swarm paper's own
method, measured there against the all-features default and not
against another probability.

Before this proposal is accepted, the executable reference runs the four
conformance subjects and the stack from the swarm paper, each over 1,000
seeds. It runs them with swarm off, at 1/2 and at 3/4, and records the
share of runs that find each bug within 100 cases and the length of the
minimal step sequence. A default that finds a bug in fewer runs than an
alternative it was measured against is revised before acceptance.

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

**Why not:** an action here draws its inputs while it runs, from values
the subject has just returned, such as a handle to close or an id to
read. A sequence generated in advance needs symbolic references for
those values and a pass that resolves them. Interleaving generation with
execution needs neither, and the engine's shrinker already works on the
recorded choices.

### C. Rules with bundles

A rule-based machine passes values between rules through named bundles:
one rule adds a handle to a bundle, and later rules draw from it. It
states the data flow between actions in the definition of the machine.

**Why not:** a model already has that data, and an action draws from
the model with `sampled-from`. Bundles would be a second place to keep
the same state, and one more concept to name six times.

### D. A simulation runtime in the standard

A scheduler, a simulated network and a fault library, specified once.
Callers would get deterministic simulation without writing a harness.

**Why not:** each is built on its language's concurrency model. Go
schedules goroutines and JavaScript runs one event loop, and no
definition makes those agree. What the standard can make agree is where
every decision comes from and how a run shrinks, which is what this
proposal specifies.

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
  actions with probability 1/4, so fewer cases exercise every action
  together. A bug that needs all three is found less often than without
  swarm.
- **The drain lengthens every case.** After the last step it runs up to
  another `max` steps, 100 by default, before `settle`, and a shrink
  reruns them for every candidate.
- **A trace needs generators that run backwards.** An action whose
  draws use `map`, `filter`, `bind` or `composite` cannot replay a trace,
  and the caller rewrites those draws to use invertible generators.
- **A campaign does not reproduce its search across languages.** Its
  findings do.
- **The naming table grows by 15 rows**, 90 names across six languages.

## Unresolved and future work

- Running a machine's steps from more than one thread and checking the
  history against the model for linearizability is not proposed here.
- A scheduler that releases a single-threaded runtime's pending tasks in
  an order taken from the case, for JavaScript promises, Python's asyncio
  or a Kotlin test dispatcher, is not proposed here. It is a helper per
  language built on choices, and Go and Java have no equivalent.
- A simulated network or a fault library is not proposed here.
- Converting a production log into a trace is each caller's own code and
  is not proposed here.

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
