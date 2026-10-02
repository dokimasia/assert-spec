"""Shapes: what each decodes from stated choices, its defaults, and how a read fails."""

from __future__ import annotations

import calendar
import unittest
from typing import Any, final

from .case import Case, Generating, Replaying
from .choice import INT64_MAX, Choice, Value
from .generator import Integer
from .shape import (
    BUDGET,
    FIRST_DAY,
    FIRST_SECOND,
    LAST_DAY,
    LAST_SECOND,
    SHAPES,
    Root,
    ShapeError,
    read,
)
from .source import case_source
from .value import NO_PAYLOAD, Pairs, Record, Variant
from .zone import zones

#: The shape ids the definition states, pinned as written there.
PINNED_SHAPES = frozenset(
    {
        "bool",
        "int",
        "float",
        "char",
        "string",
        "bytes",
        "list",
        "fixed-list",
        "set",
        "map",
        "optional",
        "record",
        "enum",
        "literal",
        "ref",
        "uuid",
        "ip-address",
        "decimal",
        "instant",
        "date",
        "time-of-day",
        "local-date-time",
        "duration",
        "offset",
        "zone",
        "zoned-date-time",
        "wall-time",
    }
)

INT8: dict[str, Any] = {"shape": "int", "width": 8, "signed": True}
UINT8: dict[str, Any] = {"shape": "int", "width": 8, "signed": False}

#: A tree: a value and a list of children, each a tree.
TREE: dict[str, Any] = {
    "shape": "ref",
    "name": "tree",
    "definitions": {
        "tree": {
            "shape": "record",
            "fields": [
                ["value", UINT8],
                ["children", {"shape": "list", "of": {"shape": "ref", "name": "tree"}}],
            ],
        }
    },
}


def _choice(value: Value) -> Choice:
    """Return value as a recorded choice of the kind its type implies."""
    if isinstance(value, tuple):
        return Choice("sequence", value)
    if isinstance(value, float):
        return Choice("float", value)
    return Choice("integer", value)


def decode(shape: dict[str, Any], *values: Value) -> tuple[object, Case]:
    """Decode a shape from recorded values, and return the value and the case."""
    case = Case(Replaying([_choice(v) for v in values]))
    return read(shape).decode(case), case


def _seconds(year: int, month: int, day: int) -> int:
    """Return the seconds since the epoch of a UTC midnight."""
    return calendar.timegm((year, month, day, 0, 0, 0))


@final
class VocabularyTest(unittest.TestCase):
    """The shape ids and the defaults of the date and time shapes."""

    def test_the_vocabulary_is_the_definitions(self) -> None:
        """Twenty-seven shapes, pinned."""
        self.assertEqual(SHAPES, PINNED_SHAPES)

    def test_the_default_range_is_the_years_1_to_9999(self) -> None:
        """The first and the last second and day of the range."""
        self.assertEqual(FIRST_SECOND, _seconds(1, 1, 1))
        self.assertEqual(LAST_SECOND, _seconds(9999, 12, 31) + 86_399)
        self.assertEqual((FIRST_DAY, LAST_DAY), (-719_162, 2_932_896))


@final
class StructuralTest(unittest.TestCase):
    """The shapes that decode as the generator vocabulary does."""

    def test_a_bool_is_a_boolean(self) -> None:
        """1 is true, and the target false."""
        self.assertIs(decode({"shape": "bool"}, 1)[0], True)
        self.assertIs(decode({"shape": "bool"})[0], False)

    def test_an_int_ranges_over_its_width(self) -> None:
        """Both ends of a signed and an unsigned byte."""
        self.assertEqual(decode(INT8, -128)[0], -128)
        self.assertEqual(decode(INT8, 128)[0], 0)
        self.assertEqual(decode(UINT8, 255)[0], 255)
        self.assertEqual(decode(UINT8, -1)[0], 0)

    def test_an_int_takes_its_bounds_from_min_and_max(self) -> None:
        """A value outside the bounds replays as the target."""
        bounded = {**INT8, "min": 1, "max": 99}
        self.assertEqual(decode(bounded, 99)[0], 99)
        self.assertEqual(decode(bounded, 100)[0], 1)

    def test_a_128_bit_int_is_two_halves(self) -> None:
        """The high half, signed, then the low half, unsigned."""
        wide = {"shape": "int", "width": 128, "signed": True}
        self.assertEqual(decode(wide, -1, 2**64 - 1)[0], -1)
        self.assertEqual(decode(wide, 1, 0)[0], 2**64)
        self.assertEqual(decode(wide, -(2**63), 0)[0], -(2**127))
        unsigned = {"shape": "int", "width": 128, "signed": False}
        self.assertEqual(decode(unsigned, 2**64 - 1, 2**64 - 1)[0], 2**128 - 1)

    def test_the_low_half_stops_at_a_bound_its_high_half_reaches(self) -> None:
        """A minimum of 2^64 + 10 keeps the low half at 10 or more."""
        bounded = {"shape": "int", "width": 128, "signed": False}
        bounded.update(min=str(2**64 + 10), max=str(2**65))
        self.assertEqual(decode(bounded, 1, 3)[0], 2**64 + 10)
        self.assertEqual(decode(bounded, 2, 9)[0], 2**65)
        self.assertEqual(decode(bounded, 1, 11)[0], 2**64 + 11)

    def test_a_float_is_finite_unless_the_infinities_are_allowed(self) -> None:
        """An infinity replays as the target until allow_infinity admits it."""
        finite = {"shape": "float", "width": 64}
        self.assertEqual(decode(finite, float("inf"))[0], 0.0)
        infinite = {**finite, "allow_infinity": True}
        self.assertEqual(decode(infinite, float("inf"))[0], float("inf"))

    def test_a_float_of_width_32_is_a_binary32_value(self) -> None:
        """0.1 is no binary32 value, and 0.5 is."""
        narrow = {"shape": "float", "width": 32}
        self.assertEqual(decode(narrow, 0.1)[0], 0.0)
        self.assertEqual(decode(narrow, 0.5)[0], 0.5)

    def test_a_char_is_one_character_of_its_alphabet(self) -> None:
        """The default alphabet starts at 0, and a stated one at its first."""
        self.assertEqual(decode({"shape": "char"}, (10,))[0], "a")
        self.assertEqual(decode({"shape": "char", "alphabet": "xyz"}, (2,))[0], "z")

    def test_a_string_is_a_sequence_of_indices(self) -> None:
        """Sizes bound the sequence, and a pattern decodes as string-matching."""
        sized = {"shape": "string", "min_size": 2, "max_size": 3}
        self.assertEqual(decode(sized, (1,))[0], "10")
        self.assertEqual(decode({"shape": "string", "pattern": "a|b"}, 1)[0], "b")

    def test_bytes_are_a_sequence_of_byte_values(self) -> None:
        """Two bytes."""
        self.assertEqual(decode({"shape": "bytes"}, (0, 255))[0], b"\x00\xff")

    def test_a_list_and_a_fixed_list_decode_as_collections(self) -> None:
        """Flags then elements, and a fixed size that forces each flag."""
        listed = {"shape": "list", "of": UINT8}
        self.assertEqual(decode(listed, 1, 7, 1, 8, 0)[0], [7, 8])
        fixed = {"shape": "fixed-list", "of": UINT8, "size": 2}
        self.assertEqual(decode(fixed, 1, 7, 1, 8, 0)[0], [7, 8])

    def test_a_set_discards_a_repeated_element(self) -> None:
        """The second 7 is discarded, and the next flag stops the set."""
        self.assertEqual(decode({"shape": "set", "of": UINT8}, 1, 7, 1, 7, 0)[0], [7])

    def test_a_map_decodes_as_a_dict(self) -> None:
        """Entries of a key and a value."""
        mapped = {"shape": "map", "key": UINT8, "of": {"shape": "bool"}}
        self.assertEqual(decode(mapped, 1, 3, 1, 0)[0], Pairs(((3, True),)))

    def test_an_optional_is_absent_or_present(self) -> None:
        """The target is absent."""
        optional = {"shape": "optional", "of": UINT8}
        self.assertIsNone(decode(optional)[0])
        self.assertEqual(decode(optional, 1, 5)[0], 5)

    def test_a_record_decodes_its_fields_in_order(self) -> None:
        """Each field's choices follow the field before it."""
        record = {
            "shape": "record",
            "fields": [["id", UINT8], ["ok", {"shape": "bool"}]],
        }
        self.assertEqual(decode(record, 4, 1)[0], Record((("id", 4), ("ok", True))))

    def test_an_enum_decodes_an_index_then_the_payload(self) -> None:
        """A variant without a payload makes no further choice."""
        enum = {"shape": "enum", "variants": [["none", None], ["some", UINT8]]}
        bare = decode(enum)[0]
        self.assertEqual(bare, Variant("none"))
        assert isinstance(bare, Variant)
        self.assertIs(bare.payload, NO_PAYLOAD)
        self.assertEqual(decode(enum, 1, 9)[0], Variant("some", 9))

    def test_a_literal_is_one_of_its_values(self) -> None:
        """An index into the stated values."""
        values = [{"type": "string", "value": v} for v in ("paid", "shipped")]
        self.assertEqual(
            decode({"shape": "literal", "values": values}, 1)[0], "shipped"
        )


@final
class DomainTest(unittest.TestCase):
    """The domain shapes and the form of their values."""

    def test_a_uuid_is_16_bytes(self) -> None:
        """A sequence of exactly 16 bytes."""
        self.assertEqual(
            decode({"shape": "uuid"}, tuple(range(16)))[0], bytes(range(16))
        )

    def test_an_address_of_either_version_is_an_index_then_bytes(self) -> None:
        """Version 4, version 6, and either."""
        self.assertEqual(
            decode({"shape": "ip-address", "version": 4}, (127, 0, 0, 1))[0],
            b"\x7f\x00\x00\x01",
        )
        self.assertEqual(decode({"shape": "ip-address", "version": 6})[0], bytes(16))
        self.assertEqual(decode({"shape": "ip-address"}, 1, (1,) * 16)[0], b"\x01" * 16)

    def test_a_decimal_is_its_unscaled_value(self) -> None:
        """A bound with more digits than the scale rounds inward."""
        money = {"shape": "decimal", "scale": 2, "min": "0.005", "max": "1.999"}
        self.assertEqual(decode(money, 0)[0], 1)
        self.assertEqual(decode(money, 199)[0], 199)
        self.assertEqual(decode(money, 200)[0], 1)
        self.assertEqual(
            decode({"shape": "decimal", "scale": 0}, INT64_MAX)[0], INT64_MAX
        )

    def test_an_instant_is_its_seconds_and_its_units(self) -> None:
        """Two choices at nanoseconds, and one at seconds."""
        self.assertEqual(
            decode({"shape": "instant", "unit": "ns"}, -1, 999_999_999)[0],
            Record((("seconds", -1), ("units", 999_999_999))),
        )
        value, case = decode({"shape": "instant", "unit": "s"}, LAST_SECOND)
        self.assertEqual(value, Record((("seconds", LAST_SECOND), ("units", 0))))
        self.assertEqual(len(case.choices), 1)

    def test_an_instant_bound_stops_the_units_of_its_second(self) -> None:
        """A minimum at half a second keeps the units of that second at 500."""
        start = _seconds(2020, 1, 1)
        bounded = {"shape": "instant", "unit": "ms", "min": "2020-01-01T00:00:00.5Z"}
        self.assertEqual(
            decode(bounded, start, 3)[0], Record((("seconds", start), ("units", 500)))
        )
        self.assertEqual(
            decode(bounded, start + 1, 3)[0],
            Record((("seconds", start + 1), ("units", 3))),
        )

    def test_a_date_is_its_days_since_the_epoch(self) -> None:
        """Bounds state dates."""
        bounded = {"shape": "date", "min": "1970-01-02", "max": "1970-01-31"}
        self.assertEqual(decode(bounded, 0)[0], 1)
        self.assertEqual(decode(bounded, 30)[0], 30)

    def test_a_time_of_day_is_its_units_since_midnight(self) -> None:
        """The last millisecond of a day."""
        self.assertEqual(
            decode({"shape": "time-of-day", "unit": "ms"}, 86_399_999)[0], 86_399_999
        )
        late = {"shape": "time-of-day", "unit": "s", "min": "23:00:00"}
        self.assertEqual(decode(late, 0)[0], 82_800)

    def test_a_local_date_time_is_its_date_and_its_time_of_day(self) -> None:
        """A bound stops the time of day on its own date."""
        bounded = {
            "shape": "local-date-time",
            "unit": "s",
            "max": "1970-01-02T12:00:00",
        }
        self.assertEqual(
            decode(bounded, 1, 86_399)[0],
            Record((("date", 1), ("time-of-day", 0))),
        )
        self.assertEqual(
            decode(bounded, 0, 86_399)[0],
            Record((("date", 0), ("time-of-day", 86_399))),
        )

    def test_a_duration_ranges_over_a_go_duration_in_its_unit(self) -> None:
        """2^63 - 1 nanoseconds, and that many seconds rounded down."""
        self.assertEqual(
            decode({"shape": "duration", "unit": "ns"}, INT64_MAX)[0], INT64_MAX
        )
        self.assertEqual(
            decode({"shape": "duration", "unit": "s"}, -9_223_372_036)[0],
            -9_223_372_036,
        )
        self.assertEqual(
            decode({"shape": "duration", "unit": "s"}, 9_223_372_037)[0], 0
        )

    def test_an_offset_is_at_most_18_hours_either_way(self) -> None:
        """64,800 seconds east and west."""
        self.assertEqual(decode({"shape": "offset"}, -64_800)[0], -64_800)
        self.assertEqual(decode({"shape": "offset"}, 64_801)[0], 0)

    def test_a_zone_is_a_name_of_the_list_and_utc_first(self) -> None:
        """The target is UTC."""
        self.assertEqual(decode({"shape": "zone"})[0], "UTC")
        self.assertEqual(decode({"shape": "zone"}, 1)[0], zones()[1].name)


@final
class ZonedTest(unittest.TestCase):
    """zoned-date-time and wall-time: a zone, then a value near a change or not."""

    def test_a_zone_without_a_change_takes_the_whole_range(self) -> None:
        """UTC makes no choice of a change, so its instant follows its index."""
        value, case = decode({"shape": "zoned-date-time", "unit": "s"}, 0, 42)
        self.assertEqual(
            value,
            Record(
                (("instant", Record((("seconds", 42), ("units", 0)))), ("zone", "UTC"))
            ),
        )
        self.assertEqual(len(case.choices), 2)

    def test_an_instant_near_a_change_is_one_unit_from_it(self) -> None:
        """Amsterdam's first change, one nanosecond before it."""
        change = zones()[1].changes[0]
        value = decode({"shape": "zoned-date-time", "unit": "ns"}, 1, 1, 0, -1)[0]
        self.assertEqual(
            value,
            Record(
                (
                    (
                        "instant",
                        Record((("seconds", change.at - 1), ("units", 999_999_999))),
                    ),
                    ("zone", "Europe/Amsterdam"),
                )
            ),
        )

    def test_an_instant_away_from_the_changes_takes_the_whole_range(self) -> None:
        """A near choice of 0, then the instant's two choices."""
        value = decode({"shape": "zoned-date-time", "unit": "ms"}, 1, 0, 7, 8)[0]
        self.assertEqual(
            value,
            Record(
                (
                    ("instant", Record((("seconds", 7), ("units", 8)))),
                    ("zone", "Europe/Amsterdam"),
                )
            ),
        )

    def test_a_wall_time_near_a_change_takes_the_offset_before_or_after(self) -> None:
        """Amsterdam's first change, at its instant, in each offset."""
        change = zones()[1].changes[0]
        for side, offset in ((0, change.before), (1, change.after)):
            value = decode({"shape": "wall-time", "unit": "s"}, 1, 1, 0, 0, side)[0]
            day, time = divmod(change.at + offset, 86_400)
            self.assertEqual(
                value,
                Record(
                    (
                        (
                            "local-date-time",
                            Record((("date", day), ("time-of-day", time))),
                        ),
                        ("zone", "Europe/Amsterdam"),
                    )
                ),
                side,
            )

    def test_one_case_in_four_comes_from_the_changes(self) -> None:
        """Of 4,000 generated values in zones with changes, about a quarter."""
        shape = read({"shape": "zoned-date-time", "unit": "s"})
        near = changed = 0
        for index in range(4000):
            case = Case(Generating(case_source(11, index)))
            shape.decode(case)
            zone = case.choices[0].value
            assert isinstance(zone, int)
            if zones()[zone].changes:
                changed += 1
                near += case.choices[1].value == 1
        self.assertGreater(changed, 3000)
        self.assertAlmostEqual(near / changed, 0.25, delta=0.03)


@final
class RecursionTest(unittest.TestCase):
    """Definitions, refs, and the budget of a recursive value."""

    def test_a_tree_decodes_through_its_definition(self) -> None:
        """A tree of one child with no children."""
        value = decode(TREE, 3, 1, 4, 0, 0)[0]
        self.assertEqual(
            value,
            Record(
                (
                    ("value", 3),
                    ("children", [Record((("value", 4), ("children", [])))]),
                )
            ),
        )

    def test_a_value_stops_growing_once_it_has_used_its_budget(self) -> None:
        """Every list takes no further element once the value has used it."""
        shape = read(TREE)

        def nodes(value: object) -> int:
            assert isinstance(value, Record)
            children = value.fields[1][1]
            assert isinstance(children, list)
            return 1 + sum(nodes(child) for child in children)

        largest = 0
        for index in range(300):
            case = Case(Generating(case_source(5, index)))
            largest = max(largest, nodes(shape.decode(case)))
        self.assertEqual(largest, BUDGET)

    def test_an_enum_takes_its_first_exit_once_the_budget_is_used(self) -> None:
        """A list of variants that each wrap a list: the exit is the leaf."""
        nested = {
            "shape": "ref",
            "name": "node",
            "definitions": {
                "node": {
                    "shape": "enum",
                    "variants": [
                        [
                            "branch",
                            {
                                "shape": "fixed-list",
                                "size": 2,
                                "of": {"shape": "ref", "name": "node"},
                            },
                        ],
                        ["leaf", None],
                    ],
                }
            },
        }
        value = decode(nested, *([0] * 400))[0]

        def count(node: object) -> int:
            assert isinstance(node, Variant)
            if node.name == "leaf":
                return 1
            assert isinstance(node.payload, list)
            return 1 + sum(count(child) for child in node.payload)

        self.assertLess(count(value), 3 * BUDGET)

    def test_a_definition_that_reaches_itself_without_an_exit_fails(self) -> None:
        """A record that contains itself has no finite value."""
        endless = {
            "shape": "ref",
            "name": "loop",
            "definitions": {
                "loop": {
                    "shape": "record",
                    "fields": [["next", {"shape": "ref", "name": "loop"}]],
                }
            },
        }
        with self.assertRaisesRegex(ShapeError, "definitions.loop has no finite value"):
            read(endless)

    def test_a_list_with_a_minimum_is_no_exit(self) -> None:
        """A list that must hold an element cannot end a tree."""
        endless = {
            "shape": "ref",
            "name": "t",
            "definitions": {
                "t": {
                    "shape": "list",
                    "min_size": 1,
                    "of": {"shape": "ref", "name": "t"},
                }
            },
        }
        with self.assertRaisesRegex(ShapeError, "has no finite value"):
            read(endless)

    def test_an_enum_whose_every_variant_refers_back_is_no_exit(self) -> None:
        """Every variant refers back, so no variant ends the value."""
        endless = {
            "shape": "ref",
            "name": "e",
            "definitions": {
                "e": {
                    "shape": "enum",
                    "variants": [["only", {"shape": "ref", "name": "e"}]],
                }
            },
        }
        with self.assertRaisesRegex(ShapeError, "has no finite value"):
            read(endless)

    def test_a_ref_to_no_definition_fails(self) -> None:
        """A ref names a definition of the file."""
        with self.assertRaisesRegex(
            ShapeError, "names 'missing', which is no definition"
        ):
            read({"shape": "ref", "name": "missing"})


@final
class ReadTest(unittest.TestCase):
    """What fails to read, and where the failure says it is."""

    def test_a_misstated_shape_fails_and_names_where(self) -> None:
        """Each fault, with the part of its message that locates it."""
        faults: list[tuple[object, str]] = [
            ([], "is not a shape"),
            ({"shape": "widget"}, "shape is 'widget', which is no shape"),
            ({"shape": "int", "width": 8}, "states no signed, which the int shape"),
            ({"shape": "int", "width": 12, "signed": True}, "states width 12"),
            ({**INT8, "mx": 1}, "shape.mx does not apply to the int shape"),
            ({**INT8, "min": 200}, "are empty or outside"),
            (
                {"shape": "record", "fields": [["id", {**UINT8, "max": "x"}]]},
                "shape.id",
            ),
            (
                {"shape": "record", "fields": [["id", UINT8], ["id", UINT8]]},
                "names 'id' twice",
            ),
            ({"shape": "record", "fields": []}, "not a list of pairs"),
            ({"shape": "enum", "variants": [["x"]]}, "not a name and a shape"),
            ({"shape": "decimal", "scale": None}, "states no scale"),
            ({"shape": "decimal", "scale": 2, "min": "1e3"}, "'1e3', not a decimal"),
            ({"shape": "fixed-list", "of": UINT8, "size": None}, "states no size"),
            (
                {"shape": "string", "pattern": "a", "max_size": 3},
                "a pattern and an alphabet",
            ),
            ({"shape": "string", "alphabet": "aa"}, "repeats a character"),
            ({"shape": "float", "width": 16}, "not 32 or 64"),
            ({"shape": "float", "width": 64, "allow_nan": "yes"}, "as no boolean"),
            (
                {
                    "shape": "float",
                    "width": 64,
                    "allow_infinity": True,
                    "min": 0,
                    "max": 1,
                },
                "bounds out both",
            ),
            ({"shape": "ip-address", "version": 5}, "not 4 or 6"),
            ({"shape": "instant", "unit": "min"}, "not one of"),
            (
                {"shape": "instant", "unit": "s", "min": "2020-01-01T00:00:00"},
                "no instant in UTC",
            ),
            (
                {"shape": "instant", "unit": "s", "min": "2020-01-01T00:00:00.5Z"},
                "finer than its unit",
            ),
            ({"shape": "date", "min": "2021-02-29"}, "which is no date"),
            (
                {"shape": "time-of-day", "unit": "s", "max": "24:00:00"},
                "which is no time",
            ),
            (
                {
                    "shape": "local-date-time",
                    "unit": "s",
                    "min": "2020-01-01T00:00:00Z",
                },
                "no local date",
            ),
            ({"shape": "list", "of": UINT8, "min_size": 3, "max_size": 2}, "are empty"),
            ({"shape": "list", "of": UINT8, "min_size": -1}, "below 0"),
            ({"shape": "optional", "of": 3}, "shape.of is 3, not a shape"),
            ({"shape": "literal", "values": []}, "not a list of literals"),
            ({**UINT8, "definitions": []}, "definitions is not a map"),
            ({**UINT8, "definitions": {"id": 3}}, "definitions.id is 3, not a shape"),
            ({**UINT8, "source": {"language": "go"}}, "not a language and a type"),
            (
                {"shape": "list", "of": {**UINT8, "source": {}}},
                "shape.of.source does not apply",
            ),
            ({"shape": "int", "width": "x", "signed": True}, "shape.width is 'x'"),
            ({"shape": "int", "width": 8, "signed": "yes"}, "signed 'yes'"),
            ({"shape": "char", "alphabet": 3}, "shape.alphabet is 3"),
            ({"shape": "string", "pattern": 3}, "shape.pattern is 3, not a pattern"),
            ({"shape": "date", "min": "2020/01/01"}, "'2020/01/01' is no date"),
            (
                {"shape": "time-of-day", "unit": "s", "min": "noon"},
                "'noon' is no time of day",
            ),
            (
                {
                    "shape": "instant",
                    "unit": "s",
                    "min": "2020-01-02T00:00:00Z",
                    "max": "2020-01-01T00:00:00Z",
                },
                "are empty or out of range",
            ),
        ]
        for shape, message in faults:
            with self.subTest(shape=shape), self.assertRaisesRegex(ShapeError, message):
                read(shape)

    def test_a_root_may_state_its_source(self) -> None:
        """The source names a language and a type, and no reader compares it."""
        shape = {**UINT8, "source": {"language": "go", "type": "example.com/x.Qty"}}
        self.assertEqual(read(shape).decode(Case(Replaying([Choice("integer", 7)]))), 7)

    def test_a_ref_to_a_definition_without_recursion_spends_no_budget(self) -> None:
        """A named shape that does not reach itself is only a name."""
        named = {
            "shape": "list",
            "of": {"shape": "ref", "name": "id"},
            "definitions": {"id": UINT8},
        }
        self.assertEqual(decode(named, 1, 4, 1, 5, 0)[0], [4, 5])

    def test_a_shape_without_recursion_reads_as_the_generator_it_maps_to(self) -> None:
        """An int is an integer, so the explain phase steps it as one.

        Only a recursive shape is wrapped, to count each value's budget.
        """
        self.assertIsInstance(read(INT8), Integer)
        self.assertIsInstance(read(TREE), Root)


@final
class MoreRecursionTest(unittest.TestCase):
    """Recursion through optionals, and through more than one definition."""

    def test_a_linked_list_ends_at_an_absent_next(self) -> None:
        """A record whose next node is optional."""
        linked = {
            "shape": "ref",
            "name": "node",
            "definitions": {
                "node": {
                    "shape": "record",
                    "fields": [
                        ["value", UINT8],
                        [
                            "next",
                            {
                                "shape": "optional",
                                "of": {"shape": "ref", "name": "node"},
                            },
                        ],
                    ],
                }
            },
        }
        self.assertEqual(
            decode(linked, 1, 1, 2)[0],
            Record(
                (
                    ("value", 1),
                    ("next", Record((("value", 2), ("next", None)))),
                )
            ),
        )

    def test_definitions_that_reach_each_other_are_cyclic_together(self) -> None:
        """An even and an odd node, each optional in the other."""
        mutual = {
            "shape": "ref",
            "name": "even",
            "definitions": {
                "even": {"shape": "optional", "of": {"shape": "ref", "name": "odd"}},
                "odd": {
                    "shape": "record",
                    "fields": [["next", {"shape": "ref", "name": "even"}]],
                },
            },
        }
        value = decode(mutual, *([1] * 400))[0]
        depth = 0
        while value is not None:
            assert isinstance(value, Record)
            value = value.fields[0][1]
            depth += 1
        self.assertEqual(depth, BUDGET // 2)

    def test_a_map_that_refers_back_stops_once_the_budget_is_used(self) -> None:
        """Children keyed by number, each a node: the value stops at the budget."""
        keyed = {
            "shape": "ref",
            "name": "node",
            "definitions": {
                "node": {
                    "shape": "map",
                    "key": {"shape": "int", "width": 64, "signed": False},
                    "of": {"shape": "ref", "name": "node"},
                }
            },
        }
        shape = read(keyed)

        def nodes(value: object) -> int:
            assert isinstance(value, Pairs)
            return 1 + sum(nodes(child) for _, child in value.items)

        largest = max(
            nodes(shape.decode(Case(Generating(case_source(3, index)))))
            for index in range(200)
        )
        self.assertEqual(largest, BUDGET)

    def test_two_definitions_that_reach_each_other_without_an_exit_fail(self) -> None:
        """Each record contains the other, so neither ends."""
        endless = {
            "shape": "ref",
            "name": "a",
            "definitions": {
                "a": {
                    "shape": "record",
                    "fields": [["b", {"shape": "ref", "name": "b"}]],
                },
                "b": {
                    "shape": "record",
                    "fields": [["a", {"shape": "ref", "name": "a"}]],
                },
            },
        }
        with self.assertRaisesRegex(ShapeError, "definitions.a has no finite value"):
            read(endless)

    def test_a_wall_time_away_from_the_changes_takes_the_whole_range(self) -> None:
        """A near choice of 0, then the local date and time's two choices."""
        value = decode({"shape": "wall-time", "unit": "s"}, 1, 0, 5, 6)[0]
        self.assertEqual(
            value,
            Record(
                (
                    ("local-date-time", Record((("date", 5), ("time-of-day", 6)))),
                    ("zone", "Europe/Amsterdam"),
                )
            ),
        )
