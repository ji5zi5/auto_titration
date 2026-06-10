import unittest
from collections.abc import Sequence
from typing import cast

from auto_titrator.pump_controller import (
    DEFAULT_MAX_RATE_ML_PER_S,
    DryRunTransport,
    MAX_RUN_RATE_ML_PER_S,
    PumpController,
    PumpSafetyConfig,
    SerialTransport,
    format_firmware_float,
)


class FakeSerial:
    def __init__(self, responses=None):
        self.writes = []
        self.responses = list(responses or [])

    def write(self, data):
        self.writes.append(data)

    def readline(self):
        if not self.responses:
            return b""
        return self.responses.pop(0)


class FailingTransport:
    mode = "serial"

    def write_command(self, command: str) -> Sequence[str]:
        raise OSError("serial disconnected")


class RespondingTransport:
    mode = "serial"

    def __init__(self, responses):
        self.commands = []
        self.responses = list(responses)

    def write_command(self, command: str):
        self.commands.append(command)
        return list(self.responses)


class PumpControllerTests(unittest.TestCase):
    def test_default_safety_rate_is_conservative_under_firmware_speed_limit(self):
        self.assertEqual(PumpSafetyConfig().max_rate_ml_per_s, DEFAULT_MAX_RATE_ML_PER_S)
        self.assertLess(PumpSafetyConfig().max_rate_ml_per_s, MAX_RUN_RATE_ML_PER_S)
        self.assertEqual(MAX_RUN_RATE_ML_PER_S, 1.0)

    def test_dry_run_records_manual_commands_and_step_volume(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.prime()
        pump.step(100)
        pump.stop()

        self.assertEqual(transport.commands, ["PRIME", "STEP 100", "STOP"])
        self.assertEqual(pump.snapshot()["pump_mode"], "dry_run")
        self.assertEqual(pump.snapshot()["pump_step_count"], 100)
        self.assertEqual(pump.snapshot()["pump_state"], "stopped")
        self.assertAlmostEqual(cast(float, pump.snapshot()["injected_volume_ml"]), 0.5)

    def test_step_command_is_tracked_as_in_progress_until_stop(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.step(100)

        self.assertEqual(transport.commands, ["STEP 100"])
        self.assertEqual(pump.snapshot()["pump_state"], "stepping")
        with self.assertRaises(RuntimeError):
            pump.set_ml_per_step(0.0025)

    def test_run_rate_command_is_manual_and_recorded(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.run_rate(0.05)

        self.assertEqual(transport.commands, ["RUN_RATE 0.05"])
        self.assertEqual(pump.snapshot()["pump_state"], "running")
        self.assertEqual(pump.snapshot()["pump_run_rate_ml_per_s"], 0.05)

        pump.stop()

        self.assertEqual(pump.snapshot()["pump_run_rate_ml_per_s"], 0.0)

    def test_float_commands_use_firmware_decimal_text_without_exponents(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.run_rate(0.00005)
        pump.stop()
        pump.set_ml_per_step(0.00005)
        pump.set_steps_per_ml(20000.0)
        pump.set_max_volume_ml(0.005)

        self.assertEqual(
            transport.commands,
            [
                "RUN_RATE 0.00005",
                "STOP",
                "SET_ML_PER_STEP 0.00005",
                "SET_STEPS_PER_ML 20000",
                "SET_MAX_VOLUME_ML 0.005",
            ],
        )
        numeric_args = [command.split(maxsplit=1)[1] for command in transport.commands if " " in command]
        self.assertTrue(all("e" not in value.lower() for value in numeric_args))

    def test_firmware_float_formatter_rejects_non_finite_or_unrepresentable_values(self):
        self.assertEqual(format_firmware_float(0.00005), "0.00005")
        with self.assertRaises(ValueError):
            format_firmware_float(float("nan"))
        with self.assertRaises(ValueError):
            format_firmware_float(float("inf"))
        with self.assertRaises(ValueError):
            format_firmware_float(0.0)

    def test_status_command_is_manual_and_does_not_change_motion_state(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.run_rate(0.05)
        pump.request_status()

        self.assertEqual(transport.commands, ["RUN_RATE 0.05", "STATUS"])
        self.assertEqual(pump.snapshot()["pump_state"], "running")
        self.assertEqual(pump.snapshot()["pump_run_rate_ml_per_s"], 0.05)

    def test_calibration_commands_update_local_volume_math_after_send(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.set_ml_per_step(0.0025)
        pump.step(100)

        self.assertEqual(transport.commands, ["SET_ML_PER_STEP 0.0025", "STEP 100"])
        self.assertAlmostEqual(cast(float, pump.snapshot()["pump_calibrated_ml_per_step"]), 0.0025)
        self.assertAlmostEqual(cast(float, pump.snapshot()["pump_calibrated_steps_per_ml"]), 400.0)
        self.assertAlmostEqual(cast(float, pump.snapshot()["injected_volume_ml"]), 0.25)

    def test_steps_per_ml_calibration_command_updates_local_inverse(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.set_steps_per_ml(500)

        self.assertEqual(transport.commands, ["SET_STEPS_PER_ML 500"])
        self.assertAlmostEqual(cast(float, pump.snapshot()["pump_calibrated_ml_per_step"]), 0.002)
        self.assertAlmostEqual(cast(float, pump.snapshot()["pump_calibrated_steps_per_ml"]), 500.0)

    def test_firmware_safety_limit_commands_are_available(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.set_max_total_steps(1200)
        pump.set_max_volume_ml(2.5)

        self.assertEqual(transport.commands, ["SET_MAX_TOTAL_STEPS 1200", "SET_MAX_VOLUME_ML 2.5"])

    def test_direction_command_allows_reverse_steps_without_negative_position(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.step(100)
        pump.stop()
        pump.set_direction("reverse")
        pump.step(40)
        pump.stop()
        pump.set_direction("forward")

        self.assertEqual(
            transport.commands,
            ["STEP 100", "STOP", "SET_DIR REVERSE", "STEP 40", "STOP", "SET_DIR FORWARD"],
        )
        self.assertEqual(pump.snapshot()["pump_step_count"], 60)
        self.assertEqual(pump.snapshot()["pump_direction"], "forward")

        pump.set_direction("reverse")
        with self.assertRaises(ValueError):
            pump.step(61)

    def test_reset_steps_and_clear_fault_commands_update_local_state(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.step(100)
        pump.stop()
        pump.reset_steps()
        pump.clear_fault()

        self.assertEqual(transport.commands, ["STEP 100", "STOP", "RESET_STEPS", "CLEAR_FAULT"])
        self.assertEqual(pump.snapshot()["pump_step_count"], 0)
        self.assertEqual(pump.snapshot()["pump_state"], "idle")

    def test_emergency_stop_records_command_and_blocks_further_motion(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.emergency_stop()

        self.assertEqual(transport.commands, ["EMERGENCY_STOP"])
        self.assertEqual(pump.snapshot()["pump_state"], "emergency_stop")
        with self.assertRaises(RuntimeError):
            pump.step(1)

    def test_stop_does_not_clear_emergency_latch_locally(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.emergency_stop()
        pump.stop()

        self.assertEqual(transport.commands, ["EMERGENCY_STOP", "STOP"])
        self.assertEqual(pump.snapshot()["pump_state"], "emergency_stop")
        with self.assertRaises(RuntimeError):
            pump.step(1)

    def test_emergency_blocks_reset_and_limit_changes(self):
        pump = PumpController(transport=DryRunTransport(), ml_per_step=0.005)

        pump.emergency_stop()

        for action in [
            pump.reset_steps,
            lambda: pump.set_max_total_steps(1000),
            lambda: pump.set_max_volume_ml(5.0),
            lambda: pump.set_ml_per_step(0.0025),
            lambda: pump.set_steps_per_ml(500),
            pump.clear_fault,
        ]:
            with self.subTest(action=action):
                with self.assertRaises(RuntimeError):
                    action()

    def test_rejects_commands_exceeding_safety_limits(self):
        pump = PumpController(
            transport=DryRunTransport(),
            ml_per_step=0.01,
            safety=PumpSafetyConfig(max_volume_ml=1.0, max_rate_ml_per_s=0.1, max_steps=200),
        )

        with self.assertRaises(ValueError):
            pump.step(201)
        with self.assertRaises(ValueError):
            pump.step(101)
        with self.assertRaises(ValueError):
            pump.run_rate(0.2)

    def test_rejects_non_finite_safety_config_and_calibration_before_any_send(self):
        transport = DryRunTransport()

        for ml_per_step in [float("nan"), float("inf")]:
            with self.subTest(ml_per_step=ml_per_step):
                with self.assertRaises(ValueError):
                    PumpController(transport=transport, ml_per_step=ml_per_step)

        for kwargs in [
            {"max_volume_ml": float("nan")},
            {"max_rate_ml_per_s": float("inf")},
            {"max_steps": cast(int, 1.5)},
        ]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    PumpSafetyConfig(**kwargs)

        self.assertEqual(transport.commands, [])

    def test_rejects_values_outside_firmware_bounds_before_serial_send(self):
        cases = [
            lambda pump: pump.step(200001),
            lambda pump: pump.run_rate(0.500001),
            lambda pump: pump.set_ml_per_step(0.0000001),
            lambda pump: pump.set_ml_per_step(1.000001),
            lambda pump: pump.set_steps_per_ml(1000001.0),
            lambda pump: pump.set_max_total_steps(1000001),
            lambda pump: pump.set_max_volume_ml(100.000001),
        ]

        for action in cases:
            transport = DryRunTransport()
            pump = PumpController(transport=transport, ml_per_step=0.005)
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    action(pump)
                self.assertEqual(transport.commands, [])

    def test_set_max_volume_rejects_calibration_derived_step_overflow_before_send(self):
        cases = [
            (
                PumpController(
                    transport=DryRunTransport(),
                    ml_per_step=0.005,
                    safety=PumpSafetyConfig(max_steps=200),
                ),
                10.0,
            ),
            (
                PumpController(
                    transport=DryRunTransport(),
                    ml_per_step=0.000001,
                ),
                2.0,
            ),
        ]

        for pump, volume_ml in cases:
            transport = cast(DryRunTransport, pump.transport)
            with self.subTest(volume_ml=volume_ml, ml_per_step=pump.ml_per_step, max_steps=pump.safety.max_steps):
                with self.assertRaises(ValueError):
                    pump.set_max_volume_ml(volume_ml)
                self.assertEqual(transport.commands, [])

    def test_rejects_too_slow_run_rate_before_serial_send(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        with self.assertRaises(ValueError):
            pump.run_rate(0.000001)

        self.assertEqual(transport.commands, [])

    def test_serial_transport_writes_newline_encoded_commands(self):
        serial = FakeSerial(responses=[b"OK STEP_STARTED 10\n"])
        transport = SerialTransport(serial)

        responses = transport.write_command("STEP 10")

        self.assertEqual(serial.writes, [b"STEP 10\n"])
        self.assertEqual(responses, ["OK STEP_STARTED 10"])

    def test_firmware_error_response_prevents_local_state_update(self):
        transport = RespondingTransport(["ERR MAX_TRAVEL"])
        pump = PumpController(transport=transport, ml_per_step=0.005)

        with self.assertRaises(RuntimeError):
            pump.step(100)

        self.assertEqual(transport.commands, ["STEP 100"])
        self.assertEqual(pump.snapshot()["pump_step_count"], 0)
        self.assertEqual(pump.snapshot()["pump_state"], "error_stopped")
        with self.assertRaises(RuntimeError):
            pump.step(1)
        self.assertEqual(transport.commands, ["STEP 100"])

    def test_missing_firmware_ack_prevents_local_state_update(self):
        transport = RespondingTransport([])
        pump = PumpController(transport=transport, ml_per_step=0.005)

        with self.assertRaises(RuntimeError):
            pump.run_rate(0.05)

        self.assertEqual(transport.commands, ["RUN_RATE 0.05"])
        self.assertEqual(pump.snapshot()["pump_run_rate_ml_per_s"], 0.0)
        self.assertEqual(pump.snapshot()["pump_state"], "error_stopped")
        with self.assertRaises(RuntimeError):
            pump.clear_fault()
        self.assertEqual(transport.commands, ["RUN_RATE 0.05"])

    def test_step_ack_must_match_requested_step_count(self):
        transport = RespondingTransport(["OK STEP_STARTED 999"])
        pump = PumpController(transport=transport, ml_per_step=0.005)

        with self.assertRaises(RuntimeError):
            pump.step(100)

        self.assertEqual(transport.commands, ["STEP 100"])
        self.assertEqual(pump.snapshot()["pump_step_count"], 0)
        self.assertEqual(pump.snapshot()["pump_state"], "error_stopped")

    def test_dry_run_ack_is_only_accepted_from_dry_run_transport(self):
        transport = RespondingTransport(["OK DRY_RUN STEP 100"])
        pump = PumpController(transport=transport, ml_per_step=0.005)

        with self.assertRaises(RuntimeError):
            pump.step(100)

        self.assertEqual(transport.commands, ["STEP 100"])
        self.assertEqual(pump.snapshot()["pump_state"], "error_stopped")

    def test_limit_ack_must_match_requested_limit_value(self):
        transport = RespondingTransport(["OK SET_MAX_TOTAL_STEPS 999"])
        pump = PumpController(transport=transport, ml_per_step=0.005)

        with self.assertRaises(RuntimeError):
            pump.set_max_total_steps(1000)

        self.assertEqual(transport.commands, ["SET_MAX_TOTAL_STEPS 1000"])
        self.assertEqual(pump.snapshot()["pump_state"], "error_stopped")

    def test_snapshot_distinguishes_commanded_and_confirmed_volume(self):
        transport = DryRunTransport()
        pump = PumpController(transport=transport, ml_per_step=0.005)

        pump.step(100)
        snapshot = pump.snapshot()

        self.assertEqual(snapshot["pump_commanded_step_count"], 100)
        self.assertEqual(snapshot["pump_confirmed_step_count"], 0)
        self.assertAlmostEqual(cast(float, snapshot["commanded_volume_ml"]), 0.5)
        self.assertAlmostEqual(cast(float, snapshot["confirmed_injected_volume_ml"]), 0.0)

    def test_transport_failure_sets_error_stopped_state(self):
        pump = PumpController(transport=FailingTransport(), ml_per_step=0.005)

        with self.assertRaises(OSError):
            pump.prime()

        self.assertEqual(pump.snapshot()["pump_state"], "error_stopped")


if __name__ == "__main__":
    unittest.main()
