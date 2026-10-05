"""The fixed algorithms of the property engine, in a form that runs.

This package is the definition of ``prop-for-all`` and of the property
forms where prose cannot be exact: the random source, every draw, how each
generator decodes its choices, the phases of a run, the case tree, the
shrink passes, the coverage test, the explain phase, the replay token, the
fuzz bridge, the store's entry format and file names, the shapes and the
inverse of each generator, each form's assertion over the inputs it
generates, and traces. It produces every vector in ``corpus/prop/``.
``make render`` reruns it, and the stale check fails the build when it
produces another vector than the one committed.

It is not a library. It has no seat and no options. A body here is a
plain function of the case, and an assertion is a function that returns
the detail of its record. It reads the zone table and the assertion table
that the definition publishes, and writes no file.

It needs only the standard library, and the history package for the
history that a case records.
"""
