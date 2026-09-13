import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_position_analysis_reports_precision_drift_linearity_and_pulse_volume(self):
        observations = [
            pump_calibration.CalibrationObservation("early", 1, 500, 4.90, pulse_count=100),
            pump_calibration.CalibrationObservation("early", 2, 500, 4.95, pulse_count=100),
            pump_calibration.CalibrationObservation("middle", 1, 250, 2.46, pulse_count=50),
            pump_calibration.CalibrationObservation("middle", 2, 500, 4.92, pulse_count=100),
            pump_calibration.CalibrationObservation("late", 1, 250, 2.43, pulse_count=50),
            pump_calibration.CalibrationObservation("late", 2, 500, 4.86, pulse_count=100),
        ]

        result = pump_calibration.analyze_observations(
            observations,
            nominal_ml_per_step=0.0099,
        )

        self.assertEqual(result.overall.trial_count, 6)
        self.assertGreater(result.overall.cv_percent, 0.0)
        self.assertAlmostEqual(result.overall.mean_volume_per_pulse_ml, 0.04904, places=5)
        self.assertEqual(set(result.by_position), {"early", "middle", "late"})
        self.assertIsNotNone(result.linearity_r_squared)
        self.assertGreater(result.linearity_r_squared, 0.999)
        self.assertGreater(result.position_drift_percent, 0.0)
        self.assertLess(result.nominal_bias_percent, 0.0)

    def test_position_analysis_reads_csv_and_writes_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "pulse_trials.csv"
            source.write_text(
                "position,trial,commanded_steps,pulse_count,measured_volume_ml\n"
                "early,1,500,100,4.90\n"
                "middle,1,500,100,4.95\n"
                "late,1,500,100,4.85\n",
                encoding="utf-8",
            )
            detail = root / "analysis.csv"
            summary = root / "analysis.json"

            result = pump_calibration.process_observation_csv(
                input_path=source,
                output=detail,
                summary_output=summary,
                nominal_ml_per_step=0.0099,
            )

            with detail.open(newline="", encoding="utf-8") as handle:
                detail_rows = list(csv.DictReader(handle))
            payload = json.loads(summary.read_text(encoding="utf-8"))

        self.assertEqual(result.overall.trial_count, 3)
        self.assertEqual(len(detail_rows), 3)
        self.assertEqual(detail_rows[0]["position"], "early")
        self.assertEqual(payload["evidence_scope"], "measured_water_trials")
        self.assertIn("by_position", payload)
        self.assertFalse(payload["claims_actual_single_drop_volume"])
        self.assertEqual(payload["minimum_repetitions_per_position_command"], 10)
        self.assertEqual(len(payload["position_command_group_counts"]), 12)
        self.assertEqual(len(payload["insufficient_position_command_groups"]), 12)
        early_step_5 = next(
            group
            for group in payload["insufficient_position_command_groups"]
            if group["position"] == "early" and group["command_steps"] == 5
        )
        self.assertEqual(early_step_5["observed_count"], 1)
        self.assertEqual(early_step_5["missing_count"], 9)

    def test_position_template_defaults_to_ten_trials_for_each_position_and_command(self):
        with tempfile.TemporaryDirectory() as temp:
            template = Path(temp) / "position-template.csv"

            pump_calibration.write_position_template(template)

            with template.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 3 * 4 * 10)
        group_counts = {}
        for row in rows:
            key = (row["position"], int(row["pulse_steps"]))
            group_counts[key] = group_counts.get(key, 0) + 1
            self.assertEqual(
                int(row["commanded_steps"]),
                int(row["pulse_count"]) * int(row["pulse_steps"]),
            )
        self.assertEqual(
            set(group_counts),
            {
                (position, command_steps)
                for position in ("early", "middle", "late")
                for command_steps in (5, 10, 20, 50)
            },
        )
        self.assertEqual(set(group_counts.values()), {10})

    def test_position_template_rejects_fewer_than_required_repetitions(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "at least 10"):
                pump_calibration.write_position_template(
                    Path(temp) / "position-template.csv",
                    repeats=9,
                )

    def test_position_analysis_cli_explicitly_warns_about_insufficient_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "pulse_trials.csv"
            source.write_text(
                "position,trial,commanded_steps,pulse_count,pulse_steps,measured_volume_ml\n"
                "early,1,500,100,5,4.90\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = pump_calibration.main(
                    [
                        "--input-csv",
                        str(source),
                        "--output",
                        str(root / "analysis.csv"),
                        "--summary-output",
                        str(root / "analysis.json"),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("WARNING: insufficient repetitions for 12 position/command group(s)", stdout.getvalue())
        self.assertIn("early STEP 5: 1/10", stdout.getvalue())

    def test_position_analysis_rejects_inconsistent_pulse_accounting(self):
        with self.assertRaises(ValueError):
            pump_calibration.CalibrationObservation(
                "early",
                1,
                500,
                4.9,
                pulse_count=99,
                pulse_steps=5,
            )


if __name__ == "__main__":
    unittest.main()
