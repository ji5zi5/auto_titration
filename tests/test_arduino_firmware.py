from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


FIRMWARE_PATH = Path("auto_titrator/arduino_stepper/arduino_stepper.ino")
COMMAND_PARSER_PATH = Path("auto_titrator/arduino_stepper/command_parser.h")
HOST_FIRMWARE_TEST_PATH = Path("tests/firmware/arduino_stepper_host_test.cpp")


class ArduinoFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FIRMWARE_PATH.read_text(encoding="utf-8")

    def test_firmware_file_exists(self):
        self.assertTrue(FIRMWARE_PATH.exists())

    def test_legacy_protocol_and_hardware_contract_are_preserved(self):
        for expected in [
            "const int STEP_PIN = 2;",
            "const int DIR_PIN = 3;",
            "const int ENABLE_PIN = 4;",
            "Serial.begin(9600);",
            "cmd == 'a'",
            "cmd == 'b'",
            "cmd == 'c'",
            'commandBuffer[0] == \'G\'',
            'strcmp(commandBuffer, "Q") == 0',
            "const unsigned long ABSOLUTE_MAX_RUN_TIME_MS = 120000UL;",
            "min(requestedMs, ABSOLUTE_MAX_RUN_TIME_MS)",
            "(unsigned long)(millis() - runStartedMs) >= activeRunLimitMs",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, self.source)

    def test_step_command_has_strict_small_positive_bound(self):
        self.assertRegex(
            self.source,
            r"const unsigned long MAX_PULSE_STEPS = (\d+)UL;",
        )
        max_steps = int(re.search(r"MAX_PULSE_STEPS = (\d+)UL", self.source).group(1))
        self.assertGreater(max_steps, 0)
        self.assertLessEqual(max_steps, 200)
        for rejection_check in [
            'strncmp(commandBuffer, "STEP ", 5) == 0',
            "!parseBoundedUnsignedLong(valueStart, MAX_PULSE_STEPS, &requestedSteps)",
            "requestedSteps == 0",
        ]:
            with self.subTest(rejection_check=rejection_check):
                self.assertIn(rejection_check, self.source)
        self.assertIn('Serial.println("STEP REJECTED");', self.source)

    def test_step_pulse_preserves_original_b_injection_direction(self):
        self.assertIn("digitalWrite(DIR_PIN, direction == 'a' ? LOW : HIGH);", self.source)
        self.assertIn("const char PULSE_DIRECTION = 'b';", self.source)
        start_pulse = re.search(
            r"void startPulse\(unsigned long stepCount\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        self.assertIn("digitalWrite(DIR_PIN, PULSE_DIRECTION == 'a' ? LOW : HIGH);", start_pulse)
        self.assertIn("digitalWrite(ENABLE_PIN, LOW);", start_pulse)

    def test_plain_manual_a_b_runs_until_explicit_c_without_firmware_deadline(self):
        start_pump = re.search(
            r"void startPump\(char direction\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        self.assertIn("activeRunLimitMs = armedRunLimitMs;", start_pump)
        self.assertNotIn(
            "armedRunLimitMs > 0 ? armedRunLimitMs : ABSOLUTE_MAX_RUN_TIME_MS",
            start_pump,
        )
        self.assertIn("&& activeRunLimitMs > 0", self.source)

    def test_pulse_is_one_step_per_loop_and_stops_after_requested_count(self):
        loop_body = self.source[self.source.index("void loop()") :]
        self.assertLess(loop_body.index("readSerialCommands();"), loop_body.index("performStep();"))
        self.assertIn("if (state == 'p')", loop_body)
        self.assertIn("pulseStepsRemaining--;", loop_body)
        self.assertIn("if (pulseStepsRemaining == 0)", loop_body)
        self.assertIn('stopPump("PULSE_COMPLETE");', loop_body)
        self.assertNotRegex(loop_body, r"for\s*\(.*pulseStepsRemaining")
        self.assertNotRegex(loop_body, r"while\s*\(.*pulseStepsRemaining")

    def test_stop_disables_driver_and_c_clears_an_in_progress_pulse(self):
        stop_pump = re.search(
            r"void stopPump\(const char\* reason\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        for expected in [
            "state = 'c';",
            "pulseStepsRemaining = 0;",
            "digitalWrite(ENABLE_PIN, HIGH);",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, stop_pump)
        self.assertIn("if (cmd == 'c')", self.source)
        self.assertIn('stopPump("COMMAND");', self.source)

    def test_guard_validates_strict_decimal_text_before_unsigned_conversion(self):
        guard_branch = re.search(
            r"commandBuffer\[0\] == 'G'.*?(?=\} else if \(strcmp\(commandBuffer, \"Q\"\))",
            self.source,
            re.DOTALL,
        ).group(0)
        self.assertIn("const char* valueStart = commandBuffer + 2;", guard_branch)
        self.assertIn(
            "valueStart, PROTOCOL_UNSIGNED_LONG_MAX, &requestedMs",
            guard_branch,
        )
        self.assertIn(
            "const unsigned long PROTOCOL_UNSIGNED_LONG_MAX = 4294967295UL;",
            self.source,
        )
        self.assertNotIn("strtoul", guard_branch)
        self.assertIn('Serial.println("GUARD REJECTED");', guard_branch)

    def test_speed_protocol_is_separate_and_q_response_remains_unchanged(self):
        self.assertIn('Serial.println("PUMP SPEED 1");', self.source)
        self.assertRegex(
            self.source,
            r'Serial\.print\("PUMP FW 2 PULSE "\);\s*'
            r'Serial\.print\(PULSE_DIRECTION\);\s*'
            r'Serial\.println\(" GUARD 1"\);',
        )
        self.assertIn('Serial.print("RATE ACCEPTED ");', self.source)
        self.assertIn('Serial.println("RATE REJECTED");', self.source)

    def test_rate_is_guarded_only_and_stop_restores_default(self):
        stop_pump = re.search(
            r"void stopPump\(const char\* reason\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        start_pump = re.search(
            r"void startPump\(char direction\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        start_pulse = re.search(
            r"void startPulse\(unsigned long stepCount\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        self.assertIn("pendingStepRate = DEFAULT_STEP_RATE;", stop_pump)
        self.assertIn(
            "activeStepRate = activeRunLimitMs > 0 ? pendingStepRate : DEFAULT_STEP_RATE;",
            start_pump,
        )
        self.assertIn("activeStepRate = DEFAULT_STEP_RATE;", start_pulse)

    def test_emergency_c_has_priority_during_partial_and_overlong_rate_lines(self):
        emergency_stop = re.search(
            r"char cmd = Serial\.read\(\);(?P<body>.*?)if \(discardingOverflowCommand\)",
            self.source,
            re.DOTALL,
        ).group("body")
        self.assertIn("if (cmd == 'c')", emergency_stop)
        self.assertIn("const bool interruptedLine = commandLength > 0", emergency_stop)
        self.assertIn("|| discardingOverflowCommand", emergency_stop)
        self.assertIn("discardingOverflowCommand = false;", emergency_stop)
        self.assertIn("discardingInterruptedCommand = interruptedLine;", emergency_stop)
        self.assertIn('stopPump("COMMAND");', emergency_stop)
        self.assertRegex(
            self.source,
            r"(?s)if \(discardingInterruptedCommand\).*?"
            r"if \(cmd == '\\n' \|\| cmd == '\\r'\).*?"
            r"discardingInterruptedCommand = false;",
        )
        self.assertIn("discardingOverflowCommand = true;", self.source)
        self.assertIn(
            'Serial.println(overflowCommandIsRate ? "RATE REJECTED" : "COMMAND REJECTED");',
            self.source,
        )

    def test_slow_continuous_mode_is_nonblocking(self):
        slow_step = re.search(
            r"void performSlowStep\(\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        self.assertIn("micros()", slow_step)
        self.assertNotIn("delayMicroseconds", slow_step)
        self.assertIn("if (activeStepRate == DEFAULT_STEP_RATE)", self.source)
        self.assertIn("performSlowStep();", self.source)

    def test_command_parser_rejects_signed_whitespace_and_mixed_values_at_runtime(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++ compiler is required for parser runtime verification")
        self.assertTrue(COMMAND_PARSER_PATH.exists())
        source = r'''
#include "command_parser.h"

int main() {
  const char* accepted[] = {"1", "120000", "0001"};
  const char* rejected[] = {"", "-1", " -1", "\t-1", "+1", "1 ", "1x", " 1"};
  for (const char* value : accepted) {
    if (!isStrictUnsignedDecimalText(value)) return 1;
  }
  for (const char* value : rejected) {
    if (isStrictUnsignedDecimalText(value)) return 2;
  }
  unsigned long parsed = 0;
  if (!parseBoundedUnsignedLong("100", 100UL, &parsed) || parsed != 100UL) return 3;
  if (parseBoundedUnsignedLong("101", 100UL, &parsed)) return 4;
  if (parseBoundedUnsignedLong("999999999999999999999999", 100UL, &parsed)) return 5;
  if (!parseBoundedUnsignedLong("4294967295", 4294967295UL, &parsed)) return 6;
  if (parsed != 4294967295UL) return 7;
  if (parseBoundedUnsignedLong("4294967296", 4294967295UL, &parsed)) return 8;
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            harness = temporary_path / "parser_test.cpp"
            executable = temporary_path / "parser_test"
            harness.write_text(source, encoding="utf-8")
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(COMMAND_PARSER_PATH.parent.resolve()),
                    str(harness),
                    "-o",
                    str(executable),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                [str(executable)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)

    def test_complete_firmware_behavior_in_host_cpp_harness(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++ compiler is required for firmware verification")
        self.assertTrue(HOST_FIRMWARE_TEST_PATH.exists())
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "arduino_stepper_host_test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(Path.cwd()),
                    str(HOST_FIRMWARE_TEST_PATH),
                    "-o",
                    str(executable),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                [str(executable)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)

    def test_duplicate_start_is_idempotent_and_direction_change_requires_stop(self):
        self.assertRegex(
            self.source,
            r"(?s)if \(state == cmd\).*?acknowledgeRunningPump\(\);"
            r".*?else if \(state == 'a' \|\| state == 'b' \|\| state == 'p'\)"
            r".*?stopPump\(\"START_REJECTED_ACTIVE\"\);",
        )
        acknowledge_body = re.search(
            r"void acknowledgeRunningPump\(\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        ).group("body")
        self.assertNotIn("runStartedMs = millis();", acknowledge_body)


if __name__ == "__main__":
    unittest.main()
