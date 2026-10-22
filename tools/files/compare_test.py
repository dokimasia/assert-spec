# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

"""The comparison of a tree read with a wanted one, and its record."""

from __future__ import annotations

import unittest
from typing import final

from .compare import RECORD_PATHS, as_compared, differing, differs, record
from .tree import Directory, File, Link, encode

#: A file of the text a, as a reader reads it.
READ = File(b"a", mode=0o644)


@final
class DiffersTest(unittest.TestCase):
    """differs: whether the entries at one path differ."""

    def test_compares_content_targets_and_kinds(self) -> None:
        """Other content, another target and another kind each differ."""
        assert differs(File(b"b"), READ)
        assert differs(Link("a"), Link("b"))
        assert differs(Directory(), READ)
        assert differs(None, READ)
        assert differs(READ, None)
        assert not differs(None, None)
        assert not differs(Link("a"), Link("a"))

    def test_compares_a_mode_only_where_want_states_one(self) -> None:
        """A wanted entry without a mode passes any read mode."""
        assert not differs(File(b"a"), READ)
        assert not differs(Directory(), Directory(0o700))
        assert differs(File(b"a", mode=0o600), READ)
        assert differs(Directory(0o755), Directory(0o700))
        assert not differs(Directory(0o700), Directory(0o700))

    def test_compares_the_execute_bit_where_want_states_no_mode(self) -> None:
        """A wanted file that is not executable differs from an executable one."""
        executable = File(b"a", executable=True, mode=0o755)
        assert differs(File(b"a"), executable)
        assert not differs(File(b"a", executable=True), executable)


@final
class DifferingTest(unittest.TestCase):
    """differing: the paths at which two trees differ."""

    def test_lists_missing_extra_and_changed_paths_in_order(self) -> None:
        """Every path of either tree is compared."""
        want = {"b": File(b"a"), "c": File(b"x")}
        got = {"a": READ, "b": READ, "c": READ}
        assert differing(want, got) == ["a", "c"]
        assert differing(got, {}) == ["a", "b", "c"]

    def test_reads_the_implied_directories_of_want(self) -> None:
        """A wanted file implies its parents, and a read directory is one."""
        want = {"d/e": File(b"a")}
        assert differing(want, {"d": Directory(0o755), "d/e": READ}) == []
        assert differing(want, {}) == ["d", "d/e"]

    def test_compares_only_the_paths_of_want_under_contains(self) -> None:
        """An extra entry is no difference, and a missing one is."""
        got = {"a": READ, "b": READ}
        assert differing({"a": File(b"a")}, got, contains=True) == []
        assert differing({"c": File(b"a")}, got, contains=True) == ["c"]


@final
class RecordTest(unittest.TestCase):
    """record and as_compared: the detail of a comparison that fails."""

    def test_lists_the_first_paths_and_counts_all(self) -> None:
        """Paths past RECORD_PATHS appear only in differences."""
        paths = [f"f{n:02}" for n in range(RECORD_PATHS + 1)]
        want = {path: File(b"b") for path in paths}
        got = dict.fromkeys(paths, READ)
        detail = record(want, got, paths)
        assert len(detail["want"]["entries"]) == RECORD_PATHS
        assert len(detail["got"]["entries"]) == RECORD_PATHS
        assert detail["differences"] == {"type": "int", "value": 65}

    def test_states_a_read_mode_only_where_want_states_one(self) -> None:
        """A path that want lacks shows no mode, and an executable file says so."""
        want = {"k": File(b"a", mode=0o600), "d/x": File(b"a")}
        got = {"k": READ, "e": File(b"a", executable=True, mode=0o755)}
        detail = record(want, got, ["d", "d/x", "e", "k"])
        assert detail["want"] == encode(
            {"d": Directory(), "d/x": File(b"a"), "k": File(b"a", mode=0o600)}
        )
        assert detail["got"] == encode({"e": File(b"a", executable=True), "k": READ})

    def test_as_compared_keeps_a_link_and_a_wanted_mode(self) -> None:
        """A directory without a wanted mode reads without one."""
        assert as_compared(Link("a"), None) == Link("a")
        assert as_compared(Directory(0o700), Directory(0o700)) == Directory(0o700)
        assert as_compared(Directory(0o700), Link("a")) == Directory()
        assert as_compared(READ, Directory(0o755)) == READ
