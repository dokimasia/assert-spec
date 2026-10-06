"""Trees of files and the assertions over them, as code that runs.

This package is the exact definition of the tree and of the ten
assertions that read files. It fixes these parts:

- the rules of a path and of a tree, and the tree's typed literal
- the tree that a workspace leaves, with the modes it sets where a tree
  states none
- the comparison of a tree read from a directory with a wanted one
- the record of a comparison that fails, with its bound on paths and its
  digest of a large file
- the verdict and the record of each assertion of one path
- what golden-match-tree compares, and what it writes under update

The vectors under corpus/files/ come from it.

It is not a library. A directory here is a tree in memory: the tree that
a platform with permission bits reads back after a workspace writes one.
The reference follows no link above a path, because the platform resolves
such a link.

It needs only the standard library and the typed literals of ``prop``.
"""
