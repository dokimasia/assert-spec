"""Events, processes, usage errors and the JSON form of the history seam."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any, final

from .seam import History, Kind, UsageError, document, record

#: The keys of a call on the key x, as typed literals.
X: list[dict[str, Any]] = [{"type": "string", "value": "x"}]


def integer(value: int) -> dict[str, Any]:
    """Return the typed literal of an int."""
    return {"type": "int", "value": value}


@final
class RecordTest(unittest.TestCase):
    """record(): the events a script records, in the history's JSON form."""

    def test_a_client_continues_on_a_new_process_after_unknown(self) -> None:
        """An unknown write, then a read on process 1, as the seam's vector states."""
        script = [
            {
                "invoke": 0,
                "client": 0,
                "operation": "write",
                "args": [integer(1)],
                "keys": X,
            },
            {"unknown": 0, "error": "the reply was lost"},
            {"invoke": 1, "client": 0, "operation": "read", "args": [], "keys": X},
            {"ok": 1, "output": integer(1)},
        ]
        self.assertEqual(
            [document(event) for event in record(script)],
            [
                {
                    "index": 0,
                    "kind": "invoke",
                    "call": 0,
                    "client": 0,
                    "process": 0,
                    "operation": "write",
                    "args": [integer(1)],
                    "keys": X,
                },
                {
                    "index": 1,
                    "kind": "unknown",
                    "call": 0,
                    "client": 0,
                    "process": 0,
                    "error": "the reply was lost",
                },
                {
                    "index": 2,
                    "kind": "invoke",
                    "call": 2,
                    "client": 0,
                    "process": 1,
                    "operation": "read",
                    "args": [],
                    "keys": X,
                },
                {
                    "index": 3,
                    "kind": "ok",
                    "call": 2,
                    "client": 0,
                    "process": 1,
                    "output": integer(1),
                },
            ],
        )

    def test_a_failure_states_its_error_and_a_pending_call_no_completion(self) -> None:
        """A fail completion keeps the process, and an open call has no completion."""
        script = [
            {
                "invoke": 0,
                "client": 0,
                "operation": "write",
                "args": [integer(1)],
                "keys": [],
            },
            {"fail": 0, "error": "refused"},
            {"invoke": 1, "client": 0, "operation": "read", "args": [], "keys": []},
        ]
        events = record(script)
        self.assertEqual(
            document(events[1]),
            {
                "index": 1,
                "kind": "fail",
                "call": 0,
                "client": 0,
                "process": 0,
                "error": "refused",
            },
        )
        self.assertEqual(
            [event.kind for event in events], [Kind.INVOKE, Kind.FAIL, Kind.INVOKE]
        )
        self.assertEqual(events[2].process, 0)


@final
class HistoryTest(unittest.TestCase):
    """History: one recording order, processes, and the usage errors."""

    def test_numbers_processes_in_the_order_of_their_first_invocation(self) -> None:
        """Client 7 invokes first and runs on process 0, client 3 on process 1."""
        history = History()
        first = history.invoke(7, "read", [], [])
        second = history.invoke(3, "read", [], [])
        second.ok(None)
        first.unknown("lost")
        history.invoke(3, "read", [], []).ok(None)
        history.invoke(7, "read", [], [])
        self.assertEqual(
            [(event.client, event.process) for event in history.events()],
            [(7, 0), (3, 1), (3, 1), (7, 0), (3, 1), (3, 1), (7, 2)],
        )

    def test_an_event_names_its_call_by_the_index_of_its_invocation(self) -> None:
        """Completions point at their invocations across interleaved clients."""
        history = History()
        a = history.invoke(0, "write", [1], ["x"])
        b = history.invoke(1, "write", [2], ["x"])
        b.ok(None)
        a.ok(None)
        self.assertEqual([event.call for event in history.events()], [0, 1, 1, 0])

    def test_refuses_a_second_open_call_of_one_client(self) -> None:
        """A client invokes once at a time."""
        history = History()
        history.invoke(0, "read", [], [])
        with self.assertRaisesRegex(UsageError, "while its call 0 is open"):
            history.invoke(0, "read", [], [])

    def test_refuses_a_second_completion_of_one_call(self) -> None:
        """A call completes once, even after its client has invoked again."""
        history = History()
        call = history.invoke(0, "read", [], [])
        call.ok(1)
        history.invoke(0, "read", [], [])
        completions: list[Callable[[], None]] = [
            lambda: call.ok(1),
            lambda: call.fail("e"),
            lambda: call.unknown("e"),
        ]
        for complete in completions:
            with self.assertRaisesRegex(UsageError, "call 0 has completed already"):
                complete()

    def test_refuses_a_key_without_a_typed_literal(self) -> None:
        """A key is a decoded value."""
        with self.assertRaisesRegex(UsageError, "has no typed literal"):
            History().invoke(0, "read", [], [object()])
