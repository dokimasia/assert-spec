"""The store: the format of an entry, its name, and what a runner does with one.

The store keeps the minimal failing case of each identity in a directory of
each test, one JSON object per file. This module states the object a runner
writes, the file's name, and the verdict a runner gives each file it reads.
The directory, the file system and the notes belong to each language, so the
module reads and writes no file.

A name is the entry's key: mix() applied to the contract's UTF-8 bytes, a
zero byte and the replay token's bytes, as 16 lowercase hexadecimal digits
followed by NAME_SUFFIX. The same failure, shrunk to the same choices, has
the same name in every language.

An entry of FORMAT is an object with exactly the fields of FIELDS:

- ``store``: FORMAT.
- ``definition``: the definition version that wrote the entry, as
  MAJOR.MINOR.PATCH.
- ``property``: the property's contract.
- ``identity``: the failure's identity, with the keys of one of IDENTITIES.
  ``line`` is an integer in [1, LINE_MAX], ``file`` a non-empty base name,
  and every other key a non-empty string.
- ``choices``: the replay token of the minimal case.
- ``counterexample``: one object per draw, with the draw's ``label`` and,
  when the value has a typed literal, its ``value``. A reader checks the
  label and leaves the value unread, because only the choices replay.
- ``found``: the UTC date on which the runner wrote the entry, as
  YYYY-MM-DD.

A file nests objects and arrays at most MAX_DEPTH levels deep, the root
object being the first level. A writer records a value whose literal would
nest deeper by its label alone.

A runner gives each file one verdict:

- REPLAY: an entry of FORMAT for the property, whose token is of the
  version replay encodes. The runner tries its choices first.
- OTHER: an entry of FORMAT for another property of the test.
- SKIP: an entry of a later format, or whose token is of a later version.
  The runner notes it and goes on.
- DAMAGED: any other file, including JSON that repeats a name within an
  object, states a non-finite number, or nests past MAX_DEPTH. The test
  fails, as it fails on a damaged golden file.
"""

from __future__ import annotations

import datetime
import enum
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypeGuard

from . import replay
from .choice import Choice
from .source import mix

#: The format of the entries this module writes and replays.
FORMAT: Final = 1

#: The version of the tokens replay encodes, the number in its PREFIX.
TOKEN_VERSION: Final = 1

#: The suffix of an entry's file name.
NAME_SUFFIX: Final = ".json"

#: The largest line of an identity, the largest signed 32-bit integer.
LINE_MAX: Final = 2**31 - 1

#: The most levels of objects and arrays a file nests, the root included.
#: JSON readers stop at different depths, and Rust's serde_json refuses a
#: 128th level by default, so the format allows half of that.
MAX_DEPTH: Final = 64

#: The levels above a draw's value: the root, the counterexample and the
#: draw.
_ABOVE_VALUE: Final = 3

#: The fields of an entry of FORMAT.
FIELDS: Final = frozenset(
    {
        "store",
        "definition",
        "property",
        "identity",
        "choices",
        "counterexample",
        "found",
    }
)

#: The keys of an identity, one set for each way a case fails: an
#: assertion's record with a location, one without a location, a message
#: to the case, and a raised error.
IDENTITIES: Final = (
    frozenset({"assertion", "file", "line"}),
    frozenset({"assertion", "contract"}),
    frozenset({"file", "line"}),
    frozenset({"error", "file", "line"}),
)

#: The keys of a draw of the counterexample, without and with a value.
DRAWS: Final = (frozenset({"label"}), frozenset({"label", "value"}))

#: The start of a token, which states the token's version.
_TOKEN: Final = re.compile(r"prop([1-9][0-9]*):")

#: A definition version.
_VERSION: Final = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

#: A date, before its calendar check.
_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

#: The characters a base name does not contain.
_SEPARATORS: Final = ("/", "\\")


class Verdict(enum.Enum):
    """What a runner does with one file of the store."""

    REPLAY = "replay"
    OTHER = "other"
    SKIP = "skip"
    DAMAGED = "damaged"


class _Later(Exception):
    """The signal that an entry is of a later format or token version."""


@dataclass(frozen=True)
class Read:
    """A file's verdict, and for REPLAY the choices of its entry."""

    verdict: Verdict
    choices: tuple[Choice, ...] = ()


@dataclass(frozen=True)
class Failure:
    """A property's minimal failing case, as an entry records it.

    identity has the keys of one of IDENTITIES, and each draw of
    counterexample the keys of one of DRAWS.
    """

    contract: str
    choices: tuple[Choice, ...]
    identity: Mapping[str, object]
    counterexample: tuple[Mapping[str, object], ...]


def name(contract: str, choices: Sequence[Choice]) -> str:
    """Return the file name of the entry for a contract and a minimal case."""
    token = replay.encode(choices)
    key = mix(contract.encode() + b"\x00" + token.encode())
    return f"{key:016x}{NAME_SUFFIX}"


def entry(failure: Failure, definition: str, found: datetime.date) -> dict[str, object]:
    """Return the entry a runner of definition writes on the date found.

    A draw whose value would nest the entry past MAX_DEPTH is recorded by
    its label alone.
    """
    return {
        "store": FORMAT,
        "definition": definition,
        "property": failure.contract,
        "identity": dict(failure.identity),
        "choices": replay.encode(failure.choices),
        "counterexample": [_recorded(draw) for draw in failure.counterexample],
        "found": found.isoformat(),
    }


def read(text: str, contract: str) -> Read:
    """Return what a runner of the property contract does with a file's text."""
    try:
        stated, choices = _parse(text)
    except _Later:
        return Read(Verdict.SKIP)
    except (ValueError, RecursionError):
        return Read(Verdict.DAMAGED)
    if stated != contract:
        return Read(Verdict.OTHER)
    return Read(Verdict.REPLAY, tuple(choices))


def depth(node: object) -> int:
    """Return the levels of objects and arrays that node nests, 0 for a scalar."""
    if isinstance(node, dict):
        return 1 + max((depth(child) for child in node.values()), default=0)
    if isinstance(node, list):
        return 1 + max((depth(child) for child in node), default=0)
    return 0


def _recorded(draw: Mapping[str, object]) -> dict[str, object]:
    """Return a draw as an entry records it, without a value nested too deep."""
    if "value" in draw and depth(draw["value"]) > MAX_DEPTH - _ABOVE_VALUE:
        return {"label": draw["label"]}
    return dict(draw)


def _parse(text: str) -> tuple[str, list[Choice]]:
    """Return the property and the choices of the entry that text states.

    Raises:
        _Later: the entry is of a later format, or its token of a later
            version.
        ValueError: text is no entry of FORMAT.
        RecursionError: text nests deeper than the parser reads.
    """
    document = json.loads(text, object_pairs_hook=_unique, parse_constant=_no_constant)
    if depth(document) > MAX_DEPTH:
        raise ValueError(f"prop: the file nests past {MAX_DEPTH} levels")
    version = document.get("store") if isinstance(document, dict) else None
    if not _is_int(version) or version < FORMAT:
        raise ValueError(f"prop: store is {version!r}, which names no format")
    if version > FORMAT:
        raise _Later
    if frozenset(document) != FIELDS or not _well_formed(document):
        raise ValueError("prop: the entry's fields are not those of its format")
    token = document["choices"]
    stated = _TOKEN.match(token)
    if stated is None:
        raise ValueError(f"prop: {token!r} states no token version")
    if int(stated.group(1)) > TOKEN_VERSION:
        raise _Later
    return document["property"], replay.decode(token)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Return an object's pairs as a dict.

    Raises:
        ValueError: the object repeats a name.
    """
    names = [key for key, _ in pairs]
    if len(set(names)) != len(names):
        raise ValueError("prop: an object repeats a name")
    return dict(pairs)


def _no_constant(constant: str) -> object:
    """Refuse NaN and the infinities, which JSON does not state.

    Raises:
        ValueError: always.
    """
    raise ValueError(f"prop: {constant} is no JSON number")


def _is_int(value: object) -> TypeGuard[int]:
    """Report whether value is an int and not a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


def _well_formed(document: Mapping[str, Any]) -> bool:
    """Report whether every field of an entry of FORMAT has its form.

    The token's own form is checked by read().
    """
    return (
        isinstance(document["definition"], str)
        and _VERSION.fullmatch(document["definition"]) is not None
        and isinstance(document["property"], str)
        and _identity(document["identity"])
        and isinstance(document["choices"], str)
        and _counterexample(document["counterexample"])
        and _date(document["found"])
    )


def _identity(identity: object) -> bool:
    """Report whether identity has the keys of one of IDENTITIES and their forms."""
    if not isinstance(identity, dict) or frozenset(identity) not in IDENTITIES:
        return False
    return all(_identity_value(key, value) for key, value in identity.items())


def _identity_value(key: str, value: object) -> bool:
    """Report whether value has the form of an identity's key.

    line is an integer in [1, LINE_MAX], file a non-empty base name, and
    every other key a non-empty string.
    """
    if key == "line":
        return _is_int(value) and 1 <= value <= LINE_MAX
    if not isinstance(value, str) or not value:
        return False
    return key != "file" or not any(s in value for s in _SEPARATORS)


def _counterexample(draws: object) -> bool:
    """Report whether draws is a list of draws with a label each."""
    if not isinstance(draws, list):
        return False
    return all(
        isinstance(draw, dict)
        and frozenset(draw) in DRAWS
        and isinstance(draw["label"], str)
        for draw in draws
    )


def _date(found: object) -> bool:
    """Report whether found is a calendar date written as YYYY-MM-DD."""
    if not isinstance(found, str) or _DATE.fullmatch(found) is None:
        return False
    try:
        datetime.date.fromisoformat(found)
    except ValueError:
        return False
    return True
