"""Machines: swarm, the steps of each part, the checks, and traces."""

from __future__ import annotations

import json
import unittest
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import final

from history.model import Model, Op
from prop.case import Case, Failed, Generating, Replaying, Span, Step
from prop.choice import Choice, IntegerBounds
from prop.generator import Integer
from prop.source import Source
from prop.trace import Draw, TraceError, Tracing

from .machine import CHECK, Action, Machine, Options, steps
from .scheduler import Scheduler, Uniform

#: The generator of the inputs the tests draw.
DIGIT = Integer(IntegerBounds(0, 9))

#: The bounds of a choice between two values.
BINARY = IntegerBounds(0, 1)


def replay(*values: int) -> Case:
    """Return a case that replays integer values."""
    return Case(Replaying([Choice("integer", v) for v in values]))


def counting(step: Callable[[int, Op], list[object]] | None = None) -> Model:
    """Return a model whose state counts the calls, or that steps as step does."""

    def count(state: object, op: Op) -> list[object]:
        assert isinstance(state, int)
        return [state + 1] if step is None else step(state, op)

    return Model(lambda: 0, count)


@dataclass
class Log:
    """What the actions of a test did, in order."""

    events: list[tuple[object, ...]] = field(default_factory=list)

    def action(
        self,
        name: str,
        *,
        weight: int = 1,
        enabled: Callable[[object], bool] | None = None,
        drain: bool = False,
        draws: bool = False,
    ) -> Action:
        """Return an action that records a call of its name, and logs its run."""

        def run(case: Case, client: int, value: object) -> None:
            args = () if value is None else (value,)
            case.history.invoke(client, name, args, ()).ok(None)
            self.events.append((name, client, value))

        def given(case: Case, state: object) -> object:
            self.events.append(("input", name, state))
            return case.draw(DIGIT, "v") if draws else None

        return Action(name, run, weight, enabled, drain, given)


@final
class SwarmTest(unittest.TestCase):
    """Swarm: one choice per action, which keeps or disables it for the case."""

    def test_one_choice_per_action_in_order_with_edge_1(self) -> None:
        """Three actions make three choices before anything else."""
        log = Log()
        case = replay(1, 1, 1)
        machine = Machine(tuple(log.action(name) for name in "abc"))
        steps(case, machine, Options(max=0))
        self.assertEqual([r.bounds for r in case.requests[:3]], [BINARY] * 3)
        self.assertEqual([r.edge for r in case.requests[:3]], [1, 1, 1])

    def test_the_last_choice_keeps_its_action_when_no_earlier_one_did(self) -> None:
        """The third action's bounds are [1, 1], and it takes the step."""
        log = Log()
        case = replay(0, 0, 0, 1, 0)
        machine = Machine(tuple(log.action(name) for name in "abc"))
        steps(case, machine, Options(max=1))
        self.assertEqual(case.requests[2].bounds, IntegerBounds(1, 1))
        self.assertEqual(case.steps, [(0, Step("c"))])

    def test_a_disabled_action_takes_no_sequential_step(self) -> None:
        """With b disabled, the step's list contains a alone."""
        log = Log()
        case = replay(1, 0, 1, 0, 0)
        machine = Machine((log.action("a"), log.action("b")))
        steps(case, machine)
        self.assertEqual(case.requests[3].bounds, IntegerBounds(0, 0))
        self.assertEqual([step.action for _, step in case.steps], ["a"])

    def test_with_swarm_off_every_action_is_kept_without_a_choice(self) -> None:
        """The first request is the first flag."""
        log = Log()
        case = replay(1, 1, 0)
        machine = Machine((log.action("a"), log.action("b")))
        steps(case, machine, Options(swarm=False))
        self.assertEqual(case.requests[0].edge, 1)
        self.assertEqual(case.requests[1].bounds, BINARY)
        self.assertEqual([step.action for _, step in case.steps], ["b"])

    def test_a_drain_action_drains_whether_or_not_swarm_kept_it(self) -> None:
        """Swarm disables d, and d still takes the drain's one step."""
        pending = [1]
        log = Log()
        drained = log.action("d", enabled=lambda state: pending[0] > 0, drain=True)

        def deliver(case: Case, client: int, value: object) -> None:
            drained.run(case, client, value)
            pending[0] = 0

        machine = Machine(
            (log.action("a"), Action("d", deliver, drain=True, enabled=drained.enabled))
        )
        case = replay(1, 0, 0)
        steps(case, machine)
        self.assertEqual(case.steps, [(0, Step("d", drain=True))])


@final
class SequentialTest(unittest.TestCase):
    """Sequential steps: the list, the flag, the index, the span and the run."""

    def test_a_step_is_a_flag_an_index_and_its_input_in_a_span_of_its_action(
        self,
    ) -> None:
        """The step of b covers its flag, its index and its input's draw."""
        log = Log()
        case = replay(1, 1, 7, 0)
        machine = Machine((log.action("a"), log.action("b", draws=True)))
        steps(case, machine, Options(swarm=False))
        self.assertEqual(
            case.spans, [Span("b", 0, 3, 0, None), Span("integer", 2, 3, 1, 0)]
        )
        self.assertEqual(case.steps, [(0, Step("b"))])
        self.assertEqual(log.events, [("input", "b", None), ("b", 0, 7)])
        self.assertEqual(case.requests[1].edge, 0)

    def test_the_list_holds_the_actions_enabled_in_every_state(self) -> None:
        """Action b is enabled in state 0 alone, so two states after a call drop it.

        The machine calls enabled once for each state, in the order of the
        states.
        """
        seen: list[object] = []
        log = Log()

        def zero(state: object) -> bool:
            seen.append(state)
            return state == 0

        lossy = counting(lambda state, op: [state + 1, state])
        machine = Machine((log.action("a"), log.action("b", enabled=zero)), lossy)
        case = replay(1, 0, 1, 0)
        steps(case, machine, Options(swarm=False, max=2))
        self.assertEqual(
            [r.bounds for r in case.requests],
            [BINARY, BINARY, BINARY, IntegerBounds(0, 0), IntegerBounds(0, 0)],
        )
        self.assertEqual(seen, [0, 1, 0, 2, 1, 0])

    def test_with_no_action_enabled_the_steps_end_without_a_flag(self) -> None:
        """The case requests nothing."""
        log = Log()
        case = replay()
        machine = Machine((log.action("a", enabled=lambda state: False),))
        steps(case, machine, Options(swarm=False))
        self.assertEqual(case.requests, [])

    def test_the_flag_continues_by_the_mean_up_to_the_maximum(self) -> None:
        """A mean of 3 continues on a coin of 3 in 4, and 5 steps force a stop."""
        most = 5
        for seed in range(40):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            machine = Machine((Log().action("a"),))
            steps(case, machine, Options(mean=3, max=most, swarm=False))
            taken = 0
            while taken < most and twin.coin(3, 4):
                taken += 1
            self.assertEqual(len(case.steps), taken, seed)
            if taken == most:
                self.assertEqual(case.requests[-1].bounds, IntegerBounds(0, 0))

    def test_the_index_follows_the_weights(self) -> None:
        """Weights 1 and 3 split below(4) into a and b."""
        most = 20
        for seed in range(20):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            log = Log()
            machine = Machine((log.action("a"), log.action("b", weight=3)))
            steps(case, machine, Options(mean=1000, max=most, swarm=False))
            want: list[str] = []
            while len(want) < most and twin.coin(1000, 1001):
                want.append("a" if twin.below(4) < 1 else "b")
            self.assertEqual([step.action for _, step in case.steps], want, seed)

    def test_a_check_that_fails_fails_the_case_with_the_record(self) -> None:
        """The model rejects every call, so the first step fails."""
        log = Log()
        machine = Machine((log.action("a"),), counting(lambda state, op: []))
        case = replay(1, 0)
        with self.assertRaises(Failed) as caught:
            steps(case, machine, Options(swarm=False))
        failed = caught.exception
        self.assertEqual(failed.identity, CHECK)
        self.assertEqual(json.loads(failed.message)["outcome"], "violated")

    def test_an_undecided_check_fails_the_case(self) -> None:
        """A step that costs more than the budget stops the search."""
        log = Log()
        costly = Model(lambda: 0, lambda state, op: [0], cost=lambda state: 10**8)
        case = replay(1, 0)
        with self.assertRaises(Failed) as caught:
            steps(case, Machine((log.action("a"),), costly), Options(swarm=False))
        detail = json.loads(caught.exception.message)
        self.assertEqual((detail["outcome"], detail["limit"]), ("undecided", "steps"))

    def test_input_receives_the_first_state_after_the_order_found(self) -> None:
        """After one call of a lossy model the states are 1 and 0."""
        log = Log()
        lossy = counting(lambda state, op: [state + 1, state])
        case = replay(1, 0, 1, 0, 0)
        steps(case, Machine((log.action("a"),), lossy), Options(swarm=False))
        self.assertEqual(
            log.events,
            [("input", "a", 0), ("a", 0, None), ("input", "a", 1), ("a", 0, None)],
        )

    def test_the_invariant_runs_after_setup_after_each_step_and_after_settle(
        self,
    ) -> None:
        """Two steps: the invariant sees 0, 1 and 2, then settle and 2 again."""
        seen: list[tuple[str, object]] = []
        machine = Machine(
            (Log().action("a"),),
            counting(),
            invariant=lambda case, state: seen.append(("invariant", state)),
            settle=lambda case, state: seen.append(("settle", state)),
        )
        steps(replay(1, 0, 1, 0, 0), machine, Options(swarm=False))
        self.assertEqual(
            seen,
            [
                ("invariant", 0),
                ("invariant", 1),
                ("invariant", 2),
                ("settle", 2),
                ("invariant", 2),
            ],
        )

    def test_a_machine_without_a_model_has_the_absent_state(self) -> None:
        """The input, enabled, invariant and settle functions all receive None."""
        seen: list[object] = []
        log = Log()

        def enabled(state: object) -> bool:
            seen.append(state)
            return True

        machine = Machine(
            (log.action("a", enabled=enabled),),
            invariant=lambda case, state: seen.append(state),
            settle=lambda case, state: seen.append(state),
        )
        steps(replay(1, 0), machine, Options(swarm=False))
        self.assertEqual(seen, [None] * 6)
        self.assertEqual(log.events[0], ("input", "a", None))

    def test_a_run_that_yields_ends_within_its_step(self) -> None:
        """Each yield on client 0 continues at once."""
        events: list[str] = []

        def run(case: Case, client: int, value: object) -> Iterator[None]:
            del case, value
            events.append(f"start {client}")
            yield
            events.append("end")

        machine = Machine((Action("a", run),))
        steps(replay(1, 0, 1, 0, 0), machine, Options(swarm=False))
        self.assertEqual(events, ["start 0", "end", "start 0", "end"])


@final
class ConcurrentTest(unittest.TestCase):
    """The concurrent section: its steps, its clients and its tasks."""

    def options(self, case: Case, **overrides: int) -> Options:
        """Return options with two clients, no sequential step and no swarm."""
        scheduler = Scheduler(case, Uniform())
        return Options(
            max=overrides.get("max", 0),
            swarm=False,
            clients=overrides.get("clients", 2),
            scheduler=scheduler,
        )

    def test_a_step_is_a_flag_a_client_and_an_index(self) -> None:
        """The client is in [0, clients] with edge 0, and the index is over a and b."""
        log = Log()
        case = replay(0, 1, 2, 1, 0)
        machine = Machine((log.action("a"), log.action("b")))
        steps(case, machine, self.options(case))
        self.assertEqual(
            [r.bounds for r in case.requests[1:4]],
            [BINARY, IntegerBounds(0, 2), BINARY],
        )
        self.assertEqual([r.edge for r in case.requests[1:4]], [1, 0, 0])
        self.assertEqual(case.steps, [(0, Step("b", client=2))])
        self.assertEqual(case.spans[0], Span("b", 1, 4, 0, None))

    def test_every_input_is_requested_before_any_step_runs(self) -> None:
        """Both inputs come from the state after the sequential steps."""
        log = Log()
        case = replay(0, 1, 2, 0, 1, 1, 0, 0)
        steps(case, Machine((log.action("a"),), counting()), self.options(case))
        self.assertEqual(
            log.events,
            [("input", "a", 0), ("input", "a", 0), ("a", 1, None), ("a", 2, None)],
        )

    def test_client_0_runs_its_steps_before_the_other_clients_start(self) -> None:
        """The step of client 1 is listed first and runs last."""
        log = Log()
        case = replay(0, 1, 1, 0, 1, 0, 0, 0)
        steps(case, Machine((log.action("a"),)), self.options(case))
        runs = [event for event in log.events if event[0] == "a"]
        self.assertEqual(runs, [("a", 0, None), ("a", 1, None)])

    def test_each_other_client_is_a_task_spawned_in_client_order(self) -> None:
        """Release index 1 runs client 2 before client 1."""
        log = Log()
        case = replay(0, 1, 1, 0, 1, 2, 0, 0, 1)
        steps(case, Machine((log.action("a"),)), self.options(case))
        runs = [event for event in log.events if event[0] == "a"]
        self.assertEqual(runs, [("a", 2, None), ("a", 1, None)])

    def test_only_actions_without_enabled_join_the_section(self) -> None:
        """Action b states enabled, so the index over a alone is forced."""
        log = Log()
        case = replay(0, 1, 1, 0, 0)
        machine = Machine(
            (log.action("a"), log.action("b", enabled=lambda state: True))
        )
        steps(case, machine, self.options(case))
        self.assertEqual(case.requests[3].bounds, IntegerBounds(0, 0))

    def test_a_section_without_an_eligible_action_records_no_flag(self) -> None:
        """After the sequential flag, the case requests nothing."""
        log = Log()
        case = replay(0)
        machine = Machine((log.action("a", enabled=lambda state: True),))
        steps(case, machine, self.options(case))
        self.assertEqual(len(case.requests), 1)

    def test_the_client_is_uniform_over_the_clients(self) -> None:
        """Each client is below(clients + 1), after the flag's coin of 5 in 6."""
        most = Options().concurrent
        for seed in range(20):
            case, twin = Case(Generating(Source(seed))), Source(seed)
            steps(case, Machine((Log().action("a"),)), self.options(case))
            want: list[int] = []
            while len(want) < most and twin.coin(5, 6):
                want.append(twin.below(3))
            self.assertEqual([step.client for _, step in case.steps], want, seed)

    def test_the_history_is_checked_once_every_task_ends(self) -> None:
        """The settle check receives the count of every call of the section."""
        seen: list[object] = []
        case = replay(0, 1, 1, 0, 1, 2, 0, 1, 0, 0)
        machine = Machine(
            (Log().action("a"),),
            counting(),
            settle=lambda case, state: seen.append(state),
        )
        steps(case, machine, self.options(case))
        self.assertEqual(seen, [3])

    def test_the_drain_starts_from_the_state_after_the_section(self) -> None:
        """Action d is enabled only once the section's two calls are counted."""
        log = Log()
        calls = 2
        case = replay(0, 1, 1, 0, 1, 2, 0, 0, 0, 0)
        machine = Machine(
            (
                log.action("a"),
                log.action("d", enabled=lambda state: state == calls, drain=True),
            ),
            counting(),
        )
        steps(case, machine, self.options(case, max=1))
        self.assertEqual(case.steps[-1], (0, Step("d", drain=True)))

    def test_a_section_that_fails_its_check_ends_before_the_drain(self) -> None:
        """The model rejects the second call, and the drain action never runs."""
        log = Log()
        case = replay(0, 1, 1, 0, 1, 2, 0, 0, 0, 0)
        rejects = counting(lambda state, op: [] if state == 1 else [state + 1])
        machine = Machine(
            (log.action("a"), log.action("d", enabled=lambda s: True, drain=True)),
            rejects,
        )
        with self.assertRaises(Failed):
            steps(case, machine, self.options(case))
        self.assertNotIn("d", [event[0] for event in log.events])

    def test_options_with_clients_need_a_scheduler(self) -> None:
        """The reference runs a section only as tasks."""
        with self.assertRaises(ValueError):
            Options(clients=2)


@final
class DrainTest(unittest.TestCase):
    """The drain: drain actions until none is enabled or max steps ran."""

    def machine(self, log: Log, pending: list[int]) -> Machine:
        """Return a machine whose a adds one pending message and d delivers it."""

        def send(case: Case, client: int, value: object) -> None:
            log.action("a").run(case, client, value)
            pending[0] += 1

        def deliver(case: Case, client: int, value: object) -> None:
            log.action("d").run(case, client, value)
            pending[0] -= 1

        return Machine(
            (
                Action("a", send),
                Action("d", deliver, enabled=lambda state: pending[0] > 0, drain=True),
            ),
            counting(),
            invariant=lambda case, state: log.events.append(("invariant", state)),
        )

    def test_drain_steps_run_until_no_drain_action_is_enabled(self) -> None:
        """Two sends, then two deliveries, each an index without a flag."""
        log, pending = Log(), [0]
        case = replay(1, 0, 1, 0, 0)
        steps(case, self.machine(log, pending), Options(swarm=False))
        self.assertEqual(
            [step for _, step in case.steps],
            [Step("a"), Step("a"), Step("d", drain=True), Step("d", drain=True)],
        )
        self.assertEqual(case.requests[-1].bounds, IntegerBounds(0, 0))
        self.assertEqual(len(case.requests), 7)
        self.assertEqual(case.spans[-1], Span("d", 6, 7, 0, None))

    def test_the_check_and_the_invariant_follow_each_drain_step(self) -> None:
        """The invariant counts every call, through the drain."""
        log, pending = Log(), [0]
        steps(replay(1, 0, 1, 0, 0), self.machine(log, pending), Options(swarm=False))
        invariants = [event[1] for event in log.events if event[0] == "invariant"]
        self.assertEqual(invariants, [0, 1, 2, 3, 4, 4])

    def test_the_drain_stops_after_max_steps(self) -> None:
        """A drain action that is enabled in every state takes max steps."""
        log = Log()
        machine = Machine((log.action("d", drain=True),))
        case = replay(0)
        steps(case, machine, Options(swarm=False, max=3))
        self.assertEqual(case.steps, [(0, Step("d", drain=True))] * 3)


@final
class TraceTest(unittest.TestCase):
    """A case that follows a trace: its swarm, its steps and what it refuses."""

    def test_swarm_keeps_the_actions_the_steps_name(self) -> None:
        """The trace names b alone, so swarm disables a and c."""
        log = Log()
        case = Case(Tracing([Step("b")]))
        steps(case, Machine(tuple(log.action(name) for name in "abc")))
        self.assertEqual([c.value for c in case.choices], [0, 1, 0, 1, 0, 0])
        self.assertEqual(case.steps, [(0, Step("b"))])

    def test_a_trace_names_the_draws_of_each_step(self) -> None:
        """The input's draw takes its entry."""
        log = Log()
        case = Case(Tracing([Step("a"), Draw("v", 4), Step("a"), Draw("v", 6)]))
        steps(case, Machine((log.action("a", draws=True),)))
        self.assertEqual([event[2] for event in log.events if event[0] == "a"], [4, 6])

    def test_a_step_whose_action_is_not_enabled_raises(self) -> None:
        """Action a is never enabled."""
        case = Case(Tracing([Step("a")]))
        machine = Machine((Log().action("a", enabled=lambda state: False),))
        with self.assertRaises(TraceError) as caught:
            steps(case, machine)
        error = caught.exception
        self.assertEqual((error.entry, error.name, error.reason), (0, "a", "step"))

    def test_a_step_past_the_maximum_raises(self) -> None:
        """The second step of a machine with max 1."""
        case = Case(Tracing([Step("a"), Step("a")]))
        with self.assertRaises(TraceError) as caught:
            steps(case, Machine((Log().action("a"),)), Options(max=1))
        self.assertEqual(caught.exception.entry, 1)

    def test_a_concurrent_step_takes_its_client(self) -> None:
        """Client 2's step is listed first, and client 1 runs first."""
        log = Log()
        case = Case(Tracing([Step("a", client=2), Step("a", client=1)]))
        scheduler = Scheduler(case, Uniform())
        steps(
            case, Machine((log.action("a"),)), Options(clients=2, scheduler=scheduler)
        )
        self.assertEqual(
            case.steps, [(0, Step("a", client=2)), (0, Step("a", client=1))]
        )
        runs = [event[1] for event in log.events if event[0] == "a"]
        self.assertEqual(runs, [1, 2])

    def test_a_client_outside_the_clients_raises(self) -> None:
        """Client 3 of a section with two clients."""
        case = Case(Tracing([Step("a", client=3)]))
        options = Options(clients=2, scheduler=Scheduler(case, Uniform()))
        with self.assertRaises(TraceError):
            steps(case, Machine((Log().action("a"),)), options)

    def test_a_concurrent_step_where_no_section_runs_raises(self) -> None:
        """A machine with one client."""
        case = Case(Tracing([Step("a", client=1)]))
        with self.assertRaises(TraceError):
            steps(case, Machine((Log().action("a"),)))

    def test_a_drain_step_chooses_its_action_among_the_drain_actions(self) -> None:
        """Actions e and then d deliver the two messages that a sent."""
        pending = [0]
        log = Log()

        def send(case: Case, client: int, value: object) -> None:
            del case, client, value
            pending[0] += 2

        def deliver(name: str) -> Action:
            def run(case: Case, client: int, value: object) -> None:
                del case, client, value
                log.events.append((name,))
                pending[0] -= 1

            return Action(name, run, enabled=lambda state: pending[0] > 0, drain=True)

        trace = [Step("a"), Step("e", drain=True), Step("d", drain=True)]
        case = Case(Tracing(trace))
        steps(case, Machine((Action("a", send), deliver("d"), deliver("e"))))
        self.assertEqual(log.events, [("e",), ("d",)])

    def test_a_drain_step_after_the_drain_raises(self) -> None:
        """One message, and two drain steps."""
        pending = [0]

        def send(case: Case, client: int, value: object) -> None:
            del case, client, value
            pending[0] += 1

        def deliver(case: Case, client: int, value: object) -> None:
            del case, client, value
            pending[0] -= 1

        trace = [Step("a"), Step("d", drain=True), Step("d", drain=True)]
        machine = Machine(
            (
                Action("a", send),
                Action("d", deliver, enabled=lambda state: pending[0] > 0, drain=True),
            )
        )
        with self.assertRaises(TraceError) as caught:
            steps(Case(Tracing(trace)), machine)
        self.assertEqual((caught.exception.entry, caught.exception.name), (2, "d"))


@final
class ValidationTest(unittest.TestCase):
    """What actions, machines and options refuse."""

    def test_a_weight_below_1_raises(self) -> None:
        """Weight 0 would make an action that a random case never takes."""
        with self.assertRaises(ValueError):
            Action("a", lambda case, client, value: None, weight=0)

    def test_two_actions_with_one_name_raise(self) -> None:
        """A trace names an action by its name."""
        log = Log()
        with self.assertRaises(ValueError):
            Machine((log.action("a"), log.action("a")))

    def test_a_negative_count_or_no_client_raises(self) -> None:
        """The counts mean, max and concurrent are at least 0, and clients 1."""
        refusals: list[Callable[[], Options]] = [
            lambda: Options(mean=-1),
            lambda: Options(max=-1),
            lambda: Options(concurrent=-1),
            lambda: Options(clients=0),
        ]
        for refused in refusals:
            with self.assertRaises(ValueError):
                refused()
