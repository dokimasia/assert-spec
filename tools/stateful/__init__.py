"""The steps of a machine and the task scheduler, in a form that runs.

This package is the definition of ``steps`` and of the task scheduler
where prose cannot be exact: the swarm choices, the list of actions before
a step, the continue flag and the index by weight, the concurrent section
and its clients, the drain, the checks after each part, how a trace's step
entries turn back into choices, and the two strategies of the scheduler
with their choices. It builds the machine subjects that the corpus names,
and produces every vector in ``corpus/stateful/``. ``make render`` reruns
it, and the stale check fails the build when it produces another vector
than the one committed.

It is not a library. A machine here runs in a case of the property
engine's reference, a task is a generator, and the scheduler releases
tasks on the thread that runs the body.

It needs only the standard library, the property engine for the case that
records every choice, and the history package for the check after each
step.
"""
