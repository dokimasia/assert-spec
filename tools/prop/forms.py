"""Property forms as data: an assertion run on every case of a run.

A form vector names a form, the kinds of the subjects that its assertion
takes, the values that the assertion takes beside them, the shape of the
arguments that the form generates, and a seed. The definition's forms
rule states the assertion of each form and the labels of what it
generates.

The reference runs a form as prop-for-all runs a body. Each case draws
the generated arguments from the shape's generator, in the rule's order
and under its labels, and decides the assertion on them. A failing case
fails with the assertion's id as its identity, because every case of a
form fails at the same call of the assertion.

Each subject behaves as its summary in the definition states, with the
generated arguments in place of the input or the operands that the
summary states. A run keeps its subjects across its cases, as a caller's
closure keeps them. Equal means equal under value.canonical(), as the
predicates state it, which agrees with equal for every value but a float.

The record of a failing case states the detail fields that a typed
literal can state and that no earlier case decides. It leaves out a
failure, a raised value and a type, which no literal states, and an
observation of a subject's state, which depends on the calls before it.
"""

from __future__ import annotations

import functools
import json
import re
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from . import literal
from .case import Case, Generator
from .runner import Outcome, Settings, run
from .value import canonical

#: The table whose forms rule states each form's assertion and labels.
TABLE: Final = Path(__file__).resolve().parents[2] / "spec" / "assertions.json"

#: The calls of a subject that deterministic compares.
REPETITIONS: Final = 32

#: The patterns the reference matches: letters and digits after an
#: optional ^, which every engine reads as the portable subset does.
PLAIN_PATTERN: Final = re.compile(r"\^?[A-Za-z0-9]*")

#: The detail a failing case's record states, by field.
Detail = dict[str, object]

#: What decides one case: it takes the generated arguments, and returns
#: None for a pass and the stated detail for a failure.
Judge = Callable[[Sequence[Any]], Detail | None]

#: What builds a judge from a vector's subjects and its decoded values.
Builder = Callable[[object, Sequence[object]], Judge]


class FormError(ValueError):
    """A form vector that names no form a case can state, or misstates its arguments."""


#: The functions of the generated input, by subject kind.
FUNCTIONS: Final[dict[str, Callable[[Any], object]]] = {
    "identity": lambda x: x,
    "is-non-negative": lambda x: x >= 0,
    "returns-null": lambda x: None,
    "drops-the-first": lambda x: x[1:],
    "prepends-zero": lambda x: [0, *x],
    "sorts": sorted,
    "wraps-in-a-and-b": lambda x: f"a{x}b",
}

#: The predicates over two adjacent items, by subject kind.
PREDICATES: Final[dict[str, Callable[[Any, Any], bool]]] = {
    "ascending": lambda first, second: first <= second,
}

#: Whether each subject kind returns its own failure for an input.
FAILS: Final[dict[str, Callable[[Any], bool]]] = {
    "returns-ok": lambda x: False,
    "fails-otherwise": lambda x: True,
    "fails-on-negative": lambda x: x < 0,
}

#: Whether each subject kind raises for an input.
RAISES: Final[dict[str, Callable[[Any], bool]]] = {
    "returns-ok": lambda x: False,
    "raises": lambda x: True,
    "raises-on-negative": lambda x: x < 0,
}

#: Whether each subject kind that takes a handle returns the handle's
#: reason for a cancelled or an expired one, and whether an absent one
#: crashes it.
HANDLES: Final[dict[str, tuple[bool, bool]]] = {
    "returns-ok": (False, False),
    "reads-handle": (True, False),
    "ignores-handle": (False, False),
    "dereferences-handle": (True, True),
}

#: The subject kinds whose calls change an observed integer.
OBSERVED: Final = frozenset({"accumulates", "leaves-state-alone", "sets-value"})

#: The subject kinds that deterministic calls.
COMPUTES: Final = frozenset({"returns-ok", "counts-calls"})

#: The combinations of two integers, by subject kind.
COMBINERS: Final[dict[str, Callable[[Any, Any], int]]] = {
    "adds": lambda a, b: a + b,
    "subtracts": lambda a, b: a - b,
}

#: The conversions of an integer to text and back, by subject kind.
CODECS: Final[dict[str, tuple[Callable[[Any], str], Callable[[str], int]]]] = {
    "renders-decimal": (str, int),
    "drops-the-sign": (lambda x: str(abs(x)), int),
}


@dataclass
class Observed:
    """A subject whose calls change an observed integer, which starts at 0.

    A call of accumulates adds one, a call of sets-value sets the integer
    to the call's input, and a call of leaves-state-alone changes nothing.
    """

    kind: str
    value: int = 0

    def call(self, given: int) -> None:
        """Call the subject once with an input."""
        if self.kind == "accumulates":
            self.value += 1
        elif self.kind == "sets-value":
            self.value = given


@dataclass
class Computing:
    """A subject that returns its input, or for counts-calls its count of calls."""

    kind: str
    calls: int = 0

    def compute(self, given: object) -> object:
        """Call the subject once with an input, and return its result."""
        self.calls += 1
        return self.calls if self.kind == "counts-calls" else given


def _takes(
    subjects: object,
    values: Sequence[object],
    tables: Sequence[Collection[str]],
    count: int = 0,
) -> list[str]:
    """Return a vector's subject kinds, after checking its subjects and its values.

    The vector states one kind from each table, in order, and count values.

    Raises:
        FormError: the vector states another number of subjects or values,
            or a kind that its table does not have.
    """
    if not isinstance(subjects, list) or len(subjects) != len(tables):
        raise FormError(
            f"prop: the form takes {len(tables)} subjects, not {subjects!r}"
        )
    if len(values) != count:
        raise FormError(
            f"prop: the vector states {len(values)} values, and the form takes {count}"
        )
    for kind, table in zip(subjects, tables, strict=True):
        if not isinstance(kind, str) or kind not in table:
            raise FormError(f"prop: the subject {kind!r} is none of {sorted(table)}")
    return [str(kind) for kind in subjects]


def _same(first: object, second: object) -> bool:
    """Report whether two values are equal under value.canonical()."""
    return canonical(first) == canonical(second)


def _found(haystack: Any, needle: object) -> bool:
    """Report whether text contains a substring, or a sequence an element."""
    if isinstance(haystack, str):
        return isinstance(needle, str) and needle in haystack
    return any(_same(item, needle) for item in haystack)


def _equal(got: Any, want: Any) -> Detail | None:
    """Decide equal: got equals want."""
    return None if _same(got, want) else {"want": want, "got": got}


def _not_equal(got: Any, want: Any) -> Detail | None:
    """Decide not-equal: got does not equal want."""
    return {"got": got} if _same(got, want) else None


def _true(cond: Any) -> Detail | None:
    """Decide true: the condition holds."""
    return None if cond is True else {}


def _false(cond: Any) -> Detail | None:
    """Decide false: the condition does not hold."""
    return None if cond is False else {}


def _nil(got: Any) -> Detail | None:
    """Decide nil: the value is absent."""
    return None if got is None else {"got": got}


def _not_nil(got: Any) -> Detail | None:
    """Decide not-nil: the value is present."""
    return {} if got is None else None


def _length(got: Any, want: Any) -> Detail | None:
    """Decide length: the container has want items."""
    return None if len(got) == want else {"want": want, "got": len(got)}


def _empty(got: Any) -> Detail | None:
    """Decide empty: the container has no item."""
    return None if len(got) == 0 else {"length": len(got)}


def _not_empty(got: Any) -> Detail | None:
    """Decide not-empty: the container has an item."""
    return {} if len(got) == 0 else None


def _contains(got: Any, needle: Any) -> Detail | None:
    """Decide contains: the needle is in the haystack."""
    return None if _found(got, needle) else {"haystack": got, "needle": needle}


def _not_contains(got: Any, needle: Any) -> Detail | None:
    """Decide not-contains: the needle is not in the haystack."""
    return {"haystack": got, "needle": needle} if _found(got, needle) else None


def _contains_in_order(got: Any, needles: Any) -> Detail | None:
    """Decide contains-in-order: each needle is in the text after the previous match."""
    at = 0
    for index, needle in enumerate(needles):
        found = got.find(needle, at)
        if found < 0:
            return {"haystack": got, "needle": needle, "index": index}
        at = found + len(needle)
    return None


def _permutation(got: Any, want: Any) -> Detail | None:
    """Decide permutation: got has want's elements, each as often."""
    same = Counter(map(canonical, got)) == Counter(map(canonical, want))
    return None if same else {"want": want, "got": got}


def _has_prefix(got: Any, prefix: Any) -> Detail | None:
    """Decide has-prefix: the text starts with the prefix."""
    return None if got.startswith(prefix) else {"got": got, "prefix": prefix}


def _has_suffix(got: Any, suffix: Any) -> Detail | None:
    """Decide has-suffix: the text ends with the suffix."""
    return None if got.endswith(suffix) else {"got": got, "suffix": suffix}


def _matches(got: Any, pattern: Any) -> Detail | None:
    """Decide matches: the pattern matches somewhere in the text.

    Raises:
        FormError: the pattern is not one of PLAIN_PATTERN's.
    """
    if not PLAIN_PATTERN.fullmatch(pattern):
        raise FormError(f"prop: the reference matches no pattern such as {pattern!r}")
    return None if re.search(pattern, got) else {"got": got, "pattern": pattern}


def _close_to(got: Any, want: Any, tolerance: Any) -> Detail | None:
    """Decide close-to: the number is within the tolerance of want."""
    if abs(got - want) <= tolerance:
        return None
    return {"got": got, "want": want, "tolerance": tolerance}


def _in_range(got: Any, low: Any, high: Any) -> Detail | None:
    """Decide in-range: the number is in the closed interval from low to high."""
    return None if low <= got <= high else {"got": got, "low": low, "high": high}


def _over(
    check: Callable[..., Detail | None], functions: int, values: int = 0
) -> Builder:
    """Return the builder of a judge that decides check on functions of the input.

    The subjects are the functions. check takes what each returns for the
    input, then the vector's values.
    """

    def build(subjects: object, given: Sequence[object]) -> Judge:
        kinds = _takes(subjects, given, [FUNCTIONS] * functions, values)
        applied = [FUNCTIONS[kind] for kind in kinds]

        def judge(drawn: Sequence[Any]) -> Detail | None:
            return check(*(function(drawn[0]) for function in applied), *given)

        return judge

    return build


def _pairwise(subjects: object, given: Sequence[object]) -> Judge:
    """Build pairwise's judge over a function of the input and a predicate."""
    kinds = _takes(subjects, given, [FUNCTIONS, PREDICATES])
    got, holds = FUNCTIONS[kinds[0]], PREDICATES[kinds[1]]

    def judge(drawn: Sequence[Any]) -> Detail | None:
        items: Any = got(drawn[0])
        for index, (first, second) in enumerate(pairwise(items)):
            if not holds(first, second):
                return {"index": index, "first": first, "second": second}
        return None

    return judge


def _failing(*, on_failure: bool, states_got: bool = False) -> Builder:
    """Return the builder of an error assertion's judge.

    The assertion fails when the subject returns its own failure and
    on_failure is set, or returns success and on_failure is not. Every
    failure a subject returns is its own, which err-is and err-as take as
    their sentinel and their type. A record states got only where
    states_got is set, as the null of the success the subject returned.
    """

    def build(subjects: object, given: Sequence[object]) -> Judge:
        fails = FAILS[_takes(subjects, given, [FAILS])[0]]

        def judge(drawn: Sequence[Any]) -> Detail | None:
            if fails(drawn[0]) is not on_failure:
                return None
            return {"got": None} if states_got else {}

        return judge

    return build


def _raising(*, on_raise: bool) -> Builder:
    """Return the builder of throws' or not-throws' judge, whose record states no field.

    The assertion fails when the subject raises and on_raise is set, or
    returns and on_raise is not.
    """

    def build(subjects: object, given: Sequence[object]) -> Judge:
        raises = RAISES[_takes(subjects, given, [RAISES])[0]]
        return lambda drawn: {} if raises(drawn[0]) is on_raise else None

    return build


def _honours(subjects: object, given: Sequence[object]) -> Judge:
    """Build the judge of honours-cancellation or honours-deadline.

    The assertion hands the subject a cancelled or an expired handle, and
    fails when the subject returns success, which got states as null.
    """
    honours, _ = HANDLES[_takes(subjects, given, [HANDLES])[0]]
    return lambda drawn: None if honours else {"got": None}


def _safe_without_handle(subjects: object, given: Sequence[object]) -> Judge:
    """Build nil-context-safe's judge.

    It fails when an absent handle crashes the subject.
    """
    _, crashes = HANDLES[_takes(subjects, given, [HANDLES])[0]]
    return lambda drawn: {} if crashes else None


def _observing(decide: Callable[[Observed, int], Detail | None]) -> Builder:
    """Return the builder of a judge over one subject with an observed integer."""

    def build(subjects: object, given: Sequence[object]) -> Judge:
        subject = Observed(_takes(subjects, given, [OBSERVED])[0])
        return lambda drawn: decide(subject, drawn[0])

    return build


def _pure(subject: Observed, given: int) -> Detail | None:
    """Decide pure: a call leaves the observed integer as it was."""
    before = subject.value
    subject.call(given)
    return {} if subject.value != before else None


def _not_pure(subject: Observed, given: int) -> Detail | None:
    """Decide not-pure: a call changes the observed integer."""
    before = subject.value
    subject.call(given)
    return {} if subject.value == before else None


def _idempotent(subject: Observed, given: int) -> Detail | None:
    """Decide idempotent: a second call leaves what the first call left."""
    subject.call(given)
    once = subject.value
    subject.call(given)
    return {} if subject.value != once else None


def _accumulates(subject: Observed, given: int) -> Detail | None:
    """Decide accumulates: two calls change the integer by one amount, which is not 0.

    The record states both changes. A subject whose change does not depend
    on its state makes the same changes in every case.
    """
    before = subject.value
    subject.call(given)
    middle = subject.value
    subject.call(given)
    first, second = middle - before, subject.value - middle
    if first != 0 and first == second:
        return None
    return {"first": first, "second": second}


def _deterministic(subjects: object, given: Sequence[object]) -> Judge:
    """Build deterministic's judge, which fails when REPETITIONS calls disagree."""
    subject = Computing(_takes(subjects, given, [COMPUTES])[0])

    def judge(drawn: Sequence[Any]) -> Detail | None:
        results = [subject.compute(drawn[0]) for _ in range(REPETITIONS)]
        return None if all(_same(result, results[0]) for result in results) else {}

    return judge


def _commutative(subjects: object, given: Sequence[object]) -> Judge:
    """Build commutative's judge over the generated a and b."""
    combine = COMBINERS[_takes(subjects, given, [COMBINERS])[0]]

    def judge(drawn: Sequence[Any]) -> Detail | None:
        a, b = drawn
        first, second = combine(a, b), combine(b, a)
        return None if first == second else {"first": first, "second": second}

    return judge


def _associative(subjects: object, given: Sequence[object]) -> Judge:
    """Build associative's judge over the generated a, b and c."""
    combine = COMBINERS[_takes(subjects, given, [COMBINERS])[0]]

    def judge(drawn: Sequence[Any]) -> Detail | None:
        a, b, c = drawn
        first, second = combine(combine(a, b), c), combine(a, combine(b, c))
        return None if first == second else {"first": first, "second": second}

    return judge


def _round_trip(subjects: object, given: Sequence[object]) -> Judge:
    """Build round-trip's judge.

    It fails unless the inverse of the forward conversion returns the input.
    """
    forward, inverse = CODECS[_takes(subjects, given, [CODECS])[0]]

    def judge(drawn: Sequence[Any]) -> Detail | None:
        back = inverse(forward(drawn[0]))
        return None if back == drawn[0] else {"want": drawn[0], "got": back}

    return judge


#: The builder of each assertion's judge. max-allocs and
#: max-allocs-with-setup have none, because no case can state an
#: allocation count.
ROOTS: Final[dict[str, Builder]] = {
    "equal": _over(_equal, 2),
    "not-equal": _over(_not_equal, 2),
    "true": _over(_true, 1),
    "false": _over(_false, 1),
    "nil": _over(_nil, 1),
    "not-nil": _over(_not_nil, 1),
    "length": _over(_length, 1, 1),
    "empty": _over(_empty, 1),
    "not-empty": _over(_not_empty, 1),
    "contains": _over(_contains, 1, 1),
    "not-contains": _over(_not_contains, 1, 1),
    "contains-in-order": _over(_contains_in_order, 1, 1),
    "permutation": _over(_permutation, 2),
    "has-prefix": _over(_has_prefix, 1, 1),
    "has-suffix": _over(_has_suffix, 1, 1),
    "matches": _over(_matches, 1, 1),
    "close-to": _over(_close_to, 1, 2),
    "in-range": _over(_in_range, 1, 2),
    "pairwise": _pairwise,
    "err-absent": _failing(on_failure=True),
    "err-present": _failing(on_failure=False),
    "err-is": _failing(on_failure=False, states_got=True),
    "err-is-not": _failing(on_failure=True),
    "err-as": _failing(on_failure=False, states_got=True),
    "throws": _raising(on_raise=False),
    "not-throws": _raising(on_raise=True),
    "pure": _observing(_pure),
    "not-pure": _observing(_not_pure),
    "nil-context-safe": _safe_without_handle,
    "honours-cancellation": _honours,
    "honours-deadline": _honours,
    "idempotent": _observing(_idempotent),
    "accumulates": _observing(_accumulates),
    "deterministic": _deterministic,
    "commutative": _commutative,
    "associative": _associative,
    "round-trip": _round_trip,
}


@dataclass(frozen=True)
class Form:
    """A form as a vector states it: its assertion, its labels and its judge."""

    assertion: str
    generates: tuple[str, ...]
    judge: Judge


@functools.cache
def rule() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Return each form's assertion and the labels of what it generates, by its id."""
    document = json.loads(TABLE.read_text())
    return {
        aid: (str(entry["form"]["of"]), tuple(map(str, entry["form"]["generates"])))
        for aid, entry in document["assertions"].items()
        if "form" in entry
    }


def build(spec: Mapping[str, Any]) -> Form:
    """Return the form a vector states, with its subjects built anew.

    Raises:
        FormError: the vector names no form of the definition or a form
            that no case can state, or misstates its subjects or values.
        LiteralError: a value is no typed literal.
    """
    stated = rule().get(str(spec.get("form")))
    if stated is None:
        raise FormError(f"prop: {spec.get('form')!r} is no form of the definition")
    assertion, generates = stated
    builder = ROOTS.get(assertion)
    if builder is None:
        raise FormError(f"prop: no case can state the form of {assertion!r}")
    values = spec.get("args", [])
    if not isinstance(values, list):
        raise FormError(f"prop: args is {values!r}, not a list of typed literals")
    judge = builder(spec.get("subjects"), [literal.decode(value) for value in values])
    return Form(assertion, generates, judge)


def run_form(
    spec: Mapping[str, Any], generator: Generator, settings: Settings, *, fresh: bool
) -> tuple[Outcome, dict[str, Any] | None]:
    """Run the form a vector states, and return the outcome and the minimal record.

    The record is None when the run found no failing case. It names the
    assertion and states the record's detail, or None in place of the
    detail when the minimal case passes when it is judged again.

    With fresh, each case and the judgement of the record get subjects
    built anew, and no subject is kept across cases.

    Raises:
        FormError: the vector does not state a form a case can run.
    """
    kept = build(spec)

    def body(case: Case) -> None:
        form = build(spec) if fresh else kept
        drawn = [case.draw(generator, label) for label in form.generates]
        if form.judge(drawn) is not None:
            case.fail(form.assertion)

    outcome = run(body, settings)
    if outcome.failing is None:
        return outcome, None
    form = build(spec) if fresh else kept
    stated = form.judge([draw.value for draw in outcome.failing.case.draws])
    detail = None
    if stated is not None:
        detail = {name: literal.encode(value) for name, value in stated.items()}
    return outcome, {"assertion": form.assertion, "detail": detail}
