"""The vector functions of the ten file assertions, and what they refuse."""

from __future__ import annotations

import hashlib
import unittest
from typing import Any, final

from prop.vectors import VectorError

from .tree import CONTENT_LIMIT
from .vectors import compute


def tree(*entries: dict[str, Any]) -> dict[str, Any]:
    """Return the tree literal of entries."""
    return {"type": "tree", "entries": list(entries)}


def text(path: str, content: str, **more: Any) -> dict[str, Any]:
    """Return the entry of a text file."""
    return {"path": path, "text": content, **more}


def string(value: str) -> dict[str, Any]:
    """Return the typed literal of a string."""
    return {"type": "string", "value": value}


#: The typed literal of null.
NULL: dict[str, Any] = {"type": "null"}

#: A workspace of a file, an empty directory and a link to the file.
WORKSPACE = tree(
    text("a.txt", "a"),
    {"path": "d", "directory": True},
    {"path": "l", "link": "a.txt"},
)


def case(expect: str, *args: dict[str, Any], **more: Any) -> dict[str, Any]:
    """Return a case over WORKSPACE that expects a verdict."""
    return {
        "id": "x/y",
        "workspace": WORKSPACE,
        "args": list(args),
        "expect": expect,
        **more,
    }


@final
class TreeTest(unittest.TestCase):
    """tree-equal, tree-contains and tree-unchanged."""

    def test_equal_trees_pass(self) -> None:
        """A pass has no outputs."""
        self.assertEqual(compute("tree-equal", case("pass", WORKSPACE)), {})

    def test_a_missing_and_an_extra_entry_fail(self) -> None:
        """The record lists the extra directory in got and the missing file in want."""
        want = tree(text("a.txt", "a"), {"path": "l", "link": "a.txt"}, text("z", "z"))
        detail = compute("tree-equal", case("fail", want))["detail"]
        self.assertEqual(
            detail,
            {
                "want": tree(text("z", "z")),
                "got": tree({"path": "d", "directory": True}),
                "differences": {"type": "int", "value": 2},
            },
        )

    def test_contains_passes_a_subset_and_fails_another_mode(self) -> None:
        """A stated mode is compared, and the record states the read mode."""
        self.assertEqual(
            compute("tree-contains", case("pass", tree(text("a.txt", "a")))), {}
        )
        detail = compute(
            "tree-contains", case("fail", tree(text("a.txt", "a", mode=0o600)))
        )["detail"]
        self.assertEqual(detail["got"], tree(text("a.txt", "a", mode=0o644)))

    def test_unchanged_runs_each_subject(self) -> None:
        """Only writes-a-file changes the tree, by one extra file."""
        for subject in ("leaves-files-alone", "rewrites-files"):
            got = compute("tree-unchanged", case("pass", subject={"kind": subject}))
            self.assertEqual(got, {})
        written = case("fail", subject={"kind": "writes-a-file"})
        self.assertEqual(
            compute("tree-unchanged", written)["detail"],
            {
                "want": tree(),
                "got": tree(text("new.txt", "new")),
                "differences": {"type": "int", "value": 1},
            },
        )

    def test_a_large_file_states_its_digest(self) -> None:
        """writes-a-large-file writes one byte more than a record states in full."""
        content = b"a" * (CONTENT_LIMIT + 1)
        large = case("fail", subject={"kind": "writes-a-large-file"})
        self.assertEqual(
            compute("tree-unchanged", large)["detail"]["got"],
            tree(
                {
                    "path": "large.bin",
                    "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                    "size": CONTENT_LIMIT + 1,
                }
            ),
        )

    def test_unchanged_refuses_an_unknown_subject_and_a_present_new_file(self) -> None:
        """writes-a-file needs a workspace without new.txt."""
        with self.assertRaisesRegex(VectorError, "no subject of tree-unchanged"):
            compute("tree-unchanged", case("pass", subject={"kind": "raises"}))
        crowded = {
            **case("fail", subject={"kind": "writes-a-file"}),
            "workspace": tree(text("new.txt", "")),
        }
        with self.assertRaisesRegex(VectorError, "writes new.txt, which is there"):
            compute("tree-unchanged", crowded)


@final
class GoldenTest(unittest.TestCase):
    """golden-match-tree: the comparison, a missing golden tree, and update."""

    def golden(
        self, expect: str, golden: dict[str, Any] | None, *, update: bool = False
    ) -> dict[str, Any]:
        """Return a case of golden-match-tree over WORKSPACE."""
        return case(
            expect,
            string("api"),
            {"type": "bool", "value": update},
            golden=golden,
        )

    def test_compares_execute_bits_and_no_modes(self) -> None:
        """A golden file of another mode passes, and other content fails."""
        modes = tree(
            text("a.txt", "a", mode=0o600),
            {"path": "d", "directory": True, "mode": 0o700},
            {"path": "l", "link": "a.txt"},
        )
        self.assertEqual(compute("golden-match-tree", self.golden("pass", modes)), {})
        other = tree(text("a.txt", "b"), {"path": "l", "link": "a.txt"})
        detail = compute("golden-match-tree", self.golden("fail", other))["detail"]
        self.assertEqual(detail["differences"], {"type": "int", "value": 2})

    def test_a_missing_golden_tree_fails_with_want_null(self) -> None:
        """The record's got lists the output's entries, and differences counts them."""
        detail = compute("golden-match-tree", self.golden("fail", None))["detail"]
        self.assertEqual(
            detail,
            {
                "want": NULL,
                "got": WORKSPACE,
                "differences": {"type": "int", "value": 3},
            },
        )

    def test_update_passes_and_leaves_the_output(self) -> None:
        """The golden tree after the call is the output, without modes."""
        got = compute("golden-match-tree", self.golden("pass", None, update=True))
        self.assertEqual(got, {"after": WORKSPACE})

    def test_refuses_a_name_that_is_no_path_and_an_update_that_is_no_bool(
        self,
    ) -> None:
        """A name follows the rules of a path."""
        broken = self.golden("pass", None)
        broken["args"][0] = string("../api")
        with self.assertRaisesRegex(VectorError, "has the name '..'"):
            compute("golden-match-tree", broken)
        broken = self.golden("pass", None)
        broken["args"][1] = string("yes")
        with self.assertRaisesRegex(VectorError, "update is 'yes', not a bool"):
            compute("golden-match-tree", broken)


@final
class PathTest(unittest.TestCase):
    """The six assertions of one path."""

    def test_reports_the_kind_at_a_path(self) -> None:
        """A link is a link, and nothing is below a file."""
        for kind, path, want in (
            ("path-absent", "b", None),
            ("path-absent", "a.txt/b", None),
            ("path-absent", "l", "link"),
            ("is-file", "a.txt", None),
            ("is-file", "l", "link"),
            ("is-file", "z/y", NULL),
            ("is-dir", "d", None),
            ("is-dir", "a.txt", "file"),
        ):
            expect = "pass" if want is None else "fail"
            got = compute(kind, case(expect, string(path)))
            stated = want if isinstance(want, dict) else string(str(want))
            with self.subTest(kind=kind, path=path):
                self.assertEqual(
                    got, {} if want is None else {"detail": {"got": stated}}
                )

    def test_links_to_compares_the_target(self) -> None:
        """A file has no target."""
        self.assertEqual(
            compute("links-to", case("pass", string("l"), string("a.txt"))), {}
        )
        detail = compute("links-to", case("fail", string("a.txt"), string("b")))
        self.assertEqual(
            detail["detail"],
            {"want": string("b"), "got": NULL, "kind": string("file")},
        )

    def test_has_content_compares_bytes(self) -> None:
        """Text and bytes compare by their bytes, and got is text where it can be."""
        bytes_a = {"type": "bytes", "value": "61"}
        self.assertEqual(
            compute("has-content", case("pass", string("a.txt"), bytes_a)), {}
        )
        detail = compute("has-content", case("fail", string("a.txt"), string("b")))
        self.assertEqual(
            detail["detail"],
            {"want": string("b"), "got": string("a"), "kind": string("file")},
        )
        binary = {
            **case("fail", string("x"), string("a")),
            "workspace": tree({"path": "x", "bytes": "ff"}),
        }
        self.assertEqual(
            compute("has-content", binary)["detail"]["got"],
            {"type": "bytes", "value": "ff"},
        )

    def test_has_mode_compares_the_permission_bits(self) -> None:
        """A link has no mode."""
        mode = {"type": "int", "value": 0o644}
        self.assertEqual(compute("has-mode", case("pass", string("a.txt"), mode)), {})
        detail = compute("has-mode", case("fail", string("l"), mode))["detail"]
        self.assertEqual(detail, {"want": mode, "got": NULL, "kind": string("link")})

    def test_refuses_values_of_another_type(self) -> None:
        """A target is text, content is text or bytes, and a mode is 0 to 511."""
        for kind, value, reason in (
            ("links-to", {"type": "int", "value": 1}, "the target 1 is no text"),
            ("has-content", {"type": "int", "value": 1}, "content 1 is no text"),
            ("has-mode", {"type": "int", "value": 512}, "the mode 512 is no"),
            ("has-mode", {"type": "bool", "value": True}, "the mode True is no"),
        ):
            with self.subTest(kind=kind), self.assertRaisesRegex(VectorError, reason):
                compute(kind, case("pass", string("a.txt"), value))

    def test_refuses_a_path_below_a_link(self) -> None:
        """The platform follows such a link, and the reference does not."""
        with self.assertRaisesRegex(VectorError, "is below the link 'l'"):
            compute("is-file", case("fail", string("l/x")))


@final
class ComputeTest(unittest.TestCase):
    """compute(): the kind, the verdict and the inputs of a vector."""

    def test_refuses_a_case_that_expects_another_verdict(self) -> None:
        """A case states expect, and the reference checks it."""
        with self.assertRaisesRegex(VectorError, "expects 'fail', and the reference"):
            compute("is-file", case("fail", string("a.txt")))

    def test_refuses_an_unknown_kind_and_a_missing_input(self) -> None:
        """A kind of the history is none of the files'."""
        with self.assertRaisesRegex(VectorError, "'seam' is no vector kind"):
            compute("seam", {})
        with self.assertRaisesRegex(VectorError, "is-file vector lacks 'workspace'"):
            compute("is-file", {"args": [string("a")], "expect": "pass"})

    def test_refuses_another_number_of_arguments(self) -> None:
        """An assertion of one path compares at most one value."""
        with self.assertRaisesRegex(VectorError, "states the args"):
            compute("is-file", case("pass", string("a.txt"), string("b")))

    def test_refuses_a_malformed_tree_or_literal(self) -> None:
        """The errors of the tree and of the codec end the vector."""
        with self.assertRaisesRegex(VectorError, "is no tree literal"):
            compute("tree-equal", case("pass", {"type": "tree"}))
        with self.assertRaisesRegex(VectorError, "not a literal of type"):
            compute("is-file", case("pass", {"type": "string", "value": 1}))
