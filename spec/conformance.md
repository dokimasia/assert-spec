# What converges and what does not

An implementation of this standard is held to some things exactly, to
some things by name, and to some things not at all. This says which is
which, and how a difference gets recorded.

Everything here is a rule about a library. Nothing here is a rule about
how a caller writes a test, except where the two are the same thing.

## The four tiers

| Tier | What it means | Where it is recorded |
|---|---|---|
| **Fixed** | The same in every language. No exceptions and no overlay entry | The definition |
| **Named** | The same idea, spelled as the language spells things | The naming table |
| **Declared** | Absent, present and partial, or written to an artifact that the language chooses | The overlay, with a reason for each gap |
| **Free** | The language's own business | Nowhere |

A thing belongs to exactly one tier. Arguing that something should move
between tiers is a change to this document.

## Fixed

These are what the standard is. An implementation that differs here is
not an implementation of it.

**Which assertions exist.** The set is closed. A library may not add an
assertion to the set, and one it cannot supply is Declared rather than
quietly missing.

**What each assertion means.** The corpus states this as data and every
implementation runs the same cases. Meaning is not negotiable and it is
not a language's answer.

**Which values a failure carries.** An assertion reports the values the
definition names for it. What the rendered sentence says is Free; what
the failure holds is not.

**That there are two surfaces.** One stops the test at the first
failure. The other records and lets it carry on. A library offering only
one has not implemented the standard.

**That an assertion never calls a test framework.** An assertion reports
what it found. What happens next belongs to whatever it reported to, and
that is what lets one assertion serve a real test, a benchmark, and a
test that checks the assertion itself.

**That a test can read what an assertion reported without suffering
it.** Every implementation offers some way to drive an assertion and
inspect the outcome rather than being stopped by it. This is what the
corpus needs to run at all.

**That a seat can be used from more than one thread.** A test holds one
seat and hands it to every assertion in the body, and several of the
assertions run the subject somewhere else: one retries a body, one
watches for work that outlives its scope, one gives a subject a handle
and waits. A seat that loses a failure because two arrived at once
reports the wrong answer, and no test would see why.

A language whose runtime has one thread meets this without doing
anything, and says so in its overlay rather than leaving a reader to
work out which it is.

**What a recorded run states.** `recording.md` fixes the fields of a
call record and their encoding, the verdicts, the phases of a property's
cases, the opaque literal, the numbering, the switch and its values,
which calls a run records, and the order of a property's call records.
Every language states the same fields of a call, in the same encoding.
Only the text of an opaque value is the language's own.

**What a history records, and how a check decides.** A history records
every call in one order. The linearizability checker searches it by one
procedure within one budget. Each isolation check derives the
dependencies between transactions and searches their cycles by one
procedure. The history vectors pin the events, the entries that the
history refuses, and the verdict, the steps and the record of each
check. One history then gives one outcome and one record in every
language.

## Named

The same idea, spelled the way the language spells things. Each has a row
in the naming table, and the completeness gate checks the row is real.

**Every assertion.** `nil` is `Nil` in Go, `is_none` in Rust,
`isNull` in Java. Same assertion, three spellings, and none of them is a
divergence.

**Every relaxation.** Two of them, named the same way.

**Every type a caller touches**, and every member on it. The seats, the
scrubbers, the benchmark contract.

**Who supplies a capability.** A row may name something the language's
own test framework provides rather than something this library ships. Go
names `testing.T` for the seat that stops and the seat that records,
because `testing.T` already is both. That is a filled row, not an empty
one.

### The rule for a new spelling

A language spells something differently when its own conventions require
it. It does not spell something differently because someone picked a word
once.

`Fatalf` against `fail` is required: those are the members of
`testing.TB`, and matching them is what lets a `*testing.T` be a seat
with no adapter. `Msg` against `message` is not required by anything, and
a difference with no reason behind it converges.

The test is whether the difference would survive someone asking why. A
convention, a reserved word, a framework's existing interface, and a type
system's demands are all reasons. Having been written first is not.

## Declared

Recorded in the overlay, with a reason, and checked.

**An assertion the language cannot supply.** A `diverge` entry with a
stance and a reason. The mechanism exists because a gap nobody could
close and a gap nobody got to look identical until someone writes down
which it is.

**A corpus case the language cannot run.** A `skip` on the case, with
the reason, or a relaxation that the overlay declines. A runner that
cannot build a subject the case names, or cannot call the assertion,
fails the case. A skip that the definition does not declare is a gap
that nobody wrote down.

**An assertion supplied partly.** A `limit` entry with what it misses and
why. Rust's `no-task-leaks` sees tasks on a runtime and not a thread,
because nothing in its standard library enumerates threads.

**A recorder that can hide a fault.** The counter that orders a
history's events synchronizes the clients that record into it. That
synchronization can supply a memory barrier that the subject lacks. Go,
Java, Kotlin and Rust run threads on more than one core. The validator
requires each of their overlays to state a limit on `history`.

**A relaxation the language does not offer.** Rust offers neither,
because its types keep an absent container and an empty one apart and its
own equality already says NaN is unequal to itself.

**The artifact that contains the call records.** A language's `records`
entry states what its runner writes for a run. It also states where
each call record is in that artifact, and where the artifact states each
test's status. A `why` explains a gap. This entry states a place and has
no `why`.

An assertion is Declared absent or Declared partial, never both, because
a divergence must be missing and a limit must be present.

## Free

Not recorded, not checked, and not the standard's business.

**How a failure reads.** The record is Fixed and the sentence is Free.
`want 2, got 1` and `expected 2, got 1` are both right, each in its
place.

**Whether an assertion takes a seat at all.** This is the one that
surprises people, so it is worth saying plainly.

The standard requires that an assertion report rather than call a
framework, and that a test be able to read what it reported. It does not
require a seat parameter. Go passes one because Go has no choice: a test
fails through the `*testing.T` it was handed and there is no other route.
A language that fails by raising has a route, and an aborting assertion
there may take no seat at all.

The definition has always said this. Arity counts the arguments to an
assertion "excluding the failure seat", which is the definition declining
to have an opinion.

What a language may not do is drop the ability to read an outcome. If the
aborting surface takes no seat, then a test reads its outcome by catching
what it raised, and the recording surface still needs somewhere to record
to.

**Whether a type is a class, a struct, a trait or an interface.**

**How the library is packaged**, how many artifacts it ships, and what it
depends on.

**What the library offers beyond the standard.** An implementation may
ship anything it likes alongside. It may not call the extra thing an
assertion, and the completeness gate does not know about it.

**How a library writes a call record into its artifact.** The record and
the artifact are fixed and declared. The code that writes one into the
other is the library's.

## How each tier is checked

| Tier | Checked by |
|---|---|
| Fixed: meaning | The corpus, run against both surfaces and every call form of each |
| Fixed: the values of a failure record | The corpus: the record of every failing case states the case's assertion and the caller's message unchanged, and it contains exactly the fields that the assertion declares |
| Fixed: two surfaces, readable outcome | The corpus needs both to run at all |
| Fixed: the call record | The corpus, run with recording on: the call record of every case. The recording vectors: the call records of a property's runs |
| Fixed: the history and the checkers | The history vectors: the events of a script or of intervals, the entry that the history refuses, and the verdict, the steps and the detail of each linearizability and isolation check |
| Named | The completeness gate, against the naming table, with each member's arity as far as the language can read it |
| Declared | The validator, which refuses an entry with no reason and an overlay that states no artifact |
| Free | Nothing |

A difference that belongs in a tier and is not recorded there is the
failure this document exists to prevent. An unrecorded difference is
indistinguishable from an oversight, which is what every implementation's
seat names were until someone counted them.
