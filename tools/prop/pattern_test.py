"""The portable pattern subset: what it accepts, refuses and decodes."""

from __future__ import annotations

import re
import unittest
from typing import final

from . import alphabet
from .case import Case, Generating, Replaying, Span
from .choice import Choice, IntegerBounds
from .generator import build
from .pattern import DOT, Class, PatternError, parse
from .source import Source

#: Seeds per pattern for the match check.
SEEDS = 200

#: The definition's values, pinned here rather than read from the code
#: under test: the largest count, the characters . leaves out, and the
#: members of \s in alphabet order.
COUNT_LIMIT = 1000
TERMINATORS = "\n\r" + chr(0x85) + chr(0x2028) + chr(0x2029)
WHITESPACE = [" ", "\t", "\n", "\f", "\r"]

#: Patterns that cover every construct of the subset.
ACCEPTED = [
    "",
    "abc",
    "^abc$",
    "^$",
    "a|b|c",
    "(foo|bar)baz",
    "(?:ab)+",
    "[a-z]+@[a-z]+\\.com",
    "\\d{3}-\\d{4}",
    "\\w+\\s\\w*",
    ".",
    ".{2,5}",
    "[^a-z]",
    "[-a]",
    "[a-]",
    "[a-z-]",
    "[\\]\\[\\\\\\-]",
    "[\\d_]x?",
    "a{0}",
    "a{2,}",
    "(a|)+",
    "x*y+z?",
    "[à-ÿ]",
    "[.$^*+?(){}|]",
    "\\.\\*\\+\\?\\(\\)\\[\\]\\{\\}\\|\\^\\$\\\\",
    f"a{{{COUNT_LIMIT}}}",
]

#: Patterns outside the subset, each with what puts it outside.
REFUSED = {
    "a quantifier after a quantifier": "a**",
    "a lazy quantifier": "a+?",
    "two counts": "a{2}{3}",
    "a quantifier with nothing to repeat": "*a",
    "a count that runs backwards": "a{2,1}",
    "a count above the limit": f"a{{{COUNT_LIMIT + 1}}}",
    "a count without a minimum": "a{,3}",
    "a count without digits": "a{x}",
    "an unclosed count": "a{1",
    "a lookahead": "(?=a)",
    "a named group": "(?P<n>a)",
    "a word boundary": "\\b",
    "a back reference": "\\1",
    "an escaped control character": "\\n",
    "a negated shorthand": "\\D",
    "an end anchor inside": "a$b",
    "a start anchor inside": "a^",
    "a start anchor in a group": "(^a)",
    "an end anchor in a group": "(a$)",
    "an intersection": "[a&&b]",
    "a nested class": "[[a]]",
    "a range to a shorthand": "[a-\\d]",
    "a range from a shorthand": "[\\d-z]",
    "a range that runs backwards": "[z-ab]",
    "an unclosed group that ends with an anchor": "(a$",
    "a non-ASCII digit in a count": "a{\N{ARABIC-INDIC DIGIT ONE}}",
    "an empty class": "[]",
    "an empty negated class": "[^]",
    "a hyphen inside a class": "[a-z-0]",
    "a range that starts with a reserved pair": "[--a]",
    "an escape inside a class": "[\\n]",
    "an unopened group": ")",
    "an unclosed group": "(a",
    "an unclosed class": "[a",
    "a bare closing bracket": "]",
    "a bare closing brace": "}",
    "a bare opening brace": "{",
    "a trailing backslash": "a\\",
    "a surrogate": "\ud800",
}


def decode(text: str, *values: int) -> tuple[str, Case]:
    """Decode a pattern from recorded integers, and return the string and the case."""
    case = Case(Replaying([Choice("integer", v) for v in values]))
    value = build({"gen": "string-matching", "pattern": text}).decode(case)
    assert isinstance(value, str)
    return value, case


@final
class ParseTest(unittest.TestCase):
    """parse(): the subset, and nothing outside it."""

    def test_every_construct_of_the_subset_parses(self) -> None:
        """One pattern per construct."""
        for text in ACCEPTED:
            parse(text)

    def test_a_pattern_outside_the_subset_raises(self) -> None:
        """Each construct the engines read differently, or not at all."""
        for name, text in REFUSED.items():
            with self.assertRaises(PatternError, msg=name):
                parse(text)


@final
class MatchTest(unittest.TestCase):
    """Every decoded string matches its pattern in full."""

    def test_generated_strings_match_in_full(self) -> None:
        """Python's re module agrees for every seed and every pattern."""
        for text in ACCEPTED:
            generator = build({"gen": "string-matching", "pattern": text})
            compiled = re.compile(text)
            for seed in range(SEEDS):
                value = generator.decode(Case(Generating(Source(seed))))
                assert isinstance(value, str)
                self.assertIsNotNone(compiled.fullmatch(value), (text, seed, value))


@final
class TargetTest(unittest.TestCase):
    """The targets: first branches, fewest repetitions, simplest characters."""

    def test_the_targets_decode_to_the_simplest_match(self) -> None:
        """One pattern per construct, decoded from no choices."""
        cases = {
            "[a-z]+@[a-z]+\\.com": "a@a.com",
            "(foo|bar)baz": "foobaz",
            "x{3}": "xxx",
            "\\d\\w\\s": "00 ",
            ".": "0",
            "[^0-9]": "a",
            "a?": "",
            "^abc$": "abc",
            "[A0a]": "0",
            "[\\d_]": "0",
        }
        for text, want in cases.items():
            self.assertEqual(decode(text)[0], want, text)


@final
class DecodeTest(unittest.TestCase):
    """What each construct decodes from stated choices."""

    def test_an_alternation_index_selects_a_branch(self) -> None:
        """Index 1 is the second branch."""
        self.assertEqual(decode("(foo|bar)", 1)[0], "bar")

    def test_a_class_index_follows_the_default_alphabet(self) -> None:
        """Digits, then lowercase, then uppercase, whatever the stated order."""
        self.assertEqual([decode("[A0a]", i)[0] for i in range(3)], ["0", "a", "A"])

    def test_a_negated_class_skips_its_members(self) -> None:
        """Index 10 of [^a] is b, because a is index 10 of the alphabet."""
        self.assertEqual(decode("[^a]", 10)[0], "b")

    def test_a_repetition_decodes_as_a_collection(self) -> None:
        """Two continue flags and a stop flag repeat a twice."""
        self.assertEqual(decode("a*", 1, 1, 0)[0], "aa")

    def test_a_fixed_count_forces_its_flags(self) -> None:
        """{2} repeats twice whatever the flags record."""
        self.assertEqual(decode("(ab|c){2}", 0, 1, 0, 0, 1)[0], "cab")

    def test_spans_and_edges_mark_each_construct(self) -> None:
        """The alternation index and the flags have edges; the class has none."""
        _, case = decode("(a|b)[cd]*", 1, 1, 1, 0)
        self.assertEqual(
            case.spans,
            [
                Span("string-matching", 0, 4, 0, None),
                Span("alternation", 0, 1, 1, 0),
                Span("repeat", 1, 4, 1, 0),
                Span("element", 1, 3, 2, 2),
            ],
        )
        self.assertEqual([r.edge for r in case.requests], [0, 1, None, 0])


@final
class ClassTest(unittest.TestCase):
    """The members of . and of the shorthands."""

    def test_dot_is_every_character_but_the_line_terminators(self) -> None:
        """Five characters fewer than the alphabet."""
        self.assertEqual(DOT.size, alphabet.SIZE - len(TERMINATORS))
        for char in TERMINATORS:
            position = alphabet.index(char)
            self.assertFalse(any(a <= position <= b for a, b in DOT.intervals), char)

    def test_the_digit_and_word_shorthands_hold_the_ascii_members(self) -> None:
        """Ten digits; 26 lowercase, 26 uppercase, ten digits and the underscore."""
        sizes = {"\\d": 10, "\\w": 63}
        for text, size in sizes.items():
            node = parse(text)
            assert isinstance(node, Class)
            self.assertEqual(node.size, size, text)

    def test_the_space_shorthand_holds_five_members_from_space(self) -> None:
        """Space, tab, newline, form feed and carriage return, in alphabet order."""
        node = parse("\\s")
        assert isinstance(node, Class)
        self.assertEqual(node.size, len(WHITESPACE))
        self.assertEqual([decode("\\s", i)[0] for i in range(5)], WHITESPACE)

    def test_a_class_index_is_a_value_with_its_size_as_bounds(self) -> None:
        """[a-c] has three members."""
        _, case = decode("[a-c]", 2)
        self.assertEqual(case.requests[0].bounds, IntegerBounds(0, 2))
        self.assertEqual(decode("[a-c]", 2)[0], "c")
