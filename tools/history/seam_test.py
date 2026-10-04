"""Events, processes, usage errors and the JSON form of the history seam."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any, final

from .seam import (
    History,
    Interval,
    IntervalError,
    Kind,
    ScriptError,
    UsageError,
    document,
    from_intervals,
    record,
)

#: The keys of a call on the key x, as typed literals.
X: list[dict[str, Any]] = [{"type": "string", "value": "x"}]


def integer(value: int) -> dict[str, Any]:
    """Return the typed literal of an int."""
    return {"type": "int", "value": value}


def read(client: int, start: int, end: int | None = None) -> Interval:
    """Return a read of x by client, ok with null output, or pending without an end."""
    kind = None if end is None else Kind.OK
    return Interval(client, "read", (), ("x",), start, end, kind)


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

    def test_names_the_entry_whose_call_raises_a_usage_error(self) -> None:
        """The second invocation of client 0 is entry 2."""
        script = [
            {"invoke": 0, "client": 0, "operation": "read", "args": [], "keys": X},
            {"invoke": 1, "client": 1, "operation": "read", "args": [], "keys": X},
            {"invoke": 2, "client": 0, "operation": "read", "args": [], "keys": X},
        ]
        with self.assertRaises(ScriptError) as refused:
            record(script)
        self.assertEqual(refused.exception.entry, 2)
        self.assertRegex(str(refused.exception), "^history: script entry 2: client 0 ")
        self.assertIsInstance(refused.exception.__cause__, UsageError)


@final
class FromIntervalsTest(unittest.TestCase):
    """from_intervals(): time order, the given order at one time, and the errors."""

    def test_puts_an_invocation_before_a_completion_at_one_time(self) -> None:
        """A read that starts when a write ends is concurrent with it."""
        events = from_intervals([read(0, 0, 5), read(1, 5, 9)]).events()
        self.assertEqual(
            [(event.kind, event.call) for event in events],
            [(Kind.INVOKE, 0), (Kind.INVOKE, 1), (Kind.OK, 0), (Kind.OK, 1)],
        )

    def test_keeps_the_given_order_among_invocations_and_completions(self) -> None:
        """Clients 2 and 0 start and end at one time, in the order of their entries."""
        events = from_intervals([read(2, 5, 9), read(0, 5, 9), read(1, 0, 9)]).events()
        self.assertEqual(
            [(event.kind, event.client) for event in events],
            [
                (Kind.INVOKE, 1),
                (Kind.INVOKE, 2),
                (Kind.INVOKE, 0),
                (Kind.OK, 2),
                (Kind.OK, 0),
                (Kind.OK, 1),
            ],
        )

    def test_records_each_completion_kind_and_the_process_after_unknown(
        self,
    ) -> None:
        """A failure keeps the process, and an unknown entry moves its client on."""
        entries = [
            Interval(0, "write", (1,), ("x",), 0, 1, Kind.UNKNOWN, error="timed out"),
            Interval(1, "write", (2,), ("x",), 0, 1, Kind.FAIL, error="refused"),
            Interval(0, "read", (), ("x",), 2, 3, Kind.OK, output=1),
            Interval(1, "read", (), ("x",), 2),
        ]
        events = from_intervals(entries).events()
        self.assertEqual(
            [(event.kind, event.client, event.process) for event in events],
            [
                (Kind.INVOKE, 0, 0),
                (Kind.INVOKE, 1, 1),
                (Kind.UNKNOWN, 0, 0),
                (Kind.FAIL, 1, 1),
                (Kind.INVOKE, 0, 2),
                (Kind.INVOKE, 1, 1),
                (Kind.OK, 0, 2),
            ],
        )
        self.assertEqual(
            (events[2].error, events[3].error, events[6].output),
            ("timed out", "refused", 1),
        )

    def test_refuses_entries_of_one_client_that_share_an_instant(self) -> None:
        """Intervals are closed, so an entry ending at 3 overlaps one starting at 3."""
        with self.assertRaisesRegex(
            IntervalError, "^history: entry 1 overlaps entry 0"
        ):
            from_intervals([read(0, 3, 6), read(0, 0, 3)])
        from_intervals([read(0, 4, 6), read(0, 0, 3), read(1, 0, 9)])

    def test_a_pending_entry_overlaps_every_later_entry_of_its_client(self) -> None:
        """An entry that ends before the pending one starts does not overlap it."""
        with self.assertRaises(IntervalError) as refused:
            from_intervals([read(0, 0, 1), read(0, 5), read(0, 9, 12)])
        self.assertEqual(refused.exception.entry, 2)

    def test_refuses_an_entry_that_ends_before_it_starts(self) -> None:
        """The error names the first entry in the given order that breaks a rule."""
        with self.assertRaises(IntervalError) as refused:
            from_intervals([read(0, 0, 2), read(1, 5, 3), read(0, 1, 3)])
        self.assertEqual(refused.exception.entry, 1)
        self.assertIn("ends at 3, before it starts at 5", str(refused.exception))
        from_intervals([read(0, 4, 4)])


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
