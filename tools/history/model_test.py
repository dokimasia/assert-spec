"""The named models, and the model built from a subject."""

from __future__ import annotations

import unittest
from typing import final, override

from prop.value import Pairs

from .model import NAMED, Op, Subject, model_from


def known(operation: str, *args: object, output: object = None) -> Op:
    """Return an op that completed with ok and output."""
    return Op(operation, args, known=True, output=output)


def unknown(operation: str, *args: object) -> Op:
    """Return an op whose outcome is unknown."""
    return Op(operation, args, known=False)


@final
class RegisterTest(unittest.TestCase):
    """register: one value, initially null."""

    model = NAMED["register"]

    def test_starts_null_and_stores_a_write(self) -> None:
        """A write leaves its value, whatever it output."""
        self.assertIsNone(self.model.init())
        self.assertEqual(
            self.model.step(None, known("write", 3, output="ignored")), [3]
        )

    def test_accepts_a_read_of_the_state(self) -> None:
        """A read that outputs the state leaves it, and any other read is rejected."""
        self.assertEqual(self.model.step(3, known("read", output=3)), [3])
        self.assertEqual(self.model.step(3, known("read", output=4)), [])
        self.assertEqual(self.model.step(None, known("read", output=0)), [])

    def test_accepts_a_read_whose_outcome_is_unknown_in_any_state(self) -> None:
        """An absent output matches every state."""
        self.assertEqual(self.model.step(3, unknown("read")), [3])

    def test_refuses_an_operation_it_does_not_define(self) -> None:
        """A cas is no register operation."""
        with self.assertRaisesRegex(
            ValueError, "register model has no operation 'cas'"
        ):
            self.model.step(None, known("cas", 1, 2, output=True))


@final
class CasRegisterTest(unittest.TestCase):
    """cas-register: a register with compare-and-set."""

    model = NAMED["cas-register"]

    def test_a_cas_that_matches_stores_its_value(self) -> None:
        """A cas outputs true exactly when the state equals from."""
        self.assertEqual(self.model.step(1, known("cas", 1, 2, output=True)), [2])
        self.assertEqual(self.model.step(1, known("cas", 1, 2, output=False)), [])

    def test_a_refused_cas_leaves_the_state(self) -> None:
        """A cas outputs false exactly when the state differs from from."""
        self.assertEqual(self.model.step(3, known("cas", 1, 2, output=False)), [3])
        self.assertEqual(self.model.step(3, known("cas", 1, 2, output=True)), [])
        self.assertEqual(
            self.model.step(None, known("cas", 1, 2, output=False)), [None]
        )

    def test_rejects_an_output_that_is_no_bool(self) -> None:
        """An output of 1 is not true."""
        self.assertEqual(self.model.step(1, known("cas", 1, 2, output=1)), [])

    def test_a_cas_whose_outcome_is_unknown_takes_effect_when_it_matches(self) -> None:
        """It stores to when the state equals from, and leaves the state otherwise."""
        self.assertEqual(self.model.step(1, unknown("cas", 1, 2)), [2])
        self.assertEqual(self.model.step(3, unknown("cas", 1, 2)), [3])

    def test_writes_and_reads_as_the_register(self) -> None:
        """A write and a read keep the register's meaning."""
        self.assertEqual(self.model.step(None, known("write", 5)), [5])
        self.assertEqual(self.model.step(5, known("read", output=5)), [5])
        with self.assertRaisesRegex(
            ValueError, "cas-register model has no operation 'pop'"
        ):
            self.model.step(5, known("pop"))


@final
class LossyRegisterTest(unittest.TestCase):
    """lossy-register: a write leaves the new value or the old one."""

    model = NAMED["lossy-register"]

    def test_a_write_leaves_the_new_value_then_the_old(self) -> None:
        """Both states follow, in that order."""
        self.assertEqual(self.model.step(1, known("write", 2)), [2, 1])

    def test_reads_as_the_register(self) -> None:
        """A read outputs the state."""
        self.assertEqual(self.model.step(1, known("read", output=1)), [1])
        with self.assertRaisesRegex(
            ValueError, "lossy-register model has no operation"
        ):
            self.model.step(1, known("cas", 1, 2))


@final
class KeyValueTest(unittest.TestCase):
    """key-value: a map from keys to strings, each of which starts empty."""

    model = NAMED["key-value"]

    def test_reads_an_unwritten_key_as_empty(self) -> None:
        """The initial map is empty, and get of any key outputs the empty string."""
        state = self.model.init()
        self.assertEqual(state, Pairs(()))
        self.assertEqual(self.model.step(state, known("get", "k", output="")), [state])
        self.assertEqual(self.model.step(state, known("get", "k", output="v")), [])

    def test_put_and_append_store_strings(self) -> None:
        """A put replaces a value in its place, and an append extends it."""
        state = Pairs((("a", "1"), ("b", "2")))
        self.assertEqual(
            self.model.step(state, known("put", "a", "9")),
            [Pairs((("a", "9"), ("b", "2")))],
        )
        self.assertEqual(
            self.model.step(state, known("append", "c", "3")),
            [Pairs((("a", "1"), ("b", "2"), ("c", "3")))],
        )
        self.assertEqual(
            self.model.step(state, known("append", "b", "x")),
            [Pairs((("a", "1"), ("b", "2x")))],
        )

    def test_stores_no_empty_value(self) -> None:
        """A put of the empty string removes the key, which leaves the initial state."""
        state = Pairs((("a", "1"),))
        self.assertEqual(self.model.step(state, known("put", "a", "")), [Pairs(())])

    def test_accepts_a_get_whose_outcome_is_unknown(self) -> None:
        """An absent output matches every value."""
        state = Pairs((("a", "1"),))
        self.assertEqual(self.model.step(state, unknown("get", "a")), [state])
        with self.assertRaisesRegex(
            ValueError, "key-value model has no operation 'delete'"
        ):
            self.model.step(state, known("delete", "a"))


@final
class QueueTest(unittest.TestCase):
    """queue: dequeue outputs the head, or null when the queue is empty."""

    model = NAMED["queue"]

    def test_enqueues_at_the_tail_and_dequeues_the_head(self) -> None:
        """The head comes out first."""
        self.assertEqual(self.model.init(), [])
        self.assertEqual(self.model.step([1], known("enqueue", 2)), [[1, 2]])
        self.assertEqual(self.model.step([1, 2], known("dequeue", output=1)), [[2]])
        self.assertEqual(self.model.step([1, 2], known("dequeue", output=2)), [])

    def test_an_empty_queue_outputs_null(self) -> None:
        """A dequeue of an empty queue outputs null and leaves it empty."""
        self.assertEqual(self.model.step([], known("dequeue", output=None)), [[]])
        self.assertEqual(self.model.step([], known("dequeue", output=1)), [])

    def test_a_dequeue_whose_outcome_is_unknown_removes_the_head(self) -> None:
        """It removes the head when one exists."""
        self.assertEqual(self.model.step([1, 2], unknown("dequeue")), [[2]])
        self.assertEqual(self.model.step([], unknown("dequeue")), [[]])
        with self.assertRaisesRegex(ValueError, "queue model has no operation 'peek'"):
            self.model.step([], known("peek"))


@final
class SetTest(unittest.TestCase):
    """set: values in the order they were added, compared as a set."""

    model = NAMED["set"]

    def test_adds_a_value_once(self) -> None:
        """A second add leaves the set."""
        self.assertEqual(self.model.init(), [])
        self.assertEqual(self.model.step([1], known("add", 2)), [[1, 2]])
        self.assertEqual(self.model.step([1], known("add", 1)), [[1]])

    def test_contains_outputs_whether_the_value_is_present(self) -> None:
        """A wrong answer is rejected, and an absent one accepted."""
        self.assertEqual(self.model.step([1], known("contains", 1, output=True)), [[1]])
        self.assertEqual(self.model.step([1], known("contains", 2, output=True)), [])
        self.assertEqual(self.model.step([1], unknown("contains", 2)), [[1]])

    def test_remove_outputs_whether_it_removed_the_value(self) -> None:
        """An output of true removes the value, and false leaves a set without it."""
        self.assertEqual(
            self.model.step([1, 2], known("remove", 1, output=True)), [[2]]
        )
        self.assertEqual(self.model.step([2], known("remove", 1, output=False)), [[2]])
        self.assertEqual(self.model.step([2], known("remove", 1, output=True)), [])
        self.assertEqual(self.model.step([1], known("remove", 1, output=False)), [])

    def test_a_remove_whose_outcome_is_unknown_removes_a_present_value(self) -> None:
        """It removes the value when present, and leaves the set otherwise."""
        self.assertEqual(self.model.step([1, 2], unknown("remove", 1)), [[2]])
        self.assertEqual(self.model.step([2], unknown("remove", 1)), [[2]])
        with self.assertRaisesRegex(ValueError, "set model has no operation 'clear'"):
            self.model.step([2], known("clear", 1))

    def test_compares_states_as_sets(self) -> None:
        """Two orders of one set are equal and share a key, and other sets are not."""
        self.assertTrue(self.model.equal([1, 2], [2, 1]))
        self.assertEqual(self.model.key([1, 2]), self.model.key([2, 1]))
        self.assertFalse(self.model.equal([1, 2], [1, 3]))
        self.assertFalse(self.model.equal([1], [1, 2]))


@final
class ModelFromTest(unittest.TestCase):
    """model_from(): a model whose state is the calls applied so far."""

    @override
    def setUp(self) -> None:
        """Count the subjects built and the calls applied to them."""
        self.built = 0
        self.applied = 0

    def counter(self) -> Subject:
        """Return a fresh counter: add(n) adds n and outputs the new total."""
        self.built += 1
        total = [0]

        def apply(operation: str, args: tuple[object, ...]) -> object:
            self.applied += 1
            assert operation == "add"
            (amount,) = args
            assert isinstance(amount, int)
            total[0] += amount
            return total[0]

        return apply

    def test_replays_the_sequence_on_a_fresh_subject(self) -> None:
        """A step at depth two builds one subject and calls it three times."""
        model = model_from(self.counter)
        state = (("add", (1,)), ("add", (2,)))
        self.assertEqual(model.cost(state), 3)
        self.assertEqual(
            model.step(state, known("add", 4, output=7)), [(*state, ("add", (4,)))]
        )
        self.assertEqual((self.built, self.applied), (1, 3))

    def test_rejects_an_output_the_subject_does_not_give(self) -> None:
        """The subject outputs 1, not 2."""
        model = model_from(self.counter)
        self.assertEqual(model.step(model.init(), known("add", 1, output=2)), [])
        self.assertEqual(model.cost(model.init()), 1)

    def test_accepts_a_call_whose_outcome_is_unknown(self) -> None:
        """The subject still applies it, and the state lists its operation."""
        model = model_from(self.counter)
        self.assertEqual(model.step((), unknown("add", 1)), [(("add", (1,)),)])
        self.assertEqual(self.applied, 1)

    def test_compares_states_by_operations_and_arguments_in_order(self) -> None:
        """Equal sequences share a key, and other orders, lengths or args differ."""
        model = model_from(self.counter)
        a, b = ("add", (1,)), ("add", (2,))
        self.assertTrue(model.equal((a, b), (("add", (1,)), b)))
        self.assertEqual(model.key((a, b)), model.key((("add", (1,)), b)))
        self.assertFalse(model.equal((a, b), (b, a)))
        self.assertFalse(model.equal((a,), (a, b)))
        self.assertFalse(model.equal((a,), (("add", (1.0,)),)))
        self.assertFalse(model.equal((a,), (("sub", (1,)),)))
