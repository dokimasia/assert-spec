"""The linearizability checker and the history it reads, as code that runs.

This package is the exact definition of ``linearizable``, ``serializable``,
``snapshot-isolation`` and the history seam. It fixes these parts:

- the events that a script records, and their processes
- the history that calls recorded with a start and an end make
- the standard equality, which merges a model's states
- the named models, and the model built from a subject
- the partitions, and the search with its order, budget and memo limit
- the workload of list-append transactions, the dependencies that its
  reads reveal, the anomalies, and the cycle search of each isolation level
- the record of a check that fails

The vectors of the history corpus come from it.

It is not a library. A history here is recorded on one thread, a model is
a set of plain functions, and the checker returns the outcome and the
detail of its record. It has no time limit, because a vector states none,
and no workers, because a check on n workers reports what one worker
reports.

It needs only the standard library and the typed literals of ``prop``.
"""
