import threading
import time
import unittest
from pathlib import Path

import numpy as np

from auto_titrator.auto_stop import (
    ABSOLUTE_PUMP_MAX_RUN_TIME_S,
    ABSOLUTE_PUMP_MAX_VOLUME_ML,
    AbsolutePumpSafetyGuard,
    ColorChangeAutoStopController,
    PersistentColorAutoStopDetector,
)


class FakeEstimator:
    classes_ = [0, 1]

    def __init__(self):
        self.n_jobs = -1

    def predict_proba(self, features):
        scores = np.asarray(
            [float(row.get("visible_test_signal") or 0.0) for row in features],
            dtype=float,
        )
        return np.column_stack([1.0 - scores, scores])


class BlockingEstimator(FakeEstimator):
    def __init__(self, blocked, release):
        super().__init__()
        self.blocked = blocked
        self.release = release
        self._blocked_once = False

    def predict_proba(self, features):
        if not self._blocked_once and any(
            float(row.get("visible_test_signal") or 0.0) >= 0.8 for row in features
        ):
            self._blocked_once = True
            self.blocked.set()
            if not self.release.wait(1.0):
                raise RuntimeError("test did not release blocked model")
        return super().predict_proba(features)


class FailingEstimator(FakeEstimator):
    def predict_proba(self, features):
        raise RuntimeError("live model crashed")


def fake_model():
    return {
        "feature_columns": ["visible_R_mean", "visible_test_signal", "titration_type"],
        "categorical_columns": ["titration_type"],
        "models": {
            "strong_acid_strong_base": {
                "estimator": FakeEstimator(),
                "selected_method_key": "fake:zone",
                "model_name": "fake",
            }
        },
    }


def color_row(
    elapsed_s,
    volume_ml,
    *,
    rgb=(120.0, 120.0, 120.0),
    hsv=(0.0, 0.05, 0.47),
    theoretical_ml=None,
    score=0.0,
):
    row = {
        "csv_recording_elapsed_s": elapsed_s,
        "injected_volume_ml": volume_ml,
        "visible_R_mean": rgb[0],
        "visible_G_mean": rgb[1],
        "visible_B_mean": rgb[2],
        "visible_H_mean": hsv[0],
        "visible_S_mean": hsv[1],
        "visible_V_mean": hsv[2],
        "signal": score,
        "visible_test_signal": score,
        "titration_type": "strong_acid_strong_base",
    }
    if theoretical_ml is not None:
        row["theoretical_equivalence_volume_ml"] = theoretical_ml
    return row


def acknowledged_test_firmware(command, state):
    """Return the exact acknowledgements required by the pump safety guard."""

    if command.startswith("G "):
        timeout_ms = int(command.split()[1])
        state["guard_timeout_ms"] = timeout_ms
        return f"GUARD ARMED {timeout_ms}"
    if command in {"a", "b"}:
        timeout_ms = state.get("guard_timeout_ms")
        return {"firmware_ack": f"PUMP RUNNING {command} {timeout_ms}"}
    if command == "c":
        state["guard_timeout_ms"] = None
        return {"firmware_ack": "PUMP STOPPED COMMAND"}
    raise AssertionError(f"unexpected firmware test command: {command!r}")


class AutoStopTests(unittest.TestCase):
    def make_detector(self, **overrides):
        settings = {
            "session_id": 3,
            "baseline_seconds": 0.2,
            "confirmation_delay_s": 0.3,
            "maximum_volume_ml": 100.0,
            "minimum_baseline_samples": 3,
            "minimum_color_distance": 0.015,
        }
        settings.update(overrides)
        return PersistentColorAutoStopDetector(**settings)

    def calibrate(self, detector):
        self.assertIsNone(detector.observe(color_row(0.0, 0.0)))
        self.assertIsNone(detector.observe(color_row(0.1, 0.1)))
        self.assertIsNone(detector.observe(color_row(0.2, 0.2)))
        self.assertTrue(detector.status()["auto_stop_baseline_ready"])

    def test_persistent_color_change_triggers_after_confirmation_delay(self):
        detector = self.make_detector()
        self.calibrate(detector)
        changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}

        self.assertIsNone(detector.observe(color_row(0.3, 0.3, **changed), endpoint_score=0.5))
        self.assertIsNone(detector.observe(color_row(0.45, 0.45, **changed), endpoint_score=0.1))
        decision = detector.observe(color_row(0.61, 0.61, **changed), endpoint_score=0.1)

        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "persistent_color_change")
        self.assertAlmostEqual(decision.color_change_started_volume_ml, 0.3)
        self.assertAlmostEqual(decision.trigger_volume_ml, 0.61)

    def test_short_color_flash_does_not_stop_pump(self):
        detector = self.make_detector()
        self.calibrate(detector)
        changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}

        self.assertIsNone(detector.observe(color_row(0.3, 0.3, **changed), endpoint_score=0.5))
        self.assertIsNone(detector.observe(color_row(0.35, 0.35)))
        self.assertIsNone(detector.observe(color_row(0.5, 0.5)))
        self.assertIsNone(detector.observe(color_row(0.7, 0.7)))

        self.assertFalse(detector.status()["auto_stop_color_change_pending"])

    def test_color_change_waits_for_live_endpoint_model_confirmation(self):
        detector = self.make_detector()
        self.calibrate(detector)
        changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}

        for elapsed in (0.3, 0.5, 0.7, 0.9):
            self.assertIsNone(detector.observe(color_row(elapsed, elapsed, **changed), endpoint_score=0.1))

        self.assertFalse(detector.status()["auto_stop_color_change_pending"])

    def test_brightness_only_change_is_not_treated_as_indicator_color(self):
        detector = self.make_detector()
        self.calibrate(detector)
        bright = {"rgb": (150.0, 150.0, 150.0), "hsv": (0.0, 0.05, 0.59)}

        for elapsed in (0.3, 0.45, 0.61, 0.8):
            self.assertIsNone(detector.observe(color_row(elapsed, elapsed, **bright), endpoint_score=0.8))

        self.assertFalse(detector.status()["auto_stop_color_change_pending"])

    def test_theoretical_equivalence_value_does_not_gate_color_stop(self):
        detector = self.make_detector()
        self.calibrate(detector)
        changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}

        self.assertIsNone(
            detector.observe(color_row(0.3, 0.3, theoretical_ml=90.0, **changed), endpoint_score=0.5)
        )
        self.assertIsNone(
            detector.observe(color_row(0.45, 0.45, theoretical_ml=90.0, **changed), endpoint_score=0.1)
        )
        decision = detector.observe(
            color_row(0.61, 0.61, theoretical_ml=90.0, **changed), endpoint_score=0.1
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "persistent_color_change")

    def test_missing_color_breaks_confirmation_continuity(self):
        detector = self.make_detector(confirmation_delay_s=0.4)
        self.calibrate(detector)
        changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}

        self.assertIsNone(detector.observe(color_row(0.3, 0.3, **changed), endpoint_score=0.8))
        missing = color_row(0.5, 0.5, **changed)
        del missing["visible_H_mean"]
        self.assertIsNone(detector.observe(missing, endpoint_score=0.8))
        self.assertIsNone(detector.observe(color_row(0.71, 0.71, **changed), endpoint_score=0.8))

        self.assertTrue(detector.status()["auto_stop_color_change_pending"])
        self.assertEqual(detector.status()["auto_stop_missing_color_samples"], 1)

    def test_excessive_timestamp_gap_restarts_confirmation_window(self):
        detector = self.make_detector(confirmation_delay_s=0.4, maximum_sample_gap_s=0.2)
        self.calibrate(detector)
        changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}

        self.assertIsNone(detector.observe(color_row(0.3, 0.3, **changed), endpoint_score=0.8))
        self.assertIsNone(detector.observe(color_row(0.71, 0.71, **changed), endpoint_score=0.8))

        status = detector.status()
        self.assertTrue(status["auto_stop_color_change_pending"])
        self.assertEqual(status["auto_stop_color_change_elapsed_s"], 0.0)

    def test_detector_hard_stops_at_physical_maximum_volume(self):
        detector = self.make_detector(maximum_volume_ml=10.0)

        decision = detector.observe(color_row(0.0, 10.0))

        self.assertEqual(decision.reason, "safety_maximum_volume")
        self.assertEqual(decision.trigger_volume_ml, 10.0)

    def test_detector_status_exposes_latest_observation_for_pulse_scheduler(self):
        detector = self.make_detector()

        detector.observe(color_row(2.5, 1.25), endpoint_score=0.42)
        status = detector.status()

        self.assertEqual(status["auto_stop_observation_elapsed_s"], 0.0)
        self.assertEqual(status["auto_stop_observation_volume_ml"], 1.25)

    def test_background_controller_arms_without_target_volume_and_stops_on_color(self):
        triggered = []
        event = threading.Event()

        def on_trigger(decision):
            triggered.append(decision)
            event.set()

        model = fake_model()
        controller = ColorChangeAutoStopController(model, on_trigger=on_trigger, sample_interval_s=0.01)
        try:
            armed = controller.arm(
                session_id=7,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
                confirmation_delay_s=0.2,
            )
            for index in range(9):
                controller.submit(7, color_row(index * 0.15, index * 0.15))
                time.sleep(0.02)
            changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}
            for index, elapsed in enumerate((1.25, 1.36, 1.48, 1.6)):
                controller.submit(7, color_row(elapsed, elapsed, score=0.8 if index == 0 else 0.1, **changed))
                time.sleep(0.02)
            self.assertTrue(event.wait(1.0))
        finally:
            controller.close()

        self.assertEqual(armed["auto_stop_state"], "armed_calibrating")
        self.assertEqual(triggered[0].reason, "persistent_color_change")
        self.assertEqual(model["models"]["strong_acid_strong_base"]["estimator"].n_jobs, 1)

    def test_controller_rejects_invalid_color_stop_settings(self):
        controller = ColorChangeAutoStopController(fake_model(), on_trigger=lambda decision: None)
        try:
            status = controller.arm(
                session_id=8,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
                confirmation_delay_s=0.0,
            )
        finally:
            controller.close()

        self.assertEqual(status["auto_stop_state"], "unavailable")
        self.assertEqual(status["auto_stop_reason"], "invalid_color_stop_settings")

    def test_controller_queue_drop_cannot_satisfy_confirmation_time(self):
        triggered = []
        blocked = threading.Event()
        release = threading.Event()
        model = fake_model()
        model["models"]["strong_acid_strong_base"]["estimator"] = BlockingEstimator(
            blocked, release
        )
        controller = ColorChangeAutoStopController(
            model,
            on_trigger=triggered.append,
            sample_interval_s=0.01,
        )

        def wait_for_elapsed(expected):
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if controller.status().get("auto_stop_observation_elapsed_s") == expected:
                    return
                time.sleep(0.005)
            self.fail(f"controller did not process elapsed={expected}: {controller.status()}")

        try:
            controller.arm(
                session_id=9,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
                confirmation_delay_s=0.4,
            )
            for elapsed in (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.05):
                controller.submit(9, color_row(elapsed, elapsed))
                wait_for_elapsed(elapsed)

            changed = {"rgb": (180.0, 95.0, 130.0), "hsv": (335.0, 0.47, 0.71)}
            controller.submit(9, color_row(1.2, 1.2, score=0.8, **changed))
            self.assertTrue(blocked.wait(1.0))
            controller.submit(9, color_row(1.35, 1.35, score=0.8, **changed))
            controller.submit(9, color_row(1.65, 1.65, score=0.8, **changed))
            release.set()
            wait_for_elapsed(1.65)

            self.assertEqual(triggered, [])
            self.assertEqual(controller.status()["auto_stop_color_change_elapsed_s"], 0.0)
        finally:
            release.set()
            controller.close()

    def test_model_failure_is_diagnostic_before_pump_then_fails_closed_after_start(self):
        triggered = []
        event = threading.Event()

        def on_trigger(decision):
            triggered.append(decision)
            event.set()

        unsafe_model = fake_model()
        unsafe_model["feature_columns"] = ["signal", "titration_type"]
        controller = ColorChangeAutoStopController(
            unsafe_model,
            on_trigger=on_trigger,
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=11,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
                confirmation_delay_s=0.2,
                maximum_volume_ml=2.0,
            )
            for elapsed in (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.05):
                controller.submit(11, color_row(elapsed, 0.0))
                time.sleep(0.02)

            self.assertEqual(triggered, [])
            status = controller.status()
            self.assertEqual(status["auto_stop_state"], "armed_safety_only")
            self.assertEqual(status["auto_stop_reason"], "model_score_failed_maximum_only")
            self.assertIn("forbidden hardware-control model feature", status["auto_stop_error"])

            controller.submit(11, color_row(1.2, 0.1, score=0.9))
            self.assertTrue(event.wait(1.0))
        finally:
            controller.close()

        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0].reason, "model_score_failed")
        self.assertFalse(controller.status()["auto_stop_armed"])
        self.assertIn(
            "forbidden hardware-control model feature",
            controller.status()["auto_stop_error"],
        )

    def test_missing_required_color_after_pump_start_triggers_existing_stop_path(self):
        events = []
        triggered = threading.Event()

        def on_status(status):
            if status["auto_stop_state"] == "triggered":
                events.append("pulse_disarmed")

        def on_trigger(decision):
            events.append("c")
            events.append(decision.reason)
            triggered.set()

        controller = ColorChangeAutoStopController(
            fake_model(),
            on_trigger=on_trigger,
            on_status=on_status,
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=12,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            missing = color_row(0.1, 0.01)
            del missing["visible_H_mean"]
            controller.submit(12, missing)
            self.assertTrue(triggered.wait(1.0))
            status = controller.status()
        finally:
            controller.close()

        self.assertEqual(events, ["pulse_disarmed", "c", "required_color_missing"])
        self.assertEqual(status["auto_stop_state"], "triggered")
        self.assertFalse(status["auto_stop_armed"])
        self.assertIn("visible ROI color", status["auto_stop_error"])

    def test_missing_required_pump_telemetry_after_start_fails_closed(self):
        triggered = []
        event = threading.Event()
        controller = ColorChangeAutoStopController(
            fake_model(),
            on_trigger=lambda decision: (triggered.append(decision), event.set()),
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=17,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            missing_time = color_row(0.1, 0.01)
            del missing_time["csv_recording_elapsed_s"]
            missing_time["pump_state"] = "running"
            controller.submit(17, missing_time)
            self.assertTrue(event.wait(1.0))
            status = controller.status()
        finally:
            controller.close()

        self.assertEqual(triggered[0].reason, "required_sensor_missing")
        self.assertIn("elapsed time", status["auto_stop_error"])
        self.assertFalse(status["auto_stop_armed"])

    def test_submit_sticky_fault_survives_latest_normal_row_and_stops_once(self):
        blocked = threading.Event()
        release = threading.Event()
        triggered = []
        event = threading.Event()
        model = fake_model()
        model["models"]["strong_acid_strong_base"]["estimator"] = BlockingEstimator(
            blocked, release
        )
        controller = ColorChangeAutoStopController(
            model,
            on_trigger=lambda decision: (triggered.append(decision), event.set()),
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=18,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            controller.submit(18, color_row(0.1, 0.01, score=0.8))
            self.assertTrue(blocked.wait(1.0))

            missing = color_row(0.2, 0.02)
            del missing["visible_H_mean"]
            self.assertTrue(controller.submit(18, missing))
            self.assertFalse(controller.submit(18, color_row(0.3, 0.03)))
            self.assertTrue(controller.submit(18, missing))

            release.set()
            self.assertTrue(event.wait(1.0))
            time.sleep(0.05)
            status = controller.status()
        finally:
            release.set()
            controller.close()

        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0].reason, "required_color_missing")
        self.assertEqual(status["auto_stop_reason"], "required_color_missing")

    def test_disarm_rearm_discards_sticky_fault_from_old_generation(self):
        blocked = threading.Event()
        release = threading.Event()
        triggered = []
        model = fake_model()
        model["models"]["strong_acid_strong_base"]["estimator"] = BlockingEstimator(
            blocked, release
        )
        controller = ColorChangeAutoStopController(
            model,
            on_trigger=triggered.append,
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=19,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            controller.submit(19, color_row(0.1, 0.01, score=0.8))
            self.assertTrue(blocked.wait(1.0))
            missing = color_row(0.2, 0.02)
            del missing["injected_volume_ml"]
            missing["pump_state"] = "running"
            controller.submit(19, missing)

            controller.disarm("test_generation_change")
            controller.arm(
                session_id=20,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            release.set()
            time.sleep(0.05)
            controller.submit(20, color_row(0.0, 0.0))
            deadline = time.monotonic() + 1.0
            while controller.status()["auto_stop_baseline_samples"] < 1:
                if time.monotonic() >= deadline:
                    self.fail(f"re-armed observation was not processed: {controller.status()}")
                time.sleep(0.005)
            status = controller.status()
        finally:
            release.set()
            controller.close()

        self.assertEqual(triggered, [])
        self.assertEqual(status["auto_stop_session_id"], 20)
        self.assertTrue(status["auto_stop_armed"])

    def test_missing_required_input_before_pump_remains_baseline_only(self):
        triggered = []
        controller = ColorChangeAutoStopController(
            fake_model(),
            on_trigger=triggered.append,
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=21,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            missing = color_row(0.0, 0.0)
            del missing["visible_H_mean"]
            self.assertTrue(controller.submit(21, missing))
            time.sleep(0.05)
            status = controller.status()
        finally:
            controller.close()

        self.assertEqual(triggered, [])
        self.assertTrue(status["auto_stop_armed"])
        self.assertEqual(status["auto_stop_state"], "armed_calibrating")

    def test_unexpected_model_exception_after_pump_start_fails_closed(self):
        model = fake_model()
        model["models"]["strong_acid_strong_base"]["estimator"] = FailingEstimator()
        triggered = []
        event = threading.Event()
        controller = ColorChangeAutoStopController(
            model,
            on_trigger=lambda decision: (triggered.append(decision), event.set()),
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=13,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            controller.submit(13, color_row(0.1, 0.01))
            self.assertTrue(event.wait(1.0))
            status = controller.status()
        finally:
            controller.close()

        self.assertEqual(triggered[0].reason, "model_score_failed")
        self.assertIn("live model crashed", status["auto_stop_error"])

    def test_disarm_invalidates_in_flight_observation_before_publish_or_trigger(self):
        blocked = threading.Event()
        release = threading.Event()
        statuses = []
        triggered = []
        model = fake_model()
        model["models"]["strong_acid_strong_base"]["estimator"] = BlockingEstimator(
            blocked, release
        )
        controller = ColorChangeAutoStopController(
            model,
            on_trigger=triggered.append,
            on_status=statuses.append,
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=14,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            controller.submit(14, color_row(0.1, 0.01, score=0.8))
            self.assertTrue(blocked.wait(1.0))
            controller.disarm("test_disarm")
            status_count = len(statuses)
            release.set()
            time.sleep(0.05)
        finally:
            release.set()
            controller.close()

        self.assertEqual(triggered, [])
        self.assertEqual(len(statuses), status_count)
        self.assertEqual(statuses[-1]["auto_stop_reason"], "test_disarm")

    def test_rearm_invalidates_in_flight_observation_generation(self):
        blocked = threading.Event()
        release = threading.Event()
        statuses = []
        triggered = []
        model = fake_model()
        model["models"]["strong_acid_strong_base"]["estimator"] = BlockingEstimator(
            blocked, release
        )
        controller = ColorChangeAutoStopController(
            model,
            on_trigger=triggered.append,
            on_status=statuses.append,
            sample_interval_s=0.01,
        )
        try:
            controller.arm(
                session_id=15,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            controller.submit(15, color_row(0.1, 0.01, score=0.8))
            self.assertTrue(blocked.wait(1.0))
            controller.arm(
                session_id=16,
                requested=True,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            rearm_status_index = len(statuses) - 1
            release.set()
            time.sleep(0.05)
            controller.submit(16, color_row(0.0, 0.0))
            deadline = time.monotonic() + 1.0
            while controller.status()["auto_stop_baseline_samples"] < 1:
                if time.monotonic() >= deadline:
                    self.fail(f"re-armed observation was not processed: {controller.status()}")
                time.sleep(0.005)
        finally:
            release.set()
            controller.close()

        self.assertEqual(triggered, [])
        self.assertTrue(
            all(status["auto_stop_session_id"] == 16 for status in statuses[rearm_status_index:])
        )


class AbsolutePumpSafetyGuardTests(unittest.TestCase):
    def wait_for_state(self, guard, expected, timeout_s=1.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = guard.status()
            if status["absolute_guard_state"] == expected:
                return status
            time.sleep(0.005)
        self.fail(f"guard did not reach {expected!r}: {guard.status()}")

    def test_disabled_optional_auto_stop_does_not_disable_absolute_guard(self):
        optional = ColorChangeAutoStopController(None, on_trigger=lambda decision: None)
        commands = []
        firmware_state = {}

        def sender(command):
            commands.append(command)
            return acknowledged_test_firmware(command, firmware_state)

        guard = AbsolutePumpSafetyGuard(sender, watchdog_interval_s=0.002)
        try:
            optional_status = optional.arm(
                session_id=10,
                requested=False,
                recording_started=True,
                titration_type="strong_acid_strong_base",
            )
            started = guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_volume_ml=1.0,
                requested_maximum_run_time_s=0.025,
            )
            triggered = self.wait_for_state(guard, "triggered")
        finally:
            guard.close()
            optional.close()

        self.assertEqual(optional_status["auto_stop_state"], "disabled")
        self.assertEqual(started["absolute_guard_state"], "armed_running")
        self.assertEqual(triggered["absolute_guard_reason"], "absolute_deadline_reached")
        self.assertEqual(commands, ["G 25\n", "b", "c"])

    def test_stalled_camera_telemetry_still_stops_on_monotonic_deadline(self):
        stopped = threading.Event()
        firmware_state = {}

        def sender(command):
            if command == "c":
                stopped.set()
            return acknowledged_test_firmware(command, firmware_state)

        guard = AbsolutePumpSafetyGuard(sender, watchdog_interval_s=0.002)
        try:
            guard.start(
                direction_command="a",
                maximum_pump_rate_ml_per_s=0.5,
                requested_maximum_volume_ml=5.0,
                requested_maximum_run_time_s=0.02,
            )
            # No camera rows, pump elapsed rows, or volume updates are submitted.
            self.assertTrue(stopped.wait(1.0))
            status = self.wait_for_state(guard, "triggered")
        finally:
            guard.close()

        self.assertFalse(status["absolute_guard_armed"])
        self.assertEqual(status["absolute_guard_stop_status"], "sent")

    def test_oversized_client_limits_are_clamped_to_application_maxima(self):
        commands = []
        firmware_state = {}

        def sender(command):
            commands.append(command)
            return acknowledged_test_firmware(command, firmware_state)

        guard = AbsolutePumpSafetyGuard(sender)
        try:
            status = guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=0.5,
                requested_maximum_volume_ml=ABSOLUTE_PUMP_MAX_VOLUME_ML * 10,
                requested_maximum_run_time_s=ABSOLUTE_PUMP_MAX_RUN_TIME_S * 10,
            )
            guard.stop()
        finally:
            guard.close()

        self.assertTrue(status["absolute_guard_limits_clamped"])
        self.assertEqual(
            status["absolute_guard_effective_maximum_volume_ml"],
            ABSOLUTE_PUMP_MAX_VOLUME_ML,
        )
        self.assertEqual(
            status["absolute_guard_effective_maximum_run_time_s"],
            ABSOLUTE_PUMP_MAX_RUN_TIME_S,
        )
        self.assertEqual(commands[:2], ["G 120000\n", "b"])

    def test_missing_firmware_guard_ack_fails_closed_before_start(self):
        commands = []

        def sender(command):
            commands.append(command)
            return None

        guard = AbsolutePumpSafetyGuard(sender)
        try:
            status = guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=1.0,
            )
        finally:
            guard.close()

        self.assertEqual(status["absolute_guard_state"], "error")
        self.assertEqual(status["absolute_guard_reason"], "guard_arm_or_start_failed")
        self.assertEqual(status["absolute_guard_stop_status"], "sent")
        self.assertEqual(commands, ["G 1000\n", "c"])

    def test_stop_cancels_arming_before_direction_command_without_g_c_b_race(self):
        commands = []
        guard_entered = threading.Event()
        release_guard = threading.Event()
        firmware_state = {}

        def sender(command):
            commands.append(command)
            if command.startswith("G "):
                guard_entered.set()
                self.assertTrue(release_guard.wait(1.0))
            return acknowledged_test_firmware(command, firmware_state)

        guard = AbsolutePumpSafetyGuard(sender)
        start_thread = threading.Thread(
            target=lambda: guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=1.0,
            )
        )
        stop_thread = threading.Thread(target=guard.stop)
        try:
            start_thread.start()
            self.assertTrue(guard_entered.wait(1.0))
            stop_thread.start()
            self.wait_for_state(guard, "stopping")
            release_guard.set()
            start_thread.join(1.0)
            stop_thread.join(1.0)
        finally:
            release_guard.set()
            guard.close()

        self.assertFalse(start_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(commands, ["G 1000\n", "c"])
        self.assertEqual(guard.status()["absolute_guard_state"], "stopped")

    def test_guard_cancels_generation_before_emergency_c_can_be_overtaken(self):
        commands = []
        guard_command_entered = threading.Event()
        release_guard_ack = threading.Event()
        emergency_written = threading.Event()
        release_emergency_return = threading.Event()
        start_result = {}
        stop_result = {}

        def sender(command):
            commands.append(command)
            if command.startswith("G "):
                guard_command_entered.set()
                self.assertTrue(release_guard_ack.wait(2.0))
                return "GUARD ARMED 1000"
            if command == "b":
                return "PUMP RUNNING b 1000"
            if command == "c":
                return "PUMP STOPPED COMMAND"
            raise AssertionError(command)

        def emergency_stop():
            commands.append("EMERGENCY_C")
            emergency_written.set()
            self.assertTrue(release_emergency_return.wait(2.0))

        guard = AbsolutePumpSafetyGuard(sender)
        start_thread = threading.Thread(
            target=lambda: start_result.setdefault(
                "status",
                guard.start(
                    direction_command="b",
                    maximum_pump_rate_ml_per_s=1.0,
                    requested_maximum_run_time_s=1.0,
                ),
            ),
            daemon=True,
        )
        stop_thread = threading.Thread(
            target=lambda: stop_result.setdefault(
                "status",
                guard.stop("concurrent_stop", emergency_stop=emergency_stop),
            ),
            daemon=True,
        )
        start_thread.start()
        try:
            self.assertTrue(guard_command_entered.wait(1.0))
            stop_thread.start()
            self.assertTrue(emergency_written.wait(1.0))
            # Let G return while emergency c is already on the wire but before
            # stop() waits for the acknowledged c command lock.
            release_guard_ack.set()
            start_thread.join(timeout=1.0)
            self.assertFalse(start_thread.is_alive())
            self.assertNotIn("b", commands)
        finally:
            release_guard_ack.set()
            release_emergency_return.set()
            start_thread.join(timeout=2.0)
            stop_thread.join(timeout=2.0)
            guard.close()

        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(commands, ["G 1000\n", "EMERGENCY_C", "c"])
        self.assertFalse(start_result["status"]["absolute_guard_armed"])
        self.assertEqual(stop_result["status"]["absolute_guard_state"], "stopped")

    def test_guarded_direction_write_cannot_be_overtaken_after_final_predicate_check(self):
        commands = []
        wire_write_lock = threading.Lock()
        predicate_checked = threading.Event()
        release_direction_write = threading.Event()
        emergency_written = threading.Event()
        start_result = {}
        stop_result = {}

        def sender(command):
            commands.append(command)
            if command == "G 1000\n":
                return "GUARD ARMED 1000"
            if command == "c":
                return "PUMP STOPPED COMMAND"
            raise AssertionError(command)

        def guarded_direction(command, can_send):
            with wire_write_lock:
                allowed = can_send()
                predicate_checked.set()
                self.assertTrue(release_direction_write.wait(2.0))
                if not allowed:
                    return {"direction_cancelled": True}
                commands.append(command)
            return "PUMP RUNNING b 1000"

        def emergency_stop():
            with wire_write_lock:
                commands.append("EMERGENCY_C")
                emergency_written.set()

        guard = AbsolutePumpSafetyGuard(
            sender,
            direction_sender=guarded_direction,
        )
        start_thread = threading.Thread(
            target=lambda: start_result.setdefault(
                "status",
                guard.start(
                    direction_command="b",
                    maximum_pump_rate_ml_per_s=1.0,
                    requested_maximum_run_time_s=1.0,
                ),
            ),
            daemon=True,
        )
        stop_thread = threading.Thread(
            target=lambda: stop_result.setdefault(
                "status",
                guard.stop("race_after_predicate", emergency_stop=emergency_stop),
            ),
            daemon=True,
        )
        start_thread.start()
        try:
            self.assertTrue(predicate_checked.wait(1.0))
            stop_thread.start()
            self.wait_for_state(guard, "stopping")
            # stop() has cancelled the generation, but its emergency c must
            # wait behind the already-authorized atomic direction byte write.
            release_direction_write.set()
            self.assertTrue(emergency_written.wait(1.0))
        finally:
            release_direction_write.set()
            start_thread.join(2.0)
            stop_thread.join(2.0)
            guard.close()

        self.assertFalse(start_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(commands, ["G 1000\n", "b", "EMERGENCY_C", "c"])
        self.assertEqual(stop_result["status"]["absolute_guard_state"], "stopped")

    def test_external_restart_predicate_cancels_after_guard_ack_before_direction(self):
        commands = []
        restart_allowed = {"value": True}

        def sender(command):
            commands.append(command)
            if command == "G 1000\n":
                restart_allowed["value"] = False
                return "GUARD ARMED 1000"
            if command == "c":
                return "PUMP STOPPED COMMAND"
            raise AssertionError(command)

        def guarded_direction(command, can_send):
            if not can_send():
                return {"direction_cancelled": True, "direction_written": False}
            commands.append(command)
            return "PUMP RUNNING b 1000"

        guard = AbsolutePumpSafetyGuard(sender, direction_sender=guarded_direction)
        try:
            status = guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=1.0,
                can_start_direction=lambda: restart_allowed["value"],
            )
        finally:
            guard.close()

        self.assertEqual(commands, ["G 1000\n", "c"])
        self.assertFalse(status["absolute_guard_armed"])

    def test_absolute_deadline_recomputes_guard_timeout_at_send_time(self):
        clock = {"now": 15.0}
        commands = []

        def sender(command):
            commands.append(command)
            if command == "G 5000\n":
                clock["now"] = 16.0
                return "GUARD ARMED 5000"
            if command == "c":
                return "PUMP STOPPED COMMAND"
            raise AssertionError(command)

        def direction_sender(command, can_send):
            self.assertTrue(can_send())
            commands.append(command)
            return {
                "firmware_ack": "PUMP RUNNING b 5000",
                "direction_written_monotonic_s": clock["now"],
            }

        guard = AbsolutePumpSafetyGuard(
            sender, direction_sender=direction_sender,
            monotonic=lambda: clock["now"], watchdog_interval_s=1.0,
        )
        try:
            status = guard.start(
                direction_command="b", maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=120.0,
                absolute_deadline_monotonic_s=20.0,
            )
        finally:
            guard.stop("test")
            guard.close()

        self.assertEqual(commands[:2], ["G 5000\n", "b"])
        self.assertEqual(status["absolute_guard_deadline_monotonic_s"], 20.0)
        self.assertEqual(status["direction_written_monotonic_s"], 16.0)

    def test_guard_ack_blocking_past_absolute_deadline_never_writes_direction(self):
        clock = {"now": 10.0}
        commands = []

        def sender(command):
            commands.append(command)
            if command == "G 2000\n":
                clock["now"] = 12.1
                return "GUARD ARMED 2000"
            if command == "c":
                return "PUMP STOPPED COMMAND"
            raise AssertionError(command)

        guard = AbsolutePumpSafetyGuard(sender, monotonic=lambda: clock["now"])
        try:
            status = guard.start(
                direction_command="b", maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=120.0,
                absolute_deadline_monotonic_s=12.0,
            )
        finally:
            guard.close()

        self.assertEqual(commands, ["G 2000\n", "c"])
        self.assertFalse(status["absolute_guard_armed"])

    def test_deadline_stop_command_failure_is_exposed(self):
        firmware_state = {}

        def sender(command):
            if command == "c":
                raise OSError("serial link lost")
            return acknowledged_test_firmware(command, firmware_state)

        guard = AbsolutePumpSafetyGuard(sender, watchdog_interval_s=0.002)
        try:
            guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=0.015,
            )
            status = self.wait_for_state(guard, "stop_unconfirmed")
        finally:
            guard.close()

        self.assertEqual(status["absolute_guard_reason"], "possibly_running")
        self.assertEqual(status["absolute_guard_stop_status"], "failed")
        self.assertTrue(status["absolute_guard_armed"])
        self.assertTrue(status["absolute_guard_possibly_running"])
        self.assertIn("serial link lost", status["absolute_guard_error"])

    def test_monotonic_clock_failure_requests_immediate_stop(self):
        commands = []
        clock_calls = 0
        firmware_state = {}

        def clock():
            nonlocal clock_calls
            clock_calls += 1
            if clock_calls <= 4:
                return 10.0
            raise RuntimeError("clock unavailable")

        def sender(command):
            commands.append(command)
            return acknowledged_test_firmware(command, firmware_state)

        guard = AbsolutePumpSafetyGuard(sender, monotonic=clock, watchdog_interval_s=0.002)
        try:
            guard.start(
                direction_command="a",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=10.0,
            )
            status = self.wait_for_state(guard, "triggered")
        finally:
            guard.close()

        self.assertEqual(status["absolute_guard_reason"], "host_monotonic_clock_failed")
        self.assertIn("clock unavailable", status["absolute_guard_error"])
        self.assertEqual(commands[-1], "c")

    def test_direction_acknowledgement_must_match_guard_deadline(self):
        commands = []

        def sender(command):
            commands.append(command)
            if command.startswith("G "):
                return f"GUARD ARMED {int(command.split()[1])}"
            if command == "b":
                return {"firmware_ack": "PUMP RUNNING b 120000"}
            if command == "c":
                return {"firmware_ack": "PUMP STOPPED COMMAND"}
            raise AssertionError(command)

        guard = AbsolutePumpSafetyGuard(sender)
        try:
            status = guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_run_time_s=2.5,
            )
        finally:
            guard.close()

        self.assertEqual(status["absolute_guard_state"], "error")
        self.assertEqual(status["absolute_guard_reason"], "guard_arm_or_start_failed")
        self.assertIn("direction and guard deadline", status["absolute_guard_error"])
        self.assertEqual(commands, ["G 2500\n", "b", "c"])


class FirmwareAbsoluteGuardContractTests(unittest.TestCase):
    def test_firmware_has_independent_bounded_deadline_and_compatible_stops(self):
        firmware = (
            Path(__file__).parents[1]
            / "auto_titrator"
            / "arduino_stepper"
            / "arduino_stepper.ino"
        ).read_text(encoding="utf-8")

        self.assertIn("ABSOLUTE_MAX_RUN_TIME_MS = 120000UL", firmware)
        self.assertIn("min(requestedMs, ABSOLUTE_MAX_RUN_TIME_MS)", firmware)
        self.assertIn("(unsigned long)(millis() - runStartedMs)", firmware)
        self.assertIn('strcmp(commandBuffer, "STOP") == 0', firmware)
        self.assertIn("if (cmd == 'c')", firmware)
        self.assertIn('stopPump("ABSOLUTE_TIMEOUT")', firmware)
        self.assertIn('"GUARD ARMED "', firmware)


if __name__ == "__main__":
    unittest.main()
