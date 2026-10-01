"""The fixed algorithms of the property engine, in a form that runs.

This package is the definition of ``prop-for-all`` where prose cannot be
exact: the random source, every draw, how each generator decodes its
choices, the phases of a run, the case tree, the shrink passes, the
coverage test, the explain phase, the replay token, the fuzz bridge, and
the store's entry format and file names. It produces every vector in
``corpus/prop/``, and ``make validate`` reruns it so that a vector it no
longer produces fails this repository's build.

It is not a library. It has no seat, no options and no assertions, it
reads and writes no file, and a body here is a plain function of the case.

Standard library only, as every tool in this repository is.
"""
