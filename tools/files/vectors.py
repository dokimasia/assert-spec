"""The corpus vectors of the file assertions, computed from their inputs.

Each kind is one of the ten assertions, and has a function that takes a
case's inputs, as the corpus states them, and returns the outputs this
reference computes for them. The renderer writes inputs and outputs
together, as it does for the property engine's vectors.

A case states workspace, the tree that the runner writes before the call,
and expect. It states the assertion's arguments in args, as typed
literals, without the directory and the message: a tree assertion reads
the whole workspace, and a path is relative to the workspace's root. A
case of tree-unchanged names a subject in place of args, and a case of
golden-match-tree states golden, the golden tree, or null for none.

The outputs are detail, the detail of a failure, and after, the golden
tree that a call under update leaves. A case whose expect is not the
verdict of this reference is refused.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from prop import literal
from prop.vectors import Vector, VectorError

from .compare import RECORD_PATHS, as_compared, differing, record
from .tree import (
    CONTENT_LIMIT,
    FILE_MODE,
    PERMISSIONS,
    Directory,
    Entry,
    File,
    Link,
    Tree,
    TreeError,
    check_path,
    decode,
    encode,
    kind_of,
    ordered,
    parents,
    without_modes,
    written,
)

#: The number of arguments of an assertion of one path that compares no
#: value, and of one that compares a value.
PATH_ONLY: Final = 1
PATH_AND_VALUE: Final = 2


def tree_equal(case: Mapping[str, Any]) -> Vector:
    """Compare the workspace with a stated tree, no entry more and none fewer."""
    (want,) = _args(case, 1)
    return _compared(case, decode(want), _workspace(case), contains=False)


def tree_contains(case: Mapping[str, Any]) -> Vector:
    """Compare the workspace with each entry of a stated tree."""
    (want,) = _args(case, 1)
    return _compared(case, decode(want), _workspace(case), contains=True)


def tree_unchanged(case: Mapping[str, Any]) -> Vector:
    """Run a subject on the workspace, and compare the tree after with the one before.

    Raises:
        VectorError: the subject is none that tree-unchanged takes.
    """
    subject = case["subject"]
    name = subject.get("kind") if isinstance(subject, Mapping) else None
    run = SUBJECTS.get(str(name))
    if run is None:
        raise VectorError(f"files: {subject!r} is no subject of tree-unchanged")
    before = _workspace(case)
    return _compared(case, before, run(before), contains=False)


def _unchanged(tree: Tree) -> Tree:
    """Return the tree as it was: a read, and a write of the bytes a file has."""
    return dict(tree)


def _writes(path: str, content: bytes) -> Callable[[Tree], Tree]:
    """Return the subject that writes a file of content at path."""

    def run(tree: Tree) -> Tree:
        """Return the tree with the file written.

        Raises:
            VectorError: the tree has an entry at the path.
        """
        if path in tree:
            raise VectorError(f"files: the subject writes {path}, which is there")
        return {**tree, path: File(content, mode=FILE_MODE)}

    return run


#: What each subject of tree-unchanged leaves of the workspace's tree.
#: writes-a-large-file writes one byte more than a record states in full.
SUBJECTS: Final[dict[str, Callable[[Tree], Tree]]] = {
    "leaves-files-alone": _unchanged,
    "rewrites-files": _unchanged,
    "writes-a-file": _writes("new.txt", b"new"),
    "writes-a-large-file": _writes("large.bin", b"a" * (CONTENT_LIMIT + 1)),
}


def golden_match_tree(case: Mapping[str, Any]) -> Vector:
    """Compare the workspace with the golden tree, or write it under update.

    The golden tree reads without modes. Under update, the call passes and
    the golden tree after it is the workspace's.

    Raises:
        VectorError: update is no bool.
    """
    name, update = (literal.decode(arg) for arg in _args(case, 2))
    check_path(name)
    if not isinstance(update, bool):
        raise VectorError(f"files: update is {update!r}, not a bool")
    output = _workspace(case)
    stated = case["golden"]
    if update:
        return {**_verdict(case, None), "after": encode(without_modes(output))}
    if stated is None:
        return _verdict(case, _missing(output))
    want = without_modes(written(decode(stated)))
    return _compared(case, want, output, contains=False)


def _missing(output: Tree) -> Vector:
    """Return the detail of a missing golden tree: no tree wanted, and the output."""
    paths = ordered(output)
    listed = {path: as_compared(output[path], None) for path in paths[:RECORD_PATHS]}
    return {
        "want": literal.encode(None),
        "got": encode(listed),
        "differences": literal.encode(len(paths)),
    }


def path_absent(case: Mapping[str, Any]) -> Vector:
    """Check that nothing is at a path."""
    (path,) = _args(case, PATH_ONLY)
    found = _found(case, path)
    return _verdict(case, None if found is None else {"got": _kind(found)})


def is_file(case: Mapping[str, Any]) -> Vector:
    """Check that a file is at a path."""
    (path,) = _args(case, PATH_ONLY)
    found = _found(case, path)
    return _verdict(case, None if isinstance(found, File) else {"got": _kind(found)})


def is_dir(case: Mapping[str, Any]) -> Vector:
    """Check that a directory is at a path."""
    (path,) = _args(case, PATH_ONLY)
    found = _found(case, path)
    passed = isinstance(found, Directory)
    return _verdict(case, None if passed else {"got": _kind(found)})


def links_to(case: Mapping[str, Any]) -> Vector:
    """Check that a link with a stated target is at a path.

    Raises:
        VectorError: the target is no text.
    """
    path, stated = _args(case, PATH_AND_VALUE)
    found = _found(case, path)
    target = literal.decode(stated)
    if not isinstance(target, str):
        raise VectorError(f"files: the target {target!r} is no text")
    got = found.target if isinstance(found, Link) else None
    if got == target:
        return _verdict(case, None)
    return _verdict(case, _compared_value(target, got, found))


def has_content(case: Mapping[str, Any]) -> Vector:
    """Check that a file whose bytes are stated text or bytes is at a path.

    Raises:
        VectorError: the content is neither text nor bytes.
    """
    path, stated = _args(case, PATH_AND_VALUE)
    found = _found(case, path)
    content = literal.decode(stated)
    if isinstance(content, str):
        wanted = content.encode()
    elif isinstance(content, bytes):
        wanted = content
    else:
        raise VectorError(f"files: the content {content!r} is no text or bytes")
    if isinstance(found, File) and found.content == wanted:
        return _verdict(case, None)
    got = _text_or_bytes(found.content) if isinstance(found, File) else None
    return _verdict(case, _compared_value(content, got, found))


def _text_or_bytes(content: bytes) -> str | bytes:
    """Return content as text when it is UTF-8, and as bytes otherwise."""
    try:
        return content.decode()
    except UnicodeDecodeError:
        return content


def has_mode(case: Mapping[str, Any]) -> Vector:
    """Check that a file or a directory with a stated mode is at a path.

    Raises:
        VectorError: the mode is no integer from 0 to 511.
    """
    path, stated = _args(case, PATH_AND_VALUE)
    found = _found(case, path)
    mode = literal.decode(stated)
    if (
        isinstance(mode, bool)
        or not isinstance(mode, int)
        or not 0 <= mode <= PERMISSIONS
    ):
        raise VectorError(f"files: the mode {mode!r} is no integer from 0 to 511")
    got = found.mode if isinstance(found, File | Directory) else None
    if got == mode:
        return _verdict(case, None)
    return _verdict(case, _compared_value(mode, got, found))


def _compared_value(want: object, got: object, found: Entry | None) -> Vector:
    """Return the detail of an assertion that compares a value at a path."""
    return {
        "want": literal.encode(want),
        "got": literal.encode(got),
        "kind": _kind(found),
    }


def _kind(entry: Entry | None) -> dict[str, Any]:
    """Return the literal of an entry's kind, or of null for no entry."""
    return literal.encode(kind_of(entry))


def _found(case: Mapping[str, Any], stated: object) -> Entry | None:
    """Return the entry at a path in the case's workspace, or None for none.

    Nothing is at a path below a file.

    Raises:
        VectorError: the path is below a link, which the platform follows and
            this reference does not.
    """
    path = check_path(literal.decode(stated))
    tree = _workspace(case)
    for parent in parents(path):
        above = tree.get(parent)
        if isinstance(above, Link):
            raise VectorError(f"files: {path!r} is below the link {parent!r}")
        if not isinstance(above, Directory):
            return None
    return tree.get(path)


def _compared(
    case: Mapping[str, Any], want: Tree, got: Tree, *, contains: bool
) -> Vector:
    """Return the outputs of a comparison of a tree read with a wanted one."""
    paths = differing(want, got, contains=contains)
    return _verdict(case, record(want, got, paths) if paths else None)


def _verdict(case: Mapping[str, Any], detail: Vector | None) -> Vector:
    """Return the outputs of a case: none for a pass, and the detail of a failure.

    Raises:
        VectorError: the case expects another verdict.
    """
    verdict = "pass" if detail is None else "fail"
    if case["expect"] != verdict:
        raise VectorError(
            f"files: {case.get('id')!r} expects {case['expect']!r}, and the "
            f"reference reports {verdict!r}"
        )
    return {} if detail is None else {"detail": detail}


def _workspace(case: Mapping[str, Any]) -> Tree:
    """Return the tree that a workspace of the case's tree leaves."""
    return written(decode(case["workspace"]))


def _args(case: Mapping[str, Any], count: int) -> list[Any]:
    """Return the arguments that a case states, as literals.

    Raises:
        VectorError: the case states another number of arguments.
    """
    args = case["args"]
    if not isinstance(args, list) or len(args) != count:
        raise VectorError(f"files: {case.get('id')!r} states the args {args!r}")
    return args


#: The function that computes each kind's outputs.
KINDS: Final[dict[str, Callable[[Mapping[str, Any]], Vector]]] = {
    "tree-equal": tree_equal,
    "tree-contains": tree_contains,
    "tree-unchanged": tree_unchanged,
    "golden-match-tree": golden_match_tree,
    "path-absent": path_absent,
    "is-file": is_file,
    "is-dir": is_dir,
    "links-to": links_to,
    "has-content": has_content,
    "has-mode": has_mode,
}


def compute(kind: str, case: Mapping[str, Any]) -> Vector:
    """Return the outputs of one case of a kind.

    Raises:
        VectorError: the kind is unknown, or the case's inputs are malformed.
    """
    function = KINDS.get(kind)
    if function is None:
        raise VectorError(f"files: {kind!r} is no vector kind")
    try:
        return function(case)
    except KeyError as missing:
        raise VectorError(f"files: a {kind} vector lacks {missing}") from None
    except (TreeError, literal.LiteralError) as bad:
        raise VectorError(str(bad)) from bad
