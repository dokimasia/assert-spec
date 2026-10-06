"""The tree of files: its entries, the rules of its paths, and its literal.

A tree is a set of entries, each at a path relative to the tree's root. An
entry is a file with its content, a directory, or a symbolic link with its
target. A file and a directory may state a mode, their nine permission
bits. A file that states no mode states whether its owner may execute it.

The literal of a tree is ``{"type": "tree", "entries": [...]}``, with the
entries in path order. Each entry states ``path`` and exactly one of
``text``, ``bytes``, ``directory`` and ``link``. A file may state
``executable``, or ``mode``, which states the execute bit. A record states
a file over CONTENT_LIMIT bytes by ``digest`` and ``size`` in place of its
content, and no other tree states that form.
"""

from __future__ import annotations

import hashlib
import string
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from prop import literal

#: The nine permission bits of a mode.
PERMISSIONS: Final = 0o777

#: The bit of a mode that lets the owner execute a file.
OWNER_EXECUTE: Final = 0o100

#: The longest content that a record states in full, in bytes.
CONTENT_LIMIT: Final = 65_536

#: What a digest starts with: the name of its algorithm.
DIGEST_PREFIX: Final = "sha256:"

#: The hexadecimal digits of a SHA-256 digest.
DIGEST_DIGITS: Final = 64

#: The mode that a workspace sets on a file that states none.
FILE_MODE: Final = 0o644

#: The mode that a workspace sets on an executable file that states none.
EXECUTABLE_MODE: Final = 0o755

#: The mode that a workspace sets on a directory that states none.
DIRECTORY_MODE: Final = 0o755

#: The keys that state an entry's kind, and the keys each kind takes.
#: digest is the form of a file in a record.
KEYS: Final = {
    "text": frozenset({"path", "text", "executable", "mode"}),
    "bytes": frozenset({"path", "bytes", "executable", "mode"}),
    "digest": frozenset({"path", "digest", "size", "executable", "mode"}),
    "directory": frozenset({"path", "directory", "mode"}),
    "link": frozenset({"path", "link"}),
}

#: The names that no path contains.
RESERVED: Final = frozenset({"", ".", ".."})


class TreeError(ValueError):
    """A tree or a path that breaks a rule of the tree."""


@dataclass(frozen=True)
class File:
    """A file: its content, whether its owner may execute it, and its mode.

    mode is None for a file that states none. A file that states a mode
    states the execute bit through it, and executable agrees with it.
    """

    content: bytes
    executable: bool = False
    mode: int | None = None


@dataclass(frozen=True)
class Directory:
    """A directory, and its mode, or None for one that states none."""

    mode: int | None = None


@dataclass(frozen=True)
class Link:
    """A symbolic link, and its target as text that no rule of a path limits."""

    target: str


#: An entry of a tree.
Entry = File | Directory | Link

#: A tree: each entry by its path.
Tree = dict[str, Entry]


def check_path(path: object) -> str:
    """Return path when it follows the rules of a path.

    A path is UTF-8 text of one or more names joined by "/". A name is not
    empty, "." or "..", and contains no backslash and no NUL.

    Raises:
        TreeError: path breaks a rule.
    """
    if not isinstance(path, str):
        raise TreeError(f"files: the path {path!r} is no text")
    _utf8(path, "the path")
    for name in path.split("/"):
        if name in RESERVED or "\\" in name or "\0" in name:
            raise TreeError(f"files: the path {path!r} has the name {name!r}")
    return path


def _utf8(text: str, what: str) -> bytes:
    """Return text as UTF-8.

    Raises:
        TreeError: text has a surrogate, which UTF-8 does not encode.
    """
    try:
        return text.encode()
    except UnicodeEncodeError:
        raise TreeError(f"files: {what} {text!r} is no UTF-8 text") from None


def parents(path: str) -> Iterator[str]:
    """Yield each directory above path, outermost first: a, then a/b, for a/b/c."""
    names = path.split("/")
    for end in range(1, len(names)):
        yield "/".join(names[:end])


def ordered(paths: Iterable[str]) -> list[str]:
    """Return paths in path order, the order of the bytes of their UTF-8."""
    return sorted(paths, key=str.encode)


def kind_of(entry: Entry | None) -> str | None:
    """Return the kind of an entry as a record names it, or None for no entry."""
    if isinstance(entry, File):
        return "file"
    if isinstance(entry, Directory):
        return "directory"
    if isinstance(entry, Link):
        return "link"
    return None


def decode(stated: object) -> Tree:
    """Return the tree that a tree literal states.

    Raises:
        TreeError: the literal is no tree literal, its tree breaks a rule, or
            it states a file by its digest.
    """
    return _parse(stated, record=False)


def check_record(stated: object) -> None:
    """Check a tree literal of a record, which may state a file by its digest.

    Raises:
        TreeError: the literal is no tree literal, or its tree breaks a rule.
    """
    _parse(stated, record=True)


def _parse(stated: object, *, record: bool) -> Tree:
    """Return the tree that a literal states, a digested file without content.

    Raises:
        TreeError: the literal is no tree literal, or its tree breaks a rule.
    """
    if not isinstance(stated, Mapping) or set(stated) != {"type", "entries"}:
        raise TreeError(f"files: {stated!r} is no tree literal")
    entries = stated["entries"]
    if stated["type"] != "tree" or not isinstance(entries, list):
        raise TreeError(f"files: {stated!r} is no tree literal")
    tree: Tree = {}
    last = b""
    for written in entries:
        path, entry = _entry(written, record=record)
        if path.encode() <= last:
            raise TreeError(f"files: {path!r} is not after the entry before it")
        last = path.encode()
        tree[path] = entry
    for path in tree:
        for parent in parents(path):
            if isinstance(tree.get(parent), File | Link):
                raise TreeError(f"files: {path!r} is below {parent!r}, no directory")
    return tree


def _entry(written: object, *, record: bool) -> tuple[str, Entry]:
    """Return the path and the entry that one entry of a literal states.

    Raises:
        TreeError: the entry breaks a rule of the literal.
    """
    if not isinstance(written, Mapping):
        raise TreeError(f"files: the entry {written!r} is no object")
    path = check_path(written.get("path"))
    kinds = [key for key in KEYS if key in written]
    if len(kinds) != 1:
        raise TreeError(f"files: {path!r} states {kinds}, and an entry states one")
    stated = kinds[0]
    extra = sorted(set(written) - KEYS[stated])
    if extra:
        raise TreeError(f"files: {path!r} states {extra}, which {stated} does not take")
    if stated == "link":
        return path, Link(_target(path, written["link"]))
    mode = _mode(path, written)
    if stated == "directory":
        if written["directory"] is not True:
            raise TreeError(f"files: {path!r} states directory, and not as true")
        return path, Directory(mode)
    content = _content(path, written, record=record)
    return path, File(content, _executable(path, written, mode), mode)


def _mode(path: str, written: Mapping[str, Any]) -> int | None:
    """Return the mode that an entry states, or None when it states none.

    Raises:
        TreeError: the mode is no integer from 0 to 511.
    """
    if "mode" not in written:
        return None
    mode = written["mode"]
    if (
        isinstance(mode, bool)
        or not isinstance(mode, int)
        or not 0 <= mode <= PERMISSIONS
    ):
        raise TreeError(f"files: {path!r} states the mode {mode!r}, not 0 to 511")
    return mode


def _executable(path: str, written: Mapping[str, Any], mode: int | None) -> bool:
    """Return whether a file's owner may execute it, by its mode or by executable.

    Raises:
        TreeError: the file states both, or executable is no bool.
    """
    if "executable" not in written:
        return mode is not None and bool(mode & OWNER_EXECUTE)
    if mode is not None:
        raise TreeError(f"files: {path!r} states a mode and executable")
    executable = written["executable"]
    if not isinstance(executable, bool):
        raise TreeError(f"files: {path!r} states executable {executable!r}")
    return executable


def _content(path: str, written: Mapping[str, Any], *, record: bool) -> bytes:
    """Return a file's content, or no bytes for a file of a record by its digest.

    Raises:
        TreeError: the content is no text or no lowercase hexadecimal, or a
            digest is malformed or outside a record.
    """
    if "text" in written:
        text = written["text"]
        if not isinstance(text, str):
            raise TreeError(f"files: {path!r} states the text {text!r}")
        return _utf8(text, "the text of")
    if "bytes" in written:
        try:
            content = literal.decode({"type": "bytes", "value": written["bytes"]})
        except literal.LiteralError as bad:
            raise TreeError(f"files: {path!r}: {bad}") from None
        assert isinstance(content, bytes)
        return content
    if not record:
        raise TreeError(f"files: {path!r} states a digest, which only a record does")
    _digest(path, written.get("digest"), written.get("size"))
    return b""


def _digest(path: str, digest: object, size: object) -> None:
    """Check the digest and the size of a file of a record.

    Raises:
        TreeError: the digest is not sha256: and 64 lowercase hexadecimal
            digits, or the size is no integer over CONTENT_LIMIT.
    """
    digits = str(digest).removeprefix(DIGEST_PREFIX)
    if (
        not isinstance(digest, str)
        or not digest.startswith(DIGEST_PREFIX)
        or len(digits) != DIGEST_DIGITS
        or not set(digits) <= set(string.hexdigits.lower())
    ):
        raise TreeError(f"files: {path!r} states the digest {digest!r}")
    if isinstance(size, bool) or not isinstance(size, int) or size <= CONTENT_LIMIT:
        raise TreeError(f"files: {path!r} states the size {size!r} of a digest")


def _target(path: str, target: object) -> str:
    """Return the target of a link.

    Raises:
        TreeError: the target is no text, is empty, or contains NUL.
    """
    if not isinstance(target, str) or not target or "\0" in target:
        raise TreeError(f"files: {path!r} links to {target!r}, which is no target")
    _utf8(target, "the target")
    return target


def encode(tree: Mapping[str, Entry]) -> dict[str, Any]:
    """Return the literal of a tree, with its entries in path order.

    A file states its content as text when the content is UTF-8 and as
    bytes otherwise, and by its digest and size when the content is longer
    than CONTENT_LIMIT bytes. A file that states no mode states executable
    only when its owner may execute it.
    """
    entries = [_written(path, tree[path]) for path in ordered(tree)]
    return {"type": "tree", "entries": entries}


def _written(path: str, entry: Entry) -> dict[str, Any]:
    """Return the literal of one entry."""
    written: dict[str, Any] = {"path": path}
    if isinstance(entry, Link):
        written["link"] = entry.target
        return written
    if isinstance(entry, Directory):
        written["directory"] = True
    else:
        written.update(_content_literal(entry.content))
        if entry.mode is None and entry.executable:
            written["executable"] = True
    if entry.mode is not None:
        written["mode"] = entry.mode
    return written


def _content_literal(content: bytes) -> dict[str, Any]:
    """Return the keys that state a file's content in a literal."""
    if len(content) > CONTENT_LIMIT:
        digest = DIGEST_PREFIX + hashlib.sha256(content).hexdigest()
        return {"digest": digest, "size": len(content)}
    try:
        return {"text": content.decode()}
    except UnicodeDecodeError:
        return {"bytes": content.hex()}


def full(tree: Mapping[str, Entry]) -> Tree:
    """Return tree with each directory that it implies stated, without a mode."""
    out: Tree = dict(tree)
    for path in tree:
        for parent in parents(path):
            out.setdefault(parent, Directory())
    return out


def written(tree: Mapping[str, Entry]) -> Tree:
    """Return the tree that a workspace of tree leaves, as a reader reads it.

    The reader is on a platform that records permission bits. Each parent
    of an entry is a directory, and each file and directory that states no
    mode has FILE_MODE, EXECUTABLE_MODE or DIRECTORY_MODE.
    """
    return {path: _with_mode(entry) for path, entry in full(tree).items()}


def _with_mode(entry: Entry) -> Entry:
    """Return an entry with the mode that a workspace sets where it states none."""
    if isinstance(entry, Link) or entry.mode is not None:
        return entry
    if isinstance(entry, Directory):
        return Directory(DIRECTORY_MODE)
    return replace(entry, mode=EXECUTABLE_MODE if entry.executable else FILE_MODE)


def without_modes(tree: Mapping[str, Entry]) -> Tree:
    """Return tree as a reader that reads no mode reads it.

    Each file keeps whether its owner may execute it.
    """
    return {path: _without_mode(entry) for path, entry in tree.items()}


def _without_mode(entry: Entry) -> Entry:
    """Return an entry without its mode."""
    if isinstance(entry, Directory):
        return Directory()
    if isinstance(entry, File):
        return replace(entry, mode=None)
    return entry
