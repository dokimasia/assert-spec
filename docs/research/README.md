# Research

Answers to questions about the world outside this repository, with the
sources behind them. An RFC or an ADR cites these by number.

| # | Question | Date | Status |
|---|---|---|---|
| [0001](0001-earning-a-place-in-five-ecosystems.md) | Which capabilities would make each implementation worth adopting in its own ecosystem? | 2026-08-30 | Answered |
| [0002](0002-what-the-assertion-layer-can-carry.md) | Which of the shape catalogue's 107 relations can the assertion standard carry? | 2026-08-30 | Answered |
| [0003](0003-what-property-testing-engines-establish.md) | Which property-testing engine capabilities have evidence behind them, and does any engine give the same inputs in more than one language? | 2026-10-01 | Answered |
| [0004](0004-deciding-linearizability-from-a-history.md) | What decides whether a linearizability check of a recorded history finishes, reports only real violations, and explains the ones it finds? | 2026-10-02 | Answered |
| [0005](0005-schedules-and-faults-that-find-bugs.md) | Which scheduling and fault-injection strategies have measured results for finding concurrency and distribution bugs, and how large must a test be? | 2026-10-02 | Answered |
| [0006](0006-checking-isolation-from-observed-histories.md) | Which transactional isolation levels can a checker decide from client-observed histories, at what cost, and what must the workload guarantee? | 2026-10-02 | Answered |
| [0007](0007-mutation-testing-as-a-library-from-one-build.md) | Can mutation testing run as a library that the test runner drives, and from one build for all mutants, in Go, Java, Kotlin, Python, TypeScript and Rust? | 2026-10-02 | Superseded |

Research goes stale on its own, without anyone changing the repository,
which is why every row carries a date. Status is Answered, Partial when
it could not be settled, Stale once something it depends on has moved,
or Superseded when a newer file replaces it.
