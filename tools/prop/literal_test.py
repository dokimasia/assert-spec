"""Typed literals: what each decodes to, and the one literal each value encodes to."""

from __future__ import annotations

import math
import unittest
from typing import Any, final

from .literal import SAFE_INTEGER, LiteralError, decode, encode
from .value import NO_PAYLOAD, Pairs, Record, Variant, canonical

#: The definition's limit on a JSON integer, pinned rather than read.
PINNED_SAFE = 2**53 - 1


@final
class DecodeTest(unittest.TestCase):
    """decode(): every form of the encoding."""

    def test_each_scalar_and_null_decodes(self) -> None:
        """null, bool, int, float, string."""
        cases: list[tuple[dict[str, Any], object]] = [
            ({"type": "null"}, None),
            ({"type": "bool", "value": True}, True),
            ({"type": "int", "value": -3}, -3),
            ({"type": "float", "value": 1}, 1.0),
            ({"type": "float", "value": "-Inf"}, -math.inf),
            ({"type": "string", "value": "x"}, "x"),
        ]
        for literal, want in cases:
            self.assertEqual(decode(literal), want, literal)

    def test_nan_is_named(self) -> None:
        """JSON has no NaN."""
        value = decode({"type": "float", "value": "NaN"})
        self.assertTrue(isinstance(value, float) and math.isnan(value))

    def test_an_int_beyond_2_to_the_53_is_a_decimal_string(self) -> None:
        """The first unsafe integers, both signs."""
        self.assertEqual(SAFE_INTEGER, PINNED_SAFE)
        big = str(PINNED_SAFE + 1)
        self.assertEqual(decode({"type": "int", "value": big}), PINNED_SAFE + 1)
        self.assertEqual(decode({"type": "int", "value": "-" + big}), -PINNED_SAFE - 1)

    def test_bytes_are_lowercase_hexadecimal(self) -> None:
        """Two bytes, and none."""
        self.assertEqual(decode({"type": "bytes", "value": "00ff"}), b"\x00\xff")
        self.assertEqual(decode({"type": "bytes", "value": ""}), b"")

    def test_a_list_decodes_from_of_and_value_or_from_items(self) -> None:
        """Scalars of one type, or literals of any type."""
        self.assertEqual(decode({"type": "list", "of": "int", "value": [1, 2]}), [1, 2])
        items = {
            "type": "list",
            "items": [{"type": "int", "value": 1}, {"type": "null"}],
        }
        self.assertEqual(decode(items), [1, None])

    def test_a_map_decodes_from_entries_or_from_string_keys(self) -> None:
        """Ordered entries of any type, or an object with string keys."""
        entries = {
            "type": "map",
            "entries": [[{"type": "int", "value": 2}, {"type": "bool", "value": True}]],
        }
        self.assertEqual(decode(entries), Pairs(((2, True),)))
        legacy = {"type": "map", "key": "string", "of": "int", "value": {"a": 1}}
        self.assertEqual(decode(legacy), Pairs((("a", 1),)))

    def test_a_record_decodes_its_fields_in_order(self) -> None:
        """Fields of different types, in declaration order."""
        literal = {
            "type": "record",
            "fields": [
                ["id", {"type": "int", "value": 7}],
                ["note", {"type": "null"}],
            ],
        }
        self.assertEqual(decode(literal), Record((("id", 7), ("note", None))))

    def test_a_variant_decodes_with_or_without_a_payload(self) -> None:
        """No payload key, and a null payload, are two values."""
        bare = decode({"type": "variant", "name": "pending"})
        self.assertEqual(bare, Variant("pending"))
        assert isinstance(bare, Variant)
        self.assertIs(bare.payload, NO_PAYLOAD)
        absent = decode(
            {"type": "variant", "name": "note", "payload": {"type": "null"}}
        )
        self.assertEqual(absent, Variant("note", None))
        self.assertNotEqual(canonical(bare), canonical(Variant("pending", None)))

    def test_a_reference_decodes_to_the_value_it_refers_to(self) -> None:
        """The id names the object, and the codec returns its value."""
        literal = {"type": "reference", "id": "a", "value": {"type": "int", "value": 1}}
        self.assertEqual(decode(literal), 1)
        self.assertEqual(encode(decode(literal)), {"type": "int", "value": 1})

    def test_an_absent_list_or_map_of_a_stated_type_decodes_to_none(self) -> None:
        """A null value in the of form states an absent container."""
        self.assertIsNone(decode({"type": "list", "of": "int", "value": None}))
        absent_map = {"type": "map", "key": "string", "of": "int", "value": None}
        self.assertIsNone(decode(absent_map))

    def test_a_literal_the_encoding_does_not_define_raises(self) -> None:
        """Each malformed form."""
        malformed: list[object] = [
            {"type": "list", "of": "widget", "value": None},
            {"type": "list", "value": None},
            {"type": "map", "key": "int", "of": "int", "value": None},
            {"type": "map", "key": "string", "of": "widget", "value": None},
            [1],
            {"type": "int", "value": "3"},
            {"type": "int", "value": True},
            {"type": "int", "value": PINNED_SAFE + 1},
            {"type": "int", "value": "09007199254740993"},
            {"type": "float", "value": "Infinity"},
            {"type": "bytes", "value": "0G"},
            {"type": "bytes", "value": "FF"},
            {"type": "list", "of": "int", "value": [1, "2"]},
            {"type": "list", "of": "int", "value": 1},
            {"type": "list", "items": 1},
            {"type": "map", "key": "int", "of": "int", "value": {}},
            {"type": "map", "entries": [[{"type": "null"}]]},
            {"type": "set", "value": []},
            {"type": "record", "fields": {"id": {"type": "int", "value": 1}}},
            {"type": "record", "fields": [["id"]]},
            {"type": "record", "fields": [["", {"type": "null"}]]},
            {"type": "record", "fields": [[1, {"type": "null"}]]},
            {
                "type": "record",
                "fields": [["id", {"type": "null"}], ["id", {"type": "null"}]],
            },
            {"type": "record", "fields": [["id", {"type": "int"}]]},
            {"type": "variant"},
            {"type": "variant", "name": ""},
            {"type": "variant", "name": "x", "payload": 1},
            {"type": "reference", "value": {"type": "int", "value": 1}},
            {"type": "reference", "id": "", "value": {"type": "int", "value": 1}},
            {"type": "reference", "id": 1, "value": {"type": "int", "value": 1}},
            {"type": "reference", "id": "a", "value": {"type": "null"}},
            {"type": "reference", "id": "a", "value": 1},
        ]
        for literal in malformed:
            with self.assertRaises(LiteralError, msg=str(literal)):
                decode(literal)


@final
class EncodeTest(unittest.TestCase):
    """encode(): the one canonical literal of each value."""

    def test_a_list_of_one_scalar_type_uses_of_and_value(self) -> None:
        """The compact form, as the existing corpus writes it."""
        self.assertEqual(encode([7, 3]), {"type": "list", "of": "int", "value": [7, 3]})

    def test_an_empty_or_mixed_list_uses_items(self) -> None:
        """No scalar type to name, or more than one."""
        self.assertEqual(encode([]), {"type": "list", "items": []})
        mixed = encode([1, [2]])
        self.assertEqual(
            mixed,
            {
                "type": "list",
                "items": [
                    {"type": "int", "value": 1},
                    {"type": "list", "of": "int", "value": [2]},
                ],
            },
        )

    def test_a_bool_list_is_not_an_int_list(self) -> None:
        """True and 1 are different types."""
        self.assertEqual(encode([True, 1])["items"][0], {"type": "bool", "value": True})

    def test_special_floats_and_large_ints_take_their_string_forms(self) -> None:
        """NaN, the infinities and an unsafe integer."""
        self.assertEqual(encode(math.nan), {"type": "float", "value": "NaN"})
        self.assertEqual(encode(-math.inf), {"type": "float", "value": "-Inf"})
        big = PINNED_SAFE + 1
        self.assertEqual(encode(big), {"type": "int", "value": str(big)})
        self.assertEqual(
            encode([big]), {"type": "list", "of": "int", "value": [str(big)]}
        )

    def test_bytes_and_maps_take_their_forms(self) -> None:
        """Hexadecimal bytes, and entries in order."""
        self.assertEqual(encode(b"\x01\xab"), {"type": "bytes", "value": "01ab"})
        self.assertEqual(
            encode(Pairs(((1, "a"),))),
            {
                "type": "map",
                "entries": [
                    [{"type": "int", "value": 1}, {"type": "string", "value": "a"}]
                ],
            },
        )

    def test_records_and_variants_take_their_forms(self) -> None:
        """Fields in order, and a payload only when the variant has one."""
        self.assertEqual(
            encode(Record((("id", 1),))),
            {"type": "record", "fields": [["id", {"type": "int", "value": 1}]]},
        )
        self.assertEqual(
            encode(Variant("pending")), {"type": "variant", "name": "pending"}
        )
        self.assertEqual(
            encode(Variant("note", None)),
            {"type": "variant", "name": "note", "payload": {"type": "null"}},
        )

    def test_every_value_round_trips(self) -> None:
        """decode(encode(v)) equals v, signed zero and NaN included."""
        values: list[object] = [
            None,
            False,
            -0.0,
            math.nan,
            2**64 - 1,
            "",
            b"",
            [],
            [[], [1.5]],
            Pairs(((None, [b"x"]),)),
            Record((("a", [Record(())]), ("b", Variant("v", Variant("w"))))),
            [Variant("x"), Variant("x", None)],
        ]
        for value in values:
            self.assertEqual(canonical(decode(encode(value))), canonical(value), value)

    def test_a_value_no_generator_decodes_raises(self) -> None:
        """A tuple has no literal."""
        with self.assertRaises(TypeError):
            encode((1,))
