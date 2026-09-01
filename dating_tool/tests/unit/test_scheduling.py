import threading
import math
import unittest

from aidating_eval.domain import CaseOutcome, CaseOutcomeStatus, RunContext, RunMode
from aidating_eval.runner import RunControl
from aidating_eval.scheduling import (
    BatchRunner,
    CreatePacer,
    EvaluationRequestGate,
    SharedCooldown,
    SlidingWindowRateLimiter,
    calculate_eval_budget,
)
from tests.helpers import FakeAdapter, FakeClock


class SchedulingTests(unittest.TestCase):
    def test_create_pacer_keeps_two_second_spacing(self):
        clock = FakeClock()
        pacer = CreatePacer(
            2.0, monotonic_fn=clock.monotonic, sleep_fn=clock.sleep
        )
        pacer.acquire()
        pacer.acquire()
        pacer.acquire()
        self.assertEqual([2.0, 2.0], clock.sleeps)

    def test_gateway_window_never_exceeds_120_calls(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(
            max_calls=120,
            period_seconds=60,
            monotonic_fn=clock.monotonic,
            sleep_fn=clock.sleep,
        )
        for _ in range(121):
            limiter.acquire()
        self.assertGreaterEqual(sum(clock.sleeps), 60)

    def test_server_retry_after_blocks_all_workers_and_is_clamped(self):
        clock = FakeClock()
        cooldown = SharedCooldown(
            monotonic_fn=clock.monotonic, sleep_fn=clock.sleep
        )
        cooldown.defer(500)
        cooldown.wait_if_needed()
        self.assertEqual([300], clock.sleeps)

    def test_non_finite_retry_after_uses_safe_default(self):
        clock = FakeClock()
        cooldown = SharedCooldown(
            monotonic_fn=clock.monotonic, sleep_fn=clock.sleep
        )
        cooldown.defer(math.nan)
        cooldown.wait_if_needed()
        self.assertEqual([300], clock.sleeps)

    def test_cooldown_registered_during_pacing_is_rechecked_before_admission(self):
        clock = FakeClock()
        entered_pacer = threading.Event()
        release_pacer = threading.Event()

        class BlockingPacer:
            def acquire(self):
                entered_pacer.set()
                self.assert_released = release_pacer.wait(timeout=2)

            def mark_admitted_now(self):
                return None

        gate = EvaluationRequestGate(
            SlidingWindowRateLimiter(
                max_calls=120,
                period_seconds=60,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            BlockingPacer(),
            SharedCooldown(
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
        )
        completed = threading.Event()

        def admit():
            gate.before_request(is_create=True)
            completed.set()

        worker = threading.Thread(target=admit)
        worker.start()
        self.assertTrue(entered_pacer.wait(timeout=2))
        gate.cooldown.defer(10)
        release_pacer.set()
        worker.join(timeout=2)

        self.assertTrue(completed.is_set())
        self.assertEqual([10], clock.sleeps)

    def test_rate_limit_wait_happens_before_final_create_spacing(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(
            max_calls=120,
            period_seconds=60,
            monotonic_fn=clock.monotonic,
            sleep_fn=clock.sleep,
        )
        for _ in range(120):
            limiter.acquire()
        gate = EvaluationRequestGate(
            limiter,
            CreatePacer(
                2,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            SharedCooldown(
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
        )

        admitted_at = []
        gate.before_request(is_create=True)
        admitted_at.append(clock.now)
        gate.before_request(is_create=True)
        admitted_at.append(clock.now)

        self.assertEqual([60, 62], admitted_at)

    def test_mixed_admission_preserves_sliding_window_at_boundary(self):
        clock = FakeClock()
        gate = EvaluationRequestGate(
            SlidingWindowRateLimiter(
                max_calls=2,
                period_seconds=60,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            CreatePacer(
                2,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            SharedCooldown(
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
        )

        admitted_at = []
        gate.before_request(is_create=True)
        admitted_at.append(clock.now)
        gate.before_request(is_create=True)
        admitted_at.append(clock.now)
        clock.sleep(58)
        gate.before_request(is_create=False)
        admitted_at.append(clock.now)
        gate.before_request(is_create=True)
        admitted_at.append(clock.now)

        self.assertEqual([0, 2, 60, 62], admitted_at)
        for index, end in enumerate(admitted_at):
            calls_in_window = [
                value
                for value in admitted_at[: index + 1]
                if end - 60 < value <= end
            ]
            self.assertLessEqual(len(calls_in_window), 2)

    def test_batch_runner_preserves_input_order_and_reuses_run_id(self):
        cases = [FakeAdapter.case(), FakeAdapter.case()]
        object.__setattr__(cases[0], "case_id", "case-a")
        object.__setattr__(cases[1], "case_id", "case-b")
        contexts: list[RunContext] = []

        class StubRunner:
            def execute(self, case, context):
                contexts.append(context)
                return CaseOutcome(
                    case.case_id,
                    CaseOutcomeStatus.COMPLETED,
                    f"task-{case.case_id}",
                    None,
                    "dating.relationship_analysis.v1",
                    None,
                )

        batch = BatchRunner(
            lambda _: StubRunner(),
            max_workers=2,
            create_pacer=CreatePacer.disabled(),
            run_control=RunControl(),
        )
        outcomes = batch.run(
            cases,
            lambda case: RunContext.for_case(
                "one-run", case.case_id, RunMode.EVAL, case.task_kind
            ),
        )
        self.assertEqual(["case-a", "case-b"], [item.case_id for item in outcomes])
        self.assertEqual({"one-run"}, {item.run_id for item in contexts})

    def test_batch_runner_does_not_start_case_after_stop(self):
        control = RunControl()
        control.request_stop("UNAUTHENTICATED")
        executed = threading.Event()

        class StubRunner:
            def execute(self, case, context):
                executed.set()
                raise AssertionError("停止后不得进入 CaseRunner")

        outcome = BatchRunner(
            lambda _: StubRunner(),
            max_workers=1,
            create_pacer=CreatePacer.disabled(),
            run_control=control,
        ).run(
            [FakeAdapter.case()],
            lambda case: FakeAdapter.context(),
        )[0]
        self.assertFalse(executed.is_set())
        self.assertEqual("RUN_STOP_REQUESTED", outcome.business_error_code)

    def test_eval_budget_includes_retry_and_idempotency_worst_case(self):
        normal = FakeAdapter.case()
        conflict = FakeAdapter.case()
        object.__setattr__(conflict, "case_id", "conflict")
        object.__setattr__(
            conflict,
            "negative_variant",
            __import__("aidating_eval.domain", fromlist=["NegativeVariant"]).NegativeVariant.IDEMPOTENCY_CONFLICT,
        )
        budget = calculate_eval_budget([normal, conflict], max_workers=3)
        self.assertEqual(2, budget.case_count)
        self.assertEqual(6, budget.worst_create_requests)
        self.assertGreater(budget.worst_input_bytes, 0)

    def test_batch_runner_rejects_more_than_five_workers(self):
        with self.assertRaises(ValueError):
            BatchRunner(
                lambda _: None,
                max_workers=6,
                create_pacer=CreatePacer.disabled(),
                run_control=RunControl(),
            )

    def test_budget_rejects_invalid_worker_count_even_without_running_batch(self):
        with self.assertRaises(Exception):
            calculate_eval_budget([FakeAdapter.case()], max_workers=0)


if __name__ == "__main__":
    unittest.main()
