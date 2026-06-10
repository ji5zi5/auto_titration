import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools import pump_calibration, pump_serial_test


class FakeSerial:
    def __init__(self, responses=None):
        self.responses = list(responses or [b"OK STATUS state=idle\n", b""])
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def readline(self):
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        self.closed = True


class PumpSerialToolTests(unittest.TestCase):
    def test_builds_supported_firmware_commands(self):
        cases = [
            (["status"], "STATUS"),
            (["prime"], "PRIME"),
            (["step", "100"], "STEP 100"),
            (["run-rate", "0.25"], "RUN_RATE 0.25"),
            (["run-rate", "0.00005"], "RUN_RATE 0.00005"),
            (["stop"], "STOP"),
            (["emergency-stop"], "EMERGENCY_STOP"),
            (["set-ml-per-step", "0.0025"], "SET_ML_PER_STEP 0.0025"),
            (["set-ml-per-step", "0.00005"], "SET_ML_PER_STEP 0.00005"),
            (["set-steps-per-ml", "400"], "SET_STEPS_PER_ML 400"),
            (["set-max-total-steps", "1200"], "SET_MAX_TOTAL_STEPS 1200"),
            (["set-max-volume-ml", "5"], "SET_MAX_VOLUME_ML 5"),
            (["set-max-volume-ml", "0.005"], "SET_MAX_VOLUME_ML 0.005"),
            (["set-dir", "forward"], "SET_DIR FORWARD"),
            (["set-dir", "reverse"], "SET_DIR REVERSE"),
            (["reset-steps"], "RESET_STEPS"),
            (["clear-fault"], "CLEAR_FAULT"),
            (["send", "STATUS"], "STATUS"),
        ]

        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = pump_serial_test.parse_args(["--port", "COM3", *argv])
                self.assertEqual(pump_serial_test.command_from_args(args), expected)

    def test_rejects_non_finite_and_out_of_firmware_bounds_commands(self):
        for argv in [
            ["run-rate", "nan"],
            ["run-rate", "1.000001"],
            ["set-ml-per-step", "inf"],
            ["set-ml-per-step", "0.0000001"],
            ["set-ml-per-step", "1.000001"],
            ["set-steps-per-ml", "1000001"],
            ["step", "200001"],
            ["set-max-total-steps", "1000001"],
            ["set-max-volume-ml", "0"],
            ["set-max-volume-ml", "100.000001"],
            ["run-rate", "0.000001"],
        ]:
            with self.subTest(argv=argv):
                args = pump_serial_test.parse_args(["--port", "COM3", *argv])
                with self.assertRaises(ValueError):
                    pump_serial_test.command_from_args(args)

    def test_run_rate_lower_bound_can_use_explicit_cli_calibration(self):
        args = pump_serial_test.parse_args(["--port", "COM3", "--ml-per-step", "0.01", "run-rate", "0.000001"])

        with self.assertRaises(ValueError):
            pump_serial_test.command_from_args(args)

    def test_set_max_volume_rejects_calibration_derived_step_overflow(self):
        for argv in [
            ["--ml-per-step", "0.000001", "set-max-volume-ml", "2"],
            ["--ml-per-step", "0.005", "--max-steps", "200", "set-max-volume-ml", "10"],
        ]:
            with self.subTest(argv=argv):
                args = pump_serial_test.parse_args(["--port", "COM3", *argv])
                with self.assertRaises(ValueError):
                    pump_serial_test.command_from_args(args)

    def test_sends_command_and_collects_serial_response(self):
        fake = FakeSerial([b"OK READY\n", b"OK STATUS state=idle\n", b""])

        responses = pump_serial_test.run_serial_command(
            port="COM3",
            firmware_command="STATUS",
            serial_factory=lambda **_: fake,
            read_lines=4,
        )

        self.assertEqual(fake.writes, [b"STATUS\n"])
        self.assertTrue(fake.closed)
        self.assertEqual(responses, ["OK READY", "OK STATUS state=idle"])


class PumpCalibrationToolTests(unittest.TestCase):
    def test_calculates_average_ml_per_step_and_steps_per_ml(self):
        result = pump_calibration.calculate_calibration(steps=1000, measured_volumes_ml=[4.8, 5.0])

        self.assertEqual(len(result.trials), 2)
        self.assertAlmostEqual(result.mean_ml_per_step, 0.0049)
        self.assertAlmostEqual(result.mean_steps_per_ml, 2000 / 9.8)
        self.assertEqual(result.set_ml_per_step_command, "SET_ML_PER_STEP 0.0049")
        self.assertEqual(result.set_steps_per_ml_command, "SET_STEPS_PER_ML 204.081633")

    def test_writes_calibration_csv_and_summary_json(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "pump-calibration.csv"
            summary = Path(temp) / "pump-calibration.summary.json"

            pump_calibration.process(
                steps=1000,
                measured_volumes_ml=[4.8, 5.0],
                output=output,
                summary_output=summary,
            )

            with output.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            payload = json.loads(summary.read_text(encoding="utf-8"))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["commanded_steps"], "1000")
        self.assertEqual(payload["set_ml_per_step_command"], "SET_ML_PER_STEP 0.0049")
        self.assertEqual(payload["trial_count"], 2)

    def test_rejects_non_positive_inputs(self):
        with self.assertRaises(ValueError):
            pump_calibration.calculate_calibration(steps=0, measured_volumes_ml=[1.0])
        with self.assertRaises(ValueError):
            pump_calibration.calculate_calibration(steps=1000, measured_volumes_ml=[0.0])


if __name__ == "__main__":
    unittest.main()
