"""Events in one recording order, and the script form in which the corpus states them.

A History records each invocation and each completion as the next event.
Each client starts on a process of its own. A call that completes as
unknown may still be in progress inside the subject, so its client
continues on a new process. Processes are numbered in the order of their
first invocation, and every process has at most one open call.

record() runs a script, the form in which the corpus states a history. An
entry with ``invoke`` opens a call under a number of the script, and an
entry with ``ok``, ``fail`` or ``unknown`` completes the call it names.
document() returns an event in the history's JSON form, with args, keys
and output as typed literals and an error as its text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, final

from prop.literal import decode, encode
from prop.value import canonical


class UsageError(Exception):
    """A call that breaks the seam's contract, which is a bug in the test's own code."""


class Kind(StrEnum):
    """The kind of an event."""

    INVOKE = "invoke"
    OK = "ok"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Event:
    """One recorded event.

    call is the index of the call's invocation event. operation, args and
    keys are set on an invocation, output on an ok completion, and error on
    a fail or an unknown completion.
    """

    index: int
    kind: Kind
    call: int
    client: int
    process: int
    operation: str = ""
    args: tuple[object, ...] = ()
    keys: tuple[object, ...] = ()
    output: object = None
    error: str = ""


@final
class Call:
    """An open call, through which its client records the completion."""

    def __init__(self, complete: Callable[[Kind, object], None]) -> None:
        """Record each completion through complete."""
        self._complete = complete

    def ok(self, output: object) -> None:
        """Record that the call returned output and took effect.

        Raises:
            UsageError: the call has completed already.
        """
        self._complete(Kind.OK, output)

    def fail(self, error: str) -> None:
        """Record that the call took no effect and returned nothing a model checks.

        Raises:
            UsageError: the call has completed already.
        """
        self._complete(Kind.FAIL, error)

    def unknown(self, error: str) -> None:
        """Record that the call ended without an outcome.

        Raises:
            UsageError: the call has completed already.
        """
        self._complete(Kind.UNKNOWN, error)


@final
class History:
    """The events of one history, in recording order."""

    def __init__(self) -> None:
        """Start an empty history."""
        self._events: list[Event] = []
        self._open: dict[int, int] = {}
        self._process: dict[int, int] = {}
        self._processes = 0

    def invoke(
        self,
        client: int,
        operation: str,
        args: Sequence[object],
        keys: Sequence[object],
    ) -> Call:
        """Record an invocation by client, and return its call.

        keys lists the keys the call touches, and an empty list means every
        key.

        Raises:
            UsageError: the client has a call open, or a key is not a value
                that a typed literal decodes to.
        """
        if client in self._open:
            raise UsageError(
                f"history: client {client} invokes {operation!r} while its call "
                f"{self._open[client]} is open"
            )
        for key in keys:
            try:
                canonical(key)
            except TypeError as bad:
                raise UsageError(
                    f"history: the key {key!r} has no typed literal"
                ) from bad
        if client not in self._process:
            self._process[client] = self._processes
            self._processes += 1
        index = len(self._events)
        self._events.append(
            Event(
                index,
                Kind.INVOKE,
                index,
                client,
                self._process[client],
                operation,
                tuple(args),
                tuple(keys),
            )
        )
        self._open[client] = index
        return Call(lambda kind, value: self._completes(index, kind, value))

    def events(self) -> list[Event]:
        """Return the recorded events in recording order."""
        return list(self._events)

    def _completes(self, call: int, kind: Kind, value: object) -> None:
        """Record the completion of the call whose invocation is at index call.

        Raises:
            UsageError: the call has completed already.
        """
        invocation = self._events[call]
        client = invocation.client
        if self._open.get(client) != call:
            raise UsageError(f"history: call {call} has completed already")
        del self._open[client]
        if kind is Kind.UNKNOWN:
            del self._process[client]
        index = len(self._events)
        process = invocation.process
        if kind is Kind.OK:
            event = Event(index, kind, call, client, process, output=value)
        else:
            event = Event(index, kind, call, client, process, error=str(value))
        self._events.append(event)


def record(script: Sequence[Mapping[str, Any]]) -> list[Event]:
    """Return the events that a script records through a history.

    Raises:
        UsageError: an entry is a call of the seam that its contract refuses.
        LiteralError: an argument, a key or an output is not a typed literal.
    """
    history = History()
    calls: dict[int, Call] = {}
    for entry in script:
        if "invoke" in entry:
            calls[entry["invoke"]] = history.invoke(
                entry["client"],
                entry["operation"],
                [decode(arg) for arg in entry["args"]],
                [decode(key) for key in entry["keys"]],
            )
        elif "ok" in entry:
            calls[entry["ok"]].ok(decode(entry["output"]))
        elif "fail" in entry:
            calls[entry["fail"]].fail(entry["error"])
        else:
            calls[entry["unknown"]].unknown(entry["error"])
    return history.events()


def document(event: Event) -> dict[str, Any]:
    """Return an event in the history's JSON form."""
    form: dict[str, Any] = {
        "index": event.index,
        "kind": event.kind.value,
        "call": event.call,
        "client": event.client,
        "process": event.process,
    }
    if event.kind is Kind.INVOKE:
        form["operation"] = event.operation
        form["args"] = [encode(arg) for arg in event.args]
        form["keys"] = [encode(key) for key in event.keys]
    elif event.kind is Kind.OK:
        form["output"] = encode(event.output)
    else:
        form["error"] = event.error
    return form
