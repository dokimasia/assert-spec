"""The comparison of a tree read from a directory with a wanted tree.

A path differs when one of the two trees has it and the other does not, or
when the entries at it differ. The wanted tree implies the parents of its
entries, and the tree read states every entry it has.

Two entries at one path differ when their kinds differ, when two files
have other content or two links other targets, when the wanted entry
states a mode and the read entry has other permission bits, and when the
wanted file states no mode and the owner's execute bits differ.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Final

from prop import literal

from .tree import Directory, Entry, File, Link, encode, full, ordered

#: The most paths that a record lists.
RECORD_PATHS: Final = 64


def differing(
    want: Mapping[str, Entry], got: Mapping[str, Entry], *, contains: bool = False
) -> list[str]:
    """Return the paths at which got differs from want, in path order.

    Under contains, a path that want lacks is no difference.
    """
    wanted = full(want)
    paths = set(wanted) if contains else set(wanted) | set(got)
    return ordered(path for path in paths if differs(wanted.get(path), got.get(path)))


def differs(want: Entry | None, got: Entry | None) -> bool:
    """Report whether the entries at one path differ, None standing for no entry."""
    if isinstance(want, File) and isinstance(got, File):
        if want.content != got.content:
            return True
        if want.mode is not None:
            return want.mode != got.mode
        return want.executable != got.executable
    if isinstance(want, Directory) and isinstance(got, Directory):
        return want.mode is not None and want.mode != got.mode
    if isinstance(want, Link) and isinstance(got, Link):
        return want.target != got.target
    return want is not None or got is not None


def record(
    want: Mapping[str, Entry], got: Mapping[str, Entry], paths: Sequence[str]
) -> dict[str, Any]:
    """Return the detail of a comparison at whose paths the trees differ.

    want and got state the entries at the first RECORD_PATHS of the paths,
    and differences states the number of paths. An entry of got states its
    mode only where the entry of want at its path states one.
    """
    wanted = full(want)
    listed = paths[:RECORD_PATHS]
    return {
        "want": encode({path: wanted[path] for path in listed if path in wanted}),
        "got": encode(
            {
                path: as_compared(got[path], wanted.get(path))
                for path in listed
                if path in got
            }
        ),
        "differences": literal.encode(len(paths)),
    }


def as_compared(read: Entry, wanted: Entry | None) -> Entry:
    """Return an entry read from a directory with its mode where wanted states one.

    A file without its mode keeps whether its owner may execute it.
    """
    if isinstance(read, Link):
        return read
    if isinstance(wanted, File | Directory) and wanted.mode is not None:
        return read
    if isinstance(read, Directory):
        return Directory()
    return replace(read, mode=None)
