"""check() over list-append histories: the workload, the anomalies and the record."""

from __future__ import annotations

import unittest
from typing import final

from prop.literal import encode

from .isolation import (
    APPEND,
    READ,
    TXN,
    Analysis,
    Anomaly,
    Level,
    TransactionError,
    check,
    transactions,
)
from .seam import Call, History

#: Both levels, for a history that each one judges alike.
LEVELS = (Level.SERIALIZABLE, Level.SNAPSHOT_ISOLATION)


def append(key: object, value: object) -> list[object]:
    """Return a micro-operation that appends value to key."""
    return [APPEND, key, value]


def read(key: object, values: object) -> list[object]:
    """Return a micro-operation that read values from key."""
    return [READ, key, values]


def invoke(history: History, client: int, *mops: list[object]) -> Call:
    """Invoke a transaction of mops, stating each read without its list."""
    invoked: list[object] = [[f, k, None if f == READ else v] for f, k, v in mops]
    keys: list[object] = list(dict.fromkeys(k for _, k, _ in mops))
    return history.invoke(client, TXN, invoked, keys)


def run(history: History, client: int, *mops: list[object]) -> None:
    """Record a transaction that commits at once, and returned mops as they are."""
    invoke(history, client, *mops).ok([list(mop) for mop in mops])


def outcome(history: History, level: Level) -> tuple[str | None, list[str]]:
    """Return the anomaly that a check of history reports, and every kind it lists."""
    detail = check(history.events(), level).detail()
    return detail["anomaly"], detail["kinds"]


def read_skew(t1_completes: str | None, observed: bool) -> History:
    """Return a read skew: call 0 sees call 1's append to y and not its append to x.

    Call 1 completes as t1_completes, or never for None. When observed is
    false, call 0 reads y empty, and no read observes call 1's appends.
    """
    history = History()
    reader = invoke(history, 0, read("x", None), read("y", None))
    writer = invoke(history, 1, append("x", 1), append("y", 2))
    if t1_completes == "ok":
        writer.ok([append("x", 1), append("y", 2)])
    elif t1_completes == "unknown":
        writer.unknown("timed out")
    reader.ok([read("x", []), read("y", [2] if observed else [])])
    return history


def write_skew() -> History:
    """Return a write skew: each of calls 0 and 1 reads the key the other appends to."""
    history = History()
    first = invoke(history, 0, read("x", None), append("y", 1))
    second = invoke(history, 1, read("y", None), append("x", 2))
    first.ok([read("x", []), append("y", 1)])
    second.ok([read("y", []), append("x", 2)])
    return history


@final
class TransactionsTest(unittest.TestCase):
    """transactions(): the workload's contract, and the history it refuses."""

    def test_refuses_a_call_that_is_no_transaction(self) -> None:
        """Every call of the history is a transaction."""
        history = History()
        history.invoke(0, "write", [1], ["x"]).ok(None)
        with self.assertRaisesRegex(TransactionError, "call 0 is 'write', not 'txn'"):
            transactions(history.events())

    def test_refuses_an_argument_that_is_no_micro_operation(self) -> None:
        """A micro-operation states a function, a key and a value."""
        history = History()
        history.invoke(0, TXN, [[APPEND, "x"]], ["x"])
        with self.assertRaisesRegex(TransactionError, "argument 0 of call 0"):
            transactions(history.events())

    def test_refuses_a_read_that_states_a_list_before_it_ran(self) -> None:
        """An invocation states a read's key and no list."""
        history = History()
        history.invoke(0, TXN, [read("x", [1])], ["x"])
        with self.assertRaisesRegex(TransactionError, "states a list before it ran"):
            transactions(history.events())

    def test_refuses_an_output_that_does_not_repeat_the_invocation(self) -> None:
        """An ok output repeats every micro-operation, and each appended value."""
        for output in ([append("x", 2)], [append("x", 1), read("x", [1])], 7):
            with self.subTest(output=output):
                history = History()
                invoke(history, 0, append("x", 1)).ok(output)
                with self.assertRaisesRegex(TransactionError, "call 0"):
                    transactions(history.events())

    def test_refuses_a_read_that_returned_no_list(self) -> None:
        """A read returns the key's whole list."""
        history = History()
        invoke(history, 0, read("x", None)).ok([read("x", 5)])
        with self.assertRaisesRegex(TransactionError, "returned 5, not a list"):
            transactions(history.events())

    def test_a_read_that_returned_null_returned_the_empty_list(self) -> None:
        """A store that returns null for a missing key returned the empty list."""
        history = History()
        invoke(history, 0, read("x", None)).ok([read("x", None)])
        (txn,) = transactions(history.events())
        self.assertEqual(txn.mops[0].value, [])

    def test_refuses_a_value_appended_twice_to_one_key(self) -> None:
        """A value names one append, so it is appended to its key once."""
        history = History()
        run(history, 0, append("x", 1))
        run(history, 0, append("x", 1))
        with self.assertRaisesRegex(TransactionError, "calls 0 and 2 both append 1"):
            transactions(history.events())
        history = History()
        run(history, 0, append("x", 1), append("x", 1))
        with self.assertRaisesRegex(TransactionError, "call 0 appends 1 .* twice"):
            transactions(history.events())

    def test_accepts_one_value_appended_to_two_keys(self) -> None:
        """A value is unique within its key, and may repeat across keys."""
        history = History()
        run(history, 0, append("x", 1), append("y", 1))
        run(history, 0, read("x", [1]), read("y", [1]))
        for level in LEVELS:
            self.assertTrue(check(history.events(), level).passed)


@final
class PassTest(unittest.TestCase):
    """Histories that exhibit no anomaly."""

    def test_passes_a_serial_history_with_no_record(self) -> None:
        """Each call observes every earlier append."""
        history = History()
        run(history, 0, append("x", 1))
        run(history, 1, read("x", [1]), append("x", 2))
        run(history, 0, read("x", [1, 2]))
        for level in LEVELS:
            verdict = check(history.events(), level)
            self.assertTrue(verdict.passed)
            self.assertEqual(
                verdict.detail(),
                {
                    "anomaly": None,
                    "kinds": [],
                    "transactions": None,
                    "cycle": None,
                    "explanation": None,
                },
            )

    def test_passes_an_empty_history(self) -> None:
        """No transaction exhibits nothing."""
        self.assertTrue(check([], Level.SERIALIZABLE).passed)

    def test_passes_a_read_of_the_transactions_own_intermediate_append(self) -> None:
        """A call that reads between two of its own appends reads no other's state."""
        history = History()
        run(history, 0, append("x", 1), read("x", [1]), append("x", 2))
        run(history, 1, read("x", [1, 2]))
        for level in LEVELS:
            self.assertTrue(check(history.events(), level).passed)


@final
class DirectTest(unittest.TestCase):
    """The six kinds that the micro-operations show without a graph."""

    def test_reports_a_garbage_read(self) -> None:
        """A read returned a value that no call appended."""
        history = History()
        run(history, 0, read("x", [9]))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["explanation"]),
            (
                "garbage-read",
                ["garbage-read"],
                [
                    {
                        "call": 0,
                        "key": encode("x"),
                        "read": encode([9]),
                        "value": encode(9),
                    }
                ],
            ),
        )

    def test_reports_a_duplicate_append(self) -> None:
        """A read returned one value twice."""
        history = History()
        run(history, 0, append("x", 1))
        run(history, 1, read("x", [1, 1]))
        self.assertEqual(
            outcome(history, Level.SNAPSHOT_ISOLATION),
            ("duplicate-append", ["duplicate-append"]),
        )

    def test_reports_a_read_that_lacks_the_transactions_own_append(self) -> None:
        """Before its first read, a call knows the key ends with its own appends."""
        history = History()
        run(history, 0, append("x", 1))
        run(history, 1, append("x", 2), read("x", [1]))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], detail["explanation"]),
            (
                "internal-inconsistency",
                [
                    {
                        "call": 2,
                        "key": encode("x"),
                        "read": encode([1]),
                        "expected": encode([2]),
                        "whole": False,
                        "future": None,
                    }
                ],
            ),
        )

    def test_reports_a_read_of_the_transactions_own_later_append(self) -> None:
        """A read contains a value that its call appends only after it."""
        history = History()
        run(history, 0, read("x", [1]), append("x", 1))
        detail = check(history.events(), Level.SNAPSHOT_ISOLATION).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["explanation"]),
            (
                "internal-inconsistency",
                ["internal-inconsistency"],
                [
                    {
                        "call": 0,
                        "key": encode("x"),
                        "read": encode([1]),
                        "expected": encode([]),
                        "whole": False,
                        "future": encode(1),
                    }
                ],
            ),
        )

    def test_reports_a_read_that_differs_from_the_transactions_earlier_read(
        self,
    ) -> None:
        """After a read, a call knows the whole list, and lists every kind it shows."""
        history = History()
        reader = invoke(history, 0, read("x", None), read("x", None))
        run(history, 1, append("x", 1))
        reader.ok([read("x", []), read("x", [1])])
        self.assertEqual(
            outcome(history, Level.SERIALIZABLE),
            ("internal-inconsistency", ["internal-inconsistency", "G-single", "G2"]),
        )

    def test_reports_reads_that_are_not_prefixes_of_one_list(self) -> None:
        """Two committed reads of x disagree on what follows 1."""
        history = History()
        for value in (1, 2, 3):
            run(history, value, append("x", value))
        run(history, 0, read("x", [1, 2]))
        run(history, 0, read("x", [1, 3]))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["explanation"]),
            (
                "incompatible-order",
                ["incompatible-order"],
                [
                    {
                        "calls": [6, 8],
                        "key": encode("x"),
                        "reads": [encode([1, 2]), encode([1, 3])],
                    }
                ],
            ),
        )

    def test_reports_an_aborted_read(self) -> None:
        """A committed read observed an append of a call that failed."""
        history = History()
        invoke(history, 0, append("x", 1)).fail("aborted")
        run(history, 1, read("x", [1]))
        detail = check(history.events(), Level.SNAPSHOT_ISOLATION).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["explanation"]),
            (
                "aborted-read",
                ["aborted-read"],
                [{"call": 2, "key": encode("x"), "value": encode(1), "appender": 0}],
            ),
        )
        self.assertEqual(
            [(t["call"], t.get("kind")) for t in detail["transactions"]],
            [(2, "ok"), (0, "fail")],
        )

    def test_reports_an_intermediate_read(self) -> None:
        """A read ends in a value that its appender followed with another append.

        The appender's later append follows the whole list the read returned,
        so the reader also precedes the appender: a G-single cycle.
        """
        history = History()
        run(history, 0, append("x", 1), append("x", 2))
        run(history, 1, read("x", [1]))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["explanation"]),
            (
                "intermediate-read",
                ["intermediate-read", "G-single", "G2"],
                [
                    {
                        "call": 2,
                        "key": encode("x"),
                        "value": encode(1),
                        "appender": 0,
                        "next": encode(2),
                    }
                ],
            ),
        )


@final
class CycleTest(unittest.TestCase):
    """The four kinds of cycle, the edges they follow and the cycle they report."""

    def test_reports_a_cycle_of_write_dependencies(self) -> None:
        """Calls 0 and 1 append to x in one order and to y in the other."""
        history = History()
        first = invoke(history, 0, append("x", 1), append("y", 4))
        second = invoke(history, 1, append("x", 2), append("y", 3))
        first.ok([append("x", 1), append("y", 4)])
        second.ok([append("x", 2), append("y", 3)])
        run(history, 2, read("x", [1, 2]), read("y", [3, 4]))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["cycle"]),
            (
                "G0",
                ["G0"],
                [{"call": 0, "relations": ["ww"]}, {"call": 1, "relations": ["ww"]}],
            ),
        )
        self.assertEqual(
            detail["explanation"],
            [
                {
                    "from": 0,
                    "to": 1,
                    "relation": "ww",
                    "key": encode("x"),
                    "value": encode(1),
                    "next": encode(2),
                },
                {
                    "from": 1,
                    "to": 0,
                    "relation": "ww",
                    "key": encode("y"),
                    "value": encode(3),
                    "next": encode(4),
                },
            ],
        )

    def test_drops_an_edge_from_a_transaction_to_itself(self) -> None:
        """Call 0 appends 1 and 2 to x, and the G0 cycle leaves that edge out."""
        history = History()
        run(history, 0, append("x", 1), append("x", 2), append("y", 1), append("z", 4))
        run(history, 1, append("y", 2), append("z", 3))
        run(history, 2, read("x", [1, 2]), read("y", [1, 2]), read("z", [3, 4]))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], [entry["call"] for entry in detail["cycle"]]),
            ("G0", [0, 2]),
        )

    def test_reports_a_cycle_of_write_and_read_dependencies(self) -> None:
        """Calls 0 and 1 each read the other's append."""
        history = History()
        first = invoke(history, 0, append("x", 1), read("y", None))
        second = invoke(history, 1, append("y", 2), read("x", None))
        first.ok([append("x", 1), read("y", [2])])
        second.ok([append("y", 2), read("x", [1])])
        detail = check(history.events(), Level.SNAPSHOT_ISOLATION).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["cycle"]),
            (
                "G1c",
                ["G1c"],
                [{"call": 0, "relations": ["wr"]}, {"call": 1, "relations": ["wr"]}],
            ),
        )

    def test_reports_a_cycle_with_exactly_one_read_write_dependency(self) -> None:
        """A read skew is G-single, and its record lists the whole evidence."""
        history = read_skew("ok", observed=True)
        verdict = check(history.events(), Level.SERIALIZABLE)
        events = history.events()
        self.assertEqual(
            verdict.detail(),
            {
                "anomaly": "G-single",
                "kinds": ["G-single", "G2"],
                "transactions": [
                    {
                        "call": 0,
                        "completion": 3,
                        "kind": "ok",
                        "process": 0,
                        "args": [encode(arg) for arg in events[0].args],
                        "output": encode(events[3].output),
                    },
                    {
                        "call": 1,
                        "completion": 2,
                        "kind": "ok",
                        "process": 1,
                        "args": [encode(arg) for arg in events[1].args],
                        "output": encode(events[2].output),
                    },
                ],
                "cycle": [
                    {"call": 0, "relations": ["rw"]},
                    {"call": 1, "relations": ["wr"]},
                ],
                "explanation": [
                    {
                        "from": 0,
                        "to": 1,
                        "relation": "rw",
                        "key": encode("x"),
                        "value": None,
                        "next": encode(1),
                    },
                    {
                        "from": 1,
                        "to": 0,
                        "relation": "wr",
                        "key": encode("y"),
                        "value": encode(2),
                    },
                ],
            },
        )
        self.assertEqual(
            outcome(history, Level.SNAPSHOT_ISOLATION), ("G-single", ["G-single"])
        )

    def test_lists_only_rw_for_the_closing_edge_of_g_single(self) -> None:
        """Call 0 precedes call 2 by ww on x and rw on y, and G-single uses the rw."""
        history = History()
        run(history, 0, append("x", 1), read("y", []), read("z", [7]))
        run(history, 1, append("x", 2), append("y", 5), append("z", 7))
        run(history, 2, read("x", [1, 2]))
        case = Analysis(transactions(history.events())).case(Anomaly.G_SINGLE)
        assert case is not None
        self.assertEqual(
            case.cycle,
            (
                {"call": 0, "relations": ["rw"]},
                {"call": 2, "relations": ["wr"]},
            ),
        )

    def test_reduces_a_walk_to_a_cycle_with_no_two_adjacent_rw_edges(self) -> None:
        """The walk from the edge 0 to 2 passes 4 twice, and reduces to a G-single.

        The edges are 0 rw 2, 2 ww 4, 4 rw 6, 6 ww 8, 8 rw 4 and 4 wr 0. The
        loop 4, 6, 8 has two adjacent rw edges, so no G-nonadjacent exists.
        """
        history = History()
        run(history, 0, read("k1", []), read("k6", [6]))
        run(history, 1, append("k1", 1), append("k2", "b"))
        run(
            history,
            2,
            append("k2", "v"),
            read("k3", []),
            append("k5", 5),
            append("k6", 6),
        )
        run(history, 3, append("k3", 3), append("k4", "p"))
        run(history, 4, append("k4", "q"), read("k5", []))
        run(history, 5, read("k2", ["b", "v"]), read("k4", ["p", "q"]))
        self.assertEqual(
            outcome(history, Level.SERIALIZABLE), ("G-single", ["G-single", "G2"])
        )

    def test_orders_an_unobserved_append_after_its_own_transactions_read(
        self,
    ) -> None:
        """Call 0 reads its own 1 from x, and call 2's unobserved 2 follows it."""
        history = History()
        run(history, 0, append("x", 1), read("x", [1]), read("y", [3]))
        run(history, 1, append("x", 2), append("y", 3))
        self.assertEqual(
            outcome(history, Level.SERIALIZABLE), ("G1c", ["G1c", "G-single", "G2"])
        )

    def test_fails_a_write_skew_as_serializable_and_passes_it_as_snapshot_isolation(
        self,
    ) -> None:
        """Each call reads the empty list that the other's append follows."""
        history = write_skew()
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], detail["kinds"], detail["cycle"]),
            (
                "G2",
                ["G2"],
                [{"call": 0, "relations": ["rw"]}, {"call": 1, "relations": ["rw"]}],
            ),
        )
        self.assertTrue(check(history.events(), Level.SNAPSHOT_ISOLATION).passed)

    def test_reports_a_long_fork_at_both_levels(self) -> None:
        """Calls 2 and 3 see the appends of calls 0 and 1 in opposite orders.

        The cycle has two read-write edges and no two of them adjacent, which
        snapshot isolation forbids.
        """
        history = History()
        calls = [
            invoke(history, 0, append("x", 1)),
            invoke(history, 1, append("y", 2)),
            invoke(history, 2, read("x", None), read("y", None)),
            invoke(history, 3, read("x", None), read("y", None)),
        ]
        calls[0].ok([append("x", 1)])
        calls[1].ok([append("y", 2)])
        calls[2].ok([read("x", [1]), read("y", [])])
        calls[3].ok([read("x", []), read("y", [2])])
        cycle = [
            {"call": 2, "relations": ["rw"]},
            {"call": 1, "relations": ["wr"]},
            {"call": 3, "relations": ["rw"]},
            {"call": 0, "relations": ["wr"]},
        ]
        for level, kinds in (
            (Level.SERIALIZABLE, ["G-nonadjacent", "G2"]),
            (Level.SNAPSHOT_ISOLATION, ["G-nonadjacent"]),
        ):
            with self.subTest(level=level):
                detail = check(history.events(), level).detail()
                self.assertEqual(
                    (detail["anomaly"], detail["kinds"], detail["cycle"]),
                    ("G-nonadjacent", kinds, cycle),
                )

    def test_orders_an_unobserved_append_after_the_empty_list(self) -> None:
        """No read observed 2, and a read of the empty list precedes it."""
        history = write_skew()
        self.assertEqual(outcome(history, Level.SERIALIZABLE)[0], "G2")

    def test_orders_an_unobserved_append_after_the_last_observed_value(self) -> None:
        """Call 4's append of 2 to k1 follows 1, the last value a read observed.

        That orders call 0 before call 4, and call 2's read of the whole list
        before it, which closes the cycle 2, 4, 6, 0.
        """
        history = History()
        run(history, 0, append("k1", 1))
        run(history, 1, read("k1", [1]))
        run(history, 2, read("k0", []), append("k1", 2))
        run(history, 3, read("k1", []), append("k0", 1))
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (
                detail["anomaly"],
                detail["kinds"],
                [entry["call"] for entry in detail["cycle"]],
            ),
            ("G2", ["G2"], [2, 4, 6, 0]),
        )
        self.assertTrue(check(history.events(), Level.SNAPSHOT_ISOLATION).passed)

    def test_drops_the_inference_when_the_one_append_did_not_commit(self) -> None:
        """An unobserved append of a call of unknown outcome orders nothing."""
        history = History()
        first = invoke(history, 0, read("x", None), append("y", 1))
        second = invoke(history, 1, read("y", None), append("x", 2))
        first.ok([read("x", []), append("y", 1)])
        second.unknown("timed out")
        self.assertTrue(check(history.events(), Level.SERIALIZABLE).passed)

    def test_takes_a_call_of_unknown_outcome_as_committed_when_a_read_observed_it(
        self,
    ) -> None:
        """Call 1 completes as unknown or never, and the read of y observes it."""
        for completes in ("unknown", None):
            with self.subTest(completes=completes):
                history = read_skew(completes, observed=True)
                self.assertEqual(
                    outcome(history, Level.SNAPSHOT_ISOLATION),
                    ("G-single", ["G-single"]),
                )

    def test_leaves_out_a_call_of_unknown_outcome_that_no_read_observed(self) -> None:
        """Call 1's appends join no graph, so no cycle forms."""
        for completes in ("unknown", None):
            with self.subTest(completes=completes):
                history = read_skew(completes, observed=False)
                self.assertTrue(check(history.events(), Level.SERIALIZABLE).passed)

    def test_reports_the_cycle_of_the_component_with_the_lowest_call(self) -> None:
        """Two write skews, on x and y and then on a and b, report the first."""
        history = write_skew()
        third = invoke(history, 2, read("a", None), append("b", 1))
        fourth = invoke(history, 3, read("b", None), append("a", 2))
        third.ok([read("a", []), append("b", 1)])
        fourth.ok([read("b", []), append("a", 2)])
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual([entry["call"] for entry in detail["cycle"]], [0, 1])

    def test_reports_the_shortest_path_back_from_the_closing_edge(self) -> None:
        """Calls 0, 1 and 2 read in a ring, and call 0 also reads call 1 directly."""
        history = History()
        zero = invoke(history, 0, append("x", 1), read("y", None), read("z", None))
        one = invoke(history, 1, append("y", 2), read("x", None))
        two = invoke(history, 2, append("z", 3), read("y", None))
        zero.ok([append("x", 1), read("y", [2]), read("z", [3])])
        one.ok([append("y", 2), read("x", [1])])
        two.ok([append("z", 3), read("y", [2])])
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (detail["anomaly"], [entry["call"] for entry in detail["cycle"]]),
            ("G1c", [0, 1]),
        )

    def test_reports_g_single_from_a_component_that_has_one(self) -> None:
        """A write skew on calls 0 and 1 has no G-single, and a later read skew has."""
        history = write_skew()
        reader = invoke(history, 2, read("a", None), read("b", None))
        writer = invoke(history, 3, append("a", 1), append("b", 2))
        writer.ok([append("a", 1), append("b", 2)])
        reader.ok([read("a", []), read("b", [2])])
        detail = check(history.events(), Level.SERIALIZABLE).detail()
        self.assertEqual(
            (
                detail["anomaly"],
                detail["kinds"],
                [entry["call"] for entry in detail["cycle"]],
            ),
            ("G-single", ["G-single", "G2"], [4, 5]),
        )


if __name__ == "__main__":
    unittest.main()
