"""The tree: the rules of a path, the literal, and the tree a workspace leaves."""

from __future__ import annotations

import hashlib
import unittest
from typing import Any, final

from .tree import (
    CONTENT_LIMIT,
    Directory,
    File,
    Link,
    TreeError,
    check_path,
    check_record,
    decode,
    encode,
    full,
    kind_of,
    ordered,
    parents,
    without_modes,
    written,
)


def tree(*entries: object) -> dict[str, Any]:
    """Return the tree literal of entries."""
    return {"type": "tree", "entries": list(entries)}


#: The literal of a tree with an entry of every kind and form.
EXAMPLE = tree(
    {"path": "bin/run", "text": "#!/bin/sh\n", "executable": True},
    {"path": "cache", "directory": True},
    {"path": "current", "link": "bin/run"},
    {"path": "keys", "directory": True, "mode": 0o700},
    {"path": "keys/id", "text": "secret\n", "mode": 0o600},
    {"path": "logo.png", "bytes": "89504e47"},
)


@final
class PathTest(unittest.TestCase):
    """check_path, parents and ordered."""

    def test_accepts_names_joined_by_slashes(self) -> None:
        """A name may contain any character but a slash, a backslash and NUL."""
        for path in ("a", "a/b.txt", "ü/.hidden/x y", "..a/b.."):
            self.assertEqual(check_path(path), path)

    def test_refuses_a_path_that_breaks_a_rule(self) -> None:
        """An empty name, . and .., a backslash and NUL are refused."""
        for path in ("", "/a", "a/", "a//b", ".", "a/./b", "..", "a/../b", "a\\b"):
            with self.subTest(path=path), self.assertRaises(TreeError):
                check_path(path)
        with self.assertRaisesRegex(TreeError, "has the name"):
            check_path("a\0b")

    def test_refuses_a_path_that_is_no_utf8_text(self) -> None:
        """A number is no text, and a lone surrogate has no UTF-8."""
        with self.assertRaisesRegex(TreeError, "is no text"):
            check_path(1)
        with self.assertRaisesRegex(TreeError, "is no UTF-8 text"):
            check_path("a\ud800")

    def test_parents_lists_each_directory_above_a_path(self) -> None:
        """The outermost directory comes first."""
        self.assertEqual(list(parents("a/b/c")), ["a", "a/b"])
        self.assertEqual(list(parents("a")), [])

    def test_ordered_sorts_by_the_bytes_of_utf8(self) -> None:
        """A dot sorts before a slash, and a parent before its entries."""
        self.assertEqual(
            ordered(["b", "a/b", "é", "a", "a.txt"]), ["a", "a.txt", "a/b", "b", "é"]
        )


@final
class DecodeTest(unittest.TestCase):
    """decode and check_record: the literal and the rules of a tree."""

    def test_decodes_every_kind_and_form(self) -> None:
        """A mode states the execute bit, and bytes are hexadecimal."""
        self.assertEqual(
            decode(EXAMPLE),
            {
                "bin/run": File(b"#!/bin/sh\n", executable=True),
                "cache": Directory(),
                "current": Link("bin/run"),
                "keys": Directory(0o700),
                "keys/id": File(b"secret\n", mode=0o600),
                "logo.png": File(bytes.fromhex("89504e47")),
            },
        )
        self.assertEqual(
            decode(tree({"path": "x", "text": "", "mode": 0o755})),
            {"x": File(b"", executable=True, mode=0o755)},
        )

    def test_refuses_what_is_no_tree_literal(self) -> None:
        """A tree literal is an object of the type tree and a list of entries."""
        literals: tuple[object, ...] = (
            [],
            {"type": "tree"},
            {"type": "list", "entries": []},
            {"type": "tree", "entries": {}},
            {"type": "tree", "entries": [], "of": "x"},
        )
        for stated in literals:
            with self.subTest(stated=stated), self.assertRaises(TreeError):
                decode(stated)

    def test_refuses_an_entry_that_breaks_a_rule_of_the_literal(self) -> None:
        """Each entry states one kind, and only the keys its kind takes."""
        for entry, reason in (
            ("a", "is no object"),
            ({"path": "a"}, r"states \[\]"),
            ({"path": "a", "text": "", "directory": True}, "states .*'directory'"),
            ({"path": "a", "link": "b", "mode": 0o644}, "which link does not take"),
            ({"path": "a", "directory": False}, "not as true"),
            ({"path": "a", "text": 1}, "states the text 1"),
            ({"path": "a", "text": "\ud800"}, "is no UTF-8 text"),
            ({"path": "a", "bytes": "FF"}, "lowercase hexadecimal"),
            ({"path": "a", "text": "", "mode": 0o1000}, "the mode 512"),
            ({"path": "a", "text": "", "mode": True}, "the mode True"),
            ({"path": "a", "text": "", "mode": 0o644, "executable": True}, "and exec"),
            ({"path": "a", "text": "", "executable": 1}, "executable 1"),
            ({"path": "a", "link": ""}, "which is no target"),
            ({"path": "a", "link": "b\0"}, "which is no target"),
            ({"path": "a", "link": "\udc00"}, "is no UTF-8 text"),
            ({"path": "a/../b", "text": ""}, "has the name"),
        ):
            with self.subTest(entry=entry), self.assertRaisesRegex(TreeError, reason):
                decode(tree(entry))

    def test_refuses_entries_out_of_path_order(self) -> None:
        """Entries are in path order, and so state each path once."""
        a, b = {"path": "a", "text": ""}, {"path": "b", "text": ""}
        for entries in ((b, a), (a, a)):
            with self.assertRaisesRegex(TreeError, "is not after the entry before"):
                decode(tree(*entries))

    def test_refuses_an_entry_below_a_file_or_a_link(self) -> None:
        """A file and a link have no entries."""
        for above in ({"path": "a", "text": ""}, {"path": "a", "link": "b"}):
            with self.assertRaisesRegex(TreeError, "is below 'a', no directory"):
                decode(tree(above, {"path": "a/b", "text": ""}))

    def test_refuses_a_digest_outside_a_record(self) -> None:
        """A case states a file by its content."""
        digested = {"path": "a", "digest": "sha256:" + "0" * 64, "size": 70_000}
        with self.assertRaisesRegex(TreeError, "which only a record does"):
            decode(tree(digested))
        check_record(tree(digested))

    def test_refuses_a_malformed_digest_in_a_record(self) -> None:
        """A digest names sha256 and 64 lowercase digits, of content over the limit."""
        good = "sha256:" + "a" * 64
        for digest, size in (
            ("md5:" + "a" * 64, 70_000),
            ("sha256:" + "A" * 64, 70_000),
            ("sha256:" + "a" * 63, 70_000),
            (good, CONTENT_LIMIT),
            (good, None),
            (good, True),
        ):
            stated: dict[str, Any] = {"path": "a", "digest": digest}
            if size is not None:
                stated["size"] = size
            with self.subTest(digest=digest, size=size), self.assertRaises(TreeError):
                check_record(tree(stated))


@final
class EncodeTest(unittest.TestCase):
    """encode: the canonical literal of a tree."""

    def test_states_each_entry_in_path_order(self) -> None:
        """A decoded literal encodes to itself."""
        self.assertEqual(encode(decode(EXAMPLE)), EXAMPLE)

    def test_states_content_as_text_bytes_or_a_digest(self) -> None:
        """UTF-8 is text, other bytes are bytes, and large content is a digest."""
        large = b"a" * (CONTENT_LIMIT + 1)
        self.assertEqual(
            encode(
                {
                    "z": File(large),
                    "y": File(b"a" * CONTENT_LIMIT),
                    "x": File(b"\xff"),
                }
            )["entries"],
            [
                {"path": "x", "bytes": "ff"},
                {"path": "y", "text": "a" * CONTENT_LIMIT},
                {
                    "path": "z",
                    "digest": "sha256:" + hashlib.sha256(large).hexdigest(),
                    "size": CONTENT_LIMIT + 1,
                },
            ],
        )

    def test_states_a_mode_in_place_of_executable(self) -> None:
        """A file with a mode states no executable."""
        self.assertEqual(
            encode({"a": File(b"", executable=True, mode=0o700)})["entries"],
            [{"path": "a", "text": "", "mode": 0o700}],
        )


@final
class WrittenTest(unittest.TestCase):
    """written, full and without_modes: the trees a reader reads."""

    def test_sets_a_mode_where_a_tree_states_none(self) -> None:
        """Files get 0644, executables and directories 0755, and parents appear."""
        self.assertEqual(
            written(decode(EXAMPLE)),
            {
                "bin": Directory(0o755),
                "bin/run": File(b"#!/bin/sh\n", executable=True, mode=0o755),
                "cache": Directory(0o755),
                "current": Link("bin/run"),
                "keys": Directory(0o700),
                "keys/id": File(b"secret\n", mode=0o600),
                "logo.png": File(bytes.fromhex("89504e47"), mode=0o644),
            },
        )

    def test_full_states_each_implied_directory_without_a_mode(self) -> None:
        """A stated directory keeps its mode."""
        self.assertEqual(
            full({"a/b/c": File(b""), "a": Directory(0o700)}),
            {"a/b/c": File(b""), "a": Directory(0o700), "a/b": Directory()},
        )

    def test_without_modes_keeps_the_execute_bit(self) -> None:
        """A reader without modes still reads whether the owner may execute."""
        self.assertEqual(
            without_modes(written(decode(EXAMPLE)))["bin/run"],
            File(b"#!/bin/sh\n", executable=True),
        )
        self.assertEqual(without_modes({"k": Directory(0o700)}), {"k": Directory()})

    def test_kind_of_names_each_kind(self) -> None:
        """No entry has no kind."""
        self.assertEqual(
            [kind_of(e) for e in (File(b""), Directory(), Link("a"), None)],
            ["file", "directory", "link", None],
        )
