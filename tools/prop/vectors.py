"""The corpus vectors of the property engine, computed from their inputs.

Each vector kind has a function that takes a case's inputs, as the corpus
states them, and returns the outputs this reference computes for them.
The renderer writes inputs and outputs together, and the validator calls
the same function again to check that a vector still holds.

A choice is written as a JSON integer, or as a decimal string beyond 2^53
- 1 in magnitude; ``{"float": …}`` with a number or a float's name; or
``{"sequence": […]}``. Values are typed literals.

A trace entry is written as a draw entry, ``{"label": …, "value": …}``, or
as a step entry, ``{"step": …}`` with ``"client"`` in a concurrent
section and ``"drain": true`` in the drain. A machine's counterexample
lists its steps among its draws in that form.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any, Final

from . import coverage, literal, replay, store
from .body import build_body
from .bridge import Bridging
from .case import Case, Failed, Generating, Generator, Rejected, Replaying, Step
from .choice import (
    Bounds,
    Choice,
    FloatBounds,
    IntegerBounds,
    SequenceBounds,
)
from .execution import Divergence, Execution, Phase
from .forms import FormError, run_form
from .generator import build
from .inverse import CannotInvert, invert
from .runner import Kind, Outcome, Requirement, Settings, run
from .shape import ShapeError
from .shape import read as read_shape
from .shrink import DEFAULT_BUDGET, Explained
from .source import case_source
from .trace import entries

#: A case of the corpus, or the outputs computed for one: a JSON object.
Vector = dict[str, Any]

#: The identity a shrinking vector's body fails with.
FAILS_WHEN: Final = "fails-when"


class VectorError(ValueError):
    """A vector whose inputs the reference cannot read."""


def choice_literal(choice: Choice) -> object:
    """Return the corpus form of one choice."""
    if choice.kind == "integer":
        return literal.plain(choice.value)
    if choice.kind == "float":
        return {"float": literal.plain(choice.value)}
    assert isinstance(choice.value, tuple)
    return {"sequence": list(choice.value)}


def parse_choice(written: object) -> Choice:
    """Return the choice a corpus form states.

    Raises:
        VectorError: the form is none of the three.
    """
    if isinstance(written, Mapping) and set(written) == {"float"}:
        return Choice("float", literal.number(written["float"]))
    if isinstance(written, Mapping) and set(written) == {"sequence"}:
        elements = written["sequence"]
        if not isinstance(elements, list):
            raise VectorError(f"prop: {written!r} is not a sequence")
        return Choice("sequence", tuple(literal.integer(e) for e in elements))
    try:
        return Choice("integer", literal.integer(written))
    except literal.LiteralError as bad:
        raise VectorError(f"prop: {written!r} is not a choice") from bad


def _choices(case: Case) -> list[object]:
    """Return a case's recorded choices in corpus form."""
    return [choice_literal(choice) for choice in case.choices]


def _parse_choices(written: object) -> list[Choice]:
    """Return the choices a list of corpus forms states."""
    if not isinstance(written, list):
        raise VectorError(f"prop: {written!r} is not a list of choices")
    return [parse_choice(choice) for choice in written]


def _seed(case: Mapping[str, Any]) -> int:
    """Return a vector's seed, stated as a decimal string."""
    seed = case.get("seed")
    if not isinstance(seed, str) or not seed.isdigit():
        raise VectorError(f"prop: seed {seed!r} is not a decimal string")
    return int(seed)


def _decoded(case: Case, decode: Callable[[], object]) -> Vector:
    """Return the recorded choices and the value, or that the case was rejected."""
    try:
        value = decode()
    except Rejected:
        return {"recorded": _choices(case), "value": None, "rejected": True}
    return {
        "recorded": _choices(case),
        "value": literal.encode(value),
        "rejected": False,
    }


def decoding(case: Mapping[str, Any]) -> Vector:
    """Decode a generator from stated choices."""
    generator = build(case["generator"])
    replayed = Case(Replaying(_parse_choices(case["choices"])))
    return _decoded(replayed, partial(generator.decode, replayed))


def _generated(generator: Generator, case: Mapping[str, Any]) -> Vector:
    """Return the choices and the value of each of the first cases of a seed."""
    seed = _seed(case)
    cases: list[Vector] = []
    for index in range(int(case["count"])):
        generated = Case(Generating(case_source(seed, index)))
        decoded = _decoded(generated, partial(generator.decode, generated))
        cases.append({"choices": decoded.pop("recorded"), **decoded})
    return {"cases": cases}


def generation(case: Mapping[str, Any]) -> Vector:
    """Decode a generator from the first cases of a seed."""
    return _generated(build(case["generator"]), case)


def _shape(written: object) -> Generator:
    """Return the generator of a shape a vector states.

    Raises:
        VectorError: the shape does not read.
    """
    try:
        return read_shape(written)
    except ShapeError as bad:
        raise VectorError(str(bad)) from bad


def shapes(case: Mapping[str, Any]) -> Vector:
    """Decode a shape from the first cases of a seed."""
    return _generated(_shape(case["shape"]), case)


def inverse(case: Mapping[str, Any]) -> Vector:
    """Run a shape or a generator backwards from a value.

    Raises:
        VectorError: the vector states both a shape and a generator, or
            neither.
    """
    if ("shape" in case) == ("generator" in case):
        raise VectorError("prop: an inverse vector states a shape or a generator")
    generator = _shape(case["shape"]) if "shape" in case else build(case["generator"])
    try:
        choices = invert(generator, literal.decode(case["value"]))
    except CannotInvert:
        return {"choices": None, "error": True}
    return {"choices": [choice_literal(c) for c in choices], "error": False}


def fixture(case: Mapping[str, Any]) -> Vector:
    """Check a fixture type's vector, which states its shape and computes nothing.

    Raises:
        VectorError: the shape does not read, or the vector names no
            fixture, describes none, or covers nothing.
    """
    _shape(case["shape"])
    for key in ("fixture", "summary", "covers"):
        if not str(case.get(key, "")).strip():
            raise VectorError(f"prop: a fixture vector states no {key}")
    return {}


def draws(case: Mapping[str, Any]) -> Vector:
    """Compute the choices of a case whose draws decode to stated entries.

    Each draw takes the entry at its position. A draw whose label differs
    from its entry's, or whose generator cannot produce the entry's value,
    is an error that names the draw's label. A draw past the last entry
    takes its target, and an entry past the last draw is not read.
    """
    body = [(str(d["label"]), build(d["generator"])) for d in case["draws"]]
    entries = case["entries"]
    choices: list[Choice] = []
    for (label, generator), entry in zip(body, entries, strict=False):
        if entry["label"] != label:
            return {
                "choices": None,
                "values": None,
                "error": _draw_error(label, "label"),
            }
        try:
            choices.extend(invert(generator, literal.decode(entry["value"])))
        except CannotInvert:
            return {
                "choices": None,
                "values": None,
                "error": _draw_error(label, "value"),
            }
    replayed = Case(Replaying(choices))
    values = [
        {"label": label, "value": literal.encode(replayed.draw(generator, label))}
        for label, generator in body
    ]
    return {
        "choices": [choice_literal(c) for c in choices],
        "values": values,
        "error": None,
    }


def _draw_error(label: str, reason: str) -> Vector:
    """Return the error of a draws vector: the draw's label and the reason."""
    return {"label": label, "reason": reason}


def shrinking(case: Mapping[str, Any]) -> Vector:
    """Run a one-draw property that fails when a predicate holds, and shrink it."""
    body = build_body(
        {
            "draw": case["generator"],
            "fails": [{"identity": FAILS_WHEN, "when": case[FAILS_WHEN]}],
        }
    )
    budget = int(case.get("budget", DEFAULT_BUDGET))
    outcome = run(body, Settings(_seed(case), shrink=budget))
    failing = outcome.failing
    return {
        "outcome": outcome.kind.value,
        "cases": outcome.cases,
        "value": None
        if failing is None
        else literal.encode(failing.case.draws[0].value),
        "choices": None if failing is None else _choices(failing.case),
        "token": outcome.token,
        "runs": outcome.runs,
    }


def coverage_verdict(case: Mapping[str, Any]) -> Vector:
    """Decide one requirement at one check."""
    verdict = coverage.verdict(
        int(case["counted"]),
        int(case["valid"]),
        float(case["share"]),
        last=bool(case["last"]),
        exact=bool(case["exact"]),
    )
    return {"verdict": verdict.value}


def bridge(case: Mapping[str, Any]) -> Vector:
    """Decode a generator from a fuzzer's bytes."""
    generator = build(case["generator"])
    bridged = Case(Bridging(bytes.fromhex(str(case["bytes"]))))
    decoded = _decoded(bridged, partial(generator.decode, bridged))
    return {"choices": decoded.pop("recorded"), **decoded}


def token(case: Mapping[str, Any]) -> Vector:
    """Encode choices as a token, or decode a token."""
    if "choices" in case:
        return {"token": replay.encode(_parse_choices(case["choices"]))}
    try:
        choices = replay.decode(str(case["token"]))
    except ValueError:
        return {"decoded": None, "error": True}
    return {"decoded": [choice_literal(c) for c in choices], "error": False}


def store_entry(case: Mapping[str, Any]) -> Vector:
    """Write a store entry and name it, or read the text of one file of a store.

    Raises:
        VectorError: found is no date, or the entry a vector writes does
            not read back as a replay of its choices.
    """
    contract = str(case["contract"])
    if "text" in case:
        verdict = store.read(str(case["text"]), contract)
        replayed = verdict.verdict is store.Verdict.REPLAY
        return {
            "verdict": verdict.verdict.value,
            "choices": [choice_literal(c) for c in verdict.choices]
            if replayed
            else None,
        }
    choices = tuple(_parse_choices(case["choices"]))
    failure = store.Failure(
        contract, choices, case["identity"], tuple(case["counterexample"])
    )
    try:
        found = datetime.date.fromisoformat(str(case["found"]))
    except ValueError as bad:
        raise VectorError(f"prop: found {case['found']!r} is no date") from bad
    written = store.entry(failure, str(case["definition"]), found)
    back = store.read(json.dumps(written), contract)
    if back.verdict is not store.Verdict.REPLAY or back.choices != choices:
        raise VectorError(f"prop: the entry of {contract!r} does not read back")
    return {"name": store.name(contract, choices), "entry": written}


def behaviour(case: Mapping[str, Any]) -> Vector:
    """Run a body under settings, and return the detail of the run."""
    body = build_body(case["body"])
    return {"detail": detail(run(body, run_settings(case.get("settings", {}))))}


def recording(case: Mapping[str, Any]) -> Vector:
    """Run a body that asserts once at its end, and return what a recorded run states.

    The body is a behaviour body followed by one call of true, which fails
    exactly when the body fails. A call of the body that ends before its
    end, rejected, repeated, past its cap or diverging, makes no call. The
    outputs are the property's verdict and, for each call in order, the
    call of the body that made it, numbered from 1, its phase and its
    verdict.
    """
    body = build_body(case["body"])
    made: list[str] = []

    def asserting(called: Case) -> None:
        try:
            body(called)
        except Failed:
            made.append("fail")
            raise
        made.append("pass")

    calls: list[Vector] = []
    runs = 0

    def observe(phase: Phase, execution: Execution) -> None:
        nonlocal runs
        del execution
        runs += 1
        calls.extend(
            {"run": runs, "phase": phase.value, "verdict": verdict} for verdict in made
        )
        made.clear()

    outcome = run(asserting, run_settings(case.get("settings", {})), observe)
    verdict = "pass" if outcome.kind is Kind.PASSED else "fail"
    return {"verdict": verdict, "calls": calls}


def form_run(case: Mapping[str, Any]) -> Vector:
    """Run a property form, and return the detail of the run.

    The form runs twice: once with its subjects kept across cases, and
    once with subjects built anew for each case. A failing run's failure
    is the record of the minimal case.

    Raises:
        VectorError: the form does not run, or the two runs differ because
            the run depends on what earlier cases leave in a subject.
    """
    generator = _shape(case["shape"])
    settings = Settings(_seed(case))
    kept = _form_detail(case, generator, settings, fresh=False)
    fresh = _form_detail(case, generator, settings, fresh=True)
    if kept != fresh:
        raise VectorError(
            f"prop: {case.get('id')!r} depends on what earlier cases leave in a subject"
        )
    return {"detail": kept}


def _form_detail(
    case: Mapping[str, Any], generator: Generator, settings: Settings, *, fresh: bool
) -> Vector:
    """Return the detail of one run of a form, its failure the minimal record.

    A run has a minimal record exactly when its detail states a failure.
    """
    try:
        outcome, record = run_form(case, generator, settings, fresh=fresh)
    except FormError as bad:
        raise VectorError(str(bad)) from bad
    return {**detail(outcome), "failure": record}


def run_settings(written: Mapping[str, Any]) -> Settings:
    """Return the run settings a vector states.

    workers is read and ignored: a run on more workers reports what a run
    on one reports.
    """
    replayed = written.get("replay")
    return Settings(
        seed=_seed(written),
        cases=int(written.get("cases", 100)),
        max_choices=int(written.get("max-choices", 8192)),
        requirements=tuple(
            Requirement(str(r["label"]), float(r["share"]))
            for r in written.get("requirements", [])
        ),
        examples=tuple(tuple(_parse_choices(e)) for e in written.get("examples", [])),
        stored=tuple(tuple(_parse_choices(s)) for s in written.get("stored", [])),
        shrink=int(written.get("shrink", DEFAULT_BUDGET)),
        replay=None if replayed is None else tuple(replay.decode(str(replayed))),
    )


def detail(outcome: Outcome) -> Vector:
    """Return the detail fields of a run's outcome; a field it does not use is null."""
    failing = outcome.failing
    concluded = failing is not None and outcome.kind in (
        Kind.COUNTEREXAMPLE,
        Kind.FLAKY,
    )
    shortfall = outcome.shortfall
    return {
        "outcome": outcome.kind.value,
        "cases": outcome.cases,
        "rejected": outcome.rejected,
        "seed": str(outcome.seed),
        "counterexample": _counterexample(failing, outcome.explanation)
        if concluded and failing is not None
        else None,
        "failure": failing.identity if concluded and failing is not None else None,
        "choices": outcome.token if outcome.kind is Kind.COUNTEREXAMPLE else None,
        "others": [_other(o) for o in outcome.others]
        if outcome.kind is Kind.COUNTEREXAMPLE
        else None,
        "divergence": None
        if outcome.divergence is None
        else _divergence(outcome.divergence),
        "coverage": None
        if shortfall is None
        else {
            "label": shortfall.requirement.label,
            "share": shortfall.requirement.share,
            "counted": shortfall.counted,
            "valid": shortfall.valid,
            "verdict": shortfall.verdict.value,
        },
    }


def _counterexample(
    failing: Execution, explanation: Sequence[Explained]
) -> list[Vector]:
    """Return a failing case's steps and draws, each draw explained where it was."""
    drawn: list[Vector] = []
    index = 0
    for entry in entries(failing.case):
        if isinstance(entry, Step):
            drawn.append(step_literal(entry))
            continue
        explained = explanation[index] if index < len(explanation) else None
        index += 1
        nearest = None if explained is None else explained.nearest_passing
        drawn.append(
            {
                "label": entry.label,
                "value": literal.encode(entry.value),
                "any-value-fails": None
                if explained is None
                else explained.any_value_fails,
                "nearest-passing": None if nearest is None else literal.encode(nearest),
            }
        )
    return drawn


def step_literal(step: Step) -> Vector:
    """Return the corpus form of a step entry."""
    form: Vector = {"step": step.action}
    if step.client is not None:
        form["client"] = step.client
    if step.drain:
        form["drain"] = True
    return form


def _other(execution: Execution) -> Vector:
    """Return another failure's identity, steps and draws, and token."""
    return {
        "failure": execution.identity,
        "counterexample": [
            step_literal(entry)
            if isinstance(entry, Step)
            else {"label": entry.label, "value": literal.encode(entry.value)}
            for entry in entries(execution.case)
        ],
        "choices": replay.encode(execution.case.choices),
    }


def _divergence(divergence: Divergence) -> Vector:
    """Return a divergence with its two versions in corpus form."""
    return {
        "what": divergence.what,
        "index": divergence.index,
        "recorded": _version(divergence.recorded),
        "replayed": _version(divergence.replayed),
    }


def _version(version: object) -> object:
    """Return one side of a divergence: bounds, a fingerprint, an identity or null."""
    if isinstance(version, IntegerBounds | FloatBounds | SequenceBounds):
        return bounds_literal(version)
    return version


def bounds_literal(bounds: Bounds) -> Vector:
    """Return the corpus form of a request's bounds."""
    if isinstance(bounds, IntegerBounds):
        return {
            "kind": "integer",
            "min": literal.plain(bounds.lo),
            "max": literal.plain(bounds.hi),
        }
    if isinstance(bounds, FloatBounds):
        return {
            "kind": "float",
            "min": literal.plain(bounds.lo),
            "max": literal.plain(bounds.hi),
            "allow_nan": bounds.allow_nan,
            "width": bounds.width,
        }
    return {
        "kind": "sequence",
        "k": bounds.k,
        "min_size": bounds.min_size,
        "max_size": bounds.max_size,
    }


#: The function that computes each kind's outputs.
KINDS: Final[dict[str, Callable[[Mapping[str, Any]], Vector]]] = {
    "decoding": decoding,
    "generation": generation,
    "shrinking": shrinking,
    "coverage": coverage_verdict,
    "bridge": bridge,
    "token": token,
    "behaviour": behaviour,
    "store": store_entry,
    "shapes": shapes,
    "inverse": inverse,
    "fixtures": fixture,
    "draws": draws,
    "forms": form_run,
    "recording": recording,
}


def compute(kind: str, case: Mapping[str, Any]) -> Vector:
    """Return the outputs of one case of a kind.

    Raises:
        VectorError: the kind is unknown, or the case's inputs are malformed.
    """
    function = KINDS.get(kind)
    if function is None:
        raise VectorError(f"prop: {kind!r} is no vector kind")
    try:
        return function(case)
    except KeyError as missing:
        raise VectorError(f"prop: a {kind} vector lacks {missing}") from None
