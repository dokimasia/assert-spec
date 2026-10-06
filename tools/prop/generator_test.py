"""The generators: what each decodes from stated choices, and how it fails."""

from __future__ import annotations

import math
import unittest
from typing import Any, final

from . import draw
from .case import Case, Generating, Generator, Rejected, Replaying, Request, Span
from .choice import Choice, IntegerBounds, Value
from .generator import DEFAULT_MAX_LEAVES, IDS, SpecError, build
from .source import Source
from .value import Pairs, canonical

#: Seeds per generation check.
SEEDS = 200

#: The generator ids the definition states, pinned as written there.
PINNED_IDS = frozenset(
    {
        "integer",
        "float",
        "boolean",
        "just",
        "sampled-from",
        "one-of",
        "optional",
        "list",
        "dict",
        "string",
        "bytes",
        "duration",
        "permutation",
        "string-matching",
        "recursive",
        "filter",
        "map",
    }
)

DIGIT: dict[str, Any] = {"gen": "integer", "min": 0, "max": 9}
TEEN: dict[str, Any] = {"gen": "integer", "min": 10, "max": 20}
BOOLEAN: dict[str, Any] = {"gen": "boolean"}
LETTERS: dict[str, Any] = {
    "gen": "sampled-from",
    "values": [{"type": "string", "value": c} for c in "abc"],
}
DIGITS: dict[str, Any] = {"gen": "list", "of": DIGIT, "min_size": 0, "max_size": 3}
UNIQUE: dict[str, Any] = {"gen": "list", "of": DIGIT, "unique": True}
TABLE: dict[str, Any] = {"gen": "dict", "keys": DIGIT, "values": BOOLEAN, "max_size": 3}
TREE: dict[str, Any] = {
    "gen": "recursive",
    "base": DIGIT,
    "extend": {"gen": "list", "of": {"gen": "self"}, "max_size": 3},
}
KEEP_EVEN: dict[str, Any] = {
    "gen": "filter",
    "of": DIGIT,
    "keep": {"kind": "divisible-by", "n": 2},
}
SORTED: dict[str, Any] = {"gen": "map", "of": DIGITS, "subject": "sorts"}

#: One spec per generator of the vocabulary, for the checks that hold for
#: every one.
EVERY: dict[str, dict[str, Any]] = {
    "integer": DIGIT,
    "float": {"gen": "float", "min": "-Inf", "max": "Inf", "allow_nan": True},
    "boolean": {"gen": "boolean", "p": [1, 3]},
    "just": {"gen": "just", "value": {"type": "int", "value": 4}},
    "sampled-from": LETTERS,
    "one-of": {"gen": "one-of", "of": [DIGIT, TEEN]},
    "optional": {"gen": "optional", "of": DIGIT},
    "list": DIGITS,
    "unique-list": UNIQUE,
    "dict": TABLE,
    "string": {"gen": "string", "max_size": 4},
    "alphabet": {"gen": "string", "alphabet": "xyz"},
    "string-matching": {"gen": "string-matching", "pattern": "(a|[0-9]+)\\.?x{2}"},
    "bytes": {"gen": "bytes"},
    "duration": {"gen": "duration", "min": -(10**9), "max": 10**9},
    "permutation": {"gen": "permutation", "values": LETTERS["values"]},
    "recursive": TREE,
    "filter": KEEP_EVEN,
    "map": SORTED,
}


@final
class _Feed:
    """A provider that returns the stated values in order, whatever the index."""

    def __init__(self, *values: Value) -> None:
        """Return values, one per request."""
        self._values = iter(values)

    def value(self, request: Request, index: int) -> Value:
        """Return the next stated value."""
        del request, index
        return next(self._values)


def _choice(value: Value) -> Choice:
    """Return value as a recorded choice of the kind its type implies."""
    if isinstance(value, tuple):
        return Choice("sequence", value)
    if isinstance(value, float):
        return Choice("float", value)
    return Choice("integer", value)


def decode(spec: dict[str, Any], *values: Value) -> tuple[object, Case]:
    """Decode spec from recorded values, and return the value and the case."""
    case = Case(Replaying([_choice(v) for v in values]))
    return build(spec).decode(case), case


def _decoded(generator: Generator, case: Case) -> object:
    """Return the canonical value generator decodes from case, or Rejected."""
    try:
        return canonical(generator.decode(case))
    except Rejected:
        return Rejected


@final
class IntegerTest(unittest.TestCase):
    """integer and duration: one integer choice."""

    def test_a_recorded_value_decodes_to_itself(self) -> None:
        """7 inside [0, 9] is 7."""
        self.assertEqual(decode(DIGIT, 7)[0], 7)

    def test_the_target_is_the_value_closest_to_zero(self) -> None:
        """[3, 9] decodes to 3 and [-9, -3] to -3 from no choices."""
        self.assertEqual(decode({"gen": "integer", "min": 3, "max": 9})[0], 3)
        self.assertEqual(decode({"gen": "integer", "min": -9, "max": -3})[0], -3)

    def test_the_choice_is_a_value_inside_a_span_named_by_the_id(self) -> None:
        """One span, one request, and no edge value."""
        _, case = decode(DIGIT, 7)
        self.assertEqual(case.spans, [Span("integer", 0, 1, 0, None)])
        self.assertIsNone(case.requests[0].edge)

    def test_a_duration_decodes_nanoseconds_under_its_own_id(self) -> None:
        """The same choice as an integer, in a span named duration."""
        value, case = decode({"gen": "duration", "min": 0, "max": 10**9}, 5)
        self.assertEqual(value, 5)
        self.assertEqual(case.spans, [Span("duration", 0, 1, 0, None)])


@final
class FloatTest(unittest.TestCase):
    """float: one float choice."""

    def test_a_recorded_value_decodes_to_itself(self) -> None:
        """0.5 inside [-1, 1] is 0.5."""
        self.assertEqual(decode({"gen": "float", "min": -1, "max": 1}, 0.5)[0], 0.5)

    def test_the_target_is_the_simplest_float_in_range(self) -> None:
        """[0.6, 0.7] decodes to 0.625 from no choices."""
        self.assertEqual(decode({"gen": "float", "min": 0.6, "max": 0.7})[0], 0.625)

    def test_bounds_may_name_the_infinities(self) -> None:
        """-Inf and Inf are bounds, and NaN replays when allowed."""
        spec = {"gen": "float", "min": "-Inf", "max": "Inf", "allow_nan": True}
        value = decode(spec, math.nan)[0]
        self.assertTrue(isinstance(value, float) and math.isnan(value))
        self.assertEqual(decode(spec, -math.inf)[0], -math.inf)

    def test_nan_takes_the_target_when_not_allowed(self) -> None:
        """allow_nan defaults to false."""
        self.assertEqual(decode({"gen": "float", "min": 1, "max": 2}, math.nan)[0], 1.0)

    def test_a_value_off_its_width_takes_the_target(self) -> None:
        """0.1 is no binary32 value."""
        spec = {"gen": "float", "min": 0, "max": 1, "width": 32}
        self.assertEqual(decode(spec, 0.1)[0], 0.0)
        self.assertEqual(decode(spec, 0.5)[0], 0.5)


@final
class BooleanTest(unittest.TestCase):
    """boolean: one integer choice in [0, 1], drawn by one coin."""

    def test_one_decodes_to_true_and_the_target_to_false(self) -> None:
        """[0, 1] with a target of 0."""
        self.assertIs(decode(BOOLEAN, 1)[0], True)
        self.assertIs(decode(BOOLEAN)[0], False)

    def test_generation_draws_one_coin_of_p(self) -> None:
        """A p of [1, 3] draws coin(1, 3), and no p draws coin(1, 2)."""
        for p, (num, den) in (([1, 3], (1, 3)), (None, (1, 2)), ([2, 6], (1, 3))):
            spec = {"gen": "boolean"} if p is None else {"gen": "boolean", "p": p}
            generator = build(spec)
            for seed in range(50):
                case, twin = Case(Generating(Source(seed))), Source(seed)
                self.assertEqual(generator.decode(case), twin.coin(num, den), (p, seed))


@final
class JustTest(unittest.TestCase):
    """just: the stated value, without a choice."""

    def test_the_stated_value_decodes_without_a_choice(self) -> None:
        """An empty span and no request."""
        value, case = decode({"gen": "just", "value": {"type": "string", "value": "x"}})
        self.assertEqual(value, "x")
        self.assertEqual(case.choices, [])
        self.assertEqual(case.spans, [Span("just", 0, 0, 0, None)])


@final
class SampledFromTest(unittest.TestCase):
    """sampled-from: an index that decides structure."""

    def test_the_index_selects_a_value(self) -> None:
        """Index 2 of a, b, c is c."""
        self.assertEqual(decode(LETTERS, 2)[0], "c")

    def test_the_target_is_the_first_value(self) -> None:
        """No choices, or an index past the end, give a."""
        self.assertEqual(decode(LETTERS)[0], "a")
        self.assertEqual(decode(LETTERS, 3)[0], "a")

    def test_the_index_decides_structure_with_the_first_value_at_the_edges(
        self,
    ) -> None:
        """The edge phase takes index 0."""
        _, case = decode(LETTERS, 1)
        self.assertEqual(case.requests[0].edge, 0)
        self.assertEqual(case.requests[0].bounds, IntegerBounds(0, 2))


@final
class OneOfTest(unittest.TestCase):
    """one-of: an index, then the chosen generator's choices."""

    spec: dict[str, Any] = EVERY["one-of"]

    def test_the_index_selects_the_generator_that_decodes_next(self) -> None:
        """Index 1 selects [10, 20], which decodes 15."""
        self.assertEqual(decode(self.spec, 1, 15)[0], 15)

    def test_the_target_is_the_first_generators_simplest_value(self) -> None:
        """No choices give 0."""
        self.assertEqual(decode(self.spec)[0], 0)

    def test_a_value_recorded_for_another_alternative_takes_the_target(self) -> None:
        """5 is outside [10, 20], so the second alternative gives 10."""
        self.assertEqual(decode(self.spec, 1, 5)[0], 10)

    def test_the_index_decides_structure_and_the_value_does_not(self) -> None:
        """The index has edge 0, the first alternative; the value has none."""
        _, case = decode(self.spec, 1, 15)
        self.assertEqual([r.edge for r in case.requests], [0, None])
        self.assertEqual(case.spans[0], Span("one-of", 0, 2, 0, None))


@final
class OptionalTest(unittest.TestCase):
    """optional: a presence choice, then the value when present."""

    spec: dict[str, Any] = EVERY["optional"]

    def test_absent_decodes_to_none(self) -> None:
        """Presence 0 makes no further choice."""
        value, case = decode(self.spec, 0, 4)
        self.assertIsNone(value)
        self.assertEqual(len(case.choices), 1)

    def test_present_decodes_the_value(self) -> None:
        """Presence 1, then 4."""
        self.assertEqual(decode(self.spec, 1, 4)[0], 4)

    def test_the_target_is_absent(self) -> None:
        """No choices give None."""
        self.assertIsNone(decode(self.spec)[0])

    def test_presence_decides_structure(self) -> None:
        """The edge phase makes an optional present."""
        _, case = decode(self.spec, 1, 4)
        self.assertEqual([r.edge for r in case.requests], [1, None])


@final
class ListTest(unittest.TestCase):
    """list: per element a continue flag and the element, then a stop flag."""

    def test_flags_and_elements_decode_to_the_list(self) -> None:
        """The decoding example: 1, 7, 1, 3, 0 is [7, 3]."""
        self.assertEqual(decode(DIGITS, 1, 7, 1, 3, 0)[0], [7, 3])

    def test_the_target_is_min_size_simplest_elements(self) -> None:
        """[] for a minimum of 0, [0, 0] for a minimum of 2."""
        self.assertEqual(decode(DIGITS)[0], [])
        self.assertEqual(decode({**DIGITS, "min_size": 2})[0], [0, 0])

    def test_the_flag_at_the_maximum_is_a_forced_stop(self) -> None:
        """A recorded 1 at the maximum replays as the stop the bounds allow."""
        value, case = decode(DIGITS, 1, 1, 1, 2, 1, 3, 1)
        self.assertEqual(value, [1, 2, 3])
        self.assertEqual(case.choices[-1], Choice("integer", 0))
        self.assertEqual(case.requests[-1].bounds, IntegerBounds(0, 0))

    def test_flags_decide_structure_and_elements_do_not(self) -> None:
        """The edge phase continues once, then stops; elements have no edge."""
        _, case = decode(DIGITS, 1, 7, 1, 3, 0)
        self.assertEqual([r.edge for r in case.requests], [1, None, 0, None, 0])

    def test_each_element_span_starts_at_its_flag(self) -> None:
        """Deleting an element span deletes the flag and the element."""
        _, case = decode(DIGITS, 1, 7, 1, 3, 0)
        self.assertEqual(
            case.spans,
            [
                Span("list", 0, 5, 0, None),
                Span("element", 0, 2, 1, 0),
                Span("integer", 1, 2, 2, 1),
                Span("element", 2, 4, 1, 0),
                Span("integer", 3, 4, 2, 3),
            ],
        )

    def test_duplicates_stay_unless_the_list_is_unique(self) -> None:
        """[4, 4] decodes as recorded."""
        self.assertEqual(decode(DIGITS, 1, 4, 1, 4, 0)[0], [4, 4])

    def test_a_unique_list_discards_a_duplicate_element(self) -> None:
        """The second 4 is discarded, and the next flag continues the list."""
        self.assertEqual(decode(UNIQUE, 1, 4, 1, 4, 1, 5, 0)[0], [4, 5])

    def test_a_unique_list_below_its_minimum_rejects_the_case(self) -> None:
        """The targets repeat, so a minimum of 2 cannot be met."""
        with self.assertRaises(Rejected):
            decode({**UNIQUE, "min_size": 2})

    def test_generation_draws_each_flag_and_then_each_element(self) -> None:
        """Each flag as draw.flag draws it, then each element: reused or drawn.

        An element after the first takes coin(1, REUSE_ODDS), and when it
        comes up, the earlier element at below(their count).
        """
        generator = build(DIGITS)
        average = draw.average_length(0, 3)
        for seed in range(SEEDS):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            want: list[int] = []
            while draw.flag(twin, len(want), 0, 3, average):
                if want and twin.coin(1, draw.REUSE_ODDS):
                    want.append(want[twin.below(len(want))])
                else:
                    want.append(draw.integer(twin, IntegerBounds(0, 9)))
            self.assertEqual(generator.decode(case), want, seed)


@final
class DictTest(unittest.TestCase):
    """dict: entries of a key and a value, with distinct keys."""

    def test_an_entry_with_a_repeated_key_is_discarded(self) -> None:
        """Key 3 twice keeps the first entry."""
        value = decode(TABLE, 1, 3, 1, 1, 3, 0, 0)[0]
        self.assertEqual(value, Pairs(((3, True),)))

    def test_each_entry_span_starts_at_its_flag(self) -> None:
        """Flag, key and value in one span labelled entry."""
        _, case = decode(TABLE, 1, 3, 1, 0)
        self.assertEqual(
            case.spans[:2], [Span("dict", 0, 4, 0, None), Span("entry", 0, 3, 1, 0)]
        )

    def test_the_target_is_empty(self) -> None:
        """A minimum of 0 gives no entries."""
        self.assertEqual(decode(TABLE)[0], Pairs(()))

    def test_a_minimum_of_two_rejects_the_targets(self) -> None:
        """Both target keys are 0."""
        with self.assertRaises(Rejected):
            decode({**TABLE, "min_size": 2})


@final
class StringTest(unittest.TestCase):
    """string and bytes: one sequence."""

    def test_the_default_alphabet_spells_the_indices(self) -> None:
        """Index 10 is a and index 0 is 0."""
        self.assertEqual(decode({"gen": "string"}, (10, 0))[0], "a0")

    def test_a_stated_alphabet_is_ordered_as_stated(self) -> None:
        """The first character of xyz is the simplest."""
        spec = EVERY["alphabet"]
        self.assertEqual(decode(spec, (2, 0, 1))[0], "zxy")
        self.assertEqual(decode({**spec, "min_size": 2})[0], "xx")

    def test_the_target_repeats_the_first_character_min_size_times(self) -> None:
        """The default alphabet starts with 0."""
        self.assertEqual(decode({"gen": "string", "min_size": 2})[0], "00")

    def test_an_index_past_the_alphabet_replays_as_its_first_character(self) -> None:
        """5 is outside xyz."""
        self.assertEqual(decode(EVERY["alphabet"], (5,))[0], "x")

    def test_bytes_are_a_sequence_of_256_values(self) -> None:
        """Each element is a byte, and 256 replays as 0."""
        self.assertEqual(decode({"gen": "bytes"}, (104, 105))[0], b"hi")
        self.assertEqual(decode({"gen": "bytes"}, (256,))[0], b"\x00")
        self.assertEqual(decode({"gen": "bytes"})[0], b"")


@final
class PermutationTest(unittest.TestCase):
    """permutation: one swap per position."""

    spec: dict[str, Any] = EVERY["permutation"]

    def test_each_position_swaps_with_the_chosen_index(self) -> None:
        """2 swaps a with c, then 2 swaps a with b."""
        self.assertEqual(decode(self.spec, 2, 2)[0], ["c", "a", "b"])

    def test_the_targets_keep_the_stated_order(self) -> None:
        """Position i targets i."""
        value, case = decode(self.spec)
        self.assertEqual(value, ["a", "b", "c"])
        bounds = [r.bounds for r in case.requests]
        self.assertEqual(bounds, [IntegerBounds(0, 2), IntegerBounds(1, 2)])

    def test_no_values_make_no_choice(self) -> None:
        """An empty permutation is empty."""
        value, case = decode({"gen": "permutation", "values": []})
        self.assertEqual((value, case.choices), ([], []))


@final
class RecursiveTest(unittest.TestCase):
    """recursive: per position, the base or the extension."""

    def test_the_target_is_the_bases_simplest_value(self) -> None:
        """Position 0 takes the base."""
        self.assertEqual(decode(TREE)[0], 0)

    def test_self_positions_decode_recursively(self) -> None:
        """An extension of two leaves, and one nested a level deeper."""
        self.assertEqual(decode(TREE, 1, 1, 0, 5, 1, 0, 7, 0)[0], [5, 7])
        self.assertEqual(decode(TREE, 1, 1, 1, 1, 0, 3, 0, 0)[0], [[3]])

    def test_each_position_is_a_recursive_span_that_decides_structure(self) -> None:
        """The outer position and the inner one share a label."""
        _, case = decode(TREE, 1, 1, 0, 5, 0)
        labels = [span.label for span in case.spans]
        self.assertEqual(
            labels, ["recursive", "list", "element", "recursive", "integer"]
        )
        self.assertEqual(case.requests[0].edge, 0)

    def test_positions_after_max_leaves_take_the_base(self) -> None:
        """With one leaf allowed, the second position is forced to the base."""
        spec = {**TREE, "max_leaves": 1}
        value, case = decode(spec, 1, 1, 0, 5, 1, 1, 7, 0)
        self.assertEqual(value, [5, 7])
        self.assertEqual(case.requests[5].bounds, IntegerBounds(0, 0))

    def test_each_value_counts_its_leaves_from_zero(self) -> None:
        """A second case is not limited by the leaves of the first."""
        generator = build({**TREE, "max_leaves": 1})
        values = (1, 1, 0, 5, 0)
        for _ in range(2):
            case = Case(Replaying([_choice(v) for v in values]))
            self.assertEqual(generator.decode(case), [5])

    def test_the_default_limit_is_100_leaves(self) -> None:
        """Hypothesis's default."""
        self.assertEqual(DEFAULT_MAX_LEAVES, 100)


@final
class FilterTest(unittest.TestCase):
    """filter: up to three attempts, each in a span of its own."""

    def test_a_kept_first_attempt_decodes_in_one_filter_span(self) -> None:
        """4 is even, so the first attempt is the value."""
        value, case = decode(KEEP_EVEN, 4)
        self.assertEqual(value, 4)
        self.assertEqual(
            case.spans, [Span("filter", 0, 1, 0, None), Span("integer", 0, 1, 1, 0)]
        )

    def test_a_rejected_attempt_is_removed_from_the_record(self) -> None:
        """3 is rejected and 4 is kept, so the record is the one choice 4."""
        case = Case(_Feed(3, 4))
        self.assertEqual(build(KEEP_EVEN).decode(case), 4)
        self.assertEqual(case.choices, [Choice("integer", 4)])
        self.assertEqual(
            case.spans, [Span("filter", 0, 1, 0, None), Span("integer", 0, 1, 1, 0)]
        )

    def test_three_rejected_attempts_reject_the_case(self) -> None:
        """1, 3 and 5 are odd, and the 6 after them is never requested."""
        case = Case(_Feed(1, 3, 5, 6))
        with self.assertRaises(Rejected):
            build(KEEP_EVEN).decode(case)
        self.assertEqual(case.choices, [Choice("integer", 5)])

    def test_a_replayed_value_the_predicate_rejects_rejects_the_case(self) -> None:
        """Each attempt reads the recorded 3 again."""
        with self.assertRaises(Rejected):
            decode(KEEP_EVEN, 3)


@final
class MapTest(unittest.TestCase):
    """map: a subject kind's function of the source's value."""

    def test_the_value_is_the_function_of_the_sources_value(self) -> None:
        """The source decodes [3, 1], and sorts returns [1, 3]."""
        self.assertEqual(decode(SORTED, 1, 3, 1, 1, 0)[0], [1, 3])

    def test_it_makes_the_sources_choices_and_opens_no_span(self) -> None:
        """The spans are the integer's alone, as an integer's draw has them."""
        spec = {"gen": "map", "of": DIGIT, "subject": "is-non-negative"}
        value, case = decode(spec, 4)
        self.assertIs(value, True)
        self.assertEqual(case.choices, [Choice("integer", 4)])
        self.assertEqual(case.spans, [Span("integer", 0, 1, 0, None)])


@final
class GenerationTest(unittest.TestCase):
    """What every generator does with a random source."""

    def test_a_generated_case_replays_to_the_same_value(self) -> None:
        """Replaying the recorded choices reproduces value and choices.

        A generated case that rejects replays to a rejection.
        """
        for name, spec in EVERY.items():
            generator = build(spec)
            for seed in range(SEEDS):
                generated = Case(Generating(Source(seed)))
                value = _decoded(generator, generated)
                replayed = Case(Replaying(generated.choices))
                again = _decoded(generator, replayed)
                self.assertEqual(again, value, (name, seed))
                self.assertEqual(replayed.choices, generated.choices, (name, seed))

    def test_unique_values_stay_distinct(self) -> None:
        """Unique list elements and dict keys never repeat."""
        unique, table = build(UNIQUE), build(TABLE)
        for seed in range(SEEDS):
            elements = unique.decode(Case(Generating(Source(seed))))
            assert isinstance(elements, list)
            self.assertEqual(len(set(elements)), len(elements), seed)
            entries = table.decode(Case(Generating(Source(seed))))
            assert isinstance(entries, Pairs)
            keys = [key for key, _ in entries.items]
            self.assertEqual(len(set(keys)), len(keys), seed)


@final
class BuildTest(unittest.TestCase):
    """build(): a spec it cannot turn into a generator raises SpecError."""

    def test_the_vocabulary_is_the_seventeen_stated_ids(self) -> None:
        """IDS names the seventeen generators, and EVERY has a spec of each."""
        self.assertEqual(IDS, PINNED_IDS)
        self.assertEqual({spec["gen"] for spec in EVERY.values()}, IDS)

    def test_a_spec_outside_the_vocabulary_raises(self) -> None:
        """No mapping, no id, or an id that names no generator."""
        for spec in ([DIGIT], {"min": 0}, {"gen": "integers"}, {"gen": 1}):
            with self.assertRaises(SpecError):
                build(spec)

    def test_a_missing_parameter_raises_and_names_it(self) -> None:
        """An integer without min raises, and the error names min."""
        with self.assertRaisesRegex(SpecError, "'min'"):
            build({"gen": "integer", "max": 9})

    def test_a_malformed_parameter_raises(self) -> None:
        """Every parameter the vocabulary checks."""
        malformed: list[dict[str, Any]] = [
            {**DIGIT, "min": True},
            {**DIGIT, "min": "0"},
            {**DIGIT, "min": 10},
            {"gen": "float", "min": "Infinity", "max": 1},
            {"gen": "float", "min": 0, "max": 1, "width": 16},
            {"gen": "float", "min": 0, "max": 1, "allow_nan": "yes"},
            {"gen": "boolean", "p": [1]},
            {"gen": "boolean", "p": [2, 1]},
            {"gen": "boolean", "p": [-1, 2]},
            {"gen": "boolean", "p": [1, 0]},
            {"gen": "boolean", "p": [1, 2**64 + 1]},
            {"gen": "boolean", "p": [True, 2]},
            {"gen": "boolean", "p": "1/2"},
            {"gen": "sampled-from", "values": []},
            {"gen": "sampled-from", "values": {"type": "int", "value": 1}},
            {"gen": "one-of", "of": []},
            {"gen": "one-of", "of": DIGIT},
            {"gen": "string", "alphabet": ""},
            {"gen": "string", "alphabet": "xx"},
            {"gen": "string", "alphabet": "\ud800"},
            {"gen": "string", "alphabet": 5},
            {**DIGITS, "min_size": -1},
            {**DIGITS, "min_size": 4},
            {**DIGITS, "max_size": "3"},
            {**UNIQUE, "unique": "yes"},
            {"gen": "just", "value": {"type": "int", "value": "3"}},
            {**TREE, "max_leaves": 0},
            {"gen": "string-matching"},
            {"gen": "string-matching", "pattern": 5},
            {"gen": "string-matching", "pattern": "a**"},
            {"gen": "filter", "of": DIGIT},
            {"gen": "filter", "of": DIGIT, "keep": {"kind": "odd"}},
            {"gen": "map", "of": DIGIT},
            {"gen": "map", "of": DIGIT, "subject": 1},
            {"gen": "map", "of": DIGIT, "subject": "ascending"},
            {"gen": "map", "subject": "identity"},
        ]
        for spec in malformed:
            with self.assertRaises(SpecError, msg=str(spec)):
                build(spec)

    def test_a_self_outside_an_extension_raises(self) -> None:
        """At the top, and inside a recursive generator's base."""
        with self.assertRaises(SpecError):
            build({"gen": "self"})
        with self.assertRaises(SpecError):
            build({**TREE, "base": {"gen": "list", "of": {"gen": "self"}}})

    def test_a_nested_self_refers_to_the_innermost_recursive_generator(self) -> None:
        """The inner tree's positions do not count the outer tree's leaves."""
        inner = {**TREE, "max_leaves": 1}
        outer = {"gen": "recursive", "base": inner, "extend": TREE["extend"]}
        value = decode(outer, 0, 1, 1, 0, 5, 1, 1, 7, 0)[0]
        self.assertEqual(value, [5, 7])
