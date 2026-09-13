import unittest

from auto_titrator.pulse_control import (
    PulseControlConfig,
    PulseController,
    PulseObservation,
    PulseState,
    simulate_trace,
)


def config(**overrides):
    values = {
        "approach_score": 0.6,
        "endpoint_score": 0.9,
        "confirmation_duration_s": 0.4,
        "pulse_steps": 10,
        "settle_time_s": 0.5,
        "max_volume_ml": 1.0,
        "ml_per_step": 0.01,
        "fast_rate_ml_per_s": 0.2,
    }
    values.update(overrides)
    return PulseControlConfig(**values)


def observation(now_s, score, volume=0.0, **kwargs):
    return PulseObservation(now_s, score, volume, **kwargs)


class PulseControllerTests(unittest.TestCase):
    def test_fast_to_wait_to_inject_to_wait_and_confirmed_stop(self):
        controller = PulseController(config())

        self.assertEqual(controller.start().intents[0].command, "RUN_RATE 0.2")
        self.assertEqual(controller.update(observation(0.2, 0.5)).state, PulseState.FAST_CONTINUOUS)

        approach = controller.update(observation(0.3, 0.7, 0.05))
        self.assertEqual(approach.state, PulseState.PULSE_WAIT)
        self.assertEqual([intent.command for intent in approach.intents], ["STOP"])

        self.assertEqual(controller.update(observation(0.7, 0.8, 0.05)).reason, "settling")
        pulse = controller.update(observation(0.8, 0.8, 0.05))
        self.assertEqual(pulse.state, PulseState.PULSE_INJECT)
        self.assertEqual([intent.command for intent in pulse.intents], ["STEP 10"])

        in_progress = controller.update(observation(0.9, 0.95, 0.10))
        self.assertEqual(in_progress.reason, "pulse_in_progress")
        self.assertEqual(in_progress.intents, ())
        complete = controller.update(observation(1.0, 0.95, 0.15, pulse_complete=True))
        self.assertEqual(complete.state, PulseState.PULSE_WAIT)

        stopped = controller.update(observation(1.4, 0.95, 0.15))
        self.assertEqual(stopped.state, PulseState.STOPPED)
        self.assertEqual(stopped.reason, "endpoint_confirmed")
        self.assertEqual([intent.command for intent in stopped.intents], ["STOP"])

    def test_endpoint_confirmation_resets_when_score_drops(self):
        controller = PulseController(config(confirmation_duration_s=0.5, settle_time_s=2.0))
        controller.start()
        controller.update(observation(0.1, 0.95))
        controller.update(observation(0.4, 0.95))

        reset = controller.update(observation(0.5, 0.89))
        self.assertIsNone(reset.endpoint_confirmation_started_s)
        controller.update(observation(0.7, 0.95))
        not_yet = controller.update(observation(1.1, 0.95))
        self.assertEqual(not_yet.state, PulseState.PULSE_WAIT)
        stopped = controller.update(observation(1.2, 0.95))
        self.assertEqual(stopped.state, PulseState.STOPPED)

    def test_external_confirmation_mode_keeps_pulsing_without_model_only_stop(self):
        controller = PulseController(
            config(
                endpoint_confirmation_enabled=False,
                endpoint_score=0.7,
                confirmation_duration_s=0.0,
            )
        )
        controller.start()

        approach = controller.update(observation(0.1, 1.0, 0.01))
        pulse = controller.update(observation(0.6, 1.0, 0.01))

        self.assertEqual(approach.state, PulseState.PULSE_WAIT)
        self.assertEqual([intent.command for intent in approach.intents], ["STOP"])
        self.assertEqual(pulse.state, PulseState.PULSE_INJECT)
        self.assertEqual([intent.command for intent in pulse.intents], ["STEP 10"])
        self.assertIsNone(pulse.endpoint_confirmation_started_s)

    def test_maximum_volume_stops_at_limit_and_before_oversized_pulse(self):
        at_limit = PulseController(config())
        at_limit.start()
        stopped = at_limit.update(observation(0.1, 0.2, 1.0))
        self.assertEqual(stopped.reason, "maximum_volume_reached")
        self.assertEqual([intent.command for intent in stopped.intents], ["STOP"])

        projected = PulseController(config(max_volume_ml=0.25))
        projected.start()
        projected.update(observation(0.1, 0.7, 0.20))
        stopped = projected.update(observation(0.6, 0.7, 0.20))
        self.assertEqual(stopped.reason, "maximum_volume_would_be_exceeded")
        self.assertEqual([intent.command for intent in stopped.intents], ["STOP"])

    def test_commanded_pulse_volume_is_reserved_when_reports_are_stale(self):
        controller = PulseController(config(max_volume_ml=0.15))
        controller.start()
        controller.update(observation(0.1, 0.7, 0.02))
        first_pulse = controller.update(observation(0.6, 0.7, 0.02))
        self.assertEqual([intent.command for intent in first_pulse.intents], ["STEP 10"])
        controller.update(observation(0.7, 0.7, 0.02, pulse_complete=True))

        stopped = controller.update(observation(1.2, 0.7, 0.02))

        self.assertEqual(stopped.reason, "maximum_volume_would_be_exceeded")
        self.assertEqual([intent.command for intent in stopped.intents], ["STOP"])

    def test_zero_duration_endpoint_confirmation_stops_on_approach_event(self):
        controller = PulseController(config(confirmation_duration_s=0.0))
        controller.start()

        stopped = controller.update(observation(0.1, 0.95))

        self.assertEqual(stopped.state, PulseState.STOPPED)
        self.assertEqual(stopped.reason, "endpoint_confirmed")
        self.assertEqual([intent.command for intent in stopped.intents], ["STOP"])
        self.assertEqual(controller.update(observation(0.2, 0.0)).intents, ())

    def test_emergency_stop_latches_and_prevents_all_later_commands(self):
        controller = PulseController(config())
        controller.start()

        emergency = controller.update(
            observation(float("nan"), float("nan"), emergency_stop=True)
        )
        self.assertEqual(emergency.state, PulseState.STOPPED)
        self.assertEqual([intent.command for intent in emergency.intents], ["EMERGENCY_STOP"])
        for later in [
            observation(0.2, 1.0),
            observation(0.3, 0.0, pulse_complete=True),
            observation(0.4, 0.0, emergency_stop=True),
        ]:
            self.assertEqual(controller.update(later).intents, ())

    def test_simulated_trace_is_deterministic(self):
        events = [
            observation(0.1, 0.7, 0.02),
            observation(0.6, 0.7, 0.02),
            observation(0.7, 0.8, 0.12, pulse_complete=True),
            observation(1.2, 0.8, 0.12),
        ]

        first = simulate_trace(config(), events)
        second = simulate_trace(config(), events)

        self.assertEqual(first, second)
        self.assertEqual(
            [intent.command for transition in first for intent in transition.intents],
            ["RUN_RATE 0.2", "STOP", "STEP 10", "STEP 10"],
        )
        self.assertEqual(
            [transition.state for transition in first],
            [
                PulseState.FAST_CONTINUOUS,
                PulseState.PULSE_WAIT,
                PulseState.PULSE_INJECT,
                PulseState.PULSE_WAIT,
                PulseState.PULSE_INJECT,
            ],
        )

    def test_command_formatting_is_explicit_uppercase_protocol(self):
        trace = simulate_trace(
            config(fast_rate_ml_per_s=0.00005, pulse_steps=37),
            [observation(0.1, 0.7), observation(0.6, 0.7)],
        )
        commands = [intent.command for transition in trace for intent in transition.intents]

        self.assertEqual(commands, ["RUN_RATE 0.00005", "STOP", "STEP 37"])
        self.assertTrue(all(command == command.upper() for command in commands))
        numeric_arguments = [command.split(" ", 1)[1] for command in commands if " " in command]
        self.assertTrue(all("e" not in argument.lower() for argument in numeric_arguments))

    def test_optional_slow_stage_requires_sustained_lower_threshold(self):
        controller = PulseController(
            config(
                slow_stage_enabled=True,
                slow_onset_score=0.3,
                slow_onset_duration_s=0.4,
                slow_rate_steps_per_s=25,
            )
        )
        controller.start()

        controller.update(observation(0.1, 0.35))
        controller.update(observation(0.3, 0.2))  # resets sustained onset
        controller.update(observation(0.4, 0.35))
        transition = controller.update(observation(0.8, 0.35))

        self.assertEqual(transition.state, PulseState.SLOW_CONTINUOUS)
        self.assertEqual(
            [intent.command for intent in transition.intents],
            ["STOP", "RATE 25", "RUN_RATE 0.05"],
        )
        self.assertEqual(controller.update(observation(0.9, 0.4)).reason, "slow_continuous")

    def test_pulse_threshold_wins_over_slow_transition(self):
        controller = PulseController(
            config(
                slow_stage_enabled=True,
                slow_onset_score=0.3,
                slow_onset_duration_s=0.0,
                slow_rate_steps_per_s=25,
            )
        )
        controller.start()

        transition = controller.update(observation(0.1, 0.7))

        self.assertEqual(transition.state, PulseState.PULSE_WAIT)
        self.assertEqual([intent.command for intent in transition.intents], ["STOP"])

    def test_invalid_config_and_non_monotonic_trace_fail_closed(self):
        for overrides in [
            {"approach_score": -0.1},
            {"endpoint_score": 0.5},
            {"confirmation_duration_s": -0.1},
            {"pulse_steps": 0},
            {"pulse_steps": 201},
            {"settle_time_s": float("nan")},
            {"max_volume_ml": 101.0},
            {"ml_per_step": 0.0},
            {"fast_rate_ml_per_s": 1.1},
            {"endpoint_confirmation_enabled": "yes"},
            {"slow_stage_enabled": "yes"},
            {"slow_stage_enabled": True, "slow_onset_score": 0.6},
            {"slow_rate_steps_per_s": 0},
            {"slow_rate_steps_per_s": 101},
        ]:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    config(**overrides)

        controller = PulseController(config())
        controller.start(now_s=1.0)
        with self.assertRaises(ValueError):
            controller.update(observation(0.9, 0.5))
        controller.update(observation(1.1, 0.5, 0.2))
        with self.assertRaises(ValueError):
            controller.update(observation(1.2, 0.5, 0.1))


if __name__ == "__main__":
    unittest.main()
