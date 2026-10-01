"""The store: an entry's name, its format, and the verdict on each file."""

from __future__ import annotations

import datetime
import json
import re
import unittest
from typing import Any, Final, final

from . import replay
from .choice import Choice
from .source import mix
from .store import (
    FIELDS,
    FORMAT,
    LINE_MAX,
    MAX_DEPTH,
    TOKEN_VERSION,
    Failure,
    Verdict,
    depth,
    entry,
    name,
    read,
)

#: The contract of the property the tests read entries for.
CONTRACT: Final = "decoding undoes encoding"

#: The choices of the minimal case: the list [0, -1].
CHOICES: Final = (
    Choice("integer", 1),
    Choice("integer", 0),
    Choice("integer", 1),
    Choice("integer", -1),
    Choice("integer", 0),
)

#: The failure the tests write.
FAILURE: Final = Failure(
    CONTRACT,
    CHOICES,
    {"assertion": "equal", "file": "codec_test.go", "line": 18},
    ({"label": "values", "value": {"type": "list", "of": "int", "value": [0, -1]}},),
)

#: The name of FAILURE's entry, pinned so that a change to the token or to
#: mix fails here before a corpus vector moves.
PINNED_NAME: Final = "ccc741d57d7f920d.json"

#: The deepest value a draw records: the root, the counterexample and the
#: draw take the first three levels.
DEEPEST_VALUE: Final = MAX_DEPTH - 3


def _written() -> dict[str, Any]:
    """Return FAILURE's entry as definition 1.2.0 writes it on 1 October 2026."""
    return entry(FAILURE, "1.2.0", datetime.date(2026, 10, 1))


def _verdict(document: object) -> Verdict:
    """Return the verdict on a file that contains document as JSON."""
    return read(json.dumps(document), CONTRACT).verdict


def _nested(levels: int) -> list[object]:
    """Return a list that nests levels arrays deep, the outer one included."""
    node: list[object] = []
    for _ in range(levels - 1):
        node = [node]
    return node


@final
class NameTest(unittest.TestCase):
    """name(): the mix of the contract, a zero byte and the token."""

    def test_the_name_is_the_mix_in_hexadecimal_with_the_json_suffix(self) -> None:
        """16 lowercase hexadecimal digits, then .json."""
        data = CONTRACT.encode() + b"\x00" + replay.encode(CHOICES).encode()
        self.assertEqual(name(CONTRACT, CHOICES), f"{mix(data):016x}.json")
        self.assertRegex(name(CONTRACT, CHOICES), re.compile(r"[0-9a-f]{16}\.json"))

    def test_the_name_of_the_failure_is_pinned(self) -> None:
        """The value every language computes."""
        self.assertEqual(name(CONTRACT, CHOICES), PINNED_NAME)

    def test_another_contract_names_the_same_choices_otherwise(self) -> None:
        """Two properties of one test never share an entry."""
        self.assertNotEqual(name("another", CHOICES), name(CONTRACT, CHOICES))


@final
class EntryTest(unittest.TestCase):
    """entry(): the object a runner writes."""

    def test_an_entry_states_exactly_the_fields_of_the_format(self) -> None:
        """Seven fields, store first among them as FORMAT."""
        written = _written()
        self.assertEqual(set(written), FIELDS)
        self.assertEqual(written["store"], FORMAT)
        self.assertEqual(written["found"], "2026-10-01")
        self.assertEqual(written["choices"], replay.encode(CHOICES))

    def test_an_entry_reads_back_as_a_replay_of_its_choices(self) -> None:
        """What a runner writes, the next run replays."""
        got = read(json.dumps(_written()), CONTRACT)
        self.assertEqual(got.verdict, Verdict.REPLAY)
        self.assertEqual(got.choices, CHOICES)

    def test_a_value_at_the_deepest_level_is_recorded(self) -> None:
        """The entry then nests exactly MAX_DEPTH levels, and replays."""
        deep = Failure(
            CONTRACT,
            CHOICES,
            FAILURE.identity,
            ({"label": "v", "value": _nested(DEEPEST_VALUE)},),
        )
        written = entry(deep, "1.2.0", datetime.date(2026, 10, 1))
        self.assertEqual(depth(written), MAX_DEPTH)
        self.assertEqual(_verdict(written), Verdict.REPLAY)

    def test_a_value_past_the_deepest_level_is_recorded_by_its_label(self) -> None:
        """One level more, and the draw has no value."""
        deep = Failure(
            CONTRACT,
            CHOICES,
            FAILURE.identity,
            ({"label": "v", "value": _nested(DEEPEST_VALUE + 1)},),
        )
        written = entry(deep, "1.2.0", datetime.date(2026, 10, 1))
        self.assertEqual(written["counterexample"], [{"label": "v"}])

    def test_the_format_and_the_token_version_are_pinned(self) -> None:
        """Format 1, and the tokens of prop1."""
        self.assertEqual(FORMAT, 1)
        self.assertEqual(replay.PREFIX, f"prop{TOKEN_VERSION}:")


@final
class ReadTest(unittest.TestCase):
    """read(): the verdict a runner gives a file."""

    def test_an_entry_of_another_property_is_other(self) -> None:
        """The test's other property replays it."""
        written = {**_written(), "property": "another"}
        self.assertEqual(_verdict(written), Verdict.OTHER)

    def test_an_entry_of_another_definition_version_replays(self) -> None:
        """Its choices decode with the current generators."""
        written = {**_written(), "definition": "1.1.0"}
        self.assertEqual(_verdict(written), Verdict.REPLAY)

    def test_an_entry_of_a_later_format_is_skipped(self) -> None:
        """Whatever its other fields state, at any later format."""
        for version in (2, 10**30):
            self.assertEqual(_verdict({"store": version}), Verdict.SKIP, version)

    def test_an_entry_whose_token_is_of_a_later_version_is_skipped(self) -> None:
        """prop2 is a later token version."""
        written = {**_written(), "choices": "prop2:AAc"}
        self.assertEqual(_verdict(written), Verdict.SKIP)

    def test_a_draw_without_a_value_replays(self) -> None:
        """A value without a typed literal is recorded by its label alone."""
        written = {**_written(), "counterexample": [{"label": "conn"}]}
        self.assertEqual(_verdict(written), Verdict.REPLAY)

    def test_a_draw_whose_value_is_no_typed_literal_replays(self) -> None:
        """A reader leaves the value unread."""
        written = {**_written(), "counterexample": [{"label": "x", "value": [1]}]}
        self.assertEqual(_verdict(written), Verdict.REPLAY)

    def test_each_identity_shape_replays(self) -> None:
        """A record with and without a location, a message and an error."""
        shapes: list[dict[str, object]] = [
            {"assertion": "equal", "file": "a_test.go", "line": 3},
            {"assertion": "equal", "contract": "x equals y"},
            {"file": "a_test.go", "line": LINE_MAX},
            {"error": "ValueError", "file": "a_test.py", "line": 3},
        ]
        for identity in shapes:
            written = {**_written(), "identity": identity}
            self.assertEqual(_verdict(written), Verdict.REPLAY, identity)

    def test_text_that_is_not_one_json_object_is_damaged(self) -> None:
        """Not JSON, a repeated name, NaN, another value, or nesting past the parser."""
        texts = [
            "{",
            '{"store": 1, "store": 1}',
            '{"store": NaN}',
            "[1]",
            "1",
            "[" * 100_000 + "]" * 100_000,
        ]
        for text in texts:
            self.assertEqual(read(text, CONTRACT).verdict, Verdict.DAMAGED, text)

    def test_an_entry_nested_past_max_depth_is_damaged(self) -> None:
        """A value one level deeper than a writer records."""
        too_deep = [{"label": "v", "value": _nested(DEEPEST_VALUE + 1)}]
        written = {**_written(), "counterexample": too_deep}
        self.assertEqual(depth(written), MAX_DEPTH + 1)
        self.assertEqual(_verdict(written), Verdict.DAMAGED)

    def test_an_entry_whose_store_is_no_format_is_damaged(self) -> None:
        """Absent, zero, a bool, a fraction or a string."""
        for version in (None, 0, True, 1.0, "1"):
            written = {**_written(), "store": version}
            if version is None:
                del written["store"]
            self.assertEqual(_verdict(written), Verdict.DAMAGED, version)

    def test_an_entry_with_a_field_out_of_form_is_damaged(self) -> None:
        """Each field the format checks, each out of its form once."""
        changes: list[dict[str, object]] = [
            {"definition": "1.2"},
            {"definition": "1.02.0"},
            {"property": 5},
            {"identity": {"assertion": "equal"}},
            {"identity": {"file": "a_test.go", "line": 0}},
            {"identity": {"file": "a_test.go", "line": LINE_MAX + 1}},
            {"identity": {"file": "a_test.go", "line": True}},
            {"identity": {"file": "a_test.go", "line": 3.0}},
            {"identity": {"file": "pkg/a_test.go", "line": 3}},
            {"identity": {"file": "pkg\\a_test.go", "line": 3}},
            {"identity": {"file": "", "line": 3}},
            {"identity": "equal"},
            {"choices": 5},
            {"choices": "AAc"},
            {"choices": "prop01:AAc"},
            {"choices": "prop1:AAc="},
            {"counterexample": {"label": "x"}},
            {"counterexample": [{"value": {"type": "int", "value": 1}}]},
            {"counterexample": [{"label": "x", "note": "y"}]},
            {"counterexample": [{"label": 5}]},
            {"counterexample": ["x"]},
            {"found": "2026-02-30"},
            {"found": "1 October 2026"},
            {"found": 20261001},
        ]
        for change in changes:
            written = {**_written(), **change}
            self.assertEqual(_verdict(written), Verdict.DAMAGED, change)

    def test_an_entry_missing_a_field_or_stating_another_is_damaged(self) -> None:
        """The fields of the format, exactly."""
        missing = _written()
        del missing["found"]
        self.assertEqual(_verdict(missing), Verdict.DAMAGED)
        extra = {**_written(), "comment": "found in review"}
        self.assertEqual(_verdict(extra), Verdict.DAMAGED)
